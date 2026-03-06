"""
Arena → OpenAI-Compatible API Server
-------------------------------------
Wraps arena_client.py logic into a FastAPI server that speaks the
OpenAI /v1/chat/completions streaming protocol so tools like opencode
can use it as a drop-in backend.

Setup:
    pip install fastapi uvicorn httpx

Run:
    uvicorn arena_openai_api:app --host 0.0.0.0 --port 8000

Configure opencode (or any OpenAI-compatible client):
    base_url = "http://localhost:8000/v1"
    api_key  = "any-string"        # not validated, just required by clients
    model    = "arena"             # or whatever you like -- it's ignored internally

Config flags:
    MARKParser  (bool, default True)  – strip all markdown from streamed tokens.
    CodeParser  (bool, default False) – only active when MARKParser is True;
                                        makes the parser ONLY remove fenced code-block
                                        fences (``` lines) and leave all other markdown
                                        formatting intact.
"""

from __future__ import annotations

import json
import re
import time
import uuid
import asyncio
import httpx

from typing import Any, AsyncIterator, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# -- your existing helpers ---------------------------------------------------
from modula import (
    load_config,
    save_config,
    load_tokens,
    get_latest_token,
    consume_token,
    should_filter_content,
    BASE_URL,
    AUTO_TOKEN,
)

# -- constants ---------------------------------------------------------------
DEFAULT_SEARCH_MODEL   = "019c6f55-308b-71ac-95af-f023a48253cf"
DEFAULT_THINK_MODEL    = "019c2f86-74db-7cc3-baa5-6891bebb5999"
DEFAULT_IMG_MODEL      = "019abc10-e78d-7932-b725-7f1563ed8a12"
RECAPTCHA_ACTION       = "chat_submit"
MAX_RECAPTCHA_ATTEMPTS = 2

app = FastAPI(title="Arena OpenAI Bridge")


# ============================================================
# Pydantic models
# ============================================================

class Message(BaseModel):
    role: str
    # ANY type so Pydantic never wraps list items in a non-serializable object.
    # opencode sends content as a plain str OR list of {"type","text"} dicts.
    content: Any = ""

    def get_text(self) -> str:
        """Return content as a plain string, no matter what format arrived."""
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            parts: list[str] = []
            for part in self.content:
                if isinstance(part, dict) and part.get("type") == "text":
                    t = part.get("text") or ""
                    if t:
                        parts.append(str(t))
                elif isinstance(part, str) and part:
                    parts.append(part)
            return "\n".join(parts)
        return str(self.content) if self.content else ""


class ChatCompletionRequest(BaseModel):
    model: str = "arena"
    messages: List[Message]
    stream: Optional[bool] = True
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


# ============================================================
# Config / mode helpers
# ============================================================

def _ensure_config(cfg: dict) -> dict:
    defaults = {
        "v2_auth": False, "search": False, "reasoning": False,
        "image": False, "image_edit": False,
        "searchmodel": DEFAULT_SEARCH_MODEL,
        "thinkmodel":  DEFAULT_THINK_MODEL,
        "imgmodel":    DEFAULT_IMG_MODEL,
        "MARKParser":  True,   # strip markdown from streamed output by default
        "CodeParser":  False,  # when True (+ MARKParser), ONLY strip fenced code blocks
    }
    changed = any(k not in cfg for k in defaults)
    for k, v in defaults.items():
        cfg.setdefault(k, v)
    if changed:
        save_config(cfg)
    return cfg


def _detect_mode(cfg: dict) -> str:
    if cfg.get("image"):
        return "image_edit" if cfg.get("image_edit") else "image"
    if cfg.get("search"):    return "search"
    if cfg.get("reasoning"): return "reasoning"
    return "chat"


def _resolve_model(cfg: dict, mode: str) -> str:
    if mode in ("image", "image_edit"): return cfg.get("imgmodel") or DEFAULT_IMG_MODEL
    if mode == "search":                return cfg.get("searchmodel") or DEFAULT_SEARCH_MODEL
    if mode == "reasoning":             return cfg.get("thinkmodel") or DEFAULT_THINK_MODEL
    return cfg.get("modelAId", "")


# ============================================================
# Header builders
# ============================================================

def _base_headers(cfg: dict) -> dict:
    return {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "origin": BASE_URL,
        "referer": f"{BASE_URL}/c/{cfg['eval_id']}",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    }


def _chat_headers(cfg: dict) -> dict:
    h = _base_headers(cfg)
    h["content-type"] = "application/json"
    return h


