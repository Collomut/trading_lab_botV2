"""Configuration loading and fail-fast validation."""
from __future__ import annotations

import math
import os
from pathlib import Path

from config.schemas import BotConfig

SUPPORTED_TIMEFRAMES = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"}
SUPPORTED_MODEL_TYPES = {"sklearn", "xgboost", "lightgbm"}
SUPPORTED_CALIBRATION = {"platt", "isotonic", "none"}
SUPPORTED_PAPER_ENVIRONMENTS = {"testnet", "demo", "simulated"}

# Operator phrase required (together with ALLOW_LIVE_TRADING) to run live.
REQUIRED_LIVE_CONFIRMATION = "I_UNDERSTAND_REAL_MONEY_IS_AT_RISK"


def load_config(*, env_path: str | None = None, require_dashboard_token: bool = False) -> BotConfig:
    """Load ``.env`` (if present), build config, validate, and return it.

    Raises :class:`ConfigError` if any validation rule fails.
    """
    try:
        from dotenv import load_dotenv

        if env_path:
            load_dotenv(env_path, override=False)
        else:
            load_dotenv(override=False)
    except Exception:  # pragma: no cover - dotenv is optional at import time
        pass

    config = BotConfig()
    errors = validate_config(config, require_dashboard_token=require_dashboard_token)
    if errors:
        raise ConfigError("; ".join(errors))
    return config


class ConfigError(ValueError):
    """Raised when configuration is invalid or unsafe."""


