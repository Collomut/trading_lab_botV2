"""Token-protected aiohttp surveillance dashboard with a token login screen.

Operators sign in at ``/login`` by entering the configured ``DASHBOARD_TOKEN``.
A successful login issues a short-lived, opaque, server-side session cookie so
the raw token is never persisted in the browser. Header/Bearer token auth is
kept for scripts and health-check clients.
"""
from __future__ import annotations

import hmac
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web

from monitoring.market_data import MarketData

logger = logging.getLogger("trade_v2.dashboard")

TEMPLATES = Path(__file__).parent / "templates"

# Sessions are in-memory (the dashboard is single-replica only) and expire so a
# forgotten browser session cannot stay valid forever.
SESSION_TTL_SECONDS = 12 * 60 * 60
SESSION_COOKIE = "dashboard_session"

class WebDashboard:
    def __init__(self, config, risk_manager, trader=None):
        self.config = config
        self.risk = risk_manager
        self.trader = trader
        self.token = config.dashboard.dashboard_token
        self.market = MarketData(config.exchange.name)
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
        # Behind Railway/reverse proxies the container may see an internal Host;
        # prefer X-Forwarded-Host/Proto, then fall back to the request's own values.
        proto = (
            request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip() or request.scheme
        ).lower()
        hosts = []
        forwarded_host = request.headers.get("X-Forwarded-Host", "")
        if forwarded_host:
            hosts.append(forwarded_host.split(",")[0].strip())
        hosts.append(request.host)
        candidate = origin.rstrip("/").lower()
        return any(
            hmac.compare_digest(candidate, f"{proto}://{host}".rstrip("/").lower())
            for host in hosts
            if host
        )

    @web.middleware
    async def _auth_middleware(self, request, handler):
        path = request.path.rstrip("/") or "/"
        is_health = path.startswith("/health/")
        is_public = path == "/login" or path == "/terms" or path.startswith("/assets/")
        is_login = path == "/login"

        if not is_health:
            if not self.token and not is_public:
                return self._secure(
                    web.json_response({"error": "Dashboard disabled: no token configured"}, status=503)
                )
            if not is_public and not self._authorized(request):
                accept = request.headers.get("Accept", "")
                is_page_get = request.method in {"GET", "HEAD"} and not path.startswith("/api/")
                if is_page_get and "text/html" in accept:
                    raise self._secure(web.HTTPSeeOther("/login"))
                return self._secure(web.json_response({"error": "Unauthorized"}, status=401))
            # Login uses a single shared secret (no per-user account to log into),
            # so login CSRF is not a risk; keep the check on state-changing endpoints.
            needs_origin_check = (
                request.method not in {"GET", "HEAD", "OPTIONS"} and not is_login
            )
            if needs_origin_check and not self._same_origin(request):
                logger.warning(
                    "origin check failed: origin=%r host=%r forwarded_host=%r proto=%r scheme=%r",
                    request.headers.get("Origin", ""),
                    request.host,
                    request.headers.get("X-Forwarded-Host", ""),
                    request.headers.get("X-Forwarded-Proto", ""),
                    request.scheme,
                )
                return self._secure(web.json_response({"error": "Same-origin required"}, status=403))
        response = await handler(request)
        return self._secure(response)

    # ---------------------------------------------------------------- routes

    def create_app(self) -> web.Application:
        app = web.Application(middlewares=[self._auth_middleware])
        app.router.add_get("/", self.handle_index)
        app.router.add_get("/positions", self.handle_positions)
        app.router.add_get("/history", self.handle_history)
        app.router.add_get("/strategy", self.handle_strategy)
        app.router.add_get("/logs", self.handle_logs)
        app.router.add_get("/terms", self.handle_terms)
        app.router.add_get("/assets/{name}", self.handle_asset)
        app.router.add_get("/login", self.handle_login_get)
        app.router.add_post("/login", self.handle_login_post)
        app.router.add_post("/logout", self.handle_logout)
        app.router.add_get("/health/liveness", self.handle_liveness)
        app.router.add_get("/health/readiness", self.handle_readiness)
        app.router.add_get("/api/status", self.handle_status)
        app.router.add_get("/api/market", self.handle_market)
        app.router.add_get("/api/candles", self.handle_candles)
        app.router.add_get("/api/trades", self.handle_trades)
        app.router.add_get("/api/activity", self.handle_activity)
        app.router.add_post("/api/emergency-stop", self.handle_emergency_stop)
        app.router.add_post("/api/resume", self.handle_resume)
        app.router.add_post("/api/exit-only", self.handle_exit_only)
        app.router.add_post("/api/refresh-market", self.handle_refresh_market)
        return app

    @staticmethod
    def _page(name: str) -> web.FileResponse:
        response = web.FileResponse(TEMPLATES / name)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    async def handle_index(self, request):
        return self._page("overview.html")

    async def handle_positions(self, request):
        return self._page("positions.html")

    async def handle_history(self, request):
        return self._page("history.html")

    async def handle_strategy(self, request):
        return self._page("strategy.html")

    async def handle_logs(self, request):
        return self._page("logs.html")

    async def handle_terms(self, request):
        return self._page("glossary.html")

    async def handle_asset(self, request):
        name = request.match_info.get("name", "")
        if name not in {"app.css", "app.js"}:
            raise web.HTTPNotFound()
        return self._page(name)

    async def handle_login_get(self, request):
        if self._authorized(request):
            raise self._secure(web.HTTPSeeOther("/"))
        return self._page("login.html")

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
            raise self._secure(web.HTTPSeeOther("/login?error=1"))

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
        risk_state = self.risk.state
        cfg = self.config
        paper_env = cfg.exchange.paper_environment if cfg.exchange.paper_trading else "live"
        return web.json_response(
            {
                "paper_trading": cfg.exchange.paper_trading,
                "halted": risk_state.halted,
                "halt_reason": risk_state.halt_reason,
                "entry_mode": self.risk.entry_mode(),
                "open_positions": len(self.risk.open_positions),
                "positions": {s: p.to_dict() for s, p in self.risk.open_positions.items()},
                "equity": risk_state.rolling_peak_equity
                or risk_state.daily_starting_equity
                or None,
                "daily_pnl": summary.get("daily_pnl"),
                "profit_factor": summary.get("profit_factor"),
                "win_rate": summary.get("win_rate"),
                "route_halts": self.risk.route_halts(),
                "unresolved_orders": len(self.risk.store.unresolved_orders()),
                "pairs": list(cfg.strategy.trading_pairs),
                "timeframe": cfg.strategy.timeframe,
                "performance": summary,
                "risk": {
                    "daily_loss": risk_state.daily_loss,
                    "daily_starting_equity": risk_state.daily_starting_equity,
                    "rolling_peak_equity": risk_state.rolling_peak_equity,
                    "consecutive_losses": risk_state.consecutive_losses,
                    "route_losses": risk_state.route_losses,
                    "max_consecutive_losses": cfg.risk.max_consecutive_losses,
                    "max_daily_loss_pct": cfg.risk.max_daily_loss_pct,
                    "max_rolling_drawdown_pct": cfg.risk.max_rolling_drawdown_pct,
                    "total_pnl": summary.get("total_pnl"),
                    "total_trades": summary.get("total_trades", 0),
                    "winners": summary.get("winners"),
                    "losers": summary.get("losers"),
                    "profit_factor": summary.get("profit_factor"),
                    "win_rate": summary.get("win_rate"),
                },
                "config": {
                    "environment": paper_env,
                    "exchange": cfg.exchange.name,
                    "pairs": list(cfg.strategy.trading_pairs),
                    "timeframe": cfg.strategy.timeframe,
                    "model_type": cfg.model.model_type,
                    "confidence_threshold": cfg.model.confidence_threshold,
                    "horizon_bars": cfg.model.horizon_bars,
                    "max_risk_per_trade": cfg.risk.max_risk_per_trade,
                    "max_daily_loss_pct": cfg.risk.max_daily_loss_pct,
                    "initial_balance": cfg.initial_balance,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    async def handle_market(self, request):
        snapshot = await self.market.snapshot(
            list(self.config.strategy.trading_pairs),
            timeframe=self.config.strategy.timeframe,
        )
        snapshot["timeframe"] = self.config.strategy.timeframe
        return web.json_response(snapshot)

    async def handle_candles(self, request):
        symbol = request.query.get("symbol", "").strip()
        timeframe = request.query.get("timeframe", self.config.strategy.timeframe)
        if symbol not in self.config.strategy.trading_pairs:
            return web.json_response({"error": "Choose a configured trading pair."}, status=400)
        if timeframe not in {"15m", "1h", "4h", "1d"}:
            return web.json_response({"error": "Unsupported chart timeframe."}, status=400)
        snapshot = await self.market.snapshot([symbol], timeframe=timeframe, limit=100)
        rows = snapshot.get("candles", {}).get(symbol) or []
        if not rows:
            return web.json_response(
                {"error": snapshot.get("error") or "Market candles are temporarily unavailable."},
                status=502,
            )
        return web.json_response(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "candles": [
                    {
                        "time": row[0], "open": row[1], "high": row[2],
                        "low": row[3], "close": row[4], "volume": row[5],
                    }
                    for row in rows
                ],
            }
        )

    async def handle_trades(self, request):
        try:
            trades = self.risk.store.list_trades(500)
        except Exception as exc:
            logger.warning("could not read trades: %s", exc)
            trades = []
        return web.json_response({"trades": trades})

    async def handle_activity(self, request):
        try:
            events = self.risk.store.list_events(limit=100)
        except Exception as exc:
            logger.warning("could not read audit events: %s", exc)
            events = []
        return web.json_response(
            {
                "events": [
                    {
                        "event_type": e.get("event_type"),
                        "details": e.get("details"),
                        "created_at": e.get("created_at"),
                    }
                    for e in events
                ]
            }
        )

    async def handle_emergency_stop(self, request):
        self.risk.halt("Emergency stop requested via dashboard")
        return web.json_response({"ok": True, "halted": True, "message": "Trading halted by operator."})

    async def handle_resume(self, request):
        # Only allow resume when flat and reconciled; operator must have reviewed.
        clean = not self.risk.open_positions and not self.risk.store.unresolved_orders()
        if not clean:
            return web.json_response(
                {"ok": False, "error": "Account not flat/reconciled — resume refused."},
                status=409,
            )
        ok = self.risk.resume()
        return web.json_response(
            {"ok": ok, "message": "Trading resumed." if ok else "Bot was not halted."}
        )

    async def handle_exit_only(self, request):
        self.risk.set_entry_mode("EXIT_ONLY")
        return web.json_response(
            {"ok": True, "entry_mode": self.risk.entry_mode(), "message": "New entries paused; exits and stops stay active."}
        )

    async def handle_refresh_market(self, request):
        await self.market.snapshot(
            list(self.config.strategy.trading_pairs),
            timeframe=self.config.strategy.timeframe,
            force=True,
        )
        return web.json_response({"ok": True, "message": "Market data refreshed."})

    def run(self, port: int | None = None) -> None:
        web.run_app(self.create_app(), port=port or self.config.dashboard.dashboard_port)
