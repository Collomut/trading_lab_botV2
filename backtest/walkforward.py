"""Purged/embargoed walk-forward splitting for out-of-sample evaluation."""
from __future__ import annotations

import pandas as pd


class WalkForwardSplitter:
    """Anchored walk-forward with a purge gap before and embargo after each test block.

    The purge gap removes training rows whose forward labels would overlap the test
    window; the embargo drops initial test rows that could be contaminated by their
    own lookback into the training period. Both are configured in bars.
    """

    def __init__(
        self,
        n_splits: int = 3,
        purge_bars: int = 24,
        embargo_bars: int = 24,
    ):
        self.n_splits = max(1, int(n_splits))
        self.purge_bars = max(0, int(purge_bars))
        self.embargo_bars = max(0, int(embargo_bars))

    def split(self, df: pd.DataFrame) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
        n = len(df)
        if n < (self.n_splits + 1) * 10:
            return []
        test_size = n // (self.n_splits + 1)
        folds: list[tuple[pd.DataFrame, pd.DataFrame]] = []
        for k in range(self.n_splits):
            test_start = n - (self.n_splits - k) * test_size
            test_end = test_start + test_size
            train_end = max(0, test_start - self.purge_bars)
            train = df.iloc[:train_end]
            test = df.iloc[test_start + self.embargo_bars : test_end]
            if len(train) > 0 and len(test) > 0:
                folds.append((train, test))
        return folds


def aggregate_folds(fold_metrics: list[dict]) -> dict:
    """Summarize per-fold metrics: mean/min/max of profit factor and drawdown."""
    if not fold_metrics:
        return {}
    pfs = [m["profit_factor"] for m in fold_metrics if isinstance(m.get("profit_factor"), (int, float))]
    dds = [m["max_drawdown_pct"] for m in fold_metrics if isinstance(m.get("max_drawdown_pct"), (int, float))]
    returns = [m["total_return_pct"] for m in fold_metrics if isinstance(m.get("total_return_pct"), (int, float))]
    return {
        "folds": len(fold_metrics),
        "mean_profit_factor": round(sum(pfs) / len(pfs), 3) if pfs else None,
        "min_profit_factor": round(min(pfs), 3) if pfs else None,
        "max_drawdown_pct": round(max(dds), 3) if dds else None,
        "mean_return_pct": round(sum(returns) / len(returns), 3) if returns else None,
        "all_folds_positive": all(m.get("total_pnl", 0) > 0 for m in fold_metrics),
    }
