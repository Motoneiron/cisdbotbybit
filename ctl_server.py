"""
Localhost control plane for CISD bot: HTTP API + HTML dashboard + event feed.

Bind: 127.0.0.1 only. Access via SSH tunnel:
  ssh -L 8765:127.0.0.1:8765 cisdbotbybit
  open http://127.0.0.1:8765
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from collections import deque
from typing import Any, Awaitable, Callable, Optional

from aiohttp import web

logger = logging.getLogger(__name__)

CTL_HOST = "127.0.0.1"
CTL_PORT = 8765
EVENT_BUFFER = 500

ControlStart = Callable[[], Awaitable[dict]]
ControlStop = Callable[[str], Awaitable[dict]]
ControlStatus = Callable[[], Awaitable[dict]]
ControlHealth = Callable[[], dict]


class EventBus:
    def __init__(self, maxlen: int = EVENT_BUFFER):
        self._events: deque[dict] = deque(maxlen=maxlen)
        self._next_id = 1
        self._subs: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    def snapshot(self, since_id: int = 0, limit: int = 100) -> list[dict]:
        out = [e for e in self._events if e["id"] > since_id]
        if limit > 0:
            out = out[-limit:]
        return out

    async def emit(self, kind: str, text: str, extra: Optional[dict] = None) -> dict:
        async with self._lock:
            ev = {
                "id": self._next_id,
                "ts": time.time(),
                "kind": kind,
                "text": (text or "")[:4000],
            }
            if extra:
                ev["extra"] = extra
            self._next_id += 1
            self._events.append(ev)
        dead = []
        for q in list(self._subs):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                dead.append(q)
            except Exception:
                dead.append(q)
        for q in dead:
            self._subs.discard(q)
        return ev

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)


bus = EventBus()

_callbacks: dict[str, Any] = {}
_token_path: Optional[str] = None
_token: Optional[str] = None
_runner: Optional[web.AppRunner] = None


def configure(
    *,
    token_path: str,
    on_start: ControlStart,
    on_stop: ControlStop,
    on_status: ControlStatus,
    on_health: ControlHealth,
) -> None:
    global _token_path, _token
    _token_path = token_path
    _token = _ensure_token(token_path)
    _callbacks["start"] = on_start
    _callbacks["stop"] = on_stop
    _callbacks["status"] = on_status
    _callbacks["health"] = on_health


def _ensure_token(path: str) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.isfile(path):
        tok = open(path, encoding="utf-8").read().strip()
        if tok:
            return tok
    tok = secrets.token_urlsafe(24)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(tok + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    logger.info(f"CTL token создан: {path}")
    return tok


def get_token() -> Optional[str]:
    return _token


async def emit_event(kind: str, text: str, **extra) -> None:
    try:
        await bus.emit(kind, text, extra or None)
    except Exception as e:
        logger.debug(f"emit_event: {e}")


def _auth_ok(request: web.Request) -> bool:
    if not _token:
        return False
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth[7:].strip() == _token:
        return True
    # browser: ?token= or cookie
    q = request.rel_url.query.get("token")
    if q and q == _token:
        return True
    cookie = request.cookies.get("ctl_token")
    if cookie and cookie == _token:
        return True
    return False


def _require_auth(handler):
    async def wrapped(request: web.Request):
        if not _auth_ok(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        return await handler(request)

    return wrapped


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>CISD BOT</title>
<style>
  :root {
    --bg: #0f1419;
    --panel: #1a2332;
    --border: #2a3544;
    --text: #e7ecf3;
    --muted: #8b9bb4;
    --ok: #3dd68c;
    --warn: #f5a524;
    --bad: #f07178;
    --accent: #5b9fd4;
    --live: #ff6b6b;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; font-family: "Segoe UI", system-ui, sans-serif;
    background: var(--bg); color: var(--text);
    min-height: 100vh;
  }
  header {
    display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
    justify-content: space-between;
    padding: 14px 18px; border-bottom: 1px solid var(--border);
    background: var(--panel);
  }
  h1 { margin: 0; font-size: 1.1rem; font-weight: 600; letter-spacing: .02em; }
  .badges { display: flex; flex-wrap: wrap; gap: 8px; }
  .badge {
    font-size: .75rem; padding: 4px 10px; border-radius: 999px;
    border: 1px solid var(--border); color: var(--muted);
  }
  .badge.on { color: var(--ok); border-color: #2a5a40; }
  .badge.off { color: var(--warn); border-color: #5a4520; }
  .badge.live { color: var(--live); border-color: #5a3030; }
  .badge.paper { color: var(--accent); border-color: #2a4560; }
  .badge.tg-on { color: var(--ok); }
  .badge.tg-off { color: var(--bad); }
  main {
    display: grid;
    grid-template-columns: 1fr 1.2fr;
    gap: 14px; padding: 14px; max-width: 1200px; margin: 0 auto;
  }
  @media (max-width: 900px) { main { grid-template-columns: 1fr; } }
  .card {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 14px 16px;
  }
  .card h2 {
    margin: 0 0 12px; font-size: .85rem; color: var(--muted);
    text-transform: uppercase; letter-spacing: .06em; font-weight: 600;
  }
  .actions { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
  button {
    background: #243044; color: var(--text); border: 1px solid var(--border);
    border-radius: 8px; padding: 8px 14px; cursor: pointer; font-size: .9rem;
  }
  button:hover { border-color: var(--accent); }
  button.primary { background: #1e3d2f; border-color: #2a5a40; color: var(--ok); }
  button.danger { background: #3a2228; border-color: #5a3030; color: var(--bad); }
  button:disabled { opacity: .45; cursor: default; }
  .kv { display: grid; grid-template-columns: 110px 1fr; gap: 6px 10px; font-size: .9rem; }
  .kv span:first-child { color: var(--muted); }
  pre.block {
    margin: 0; white-space: pre-wrap; word-break: break-word;
    font-family: ui-monospace, Consolas, monospace; font-size: .8rem;
    line-height: 1.45; color: #c5d0de; max-height: 280px; overflow: auto;
  }
  #feed {
    list-style: none; margin: 0; padding: 0;
    max-height: calc(100vh - 180px); overflow: auto;
  }
  #feed li {
    padding: 8px 0; border-bottom: 1px solid var(--border);
    font-size: .82rem; line-height: 1.4;
  }
  #feed .meta { color: var(--muted); font-size: .72rem; margin-bottom: 2px; }
  #feed .kind-telegram { border-left: 3px solid var(--accent); padding-left: 8px; }
  #feed .kind-system { border-left: 3px solid var(--warn); padding-left: 8px; }
  #feed .kind-trade { border-left: 3px solid var(--ok); padding-left: 8px; }
  #err { color: var(--bad); font-size: .85rem; min-height: 1.2em; margin-top: 8px; }
  .login {
    max-width: 380px; margin: 80px auto; padding: 24px;
    background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
  }
  input[type=password], input[type=text] {
    width: 100%; padding: 10px; margin: 10px 0 14px;
    background: var(--bg); border: 1px solid var(--border);
    border-radius: 8px; color: var(--text);
  }
  .hidden { display: none !important; }
</style>
</head>
<body>
<div id="login" class="login">
  <h1>CISD BOT</h1>
  <p style="color:var(--muted);font-size:.9rem">Токен из <code>/opt/cisdbot/.ctl_token</code></p>
  <input id="tokenInput" type="password" placeholder="Bearer token" autocomplete="off"/>
  <button class="primary" id="loginBtn" style="width:100%">Войти</button>
  <div id="loginErr" style="color:var(--bad);margin-top:10px;font-size:.85rem"></div>
</div>

<div id="app" class="hidden">
  <header>
    <h1>CISD BOT</h1>
    <div class="badges">
      <span class="badge" id="bMode">—</span>
      <span class="badge" id="bRun">—</span>
      <span class="badge" id="bTg">TG</span>
      <span class="badge" id="bTf">TF</span>
    </div>
  </header>
  <main>
    <section class="card">
      <h2>Управление</h2>
      <div class="actions">
        <button class="primary" id="btnStart">▶ Start</button>
        <button id="btnPause">⏸ Pause</button>
        <button class="danger" id="btnHalt">🛑 Halt</button>
        <button id="btnRefresh">↻ Status</button>
      </div>
      <div class="kv" id="kv"></div>
      <h2 style="margin-top:16px">Status</h2>
      <pre class="block" id="statusText">…</pre>
      <div id="err"></div>
    </section>
    <section class="card">
      <h2>Лента событий</h2>
      <ul id="feed"></ul>
    </section>
  </main>
</div>

<script>
const $ = (id) => document.getElementById(id);
const _q = new URLSearchParams(location.search);
let TOKEN = _q.get('token') || localStorage.getItem('ctl_token') || '';
let es = null;
let lastId = 0;

function authHeaders() {
  return { 'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json' };
}

async function api(path, opts={}) {
  const r = await fetch(path, {
    ...opts,
    headers: { ...authHeaders(), ...(opts.headers||{}) },
  });
  if (r.status === 401) throw new Error('unauthorized');
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || ('HTTP ' + r.status));
  return data;
}

function fmtTs(ts) {
  const d = new Date((ts || 0) * 1000);
  return d.toLocaleString('ru-RU', { hour12: false });
}

function addFeedItem(ev, prepend=true) {
  const li = document.createElement('li');
  li.className = 'kind-' + (ev.kind || 'system');
  li.dataset.id = ev.id;
  const text = (ev.text || '').replace(/</g,'&lt;');
  li.innerHTML = `<div class="meta">#${ev.id} · ${fmtTs(ev.ts)} · ${ev.kind||''}</div><div>${text.replace(/\n/g,'<br>')}</div>`;
  const feed = $('feed');
  if (prepend) feed.prepend(li); else feed.appendChild(li);
  while (feed.children.length > 300) feed.removeChild(feed.lastChild);
}

function setBadges(h) {
  const mode = $('bMode');
  mode.textContent = h.paper ? 'PAPER' : 'LIVE';
  mode.className = 'badge ' + (h.paper ? 'paper' : 'live');
  const run = $('bRun');
  run.textContent = h.running ? 'RUNNING' : (h.tasks_live ? 'PAUSED' : 'HALTED');
  run.className = 'badge ' + (h.running ? 'on' : 'off');
  const tg = $('bTg');
  tg.textContent = h.tg_online ? 'TG online' : 'TG offline';
  tg.className = 'badge ' + (h.tg_online ? 'tg-on' : 'tg-off');
  $('bTf').textContent = h.tf_label || h.active_tf || 'TF';
}

function setKv(h, st) {
  const rows = [
    ['Пара', h.symbol || '—'],
    ['Цена', st && st.price_str != null ? st.price_str : '—'],
    ['Баланс', st && st.balance != null ? st.balance.toFixed(2) + ' USDT' : '—'],
    ['Open', String(h.n_open ?? '—')],
    ['Pending', String(h.n_pending ?? '—')],
  ];
  $('kv').innerHTML = rows.map(([k,v]) => `<span>${k}</span><span>${v}</span>`).join('');
}

async function refresh() {
  $('err').textContent = '';
  const [h, st] = await Promise.all([api('/api/health'), api('/api/status')]);
  setBadges(h);
  setKv({...h, ...st}, st);
  $('statusText').textContent = st.text || JSON.stringify(st, null, 2);
}

function connectSSE() {
  if (es) { try { es.close(); } catch(_){} }
  const url = '/api/events?token=' + encodeURIComponent(TOKEN) + '&since_id=' + lastId;
  es = new EventSource(url);
  es.onmessage = (msg) => {
    try {
      const ev = JSON.parse(msg.data);
      if (ev.id <= lastId) return;
      lastId = ev.id;
      addFeedItem(ev, true);
    } catch(_){}
  };
  es.onerror = () => {
    // browser reconnects; no spam
  };
}

async function loadHistory() {
  const data = await api('/api/events/history?limit=80');
  const events = data.events || [];
  $('feed').innerHTML = '';
  for (const ev of events) {
    addFeedItem(ev, false);
    if (ev.id > lastId) lastId = ev.id;
  }
}

async function enterApp() {
  $('login').classList.add('hidden');
  $('app').classList.remove('hidden');
  document.cookie = 'ctl_token=' + encodeURIComponent(TOKEN) + '; path=/; SameSite=Strict';
  await loadHistory();
  await refresh();
  connectSSE();
}

async function tryLogin(tok) {
  TOKEN = tok.trim();
  $('loginErr').textContent = '';
  try {
    await api('/api/health');
    localStorage.setItem('ctl_token', TOKEN);
    await enterApp();
  } catch (e) {
    $('loginErr').textContent = 'Неверный токен или сервер недоступен';
    TOKEN = '';
  }
}

$('loginBtn').onclick = () => tryLogin($('tokenInput').value);
$('tokenInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') tryLogin($('tokenInput').value);
});

async function act(fn) {
  $('err').textContent = '';
  try {
    await fn();
    await refresh();
  } catch (e) {
    $('err').textContent = String(e.message || e);
  }
}

$('btnStart').onclick = () => act(() => api('/api/start', { method: 'POST', body: '{}' }));
$('btnPause').onclick = () => act(() => api('/api/stop', { method: 'POST', body: JSON.stringify({mode:'pause'}) }));
$('btnHalt').onclick = () => act(() => api('/api/stop', { method: 'POST', body: JSON.stringify({mode:'halt'}) }));
$('btnRefresh').onclick = () => act(() => refresh());

if (TOKEN) {
  tryLogin(TOKEN);
}
</script>
</body>
</html>
"""


