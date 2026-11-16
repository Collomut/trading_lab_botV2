import pytest

from risk.validators import PreTradeValidator
from config.schemas import BotConfig, RiskConfig


@pytest.fixture
def validator():
    cfg = BotConfig()
    cfg.risk = RiskConfig(max_spread_bps=20.0, max_slippage_bps=30.0, max_pairwise_correlation=0.85)
    return PreTradeValidator(cfg)


def test_spread(validator):
    assert validator.validate_spread(10.0)[0]
    assert not validator.validate_spread(25.0)[0]
    assert not validator.validate_spread(float("nan"))[0]


def test_depth(validator):
    book = {"bids": [[100.0, 5.0]], "asks": [[100.1, 1.0]]}
    assert not validator.validate_depth(2.0, book)[0]
    book2 = {"bids": [[100.0, 5.0]], "asks": [[100.1, 5.0]]}
    assert validator.validate_depth(2.0, book2)[0]
    assert not validator.validate_depth(2.0, {"bids": [], "asks": []})[0]


def test_notional(validator):
    limits = {"min_amount": 0.001, "min_cost": 10.0, "max_cost": None, "max_amount": None, "active": True}
    assert validator.validate_notional(1.0, 100.0, limits)[0]
    assert not validator.validate_notional(0.0001, 100.0, limits)[0]


def test_balance(validator):
    assert validator.validate_balance("buy", 1.0, 100.0, 150.0, 0.0)[0]
    assert not validator.validate_balance("buy", 2.0, 100.0, 150.0, 0.0)[0]
    assert validator.validate_balance("sell", 1.0, 100.0, 0.0, 2.0)[0]


def test_correlation(validator):
    assert not validator.validate_correlation(0.9)[0]
    assert validator.validate_correlation(0.5)[0]


def test_price_parity(validator):
    assert validator.validate_price_parity(100.0, 100.1)[0]
    assert not validator.validate_price_parity(100.0, 101.0)[0]