import math

import pytest

from execution.fills import FillNormalizer
from execution.simulation import SimulatedExchange
from execution.order_manager import OrderManager


def _temp_store(tmp_path):
    from state.sqlite_store import SQLiteStore

    return SQLiteStore(tmp_path / "s.sqlite3")


def test_fee_quote_cost_quote_currency():
    order = {"filled": 1.0, "fees": [{"currency": "USDT", "cost": 0.5}]}
    assert FillNormalizer.fee_quote_cost(order, "BTC/USDT", 100.0) == pytest.approx(0.5)


def test_fee_quote_cost_base_currency_converts():
    order = {"filled": 1.0, "fees": [{"currency": "BTC", "cost": 0.001}]}
    assert FillNormalizer.fee_quote_cost(order, "BTC/USDT", 100.0) == pytest.approx(0.1)


def test_fee_quote_cost_missing_returns_none():
    assert FillNormalizer.fee_quote_cost({"filled": 1.0}, "BTC/USDT", 100.0) is None


def test_fee_quote_cost_unknown_third_asset_returns_none():
    order = {"filled": 1.0, "fees": [{"currency": "BNB", "cost": 0.1}]}
    assert FillNormalizer.fee_quote_cost(order, "BTC/USDT", 100.0) is None


def test_fee_quote_cost_third_asset_with_price():
    order = {"filled": 1.0, "fees": [{"currency": "BNB", "cost": 0.1}]}
    assert FillNormalizer.fee_quote_cost(order, "BTC/USDT", 100.0, {"BNB": 600.0}) == pytest.approx(60.0)


def test_is_confirmed_full_fill():
    order = {"status": "closed", "filled": 1.0}
    assert FillNormalizer.is_confirmed_full_fill(order, 1.0)
    assert not FillNormalizer.is_confirmed_full_fill(order, 2.0)
    assert not FillNormalizer.is_confirmed_full_fill({"status": "open", "filled": 1.0}, 1.0)


def test_simulated_exchange_round_trip():
    prices = {"BTC/USDT": 100.0}
    sim = SimulatedExchange(initial_balance=10000.0, fee_rate=0.001, price_provider=lambda s: prices.get(s))
    buy = sim.place_market_buy("BTC/USDT", 1.0, "cb1")
    assert buy is not None and buy["filled"] == 1.0
    held = sim.get_balance()["BTC"]["free"]
    sell = sim.place_market_sell("BTC/USDT", held, "cb2")
    assert sell is not None and sell["filled"] == held


def test_order_manager_journals_and_halt_on_unknown(tmp_path):
    from execution.order_manager import OrderManager

    store = _temp_store(tmp_path)

    class FakeExchange:
        def __init__(self):
            self.calls = 0

        def place_market_buy(self, symbol, amount, client_id=None):
            self.calls += 1
            raise RuntimeError("timeout")

        def fetch_order_by_client_id(self, client_id, symbol):
            raise RuntimeError("unknown")

    om = OrderManager(store, FakeExchange())
    try:
        om.submit_market("BTC/USDT", "buy", 1.0, "1")
        assert False
    except RuntimeError:
        pass
    # Order intent must be persisted as UNKNOWN.
    orders = store.unresolved_orders()
    assert any(o["state"] == "UNKNOWN" for o in orders)


def test_order_manager_full_fill(tmp_path):
    store = _temp_store(tmp_path)

    class FakeExchange:
        def place_market_buy(self, symbol, amount, client_id=None):
            return {"id": "ord1", "status": "closed", "filled": float(amount), "average": 100.0}

        def cancel_order(self, order_id, symbol):
            return True

    om = OrderManager(store, FakeExchange())
    order, client_id = om.submit_market("BTC/USDT", "buy", 1.0, "1")
    assert order is not None
    assert store.get_order(client_id)["state"] == "FILLED"