async def handle_index(request: web.Request) -> web.Response:
    return web.Response(text=DASHBOARD_HTML, content_type="text/html", charset="utf-8")


@_require_auth
async def handle_health(request: web.Request) -> web.Response:
    fn = _callbacks.get("health")
    data = fn() if fn else {}
    return web.json_response(data)


@_require_auth
async def handle_status(request: web.Request) -> web.Response:
    fn = _callbacks["status"]
    data = await fn()
    return web.json_response(data)


@_require_auth
async def handle_start(request: web.Request) -> web.Response:
    fn = _callbacks["start"]
    data = await fn()
    await bus.emit("system", data.get("text") or "▶ start")
    return web.json_response(data)


@_require_auth
async def handle_stop(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        body = {}
    mode = (body.get("mode") or "pause").strip().lower()
    if mode not in ("pause", "halt"):
        return web.json_response({"error": "mode must be pause|halt"}, status=400)
    fn = _callbacks["stop"]
    data = await fn(mode)
    await bus.emit("system", data.get("text") or f"stop:{mode}")
    return web.json_response(data)


@_require_auth
async def handle_events_history(request: web.Request) -> web.Response:
    try:
        since = int(request.rel_url.query.get("since_id") or 0)
    except ValueError:
        since = 0
    try:
        limit = int(request.rel_url.query.get("limit") or 100)
    except ValueError:
        limit = 100
    return web.json_response({"events": bus.snapshot(since_id=since, limit=limit)})


async def handle_events_sse(request: web.Request) -> web.StreamResponse:
    # EventSource cannot set Authorization — token via query/cookie
    if not _auth_ok(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        since = int(request.rel_url.query.get("since_id") or 0)
    except ValueError:
        since = 0

    resp = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await resp.prepare(request)

    for ev in bus.snapshot(since_id=since, limit=0):
        payload = json.dumps(ev, ensure_ascii=False)
        await resp.write(f"data: {payload}\n\n".encode("utf-8"))

    q = bus.subscribe()
    try:
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=25.0)
                payload = json.dumps(ev, ensure_ascii=False)
                await resp.write(f"data: {payload}\n\n".encode("utf-8"))
            except asyncio.TimeoutError:
                await resp.write(b": ping\n\n")
    except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
        pass
    finally:
        bus.unsubscribe(q)
    return resp


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/health", handle_health)
    app.router.add_get("/api/status", handle_status)
    app.router.add_post("/api/start", handle_start)
    app.router.add_post("/api/stop", handle_stop)
    app.router.add_get("/api/events/history", handle_events_history)
    app.router.add_get("/api/events", handle_events_sse)
    return app


async def start_ctl_server() -> None:
    global _runner
    if not _callbacks.get("status"):
        logger.warning("ctl_server: callbacks not configured — skip")
        return
    app = build_app()
    _runner = web.AppRunner(app, access_log=None)
    await _runner.setup()
    site = web.TCPSite(_runner, CTL_HOST, CTL_PORT, reuse_address=True)
    await site.start()
    logger.info(
        f"CTL dashboard: http://{CTL_HOST}:{CTL_PORT}/  "
        f"(SSH: ssh -L {CTL_PORT}:{CTL_HOST}:{CTL_PORT} cisdbot)"
    )
    await emit_event("system", f"CTL dashboard слушает {CTL_HOST}:{CTL_PORT}")


async def stop_ctl_server() -> None:
    global _runner
    if _runner is not None:
        try:
            await _runner.cleanup()
        except Exception as e:
            logger.debug(f"ctl stop: {e}")
        _runner = None
