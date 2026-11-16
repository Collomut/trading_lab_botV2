import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.schemas import BotConfig, ExchangeConfig, ModelConfig, RiskConfig, StrategyConfig
from state.sqlite_store import SQLiteStore


@pytest.fixture
def temp_store(tmp_path):
    return SQLiteStore(tmp_path / "state.sqlite3")


@pytest.fixture
def risk_config():
    return RiskConfig(
        max_risk_per_trade=1.0,
        max_notional_pct=10.0,
        stop_loss_atr_multiple=1.5,
        stop_loss_min_pct=1.5,
        stop_loss_max_pct=4.0,
        break_even_trigger_r=1.5,
        trailing_stop_atr_multiple=3.0,
        time_stop_bars=48,
        max_daily_loss_pct=3.0,
        max_rolling_drawdown_pct=5.0,
        max_consecutive_losses=3,
        rolling_pf_window=20,
        min_rolling_pf=1.0,
        max_spread_bps=20.0,
        max_slippage_bps=30.0,
        max_pairwise_correlation=0.85,
    )


@pytest.fixture
def simulated_config(risk_config, tmp_path):
    config = BotConfig(
        exchange=ExchangeConfig(paper_trading=True, paper_environment="simulated"),
        risk=risk_config,
        model=ModelConfig(model_type="sklearn", confidence_threshold=0.60, min_expected_return_pct=1.5),
        strategy=StrategyConfig(trading_pairs=["BTC/USDT", "ETH/USDT"], timeframe="1h", lookback_candles=1000),
    )
    config.dashboard.dashboard_token = "x" * 40
    config.data_dir = str(tmp_path / "data")
    return config


@pytest.fixture
def synthetic_df():
    from data.synthetic import generate_ohlcv

    return generate_ohlcv(n=4000, seed=11)
