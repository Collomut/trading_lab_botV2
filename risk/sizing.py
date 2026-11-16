"""Position sizing: volatility- and confidence-scaled fixed-fractional sizing."""
from __future__ import annotations

import math

from config.schemas import RiskConfig


class PositionSizer:
    """Compute a safe position size given equity, prices, stop, and model confidence.

    The result is the smaller of:
      * a fixed-fractional risk budget (``max_risk_per_trade`` of equity), and
      * a notional exposure cap (``max_notional_pct`` of equity),
    scaled down by confidence and volatility multipliers.
    """

    def __init__(self, config: RiskConfig):
        self.config = config

    def confidence_multiplier(self, probability: float, threshold: float) -> float:
        """Linearly scale from 0 at 50% to 1 at the entry threshold.

        A model that is barely above 0.5 receives a small allocation; a model at
        or above the configured threshold receives full size.
        """
        try:
            p = float(probability)
            t = float(threshold)
        except (TypeError, ValueError):
            return 0.0
        if not (math.isfinite(p) and math.isfinite(t)):
            return 0.0
        if t <= 0.5:
            return 1.0 if p >= t else 0.0
        if p <= 0.5:
            return 0.0
        if p >= t:
            return 1.0
        return max(0.0, min(1.0, (p - 0.5) / (t - 0.5)))

    def volatility_multiplier(
        self, target_volatility: float | None, current_volatility: float | None
    ) -> float:
        """Inverse-volatility scale bounded to [0.5, 1.0].

        Returns 1.0 (no scaling) when either input is missing or invalid so
        callers without volatility data keep prior behaviour.
        """
        if target_volatility is None or current_volatility is None:
            return 1.0
        try:
            target = float(target_volatility)
            current = float(current_volatility)
        except (TypeError, ValueError):
            return 1.0
        if not (math.isfinite(target) and math.isfinite(current)) or target <= 0 or current <= 0:
            return 1.0
        return min(1.0, max(0.5, target / current))

    def calculate(
        self,
        equity: float,
        entry_price: float,
        stop_price: float,
        *,
        probability: float = 1.0,
        confidence_threshold: float = 0.60,
        target_volatility: float | None = None,
        current_volatility: float | None = None,
        entry_fee_rate: float = 0.0,
        amount_step: float | None = None,
        min_amount: float | None = None,
        min_notional: float | None = None,
    ) -> float:
        """Return position size in base units (0.0 if the trade is rejected)."""
        try:
            equity = float(equity)
            entry_price = float(entry_price)
            stop_price = float(stop_price)
            entry_fee_rate = float(entry_fee_rate)
        except (TypeError, ValueError):
            return 0.0
        if not all(math.isfinite(v) for v in (equity, entry_price, stop_price, entry_fee_rate)):
            return 0.0
        if equity <= 0 or entry_price <= 0 or stop_price <= 0 or stop_price >= entry_price:
            return 0.0
        if entry_fee_rate < 0 or entry_fee_rate > 0.05:
            return 0.0

        risk_per_unit = (entry_price - stop_price) + entry_price * entry_fee_rate
        if risk_per_unit <= 0:
            return 0.0

        risk_amount = equity * (self.config.max_risk_per_trade / 100.0)
        base_size = risk_amount / risk_per_unit

        conf = self.confidence_multiplier(probability, confidence_threshold)
        if conf <= 0:
            return 0.0
        vol = self.volatility_multiplier(target_volatility, current_volatility)

        size = base_size * conf * vol

        # Notional exposure cap.
        max_notional = equity * (self.config.max_notional_pct / 100.0)
        size = min(size, max_notional / entry_price)

        if not math.isfinite(size) or size <= 0:
            return 0.0

        if amount_step and amount_step > 0:
            size = math.floor(size / amount_step) * amount_step

        if min_amount is not None and size < min_amount:
            return 0.0
        if min_notional is not None and size * entry_price < min_notional:
            return 0.0
        return float(size)
