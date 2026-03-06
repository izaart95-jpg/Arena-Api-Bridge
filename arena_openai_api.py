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
# Core streaming generator
# ============================================================

async def _stream_arena(prompt: str) -> AsyncIterator[str]:
    cfg      = load_config()
    cfg      = _ensure_config(cfg)
    mode     = _detect_mode(cfg)
    model_id = _resolve_model(cfg, mode)

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
                yield _openai_chunk(token)
        # ag / ac / a2 silently dropped

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