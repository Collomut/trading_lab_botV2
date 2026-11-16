import pandas as pd

from state.sqlite_store import SQLiteStore
from state.store import StateStore


def test_state_roundtrip(temp_store):
    temp_store.write_state("k", {"a": 1})
    assert temp_store.read_state("k") == {"a": 1}
    assert temp_store.read_state("missing") is None


def test_positions_roundtrip(temp_store):
    temp_store.write_positions({"BTC/USDT": {"entry_price": 100.0, "amount": 1.0}})
    assert temp_store.read_positions()["BTC/USDT"]["entry_price"] == 100.0


def test_order_state_machine_valid_transitions(temp_store):
    temp_store.create_order_intent("cb1", "BTC/USDT", "buy", "1.0", {"x": 1})
    temp_store.update_order("cb1", "SUBMITTED")
    temp_store.update_order("cb1", "FILLED", filled="1.0", average="100.0")
    order = temp_store.get_order("cb1")
    assert order["state"] == "FILLED"
    temp_store.mark_order_applied("cb1")
    assert temp_store.unresolved_orders() == []


def test_invalid_order_transition_raises(temp_store):
    temp_store.create_order_intent("cb2", "BTC/USDT", "buy", "1.0", {})
    try:
        temp_store.update_order("cb2", "FILLED")  # PENDING -> FILLED is invalid
        assert False
    except ValueError:
        pass


def test_audit_events(temp_store):
    temp_store.append_event("test_event", {"a": 1})
    events = temp_store.list_events(10, event_type="test_event")
    assert len(events) == 1
    assert events[0]["details"] == {"a": 1}


def test_trades_dedup(temp_store):
    trade = {"action": "CLOSE", "symbol": "BTC/USDT", "pnl": 1.0, "timestamp": "2024-01-01T00:00:00+00:00"}
    temp_store.append_trade(trade)
    temp_store.append_trade(trade)
    assert len(temp_store.list_trades()) == 1


def test_unresolved_orders(temp_store):
    temp_store.create_order_intent("cb3", "BTC/USDT", "buy", "1.0", {})
    unresolved = temp_store.unresolved_orders()
    assert len(unresolved) == 1


def test_quick_check(temp_store):
    assert temp_store.quick_check() in {"ok", "ok"} or "ok" in temp_store.quick_check()