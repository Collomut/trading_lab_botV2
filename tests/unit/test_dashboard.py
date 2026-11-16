import asyncio

import pytest

from config.schemas import BotConfig, ExchangeConfig, ModelConfig, RiskConfig, StrategyConfig
from monitoring.dashboard import WebDashboard
from risk.manager import RiskManager
from state.sqlite_store import SQLiteStore


@pytest.fixture
def app_ctx(tmp_path):
    store = SQLiteStore(tmp_path / "s.sqlite3")
    risk = RiskManager(RiskConfig(), store)
    cfg = BotConfig()
    cfg.exchange.paper_trading = True
    cfg.exchange.paper_environment = "simulated"
    cfg.dashboard.dashboard_token = "t" * 40
    cfg.data_dir = str(tmp_path / "data")
    dash = WebDashboard(cfg, risk)
    return dash, risk, store


def test_index_unauthorized(app_ctx):
    dash, _, _ = app_ctx
    app = dash.create_app()
    from aiohttp.test_utils import TestClient, TestServer

    async def run():
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            resp = await client.get("/")
            assert resp.status == 401
        finally:
            await client.close()

    asyncio.run(run())


def test_status_with_token(app_ctx):
    dash, risk, _ = app_ctx
    app = dash.create_app()
    from aiohttp.test_utils import TestClient, TestServer

    async def run():
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            resp = await client.get("/api/status", headers={"X-Dashboard-Token": "t" * 40})
            assert resp.status == 200
            body = await resp.json()
            assert "halted" in body
        finally:
            await client.close()

    asyncio.run(run())


def test_emergency_stop_endpoint(app_ctx):
    dash, risk, _ = app_ctx
    app = dash.create_app()
    from aiohttp.test_utils import TestClient, TestServer

    async def run():
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            resp = await client.post("/api/emergency-stop", headers={"X-Dashboard-Token": "t" * 40})
            assert resp.status == 200
            assert risk.state.halted
        finally:
            await client.close()

    asyncio.run(run())


def test_health_unauthenticated(app_ctx):
    dash, _, _ = app_ctx
    app = dash.create_app()
    from aiohttp.test_utils import TestClient, TestServer

    async def run():
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            resp = await client.get("/health/liveness")
            assert resp.status == 200
        finally:
            await client.close()

    asyncio.run(run())


def test_csrf_blocks_cross_origin_write(app_ctx):
    dash, _, _ = app_ctx
    app = dash.create_app()
    from aiohttp.test_utils import TestClient, TestServer

    async def run():
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            resp = await client.post(
                "/api/emergency-stop",
                headers={"X-Dashboard-Token": "t" * 40, "Origin": "http://evil.example"},
            )
            assert resp.status == 403
        finally:
            await client.close()

    asyncio.run(run())


def _session_cookie(response):
    for raw in response.headers.getall("Set-Cookie", []):
        if raw.startswith("dashboard_session="):
            return raw.split(";", 1)[0]
    raise AssertionError("no dashboard_session cookie was set")


def test_login_page_is_public(app_ctx):
    dash, _, _ = app_ctx
    app = dash.create_app()
    from aiohttp.test_utils import TestClient, TestServer

    async def run():
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            resp = await client.get("/login")
            assert resp.status == 200
            body = await resp.text()
            assert 'action="/login"' in body
            assert 'name="token"' in body
        finally:
            await client.close()

    asyncio.run(run())


def test_login_rejects_wrong_token(app_ctx):
    dash, _, _ = app_ctx
    app = dash.create_app()
    from aiohttp.test_utils import TestClient, TestServer

    async def run():
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            resp = await client.post("/login", data={"token": "wrong"}, allow_redirects=False)
            assert resp.status == 401
            assert "Invalid dashboard token" in await resp.text()
            assert not resp.headers.getall("Set-Cookie", [])
        finally:
            await client.close()

    asyncio.run(run())


def test_login_success_sets_session_cookie_and_grants_access(app_ctx):
    dash, _, _ = app_ctx
    app = dash.create_app()
    from aiohttp.test_utils import TestClient, TestServer

    async def run():
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            resp = await client.post("/login", data={"token": "t" * 40}, allow_redirects=False)
            assert resp.status == 303
            assert resp.headers["Location"] == "/"
            cookie = _session_cookie(resp)
            set_cookie = next(
                raw for raw in resp.headers.getall("Set-Cookie", [])
                if raw.startswith("dashboard_session=")
            )
            assert "HttpOnly" in set_cookie
            assert "SameSite=Strict" in set_cookie
            client.session.cookie_jar.clear()
            resp = await client.get("/api/status", headers={"Cookie": cookie})
            assert resp.status == 200
        finally:
            await client.close()

    asyncio.run(run())


def test_logout_invalidates_session(app_ctx):
    dash, _, _ = app_ctx
    app = dash.create_app()
    from aiohttp.test_utils import TestClient, TestServer

    async def run():
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            resp = await client.post("/login", data={"token": "t" * 40}, allow_redirects=False)
            cookie = _session_cookie(resp)
            out = await client.post("/logout", allow_redirects=False)
            assert out.status == 303
            assert out.headers["Location"] == "/login"
            client.session.cookie_jar.clear()
            resp = await client.get("/api/status", headers={"Cookie": cookie})
            assert resp.status == 401
        finally:
            await client.close()

    asyncio.run(run())


def test_browser_navigation_redirects_to_login(app_ctx):
    dash, _, _ = app_ctx
    app = dash.create_app()
    from aiohttp.test_utils import TestClient, TestServer

    async def run():
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            resp = await client.get("/", headers={"Accept": "text/html"}, allow_redirects=False)
            assert resp.status == 303
            assert resp.headers["Location"] == "/login"
        finally:
            await client.close()

    asyncio.run(run())


def test_login_csrf_blocks_cross_origin(app_ctx):
    dash, _, _ = app_ctx
    app = dash.create_app()
    from aiohttp.test_utils import TestClient, TestServer

    async def run():
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            resp = await client.post(
                "/login",
                data={"token": "t" * 40},
                headers={"Origin": "http://evil.example"},
                allow_redirects=False,
            )
            assert resp.status == 403
        finally:
            await client.close()

    asyncio.run(run())