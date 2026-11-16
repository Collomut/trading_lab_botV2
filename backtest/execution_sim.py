"""Execution simulation: slippage, fees, latency assumptions for backtests."""
from __future__ import annotations

import math


class ExecutionSimulator:
    """Deterministic cost model applied to every simulated fill.

    Slippage is a base component plus a square-root market-impact term driven by
    order size relative to average volume. This is intentionally conservative and
    fully disclosed in the backtest report.
    """

    def __init__(
        self,
        fee_rate: float = 0.001,
        base_slippage_bps: float = 5.0,
        impact_coefficient_bps: float = 10.0,
        latency_bars: int = 1,
    ):
        self.fee_rate = float(fee_rate)
        self.base_slippage_bps = float(base_slippage_bps)
        self.impact_coefficient_bps = float(impact_coefficient_bps)
        self.latency_bars = int(latency_bars)

    def slippage_bps(self, order_notional: float, avg_dollar_volume: float | None) -> float:
        base = self.base_slippage_bps
        if avg_dollar_volume is None or not math.isfinite(avg_dollar_volume) or avg_dollar_volume <= 0:
            return base
        ratio = max(0.0, order_notional) / avg_dollar_volume
        impact = self.impact_coefficient_bps * math.sqrt(ratio)
        return base + impact

    def buy_fill_price(self, reference_price: float, order_notional: float, adv: float | None) -> float:
        slip = self.slippage_bps(order_notional, adv) / 10000.0
        return reference_price * (1.0 + slip)

    def sell_fill_price(self, reference_price: float, order_notional: float, adv: float | None) -> float:
        slip = self.slippage_bps(order_notional, adv) / 10000.0
        return reference_price * (1.0 - slip)

    def fee(self, notional: float) -> float:
        return max(0.0, notional) * self.fee_rate
