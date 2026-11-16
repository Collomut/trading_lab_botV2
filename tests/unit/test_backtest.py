import numpy as np
import pandas as pd
import pytest

from backtest.baseline import BaselineEma72Strategy
from backtest.engine import BacktestEngine
from backtest.metrics import BacktestMetrics
from backtest.model_strategy import ModelStrategy
from backtest.compare import run_full_comparison, comparison_table
from config.schemas import RiskConfig
from models.features import FeatureEngine
from models.sklearn_model import SklearnGradientModel
from models.trainer import ModelTrainer
from data.synthetic import generate_ohlcv


def test_metrics_profit_factor_and_drawdown():
    trades = [
        {"pnl": 100.0},
        {"pnl": -50.0},
        {"pnl": 150.0},
        {"pnl": -30.0},
    ]
    equity = [10000, 10100, 10050, 10200, 10170]
    m = BacktestMetrics(trades, equity, 10000.0)
    assert m.gross_profit == 250.0
    assert m.gross_loss == 80.0
    assert m.profit_factor == pytest.approx(3.125)
    assert m.max_loss_streak == 1


def test_backtest_no_lookahead_engine(risk_config):
    df = generate_ohlcv(n=3000, seed=5)
    strategy = BaselineEma72Strategy(min_candles=600)
    engine = BacktestEngine(strategy, risk_config, confidence_threshold=0.60, initial_balance=10000.0)
    result = engine.run(df, "BTC/USDT")
    # If the first trade's entry exists, it must occur after min_candles.
    for trade in result.trades:
        entry_idx = df.index.get_loc(pd.Timestamp(trade["entry_time"]))
        assert entry_idx >= 600


def test_baseline_runs_on_synthetic(synthetic_df):
    from backtest.compare import run_candidate
    from config.schemas import BotConfig

    cfg = BotConfig()
    result = run_candidate(BaselineEma72Strategy(min_candles=600), synthetic_df, "BTC/USDT", cfg)
    assert result.bars == len(synthetic_df)
    assert isinstance(result.trades, list)


def test_full_comparison_runs_and_report_shape():
    from config.schemas import BotConfig

    df = generate_ohlcv(n=6000, seed=7)
    cfg = BotConfig()
    split = int(len(df) * 0.6)
    trainer = ModelTrainer(FeatureEngine(), cfg.model)
    model, _ = trainer.train(df.iloc[:split], cost_pct=cfg.execution.fee_rate * 2)
    results = run_full_comparison(df.iloc[split:], "BTC/USDT", cfg, model)
    assert set(results) >= {"baseline", "challenger", "ablation_prob_only", "ablation_return_only", "ablation_model_sizing"}
    for name, res in results.items():
        assert "metrics" in res
        m = res["metrics"]
        for key in ("total_trades", "profit_factor", "max_drawdown_pct", "expectancy", "tail_loss_95"):
            assert key in m
    table = comparison_table(results)
    assert "candidate" in table and "baseline" in table


def test_model_strategy_enters_when_confident():
    """A hand-built model that always returns high probability should enter."""
    class ConstantModel:
        confidence_threshold = 0.6
        min_expected_return_pct = 1.0

        def predict(self, features):
            return 0.9, 5.0

        def predict_batch(self, X):
            return np.full(len(X), 0.9), np.full(len(X), 5.0)

        def should_enter_long(self, features):
            return True

    df = generate_ohlcv(n=1000, seed=1)
    strategy = ModelStrategy(ConstantModel(), FeatureEngine(), exit_probability=0.4, use_model_exit=False)
    strategy.prepare(df)
    decision = strategy.entry(df, 800)
    assert decision.enter
    assert decision.probability == 0.9