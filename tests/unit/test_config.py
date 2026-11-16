from config.loader import REQUIRED_LIVE_CONFIRMATION, validate_config
from config.schemas import BotConfig, ExchangeConfig


def _base():
    cfg = BotConfig()
    cfg.exchange.paper_trading = True
    cfg.exchange.paper_environment = "simulated"
    cfg.dashboard.dashboard_token = "x" * 40
    return cfg


def test_default_simulated_config_is_structurally_valid():
    errors = validate_config(_base())
    assert errors == []


def test_live_trading_blocked_without_flag():
    cfg = _base()
    cfg.exchange.paper_trading = False
    cfg.exchange.allow_live_trading = False
    errors = validate_config(cfg)
    assert any("Live trading is disabled" in e for e in errors)


def test_live_trading_requires_confirmation_phrase():
    cfg = _base()
    cfg.exchange.paper_trading = False
    cfg.exchange.allow_live_trading = True
    cfg.exchange.live_confirmation = "nope"
    errors = validate_config(cfg)
    assert any("LIVE_CONFIRMATION" in e for e in errors)


def test_live_trading_with_correct_confirmation_has_no_mode_error():
    cfg = _base()
    cfg.exchange.paper_trading = False
    cfg.exchange.allow_live_trading = True
    cfg.exchange.live_confirmation = REQUIRED_LIVE_CONFIRMATION
    cfg.exchange.api_key = "k"
    cfg.exchange.api_secret = "s"
    errors = validate_config(cfg)
    assert not any("Live trading" in e for e in errors)


def test_extreme_risk_rejected():
    cfg = _base()
    cfg.risk.max_risk_per_trade = 6.0
    cfg.risk.max_notional_pct = 50.0
    cfg.risk.max_daily_loss_pct = 20.0
    errors = validate_config(cfg)
    assert any("MAX_RISK_PER_TRADE" in e for e in errors)
    assert any("MAX_NOTIONAL_PCT" in e for e in errors)
    assert any("MAX_DAILY_LOSS_PCT" in e for e in errors)


def test_stop_min_must_not_exceed_max():
    cfg = _base()
    cfg.risk.stop_loss_min_pct = 5.0
    cfg.risk.stop_loss_max_pct = 2.0
    errors = validate_config(cfg)
    assert any("STOP_LOSS_MIN_PCT" in e for e in errors)


def test_confidence_threshold_bounds():
    cfg = _base()
    cfg.model.confidence_threshold = 0.99
    assert any("CONFIDENCE_THRESHOLD" in e for e in validate_config(cfg))
    cfg.model.confidence_threshold = 0.60
    assert not any("CONFIDENCE_THRESHOLD" in e for e in validate_config(cfg))


def test_pair_validation():
    cfg = _base()
    cfg.strategy.trading_pairs = ["BTCUSDT"]
    assert any("Invalid TRADING_PAIRS" in e for e in validate_config(cfg))
    cfg.strategy.trading_pairs = ["BTC/EUR"]
    assert any("USDT-quoted" in e for e in validate_config(cfg))
    cfg.strategy.trading_pairs = ["BTC/USDT", "BTC/USDT"]
    assert any("duplicates" in e for e in validate_config(cfg))


def test_dashboard_token_required_when_requested():
    cfg = _base()
    cfg.dashboard.dashboard_token = "short"
    assert any("DASHBOARD_TOKEN" in e for e in validate_config(cfg, require_dashboard_token=True))
    cfg.dashboard.dashboard_token = "x" * 40
    assert not any("DASHBOARD_TOKEN" in e for e in validate_config(cfg, require_dashboard_token=True))


def test_non_finite_values_rejected():
    cfg = _base()
    cfg.risk.max_risk_per_trade = float("nan")
    assert any("must be finite" in e for e in validate_config(cfg))
