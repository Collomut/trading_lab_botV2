"""Stop-loss, break-even, trailing, and time-stop calculations."""
from __future__ import annotations

import math

from config.schemas import RiskConfig
from risk.types import Position


class StopManager:
    """Stateless stop calculations; the manager applies them to positions."""

    def __init__(self, config: RiskConfig):
        self.config = config

    def initial_stop(self, entry_price: float, atr: float) -> float:
        """ATR-based stop clamped between the configured min and max percentages."""
        entry = float(entry_price)
        if not math.isfinite(entry) or entry <= 0:
            return 0.0
        min_dist = entry * (self.config.stop_loss_min_pct / 100.0)
        max_dist = entry * (self.config.stop_loss_max_pct / 100.0)
        if atr is not None and math.isfinite(float(atr)) and float(atr) > 0:
            atr_dist = float(atr) * self.config.stop_loss_atr_multiple
            dist = max(min_dist, min(max_dist, atr_dist))
        else:
            dist = min_dist
        stop = entry - dist
        return float(stop) if stop > 0 else 0.0

    def break_even_stop(
        self, position: Position, current_price: float
    ) -> tuple[float, bool]:
        """Move the stop to entry (plus fee buffer) once the trigger R is reached.

        Returns ``(new_stop, activated)``; the new stop is never below the current
        stop (one-way ratchet) and never below entry once activated.
        """
        current_stop = position.stop_loss_price
        r = position.r_multiple(current_price)
        if r is None or r < self.config.break_even_trigger_r:
            return current_stop, False
        if position.break_even_activated:
            return current_stop, True
        fee_buffer = position.entry_price * 0.001
        candidate = position.entry_price + fee_buffer
        new_stop = max(current_stop, candidate)
        if new_stop >= current_price:
            # Never place a stop at/above the market; fall back to entry.
            new_stop = max(current_stop, position.entry_price)
        return float(new_stop), True

    def trailing_stop(
        self, position: Position, current_price: float, atr: float
    ) -> float:
        """Chandelier-style trail below the highest price; only moves up."""
        current_stop = position.stop_loss_price
        if atr is None or not math.isfinite(float(atr)) or float(atr) <= 0:
            return current_stop
        highest = max(position.highest_price, current_price)
        trail = highest - float(atr) * self.config.trailing_stop_atr_multiple
        return float(max(current_stop, trail))

    def time_stop_exit(self, position: Position, current_price: float) -> bool:
        """True if the position has exceeded its bar budget without >= 0.5R progress."""
        if position.bars_held < self.config.time_stop_bars:
            return False
        r = position.r_multiple(current_price)
        return r is not None and r < 0.5
