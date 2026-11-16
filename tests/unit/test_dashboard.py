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