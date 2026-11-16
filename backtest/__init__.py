"""Backtesting package."""
from backtest.baseline import BaselineEma72Strategy
from backtest.compare import HybridSizingStrategy, comparison_table, run_candidate, run_full_comparison
from backtest.engine import BacktestEngine
from backtest.execution_sim import ExecutionSimulator
from backtest.metrics import BacktestMetrics
from backtest.model_strategy import ModelStrategy
from backtest.types import BacktestResult, SignalDecision
from backtest.walkforward import WalkForwardSplitter, aggregate_folds

__all__ = [
    "BacktestEngine",
    "BacktestMetrics",
    "BacktestResult",
    "BaselineEma72Strategy",
    "ExecutionSimulator",
    "HybridSizingStrategy",
    "ModelStrategy",
    "SignalDecision",
    "WalkForwardSplitter",
    "aggregate_folds",
    "comparison_table",
    "run_candidate",
    "run_full_comparison",
]
