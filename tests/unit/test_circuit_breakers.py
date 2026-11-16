import pytest

from risk.circuit_breakers import CircuitBreakers


def test_daily_loss_trips_at_threshold(risk_config):
    cb = CircuitBreakers(risk_config)
    assert not cb.daily_loss_tripped(-290.0, 10000.0)  # 2.9%
    assert cb.daily_loss_tripped(-300.0, 10000.0)  # 3.0%


def test_rolling_drawdown_trips(risk_config):
    cb = CircuitBreakers(risk_config)
    assert cb.rolling_drawdown_tripped(9500.0, 10000.0)  # exactly 5%
    assert not cb.rolling_drawdown_tripped(9600.0, 10000.0)


def test_consecutive_losses(risk_config):
    cb = CircuitBreakers(risk_config)
    assert cb.consecutive_losses_tripped(3)
    assert not cb.consecutive_losses_tripped(2)


def test_rolling_pf(risk_config):
    cb = CircuitBreakers(risk_config)
    assert cb.rolling_pf_tripped(0.9)
    assert not cb.rolling_pf_tripped(1.2)
    assert not cb.rolling_pf_tripped(None)


def test_profit_factor_calculation():
    cb = CircuitBreakers.__new__(CircuitBreakers)
    pnls = [10.0, -5.0, 15.0, -5.0]
    assert cb.rolling_profit_factor(pnls, 4) == pytest.approx(2.5)
    assert cb.rolling_profit_factor([], 4) is None