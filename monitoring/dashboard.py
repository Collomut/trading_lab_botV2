"""Token-protected aiohttp surveillance dashboard."""
from __future__ import annotations

import hmac
import logging
from datetime import datetime, timezone

from aiohttp import web

logger = logging.getLogger("trade_v2.dashboard")

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
<script>
async function load(){const r=await fetch('/api/status');const d=await r.json();
const el=document.getElementById('status');
el.innerHTML=`<div><span class="k">Mode:</span> <span class="v">${d.paper_trading?'PAPER':'LIVE'}</span></div>
<div><span class="k">Halted:</span> <span class="v">${d.halted} ${d.halt_reason||''}</span></div>
<div><span class="k">Equity:</span> <span class="v">${d.equity??'n/a'}</span></div>
<div><span class="k">Open positions:</span> <span class="v">${d.open_positions}</span></div>
<div><span class="k">Profit factor:</span> <span class="v">${d.profit_factor??'n/a'}</span></div>`;
}
async function post(path){const r=await fetch(path,{method:'POST'});if(!r.ok){alert('Failed: '+r.status)}load();}
load();setInterval(load,5000);
</script></body></html>"""


class WebDashboard:
    def __init__(self, config, risk_manager, trader=None):
        self.config = config
        self.risk = risk_manager
        self.trader = trader
        self.token = config.dashboard.dashboard_token

    def _authorized(self, request) -> bool:
        if not self.token:
            return False
        cookie = request.cookies.get("dashboard_token", "")
        header = request.headers.get("X-Dashboard-Token", "")
        auth = request.headers.get("Authorization", "")
        candidates = [cookie, header]
        if auth.startswith("Bearer "):
            candidates.append(auth[7:].strip())
        return any(c and hmac.compare_digest(c, self.token) for c in candidates)

    def _same_origin(self, request) -> bool:
        origin = request.headers.get("Origin", "")
        if not origin:
            return True  # non-browser clients (e.g., curl) must still present the token
        proto = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip() or request.scheme
        return hmac.compare_digest(origin.rstrip("/"), f"{proto}://{request.host}".rstrip("/"))

    @web.middleware
    async def _auth_middleware(self, request, handler):
        if request.path.startswith("/health/"):
            return await handler(request)
        if not self.token:
            return web.json_response({"error": "Dashboard disabled: no token configured"}, status=503)
        if not self._authorized(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not self._same_origin(request):
            return web.json_response({"error": "Same-origin required"}, status=403)
        response = await handler(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def create_app(self) -> web.Application:
        app = web.Application(middlewares=[self._auth_middleware])
        app.router.add_get("/", self.handle_index)
        app.router.add_get("/health/liveness", self.handle_liveness)
        app.router.add_get("/health/readiness", self.handle_readiness)
        app.router.add_get("/api/status", self.handle_status)
        app.router.add_post("/api/emergency-stop", self.handle_emergency_stop)
        app.router.add_post("/api/resume", self.handle_resume)
        return app

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
