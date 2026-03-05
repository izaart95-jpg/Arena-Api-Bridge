"""
Arena reCAPTCHA Token Server
============================
Lightweight local server that receives tokens from the browser extension
and stores them to tokens.json (compatible with modula.py / main.py).

Usage:
    pip install fastapi uvicorn
    python server.py

Then install the extension from the arena_harvester_extension/ folder
in your browser and open https://arena.ai to start harvesting.

Dashboard: http://localhost:5000
"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

# ============================================================
# CONFIG
# ============================================================

SERVER_PORT  = 5000
TOKENS_FILE  = "tokens.json"
CONFIG_FILE  = "config.json"

# ============================================================

app = FastAPI()

# Allow the extension (chrome-extension://*) and localhost to POST tokens
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_tokens_lock = asyncio.Lock()

# ─── Token file helpers ───────────────────────────────────────

def _load_tokens_file() -> dict:
    if os.path.exists(TOKENS_FILE):
        try:
            with open(TOKENS_FILE, "r") as f:
                data = json.load(f)
            if isinstance(data, dict) and "tokens" in data:
                return data
        except Exception:
            pass
    return {"tokens": [], "total_count": 0, "last_updated": ""}


def _save_tokens_file(data: dict):
    with open(TOKENS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _append_token(data: dict) -> int:
    tokens_data = _load_tokens_file()
    now_utc   = datetime.utcnow()
    raw_token = data.get("token", "")

    entry = {
        "token":           raw_token,
        "version":         data.get("version", "v3"),
        "action":          data.get("action", ""),
        "source_url":      data.get("source_url", ""),
        "tab_id":          data.get("tab_id", -1),
        "window_id":       data.get("window_id", data.get("tab_id", -1)),  # back-compat
        "harvest_number":  data.get("harvest_number", 0),
        "timestamp_utc":   now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timestamp_local": now_utc.strftime("%Y-%m-%d %H:%M:%S"),
        "token_preview":   (raw_token[:40] + "...") if len(raw_token) > 40 else raw_token,
    }

    tokens_data["tokens"].append(entry)
    tokens_data["total_count"]  = len(tokens_data["tokens"])
    tokens_data["last_updated"] = entry["timestamp_utc"]
    _save_tokens_file(tokens_data)
    return tokens_data["total_count"]

# ─── Dashboard ────────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Arena Harvester — Server</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0f0f1a; color: #e0e0e0; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 14px; }
  .header { background: linear-gradient(135deg,#1a1a2e,#16213e); padding: 20px 24px; border-bottom: 1px solid #2a2a4e; }
  .header h1 { font-size: 20px; font-weight: 700; color: #c084fc; }
  .header p  { color: #6b7280; font-size: 12px; margin-top: 4px; }
  .stats { display: flex; gap: 1px; background: #1e1e3a; border-bottom: 1px solid #2a2a4e; }
  .stat  { flex: 1; padding: 16px; text-align: center; background: #12122a; }
  .stat .val { font-size: 28px; font-weight: 700; color: #4ade80; }
  .stat .lbl { font-size: 11px; color: #6b7280; margin-top: 4px; }
  .section { padding: 20px 24px; }
  .section h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .08em; color: #6b7280; margin-bottom: 14px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th { text-align: left; color: #6b7280; font-weight: 600; padding: 6px 10px; border-bottom: 1px solid #1e1e3a; }
  td { padding: 7px 10px; border-bottom: 1px solid #1a1a2e; color: #d1d5db; }
  tr:hover td { background: #1a1a2e; }
  .version { display: inline-block; padding: 2px 8px; border-radius: 99px; font-size: 11px; font-weight: 600; }
  .v2  { background:#14532d; color:#4ade80; }
  .v3  { background:#1e3a5f; color:#60a5fa; }
  .v2_initial  { background:#1f2937; color:#9ca3af; }
  .v2_ondemand { background:#3b1e5f; color:#a78bfa; }
  .preview { font-family: monospace; font-size: 11px; color: #6b7280; }
  .actions { display: flex; gap: 10px; margin-bottom: 16px; }
  .btn { padding: 8px 16px; border: 1px solid #374151; border-radius: 6px; background: #1a1a2e; color: #9ca3af; cursor: pointer; font-size: 12px; }
  .btn:hover { background: #2a2a4e; }
  .btn.danger { border-color: #7f1d1d; color: #f87171; }
  .btn.danger:hover { background: #1f0a0a; }
  .refresh-info { font-size: 11px; color: #374151; margin-left: auto; }
  .info-box { background: #12122a; border: 1px solid #2a2a4e; border-radius: 8px; padding: 14px 18px; margin-bottom: 20px; font-size: 12px; color: #9ca3af; line-height: 1.6; }
  .info-box code { background: #1a1a2e; color: #c084fc; padding: 1px 5px; border-radius: 4px; }
  a { color: #7c3aed; }
</style>
</head>
<body>
<div class="header">
  <h1>🎯 Arena Harvester — Token Server</h1>
  <p>Extension-based harvester. Open arena.ai in your browser and use the extension popup to start.</p>
</div>

<div class="stats">
  <div class="stat"><div class="val" id="stat-total">–</div><div class="lbl">Total Tokens</div></div>
  <div class="stat"><div class="val" id="stat-v2" style="color:#4ade80">–</div><div class="lbl">v2</div></div>
  <div class="stat"><div class="val" id="stat-v3" style="color:#60a5fa">–</div><div class="lbl">v3</div></div>
  <div class="stat"><div class="val" id="stat-fresh" style="color:#fbbf24">–</div><div class="lbl">Fresh (&lt;2m)</div></div>
</div>

<div class="section">
  <div class="info-box">
    Server is running on <code>http://localhost:5000</code>. Tokens are saved to <code>tokens.json</code>.<br>
    Install the extension → open <a href="https://arena.ai" target="_blank">arena.ai</a> → click the 🎯 icon to harvest.
  </div>

  <h2>Recent Tokens</h2>
  <div class="actions">
    <button class="btn" onclick="refresh()">↻ Refresh</button>
    <button class="btn danger" onclick="clearTokens()">🗑 Clear All Tokens</button>
    <span class="refresh-info" id="refresh-info"></span>
  </div>

  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Version</th>
        <th>Action</th>
        <th>Tab</th>
        <th>Time</th>
        <th>Preview</th>
      </tr>
    </thead>
    <tbody id="token-tbody">
      <tr><td colspan="6" style="color:#4b5563;text-align:center;padding:20px;">Loading...</td></tr>
    </tbody>
  </table>
</div>

<script>
async function refresh() {
  try {
    const [tokData] = await Promise.all([
      fetch('/api/tokens').then(r => r.json()),
    ]);
    const tokens = (tokData.tokens || []).slice().reverse();
    const now = Date.now();
    const v2    = tokens.filter(t => (t.version || '').includes('v2')).length;
    const v3    = tokens.filter(t => t.version === 'v3').length;
    const fresh = tokens.filter(t => {
      try { return (now - new Date(t.timestamp_utc).getTime()) / 1000 < 120; } catch { return false; }
    }).length;

    document.getElementById('stat-total').textContent = tokens.length;
    document.getElementById('stat-v2').textContent    = v2;
    document.getElementById('stat-v3').textContent    = v3;
    document.getElementById('stat-fresh').textContent = fresh;
    document.getElementById('refresh-info').textContent = 'Updated ' + new Date().toLocaleTimeString();

    const tbody = document.getElementById('token-tbody');
    if (!tokens.length) {
      tbody.innerHTML = '<tr><td colspan="6" style="color:#4b5563;text-align:center;padding:20px;">No tokens yet. Start harvesting from the extension.</td></tr>';
      return;
    }
    tbody.innerHTML = tokens.slice(0, 50).map((t, i) => {
      const cls = t.version?.replace(/[^a-z0-9_]/gi, '_') || 'v3';
      return `<tr>
        <td>${tokens.length - i}</td>
        <td><span class="version ${cls}">${t.version || '?'}</span></td>
        <td>${t.action || '–'}</td>
        <td>${t.tab_id ?? t.window_id ?? '–'}</td>
        <td>${(t.timestamp_local || '').slice(11)}</td>
        <td class="preview">${t.token_preview || '...'}</td>
      </tr>`;
    }).join('');
  } catch(e) {
    document.getElementById('stat-total').textContent = 'ERR';
  }
}

async function clearTokens() {
  if (!confirm('Clear all tokens from tokens.json?\\nCannot be undone.')) return;
  const r = await fetch('/tokens/clear', { method: 'DELETE' });
  const d = await r.json();
  if (d.ok) alert(`Cleared ${d.removed} token(s)`);
  await refresh();
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""

# ─── Routes ───────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML


@app.post("/api")
async def store_token(request: Request):
    """Receive a harvested token from the extension and persist it to tokens.json."""
    data = await request.json()
    async with _tokens_lock:
        total = _append_token(data)

    version = data.get("version", "v3")
    action  = data.get("action", "")
    token   = data.get("token", "")
    preview = (token[:40] + "...") if len(token) > 40 else token
    tab_id  = data.get("tab_id", data.get("window_id", -1))
    print(f"[token] {version:<14} {action:<22} tab={tab_id:<4} {preview}  (total: {total})")

    return {"total_count": total, "ok": True}


@app.get("/api/tokens")
async def get_tokens():
    async with _tokens_lock:
        data = _load_tokens_file()
    return {"tokens": data.get("tokens", []), "total": data.get("total_count", 0)}


@app.get("/api/tokens/latest")
async def get_latest_tokens():
    async with _tokens_lock:
        data = _load_tokens_file()
    tokens = data.get("tokens", [])
    latest: dict = {}
    for t in tokens:
        latest[str(t.get("version", "unknown"))] = t
    return {"latest": latest}


@app.delete("/tokens/clear")
async def clear_tokens():
    async with _tokens_lock:
        data    = _load_tokens_file()
        removed = len(data.get("tokens", []))
        empty   = {"tokens": [], "total_count": 0, "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
        _save_tokens_file(empty)
    print(f"[tokens] Cleared {removed} token(s)")
    return {"ok": True, "removed": removed}


# ─── Entry point ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  Arena reCAPTCHA Token Server")
    print(f"  Dashboard  : http://localhost:{SERVER_PORT}")
    print(f"  Tokens file: {TOKENS_FILE}")
    print("=" * 55)
    print("  Install the extension, open arena.ai, and")
    print("  click the 🎯 icon in your browser toolbar.")
    print("=" * 55)
    uvicorn.run(app, host="0.0.0.0", port=SERVER_PORT, log_level="warning")
