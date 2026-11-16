"""Typed configuration schemas for trade_v2.

Every value is sourced from the environment (or ``defaults.yaml`` fallbacks) and
validated by :func:`config.loader.load_config`. Dangerous combinations raise
rather than silently degrading to live trading.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_bool(name: str, default: bool, *, strict: bool = True) -> bool:
    """Parse booleans without silently mapping typos to a live-trading mode."""
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    accepted = {"true": True, "false": False}
    if not strict:
        accepted.update({"1": True, "0": False, "yes": True, "no": False})
    if value not in accepted:
        allowed = "true or false" if strict else "true/false, 1/0, yes/no"
        raise ValueError(f"{name} must be {allowed}; got {raw!r}")
    return accepted[value]


@dataclass
class ExchangeConfig:
    name: str = field(default_factory=lambda: _env("EXCHANGE", "binance"))
    api_key: str = field(default_factory=lambda: _env("API_KEY"))
    api_secret: str = field(default_factory=lambda: _env("API_SECRET"))
    demo_api_key: str = field(default_factory=lambda: _env("DEMO_API_KEY"))
    demo_api_secret: str = field(default_factory=lambda: _env("DEMO_API_SECRET"))
    paper_trading: bool = field(default_factory=lambda: _env_bool("PAPER_TRADING", True))
    paper_environment: str = field(
        default_factory=lambda: _env("PAPER_ENVIRONMENT", "testnet").strip().lower()
    )
    fallback_to_simulation: bool = field(
        default_factory=lambda: _env_bool("FALLBACK_TO_SIMULATION", False, strict=False)
    )
    allow_live_trading: bool = field(default_factory=lambda: _env_bool("ALLOW_LIVE_TRADING", False))
    live_confirmation: str = field(default_factory=lambda: _env("LIVE_CONFIRMATION"))


@dataclass
class RiskConfig:
    max_risk_per_trade: float = field(default_factory=lambda: _env_float("MAX_RISK_PER_TRADE", 1.0))
    max_notional_pct: float = field(default_factory=lambda: _env_float("MAX_NOTIONAL_PCT", 10.0))
    stop_loss_atr_multiple: float = field(default_factory=lambda: _env_float("STOP_LOSS_ATR_MULTIPLE", 1.5))
    stop_loss_min_pct: float = field(default_factory=lambda: _env_float("STOP_LOSS_MIN_PCT", 1.5))
    stop_loss_max_pct: float = field(default_factory=lambda: _env_float("STOP_LOSS_MAX_PCT", 4.0))
    break_even_trigger_r: float = field(default_factory=lambda: _env_float("BREAK_EVEN_TRIGGER_R", 1.5))
    trailing_stop_atr_multiple: float = field(
        default_factory=lambda: _env_float("TRAILING_STOP_ATR_MULTIPLE", 3.0)
    )
    time_stop_bars: int = field(default_factory=lambda: _env_int("TIME_STOP_BARS", 48))
    max_daily_loss_pct: float = field(default_factory=lambda: _env_float("MAX_DAILY_LOSS_PCT", 3.0))
    max_rolling_drawdown_pct: float = field(
        default_factory=lambda: _env_float("MAX_ROLLING_DRAWDOWN_PCT", 5.0)
    )
    max_consecutive_losses: int = field(default_factory=lambda: _env_int("MAX_CONSECUTIVE_LOSSES", 3))
    rolling_pf_window: int = field(default_factory=lambda: _env_int("ROLLING_PF_WINDOW", 20))
    min_rolling_pf: float = field(default_factory=lambda: _env_float("MIN_ROLLING_PF", 1.0))
    max_spread_bps: float = field(default_factory=lambda: _env_float("MAX_SPREAD_BPS", 20.0))
    max_slippage_bps: float = field(default_factory=lambda: _env_float("MAX_SLIPPAGE_BPS", 30.0))
    max_pairwise_correlation: float = field(
        default_factory=lambda: _env_float("MAX_PAIRWISE_CORRELATION", 0.85)
    )
    max_signal_fill_divergence_bps: float = field(
        default_factory=lambda: _env_float("MAX_SIGNAL_FILL_DIVERGENCE_BPS", 100.0)
    )
    max_testnet_price_divergence_pct: float = field(
        default_factory=lambda: _env_float("MAX_TESTNET_PRICE_DIVERGENCE_PCT", 0.5)
    )


@dataclass
class ModelConfig:
    model_type: str = field(default_factory=lambda: _env("MODEL_TYPE", "sklearn").strip().lower())
    model_path: str = field(default_factory=lambda: _env("MODEL_PATH", "models/artifacts/model.joblib"))
    feature_version: int = field(default_factory=lambda: _env_int("FEATURE_VERSION", 1))
    confidence_threshold: float = field(
        default_factory=lambda: _env_float("CONFIDENCE_THRESHOLD", 0.60)
    )
    min_expected_return_pct: float = field(
        default_factory=lambda: _env_float("MIN_EXPECTED_RETURN_PCT", 1.5)
    )
    calibration_method: str = field(
        default_factory=lambda: _env("CALIBRATION_METHOD", "platt").strip().lower()
    )
    model_refresh_hours: int = field(default_factory=lambda: _env_int("MODEL_REFRESH_HOURS", 168))
    horizon_bars: int = field(default_factory=lambda: _env_int("MODEL_HORIZON_BARS", 4))


@dataclass
class StrategyConfig:
    trading_pairs: list = field(
        default_factory=lambda: [p.strip() for p in _env("TRADING_PAIRS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",") if p.strip()]
    )
    timeframe: str = field(default_factory=lambda: _env("TIMEFRAME", "1h"))
    lookback_candles: int = field(default_factory=lambda: _env_int("LOOKBACK_CANDLES", 1000))
    min_volume_usdt: float = field(default_factory=lambda: _env_float("MIN_VOLUME_USDT", 10_000_000.0))


@dataclass
class ExecutionConfig:
    post_only_entries: bool = field(
        default_factory=lambda: _env_bool("POST_ONLY_ENTRIES", False, strict=False)
    )
    order_timeout_seconds: int = field(default_factory=lambda: _env_int("ORDER_TIMEOUT_SECONDS", 30))
    max_requotes: int = field(default_factory=lambda: _env_int("MAX_REQUOTES", 5))
    fee_rate: float = field(default_factory=lambda: _env_float("FEE_RATE", 0.001))
    slippage_bps: float = field(default_factory=lambda: _env_float("SLIPPAGE_BPS", 5.0))


@dataclass
class DashboardConfig:
    dashboard_token: str = field(default_factory=lambda: _env("DASHBOARD_TOKEN"))
    dashboard_port: int = field(default_factory=lambda: _env_int("DASHBOARD_PORT", 5000))


@dataclass
class NotificationConfig:
    enable_notifications: bool = field(
        default_factory=lambda: _env_bool("ENABLE_NOTIFICATIONS", True, strict=False)
    )
    telegram_bot_token: str = field(default_factory=lambda: _env("TELEGRAM_BOT_TOKEN"))
    telegram_chat_id: str = field(default_factory=lambda: _env("TELEGRAM_CHAT_ID"))
    smtp_host: str = field(default_factory=lambda: _env("SMTP_HOST"))
    smtp_port: int = field(default_factory=lambda: _env_int("SMTP_PORT", 587))
    smtp_user: str = field(default_factory=lambda: _env("SMTP_USER"))
    smtp_password: str = field(default_factory=lambda: _env("SMTP_PASSWORD"))
    alert_email: str = field(default_factory=lambda: _env("ALERT_EMAIL"))
    discord_webhook_url: str = field(default_factory=lambda: _env("DISCORD_WEBHOOK_URL"))


@dataclass
class BotConfig:
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))
    log_file: str = field(default_factory=lambda: _env("LOG_FILE", "logs/trading_bot.log"))
    data_dir: str = field(default_factory=lambda: _env("DATA_DIR", "data"))
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL"))
    initial_balance: float = field(default_factory=lambda: _env_float("INITIAL_BALANCE", 10000.0))
