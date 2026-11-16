"""Backtest result types and the strategy protocol."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class SignalDecision:
    """One entry decision produced from a closed-candle window."""

    enter: bool
    probability: float = 1.0
    expected_return_pct: float = 0.0
    stop_ref: float | None = None
    atr: float = 0.0
    take_profit_atr_multiple: float | None = None
    reason: str = ""


@dataclass
class BacktestResult:
    """Aggregated results for one symbol/candidate run."""

    candidate: str
    symbol: str
    initial_balance: float
    final_balance: float
    trades: list[dict] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    bars: int = 0
    bars_in_market: int = 0
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "candidate": self.candidate,
            "symbol": self.symbol,
            "initial_balance": self.initial_balance,
            "final_balance": self.final_balance,
            "trades": self.trades,
            "bars": self.bars,
            "bars_in_market": self.bars_in_market,
            "metrics": self.metrics,
        }


class Strategy(Protocol):
    """Decision interface shared by the deterministic baseline and the model.

    ``prepare`` may precompute indicator/feature columns once for efficiency.
    ``entry`` and ``exit`` must use only rows ``<= i`` (closed candles).
    """

    name: str

    def prepare(self, df) -> None: ...

    def entry(self, df, i: int) -> SignalDecision: ...

    def exit(self, df, i: int, position) -> bool: ...
