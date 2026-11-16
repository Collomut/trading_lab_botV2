import pytest

from backtest.walkforward import WalkForwardSplitter, aggregate_folds
from data.synthetic import generate_ohlcv


def test_walkforward_no_overlap_with_purge_and_embargo():
    import pandas as pd

    df = generate_ohlcv(n=2000, seed=1)
    splitter = WalkForwardSplitter(n_splits=3, purge_bars=24, embargo_bars=12)
    folds = splitter.split(df)
    assert len(folds) == 3
    for train, test in folds:
        # Train and test must be disjoint; the test block starts at least purge+embargo after train.
        assert train.index[-1] < test.index[0]
        gap = (test.index[0] - train.index[-1]).total_seconds()
        assert gap >= 36 * 3600


def test_aggregate_folds():
    metrics = [
        {"profit_factor": 1.5, "max_drawdown_pct": 5.0, "total_return_pct": 10.0, "total_pnl": 100},
        {"profit_factor": 1.8, "max_drawdown_pct": 3.0, "total_return_pct": 12.0, "total_pnl": 120},
    ]
    summary = aggregate_folds(metrics)
    assert summary["folds"] == 2
    assert summary["mean_profit_factor"] == pytest.approx(1.65)
    assert summary["min_profit_factor"] == 1.5
    assert summary["all_folds_positive"] is True