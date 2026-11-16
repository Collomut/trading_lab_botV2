import pytest

from risk.stops import StopManager
from risk.types import Position


def _position(entry=100.0, stop=98.0):
    return Position(
        symbol="BTC/USDT",
        side="long",
        entry_price=entry,
        amount=1.0,
        entry_time="2024-01-01T00:00:00+00:00",
        stop_loss_price=stop,
        take_profit_price=None,
        highest_price=entry,
    )


def test_initial_stop_uses_min_pct_floor(risk_config):
    stops = StopManager(risk_config)
    assert abs(stops.initial_stop(100.0, atr=0.0) - 98.5) < 1e-9


def test_initial_stop_capped_at_max_pct(risk_config):
    stops = StopManager(risk_config)
    assert abs(stops.initial_stop(100.0, atr=5.0) - 96.0) < 1e-9


def test_break_even_triggers_at_threshold_and_ratchets(risk_config):
    stops = StopManager(risk_config)
    pos = _position()
    new_stop, activated = stops.break_even_stop(pos, 102.0)  # 1.0R, below 1.5R
    assert not activated and new_stop == 98.0
    new_stop, activated = stops.break_even_stop(pos, 103.0)  # 1.5R
    assert activated and new_stop > 100.0
    pos.stop_loss_price = new_stop
    pos.break_even_activated = True
    again, activated2 = stops.break_even_stop(pos, 120.0)
    assert again == pos.stop_loss_price  # unchanged once activated


def test_trailing_stop_only_moves_up(risk_config):
    stops = StopManager(risk_config)
    pos = _position()
    pos.highest_price = 110.0
    trail = stops.trailing_stop(pos, 110.0, atr=2.0)  # 110 - 6 = 104
    assert abs(trail - 104.0) < 1e-9
    pos.stop_loss_price = trail
    lower = stops.trailing_stop(pos, 100.0, atr=2.0)
    assert lower == trail


def test_time_stop(risk_config):
    stops = StopManager(risk_config)
    pos = _position()
    pos.bars_held = risk_config.time_stop_bars
    assert stops.time_stop_exit(pos, 100.5) is True  # 0.25R
    assert stops.time_stop_exit(pos, 101.0) is False  # 0.5R