def _finite(value: float) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def validate_config(config: BotConfig, *, require_dashboard_token: bool = False) -> list[str]:
    """Return a list of human-readable validation errors (empty means valid).

    This function intentionally does NOT mutate the supplied config.
    """
    errors: list[str] = []
    risk = config.risk
    exchange = config.exchange
    model = config.model
    strategy = config.strategy

    # --- Exchange / mode ---
    if not exchange.paper_trading:
        if not exchange.allow_live_trading:
            errors.append("Live trading is disabled: set ALLOW_LIVE_TRADING=true only after the live-readiness checklist passes")
        elif exchange.live_confirmation != REQUIRED_LIVE_CONFIRMATION:
            errors.append(
                "Live trading requires LIVE_CONFIRMATION to equal the documented operator phrase; refuse to start"
            )
    if exchange.paper_trading and exchange.paper_environment not in SUPPORTED_PAPER_ENVIRONMENTS:
        errors.append("PAPER_ENVIRONMENT must be one of: testnet, demo, simulated")
    if exchange.paper_trading and exchange.paper_environment == "demo":
        if not exchange.demo_api_key or not exchange.demo_api_secret:
            errors.append("DEMO_API_KEY and DEMO_API_SECRET are required for Binance Demo mode")
    elif not exchange.paper_trading or exchange.paper_environment == "testnet":
        if not exchange.api_key or exchange.api_key in {"your_testnet_api_key_here", ""}:
            errors.append("API_KEY is not set")
        if not exchange.api_secret or exchange.api_secret in {"your_testnet_api_secret_here", ""}:
            errors.append("API_SECRET is not set")

    # --- Risk numeric safety ---
    for label, value in (
        ("MAX_RISK_PER_TRADE", risk.max_risk_per_trade),
        ("MAX_NOTIONAL_PCT", risk.max_notional_pct),
        ("STOP_LOSS_ATR_MULTIPLE", risk.stop_loss_atr_multiple),
        ("STOP_LOSS_MIN_PCT", risk.stop_loss_min_pct),
        ("STOP_LOSS_MAX_PCT", risk.stop_loss_max_pct),
        ("BREAK_EVEN_TRIGGER_R", risk.break_even_trigger_r),
        ("TRAILING_STOP_ATR_MULTIPLE", risk.trailing_stop_atr_multiple),
        ("MAX_DAILY_LOSS_PCT", risk.max_daily_loss_pct),
        ("MAX_ROLLING_DRAWDOWN_PCT", risk.max_rolling_drawdown_pct),
        ("MIN_ROLLING_PF", risk.min_rolling_pf),
        ("MAX_SPREAD_BPS", risk.max_spread_bps),
        ("MAX_SLIPPAGE_BPS", risk.max_slippage_bps),
        ("MAX_PAIRWISE_CORRELATION", risk.max_pairwise_correlation),
        ("MAX_SIGNAL_FILL_DIVERGENCE_BPS", risk.max_signal_fill_divergence_bps),
        ("MAX_TESTNET_PRICE_DIVERGENCE_PCT", risk.max_testnet_price_divergence_pct),
    ):
        if not _finite(value):
            errors.append(f"{label} must be finite")

    if risk.max_risk_per_trade <= 0 or risk.max_risk_per_trade > 5:
        errors.append("MAX_RISK_PER_TRADE must be > 0 and <= 5")
    if risk.max_notional_pct <= 0 or risk.max_notional_pct > 20:
        errors.append("MAX_NOTIONAL_PCT must be > 0 and <= 20")
    if not (0 < risk.stop_loss_min_pct <= risk.stop_loss_max_pct <= 10):
        errors.append("STOP_LOSS_MIN_PCT must be > 0 and <= STOP_LOSS_MAX_PCT <= 10")
    if risk.max_daily_loss_pct <= 0 or risk.max_daily_loss_pct > 10:
        errors.append("MAX_DAILY_LOSS_PCT must be > 0 and <= 10")
    if risk.max_rolling_drawdown_pct <= 0 or risk.max_rolling_drawdown_pct > 20:
        errors.append("MAX_ROLLING_DRAWDOWN_PCT must be > 0 and <= 20")
    if risk.max_consecutive_losses < 1 or risk.max_consecutive_losses > 10:
        errors.append("MAX_CONSECUTIVE_LOSSES must be between 1 and 10")
    if risk.rolling_pf_window < 5 or risk.rolling_pf_window > 200:
        errors.append("ROLLING_PF_WINDOW must be between 5 and 200")
    if risk.min_rolling_pf <= 0 or risk.min_rolling_pf > 5:
        errors.append("MIN_ROLLING_PF must be > 0 and <= 5")
    if not (0 < risk.max_spread_bps <= 200):
        errors.append("MAX_SPREAD_BPS must be > 0 and <= 200")
    if not (0 < risk.max_slippage_bps <= 200):
        errors.append("MAX_SLIPPAGE_BPS must be > 0 and <= 200")
    if not (0.5 <= risk.max_pairwise_correlation < 1):
        errors.append("MAX_PAIRWISE_CORRELATION must be in [0.5, 1)")

    # --- Model ---
    if model.model_type not in SUPPORTED_MODEL_TYPES:
        errors.append(f"MODEL_TYPE must be one of: {', '.join(sorted(SUPPORTED_MODEL_TYPES))}")
    if model.calibration_method not in SUPPORTED_CALIBRATION:
        errors.append(f"CALIBRATION_METHOD must be one of: {', '.join(sorted(SUPPORTED_CALIBRATION))}")
    if not (0.5 <= model.confidence_threshold <= 0.95):
        errors.append("CONFIDENCE_THRESHOLD must be in [0.5, 0.95]")
    if not _finite(model.min_expected_return_pct) or model.min_expected_return_pct <= 0:
        errors.append("MIN_EXPECTED_RETURN_PCT must be finite and > 0")
    if model.horizon_bars < 1 or model.horizon_bars > 100:
        errors.append("MODEL_HORIZON_BARS must be between 1 and 100")

    # --- Universe ---
    pairs = strategy.trading_pairs
    if not pairs:
        errors.append("TRADING_PAIRS must contain at least one pair")
    normalized = [p.strip().upper() for p in pairs]
    if len(set(normalized)) != len(normalized):
        errors.append("TRADING_PAIRS must not contain duplicates")
    for pair in normalized:
        parts = pair.split("/")
        if len(parts) != 2 or not all(parts):
            errors.append(f"Invalid TRADING_PAIRS entry {pair!r}: use BASE/QUOTE")
        elif parts[1] != "USDT":
            errors.append(f"All pairs must be USDT-quoted; got {pair!r}")
    if strategy.timeframe not in SUPPORTED_TIMEFRAMES:
        errors.append(f"TIMEFRAME must be one of: {', '.join(sorted(SUPPORTED_TIMEFRAMES))}")
    if not (100 <= strategy.lookback_candles <= 5000):
        errors.append("LOOKBACK_CANDLES must be between 100 and 5000")

    # --- Dashboard ---
    if require_dashboard_token and len(config.dashboard.dashboard_token) < 32:
        errors.append("DASHBOARD_TOKEN must be at least 32 characters")

    # --- Initial balance ---
    if not _finite(config.initial_balance) or config.initial_balance <= 0:
        errors.append("INITIAL_BALANCE must be finite and > 0")

    return errors


def validate_model_artifact(config: BotConfig, *, base_dir: str | Path = ".") -> list[str]:
    """Check that the configured model artifact exists (live/paper modes only)."""
    errors: list[str] = []
    path = Path(base_dir) / config.model.model_path
    if not path.exists():
        errors.append(
            f"MODEL_PATH does not exist: {path}. Train a model first (scripts/train_model.py)."
        )
    return errors
