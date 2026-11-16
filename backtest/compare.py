"""Backtest comparison: baseline vs AI challenger vs ablations."""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.baseline import BaselineEma72Strategy
from backtest.engine import BacktestEngine
from backtest.execution_sim import ExecutionSimulator
from backtest.model_strategy import ModelStrategy
from backtest.types import BacktestResult, SignalDecision
from config.schemas import BotConfig
from models.features import FeatureEngine
from models.model import BaseModel


class HybridSizingStrategy:
    """Ablation: deterministic baseline entries, model-scaled position size only.

    Isolates whether the model adds value as a sizing/confidence signal rather than
    as the primary entry decision.
    """

    name = "ablation_baseline_entries_model_sizing"

    def __init__(self, model: BaseModel, feature_engine: FeatureEngine):
        self.baseline = BaselineEma72Strategy()
        self.model = model
        self.feature_engine = feature_engine
        self._inner = ModelStrategy(model, feature_engine)

    def prepare(self, df) -> None:
        self.baseline.prepare(df)
        self._inner.prepare(df)

    def entry(self, df, i: int) -> SignalDecision:
        decision = self.baseline.entry(df, i)
        if not decision.enter:
            return decision
        if self._inner._prepared and i < len(df) and np.isfinite(self._inner._prob.iloc[i]):
            prob = float(self._inner._prob.iloc[i])
            decision.probability = prob
            decision.reason = f"{decision.reason} | model p={prob:.3f}"
        return decision

    def exit(self, df, i: int, position) -> bool:
        return self.baseline.exit(df, i, position)


def _engine_for(strategy, config: BotConfig, initial_balance: float) -> BacktestEngine:
    execution = ExecutionSimulator(
        fee_rate=config.execution.fee_rate,
        base_slippage_bps=config.execution.slippage_bps,
    )
    return BacktestEngine(
        strategy,
        config.risk,
        confidence_threshold=config.model.confidence_threshold,
        execution=execution,
        initial_balance=initial_balance,
        fee_rate=config.execution.fee_rate,
    )


def run_candidate(
    strategy,
    df: pd.DataFrame,
    symbol: str,
    config: BotConfig,
    *,
    initial_balance: float = 10000.0,
) -> BacktestResult:
    engine = _engine_for(strategy, config, initial_balance)
    return engine.run(df, symbol)


def run_full_comparison(
    df: pd.DataFrame,
    symbol: str,
    config: BotConfig,
    model: BaseModel,
    *,
    initial_balance: float = 10000.0,
    include_ablations: bool = True,
) -> dict:
    """Run baseline, challenger, and ablations on identical data and costs."""
    feature_engine = FeatureEngine(config.model.feature_version)
    results: dict[str, BacktestResult] = {}

    baseline = BaselineEma72Strategy()
    results["baseline"] = run_candidate(baseline, df, symbol, config, initial_balance=initial_balance)

    challenger = ModelStrategy(model, feature_engine, gate_mode="full")
    results["challenger"] = run_candidate(challenger, df, symbol, config, initial_balance=initial_balance)

    if include_ablations:
        prob_only = ModelStrategy(model, feature_engine, gate_mode="prob_only")
        results["ablation_prob_only"] = run_candidate(
            prob_only, df, symbol, config, initial_balance=initial_balance
        )
        return_only = ModelStrategy(model, feature_engine, gate_mode="return_only")
        results["ablation_return_only"] = run_candidate(
            return_only, df, symbol, config, initial_balance=initial_balance
        )
        hybrid = HybridSizingStrategy(model, feature_engine)
        results["ablation_model_sizing"] = run_candidate(
            hybrid, df, symbol, config, initial_balance=initial_balance
        )

    return {name: result.to_dict() for name, result in results.items()}


def comparison_table(results: dict) -> str:
    """Render a compact side-by-side text table for the required metrics."""
    headers = [
        "candidate",
        "trades",
        "PF",
        "win%",
        "avg_win",
        "avg_loss",
        "payoff",
        "expect",
        "maxDD%",
        "return%",
        "calmar",
        "tail95",
    ]
    rows = [headers]
    for name, result in results.items():
        m = result["metrics"]
        rows.append(
            [
                name,
                m.get("total_trades", 0),
                m.get("profit_factor"),
                m.get("win_rate", 0),
                m.get("avg_win", 0),
                m.get("avg_loss", 0),
                m.get("payoff_ratio"),
                m.get("expectancy", 0),
                m.get("max_drawdown_pct", 0),
                m.get("total_return_pct", 0),
                m.get("calmar_ratio"),
                m.get("tail_loss_95", 0),
            ]
        )
    widths = [max(len(str(row[c])) for row in rows) for c in range(len(headers))]
    lines = []
    for idx, row in enumerate(rows):
        line = " | ".join(str(row[c]).ljust(widths[c]) for c in range(len(headers)))
        lines.append(line)
        if idx == 0:
            lines.append("-+-".join("-" * widths[c] for c in range(len(headers))))
    return "\n".join(lines)