def _search_headers(cfg: dict) -> dict:
    h = _base_headers(cfg)
    h.update({
        "content-type": "text/plain;charset=UTF-8",
        "priority": "u=1, i",
        "sec-ch-ua": '"Chromium";v="145", "Not:A-Brand";v="99"',
        "sec-ch-ua-arch": '"x86"',
        "sec-ch-ua-bitness": '"64"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-model": '""',
        "sec-ch-ua-platform": '"Linux"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    })
    return h


# ============================================================
# Payload builder
# ============================================================

def _build_payload(cfg: dict, mode: str, model_id: str,
                   prompt: str, recaptcha_token: str) -> dict:
    modality = ("image" if mode in ("image", "image_edit")
                else "search" if mode == "search" else "chat")
    return {
        "id":              cfg["eval_id"],
        "modelAId":        model_id,
        "userMessageId":   str(uuid.uuid4()),
        "modelAMessageId": str(uuid.uuid4()),
        "userMessage": {
            "content":                  prompt,   # always a plain str
            "experimental_attachments": [],
            "metadata":                 {},
        },
        "modality":         modality,
        "recaptchaV3Token": recaptcha_token,
    }


# ============================================================
# reCAPTCHA
# ============================================================

def _is_recaptcha_failure(status: int, body: str) -> bool:
    if status != 403:
        return False
    try:
        return json.loads(body).get("error") == "recaptcha validation failed"
    except Exception:
        return False


def _get_token() -> str:
    token, _ = get_latest_token(version="v3", max_age_seconds=110)
    if not token:
        token, _ = get_latest_token(version=None, max_age_seconds=0)
    return token or ""


# ============================================================
# SSE helpers
# ============================================================

def _decode_token(raw: str) -> str:
    if raw.startswith('"') and raw.endswith('"'):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return raw


def _openai_chunk(content: str, finish: bool = False) -> str:
    if finish:
        obj = {"id": "chatcmpl-arena", "object": "chat.completion.chunk",
               "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
    else:
        obj = {"id": "chatcmpl-arena", "object": "chat.completion.chunk",
               "choices": [{"index": 0,
                             "delta": {"role": "assistant", "content": content},
                             "finish_reason": None}]}
    return f"data: {json.dumps(obj)}\n\n"


# ============================================================
# Markdown / CodeFence parsers
# ============================================================

class _StreamMarkdownStripper:
    """
    Stateful, token-by-token markdown stripper.

    Accumulates tokens into a buffer, applies the chosen stripping mode,
    and flushes clean text back to the caller.

    Modes
    -----
    MARKParser=True, CodeParser=False  →  strip ALL markdown syntax.
    MARKParser=True, CodeParser=True   →  strip ONLY fenced code-block
                                          delimiters (``` lines); everything
                                          else is left untouched.
    MARKParser=False                   →  pass-through, no processing.
    """

    # Compiled once at class level
    _FENCE_LINE   = re.compile(r'^```[^\n]*\n?')          # opening/closing fence
    _HEADING      = re.compile(r'^#{1,6}\s+', re.M)
    _BOLD_ITALIC  = re.compile(r'\*{1,3}([^*\n]+)\*{1,3}')
    _UNDER_BI     = re.compile(r'_{1,3}([^_\n]+)_{1,3}')
    _STRIKE       = re.compile(r'~~([^~\n]+)~~')
    _INLINE_CODE  = re.compile(r'`{1,2}([^`]+)`{1,2}')
    _BLOCKQUOTE   = re.compile(r'^\s*>\s?', re.M)
    _HR           = re.compile(r'^[-*_]{3,}\s*$', re.M)
    _IMAGE        = re.compile(r'!\[([^\]]*)\]\([^)]*\)')
    _LINK         = re.compile(r'\[([^\]]+)\]\([^)]+\)')
    _REF_LINK     = re.compile(r'\[([^\]]+)\]\[[^\]]*\]')
    _LINK_DEF     = re.compile(r'^\[[^\]]+\]:\s+\S+.*$', re.M)
    _UL           = re.compile(r'^\s*[-*+]\s+', re.M)
    _OL           = re.compile(r'^\s*\d+\.\s+', re.M)
    _TABLE_SEP    = re.compile(r'^\|?[\s:|-]+\|[\s:|-]*\|?\s*$', re.M)
    _TABLE_PIPE   = re.compile(r'\|')
    _MULTI_BLANK  = re.compile(r'\n{3,}')

    def __init__(self, mark_parser: bool, code_parser: bool):
        self.mark_parser  = mark_parser
        # CodeParser is only meaningful when MARKParser is also on
        self.code_parser  = code_parser and mark_parser
        self._buf         = ""           # rolling accumulation buffer
        self._in_fence    = False        # are we inside a fenced block?

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def feed(self, token: str) -> str:
        """Accept one streamed token; return immediately-flushable clean text."""
        if not self.mark_parser:
            return token                 # pass-through

        self._buf += token

        # We need a newline boundary to safely process lines that contain
        # markdown syntax (headings, fences, etc.).  Hold back the last
        # incomplete line so we never accidentally split a pattern.
        if "\n" in self._buf:
            safe, self._buf = self._buf.rsplit("\n", 1)
            return self._process(safe + "\n")
        return ""

    def flush(self) -> str:
        """Call once after the stream ends to drain any buffered remainder."""
        if not self.mark_parser or not self._buf:
            return ""
        out, self._buf = self._process(self._buf), ""
        return out

    # ------------------------------------------------------------------
    # Internal processing
    # ------------------------------------------------------------------

    def _process(self, text: str) -> str:
        if self.code_parser:
            return self._strip_fences_only(text)
        return self._strip_all(text)

    def _strip_fences_only(self, text: str) -> str:
        """Remove ``` opening/closing fence lines; keep everything else verbatim."""
        lines = text.split("\n")
        out   = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```"):
                # Toggle fence state; swallow the delimiter line entirely
                self._in_fence = not self._in_fence
                continue          # drop the fence line itself
            out.append(line)
        return "\n".join(out)

    def _strip_all(self, text: str) -> str:
        """Full markdown removal (same rules as strip_markdown.py)."""
        # Fenced code blocks → keep inner content
        def _unwrap_fence(m: re.Match) -> str:
            self._in_fence = False   # reset after full block consumed
            return m.group(1)

        # Multi-line fenced blocks accumulate across tokens; handle open fences
        # by stripping the delimiter line and tracking state.
        lines, out = text.split("\n"), []
        result_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```"):
                self._in_fence = not self._in_fence
                continue          # always drop fence delimiter
            result_lines.append(line)
        text = "\n".join(result_lines)

        # Inline code
        text = self._INLINE_CODE.sub(r'\1', text)
        # HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        # ATX headings
        text = self._HEADING.sub('', text)
        # Bold / italic
        text = self._BOLD_ITALIC.sub(r'\1', text)
        text = self._UNDER_BI.sub(r'\1', text)
        # Strikethrough
        text = self._STRIKE.sub(r'\1', text)
        # Blockquotes
        text = self._BLOCKQUOTE.sub('', text)
        # Horizontal rules
        text = self._HR.sub('', text)
        # Images (keep alt text)
        text = self._IMAGE.sub(r'\1', text)
        # Links (keep link text)
        text = self._LINK.sub(r'\1', text)
        text = self._REF_LINK.sub(r'\1', text)
        text = self._LINK_DEF.sub('', text)
        # List markers
        text = self._UL.sub('', text)
        text = self._OL.sub('', text)
        # Tables
        text = self._TABLE_SEP.sub('', text)
        text = self._TABLE_PIPE.sub(' ', text)
        # Collapse excess blank lines
        text = self._MULTI_BLANK.sub('\n\n', text)

        return text


# ============================================================
# Core streaming generator
# ============================================================

async def _stream_arena(prompt: str) -> AsyncIterator[str]:
    cfg      = load_config()
    cfg      = _ensure_config(cfg)
    mode     = _detect_mode(cfg)
    model_id = _resolve_model(cfg, mode)

    # Instantiate the stateful parser once per request
    parser = _StreamMarkdownStripper(
        mark_parser=cfg.get("MARKParser", True),
        code_parser=cfg.get("CodeParser", False),
    )

    recaptcha_token = _get_token()

    auth_key = "arena-auth-prod-v1.0" if cfg.get("v2_auth") else "arena-auth-prod-v1"
    cookies: dict = {
        auth_key:       cfg["auth_prod"],
        "cf_clearance": cfg["cf_clearance"],
        "__cf_bm":      cfg["cf_bm"],
    }
    if cfg.get("v2_auth"):
        cookies["domain_migration_completed"] = "true"
        cookies["arena-auth-prod-v1.1"]       = cfg.get("auth_prod_v2", "")

    url     = f"{BASE_URL}/nextjs-api/stream/post-to-evaluation/{cfg['eval_id']}"
    headers = _search_headers(cfg) if mode in ("search", "image", "image_edit") \
              else _chat_headers(cfg)

    if recaptcha_token:
        headers["X-Recaptcha-Token"]  = recaptcha_token
        headers["X-Recaptcha-Action"] = RECAPTCHA_ACTION

    payload = _build_payload(cfg, mode, model_id, prompt, recaptcha_token)

    loop = asyncio.get_event_loop()

    def _do_request() -> list:
        chunks: list = []

        with httpx.Client(http2=True, timeout=None, cookies=cookies) as client:
            for attempt in range(MAX_RECAPTCHA_ATTEMPTS):
                # Always hand httpx raw bytes — no Python objects can leak in.
                req_headers = dict(headers)
                if mode not in ("search", "image", "image_edit"):
                    req_headers["content-type"] = "application/json"
                body_bytes = json.dumps(payload).encode("utf-8")
                stream_ctx = client.stream("POST", url,
                                           headers=req_headers,
                                           content=body_bytes)

                with stream_ctx as response:
                    if response.status_code != 200:
                        error_body = (b"".join(response.iter_bytes())
                                      .decode("utf-8", errors="replace"))

                        if _is_recaptcha_failure(response.status_code, error_body):
                            if attempt < MAX_RECAPTCHA_ATTEMPTS - 1:
                                v2, _ = get_latest_token(version="v2", max_age_seconds=110)
                                if v2:
                                    payload["recaptchaV2Token"] = v2
                                    payload.pop("recaptchaV3Token", None)
                                    req_headers.pop("X-Recaptcha-Token", None)
                                    req_headers.pop("X-Recaptcha-Action", None)
                                    headers.pop("X-Recaptcha-Token", None)
                                    headers.pop("X-Recaptcha-Action", None)
                                    consume_token(v2)
                                    continue
                                fv3, _ = get_latest_token(version="v3", max_age_seconds=110)
                                if fv3 and fv3 != recaptcha_token:
                                    payload["recaptchaV3Token"] = fv3
                                    payload.pop("recaptchaV2Token", None)
                                    headers["X-Recaptcha-Token"]  = fv3
                                    headers["X-Recaptcha-Action"] = RECAPTCHA_ACTION
                                    continue
                            chunks.append(f"__ERROR__:reCAPTCHA failed: {error_body[:200]}")
                            return chunks

                        chunks.append(
                            f"__ERROR__:Arena {response.status_code}: {error_body[:200]}"
                        )
                        return chunks

                    if cfg.get("Tokenizer"):
                        new_tok = response.cookies.get(auth_key)
                        if new_tok:
                            cfg["auth_prod"] = new_tok
                            save_config(cfg)

                    for line in response.iter_lines():
                        chunks.append(line)
                    return chunks

        return chunks

    raw_lines: list = await loop.run_in_executor(None, _do_request)

    if recaptcha_token:
        consume_token(recaptcha_token)

    for raw_line in raw_lines:
        if not raw_line:
            continue
        if raw_line.startswith("__ERROR__:"):
            yield _openai_chunk(raw_line[len("__ERROR__:"):])
            break

        m = re.match(r'^([a-z0-9]+):(.*)', raw_line)
        if not m:
            continue
        prefix, data = m.group(1), m.group(2).strip()

        if prefix == "ad":
            break
        if prefix == "a0":
            token = _decode_token(data)
            if token and not should_filter_content(token):
                # Feed through the stateful parser; emit only non-empty output
                cleaned = parser.feed(token)
                if cleaned:
                    yield _openai_chunk(cleaned)
        # ag / ac / a2 silently dropped

    # Flush any remaining buffered text
    tail = parser.flush()
    if tail:
        yield _openai_chunk(tail)

    yield _openai_chunk("", finish=True)
    yield "data: [DONE]\n\n"


# ============================================================
# Routes
# ============================================================

@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [{
            "id": "arena", "object": "model",
            "created": int(time.time()), "owned_by": "arena",
        }],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """
    OpenAI-compatible streaming chat endpoint.
    Accepts plain string OR content-part-list messages (as sent by opencode).
    Only assistant text tokens are forwarded; reasoning/citations/images are dropped.

    Markdown stripping is controlled by two config flags:
        MARKParser  (default True)  – strip all markdown.
        CodeParser  (default False) – when True, ONLY strip fenced code-block
                                      delimiters (overrides full-strip mode).
    """
    prompt = ""
    for msg in reversed(request.messages):
        if msg.role == "user":
            prompt = msg.get_text()
            break

    if not prompt:
        raise HTTPException(status_code=400, detail="No user message found.")

    return StreamingResponse(
        _stream_arena(prompt),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ============================================================
# Dev entrypoint
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("arena_openai_api:app", host="0.0.0.0", port=8000, reload=False)