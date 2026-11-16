"""Token-protected aiohttp surveillance dashboard with a token login screen.

Operators sign in at ``/login`` by entering the configured ``DASHBOARD_TOKEN``.
A successful login issues a short-lived, opaque, server-side session cookie so
the raw token is never persisted in the browser. Header/Bearer token auth is
kept for scripts and health-check clients.
"""
from __future__ import annotations

import hmac
import logging
import secrets
import time
from datetime import datetime, timezone
from string import Template

from aiohttp import web

logger = logging.getLogger("trade_v2.dashboard")

# Sessions are in-memory (the dashboard is single-replica only) and expire so a
# forgotten browser session cannot stay valid forever.
SESSION_TTL_SECONDS = 12 * 60 * 60
SESSION_COOKIE = "dashboard_session"

INDEX_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>trade_v2</title>
<style>body{font-family:system-ui,sans-serif;margin:24px;background:#0f1115;color:#e6e6e6}
.card{background:#171a21;border:1px solid #2a2f3a;border-radius:8px;padding:16px;margin:12px 0}
.k{color:#8b93a7}.v{font-weight:600}button{padding:8px 14px;margin-right:8px;border-radius:6px;border:1px solid #2a2f3a;background:#222833;color:#e6e6e6;cursor:pointer}
.err{color:#ff6b6b}</style></head>
<body><h2>trade_v2 — surveillance</h2>
<div id="status" class="card">Loading…</div>
<div class="card">
<button onclick="post('/api/emergency-stop')">Emergency stop</button>
<button onclick="post('/api/resume')">Resume (reviewed)</button>
</div>
<div class="card"><form method="post" action="/logout"><button type="submit">Sign out</button></form></div>
<script>
async function load(){const r=await fetch('/api/status');if(r.status===401){location='/login';return}const d=await r.json();
const el=document.getElementById('status');
el.innerHTML=`<div><span class="k">Mode:</span> <span class="v">${d.paper_trading?'PAPER':'LIVE'}</span></div>
<div><span class="k">Halted:</span> <span class="v">${d.halted} ${d.halt_reason||''}</span></div>
<div><span class="k">Equity:</span> <span class="v">${d.equity??'n/a'}</span></div>
<div><span class="k">Open positions:</span> <span class="v">${d.open_positions}</span></div>
<div><span class="k">Profit factor:</span> <span class="v">${d.profit_factor??'n/a'}</span></div>`;
}
async function post(path){const r=await fetch(path,{method:'POST'});if(r.status===401){location='/login';return}if(!r.ok){alert('Failed: '+r.status)}load();}
load();setInterval(load,5000);
</script></body></html>"""

LOGIN_HTML = Template("""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>trade_v2 — sign in</title>
<style>
body{font-family:system-ui,sans-serif;margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#0f1115;color:#e6e6e6}
main{width:min(92vw,380px);background:#171a21;border:1px solid #2a2f3a;border-radius:10px;padding:28px}
h1{margin:0 0 4px;font-size:22px}.muted{color:#8b93a7;font-size:13px;line-height:1.5}
label{display:block;margin:22px 0 8px;font-size:14px;font-weight:600}
input{width:100%;box-sizing:border-box;padding:11px 12px;border-radius:6px;border:1px solid #2a2f3a;
background:#0f1115;color:#e6e6e6;font-size:14px}
input:focus{outline:2px solid #4c7dff;outline-offset:1px}
button{width:100%;margin-top:18px;padding:11px 14px;border-radius:6px;border:1px solid #4c7dff;
background:#2f5fe0;color:#fff;font-size:14px;font-weight:600;cursor:pointer}
.err{margin:14px 0 0;padding:10px 12px;border-radius:6px;background:#3a1d22;color:#ff8a8a;font-size:13px}
</style></head>
<body><main>
<h1>trade_v2</h1>
<p class="muted">Surveillance console. Sign in with the dashboard token configured on the server.</p>
<form method="post" action="/login">
<label for="token">Dashboard token</label>
<input id="token" name="token" type="password" required autofocus autocomplete="current-password" spellcheck="false">
$error
<button type="submit">Sign in</button>
</form>
<p class="muted" style="margin-top:20px">The token is never stored in the browser; sign-in issues a 12-hour session instead.</p>
</main></body></html>""")


class WebDashboard:
    def __init__(self, config, risk_manager, trader=None):
        self.config = config
        self.risk = risk_manager
        self.trader = trader
        self.token = config.dashboard.dashboard_token
        # session id -> expiry (unix timestamp)
        self._sessions: dict[str, float] = {}

    # ------------------------------------------------------------------ auth

    @staticmethod
    def _secure(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @staticmethod
    def _is_secure_request(request) -> bool:
        proto = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip()
        return (proto or request.scheme).lower() == "https"

    def _token_matches(self, supplied: str) -> bool:
        return bool(self.token and supplied and hmac.compare_digest(supplied, self.token))

    def _new_session(self) -> str:
        sid = secrets.token_urlsafe(32)
        self._sessions[sid] = time.time() + SESSION_TTL_SECONDS
        return sid

    def _valid_session(self, sid: str) -> bool:
        if not sid:
            return False
        expiry = self._sessions.get(sid)
        if expiry is None:
            return False
        if expiry < time.time():
            self._sessions.pop(sid, None)
            return False
        return True

    def _authorized(self, request) -> bool:
        if not self.token:
            return False
        cookie = request.cookies.get("dashboard_token", "")
        header = request.headers.get("X-Dashboard-Token", "")
        auth = request.headers.get("Authorization", "")
        candidates = [cookie, header]
        if auth.startswith("Bearer "):
            candidates.append(auth[7:].strip())
        if any(c and hmac.compare_digest(c, self.token) for c in candidates):
            return True
        return self._valid_session(request.cookies.get(SESSION_COOKIE, ""))

    def _same_origin(self, request) -> bool:
        origin = request.headers.get("Origin", "")
        if not origin:
            return True  # non-browser clients (e.g., curl) must still present the token
        proto = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip() or request.scheme
        return hmac.compare_digest(origin.rstrip("/"), f"{proto}://{request.host}".rstrip("/"))

    @web.middleware
    async def _auth_middleware(self, request, handler):
        path = request.path.rstrip("/") or "/"
        is_health = path.startswith("/health/")
        is_login = path == "/login"

        if not is_health:
            if not self.token and not is_login:
                return self._secure(
                    web.json_response({"error": "Dashboard disabled: no token configured"}, status=503)
                )
            if not is_login and not self._authorized(request):
                accept = request.headers.get("Accept", "")
                is_page_get = request.method in {"GET", "HEAD"} and not path.startswith("/api/")
                if is_page_get and "text/html" in accept:
                    raise self._secure(web.HTTPSeeOther("/login"))
                return self._secure(web.json_response({"error": "Unauthorized"}, status=401))
            if request.method not in {"GET", "HEAD", "OPTIONS"} and not self._same_origin(request):
                return self._secure(web.json_response({"error": "Same-origin required"}, status=403))
        response = await handler(request)
        return self._secure(response)

    # ---------------------------------------------------------------- routes

    def create_app(self) -> web.Application:
        app = web.Application(middlewares=[self._auth_middleware])
        app.router.add_get("/", self.handle_index)
        app.router.add_get("/login", self.handle_login_get)
        app.router.add_post("/login", self.handle_login_post)
        app.router.add_post("/logout", self.handle_logout)
        app.router.add_get("/health/liveness", self.handle_liveness)
        app.router.add_get("/health/readiness", self.handle_readiness)
        app.router.add_get("/api/status", self.handle_status)
        app.router.add_post("/api/emergency-stop", self.handle_emergency_stop)
        app.router.add_post("/api/resume", self.handle_resume)
        return app

    @staticmethod
    def _render_login(error: str = "") -> str:
        error_html = f'<p class="err" role="alert">{error}</p>' if error else ""
        return LOGIN_HTML.substitute(error=error_html)

    async def handle_login_get(self, request):
        if self._authorized(request):
            raise self._secure(web.HTTPSeeOther("/"))
        if not self.token:
            return self._secure(
                web.Response(
                    text=self._render_login("Dashboard disabled: no token configured."),
                    content_type="text/html",
                    status=503,
                )
            )
        return self._secure(web.Response(text=self._render_login(), content_type="text/html"))

    async def handle_login_post(self, request):
        if not self.token:
            return self._secure(
                web.json_response({"error": "Dashboard disabled: no token configured"}, status=503)
            )
        try:
            form = await request.post()
        except Exception:  # malformed body -> treat as a bad token
            form = {}
        supplied = str(form.get("token", "")).strip()
        if not self._token_matches(supplied):
            response = web.Response(
                text=self._render_login("Invalid dashboard token."),
                content_type="text/html",
                status=401,
            )
            return self._secure(response)

        sid = self._new_session()
        response = self._secure(web.HTTPSeeOther("/"))
        response.set_cookie(
            SESSION_COOKIE,
            sid,
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            secure=self._is_secure_request(request),
            samesite="Strict",
            path="/",
        )
        raise response

    async def handle_logout(self, request):
        sid = request.cookies.get(SESSION_COOKIE, "")
        self._sessions.pop(sid, None)
        response = self._secure(web.HTTPSeeOther("/login"))
        response.del_cookie(SESSION_COOKIE, path="/")
        response.del_cookie("dashboard_token", path="/")
        raise response

    async def handle_index(self, request):
        return web.Response(text=INDEX_HTML, content_type="text/html")

    async def handle_liveness(self, request):
        return web.json_response({"status": "alive", "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000)})

    async def handle_readiness(self, request):
        ready = not self.risk.state.halted
        return web.json_response(
            {"status": "ready" if ready else "not_ready", "halted": self.risk.state.halted},
            status=200 if ready else 503,
        )

    async def handle_status(self, request):
        summary = self.risk.get_performance_summary()
        return web.json_response(
            {
                "paper_trading": self.config.exchange.paper_trading,
                "halted": self.risk.state.halted,
                "halt_reason": self.risk.state.halt_reason,
                "entry_mode": self.risk.entry_mode(),
                "open_positions": len(self.risk.open_positions),
                "positions": {s: p.to_dict() for s, p in self.risk.open_positions.items()},
                "daily_pnl": summary.get("daily_pnl"),
                "profit_factor": summary.get("profit_factor"),
                "win_rate": summary.get("win_rate"),
                "route_halts": self.risk.route_halts(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    async def handle_emergency_stop(self, request):
        self.risk.halt("Emergency stop requested via dashboard")
        return web.json_response({"ok": True, "halted": True})

    async def handle_resume(self, request):
        # Only allow resume when flat and reconciled; operator must have reviewed.
        clean = not self.risk.open_positions and not self.risk.store.unresolved_orders()
        if not clean:
            return web.json_response({"ok": False, "error": "Account not flat/reconciled"}, status=409)
        ok = self.risk.resume()
        return web.json_response({"ok": ok})

    def run(self, port: int | None = None) -> None:
        web.run_app(self.create_app(), port=port or self.config.dashboard.dashboard_port)
