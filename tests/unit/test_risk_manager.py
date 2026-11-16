import math

from risk.manager import RiskManager


def test_open_and_close_position(temp_store, risk_config):
    risk = RiskManager(risk_config, temp_store)
    pos = risk.open_position("BTC/USDT", 100.0, 1.0, stop_price=98.0)
    assert "BTC/USDT" in risk.open_positions
    record = risk.close_position("BTC/USDT", 102.0, "TAKE-PROFIT", fee_cost=0.1)
    assert record is not None
    assert record.pnl is not None
    assert record.pnl > 0


def test_position_persists_across_restart(temp_store, risk_config):
    risk = RiskManager(risk_config, temp_store)
    risk.open_position("BTC/USDT", 100.0, 1.0, stop_price=98.0)
    restored = RiskManager(risk_config, temp_store)
    assert "BTC/USDT" in restored.open_positions
    assert restored.open_positions["BTC/USDT"].stop_loss_price == 98.0


def test_max_open_positions(risk_config, temp_store):
    risk = RiskManager(risk_config, temp_store)
    for symbol in ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
        ok, _ = risk.can_open_position(symbol, 10000.0, route="model")
        assert ok
        risk.open_position(symbol, 100.0, 1.0, stop_price=98.0)
    ok, reason = risk.can_open_position("XRP/USDT", 10000.0, route="model")
    assert not ok


def test_duplicate_symbol_blocked(temp_store, risk_config):
    risk = RiskManager(risk_config, temp_store)
    risk.open_position("BTC/USDT", 100.0, 1.0, stop_price=98.0)
    ok, reason = risk.can_open_position("BTC/USDT", 10000.0)
    assert not ok


def test_daily_loss_halt_on_close(temp_store, risk_config):
    risk = RiskManager(risk_config, temp_store)
    risk.state.observe_equity(10000.0)
    risk.state.daily_starting_equity = 10000.0
    risk.open_position("BTC/USDT", 100.0, 100.0, stop_price=98.0)  # 100 units = $10,000
    risk.close_position("BTC/USDT", 90.0, "STOP-LOSS", fee_cost=0.0)  # -1000 => 10%
    risk.state.observe_equity(9000.0)
    ok, reason = risk.can_open_position("ETH/USDT", 9000.0, route="model")
    assert not ok
    assert "Daily loss limit reached" in reason


def test_consecutive_losses_halt_route(temp_store, risk_config):
    risk = RiskManager(risk_config, temp_store)
    for i in range(3):
        sym = f"S{i}/USDT"
        risk.open_position(sym, 100.0, 10.0, stop_price=98.0, route="model")
        risk.close_position(sym, 90.0, "STOP-LOSS", fee_cost=0.0)
    assert "model" in risk.route_halts()


def test_check_positions_emits_stop_and_take_profit(temp_store, risk_config):
    risk = RiskManager(risk_config, temp_store)
    risk.open_position("BTC/USDT", 100.0, 1.0, stop_price=98.0, take_profit_price=110.0)
    risk.open_position("ETH/USDT", 100.0, 1.0, stop_price=98.0, take_profit_price=110.0)
    exits = dict(risk.check_positions(lambda s: 95.0 if s == "BTC/USDT" else 115.0))
    assert "STOP-LOSS" in exits["BTC/USDT"]
    assert "TAKE-PROFIT" in exits["ETH/USDT"]


def test_check_positions_breakeven_then_trailing(temp_store, risk_config):
    risk = RiskManager(risk_config, temp_store)
    risk.open_position("BTC/USDT", 100.0, 1.0, stop_price=98.0)
    risk.check_positions(lambda s: 103.0)  # 1.5R
    assert risk.open_positions["BTC/USDT"].break_even_activated
    assert risk.open_positions["BTC/USDT"].stop_loss_price >= 100.0


def test_accounting_incomplete_close_blocks_pnl(temp_store, risk_config):
    risk = RiskManager(risk_config, temp_store)
    pos = risk.open_position("BTC/USDT", 100.0, 1.0, stop_price=98.0)
    risk.open_positions["BTC/USDT"].accounting_complete = False
    record = risk.close_position("BTC/USDT", 102.0, "PARTIAL", fee_cost=None)
    assert record is not None
    assert record.pnl is None
    assert risk.state.halted