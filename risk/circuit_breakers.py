"""Circuit breakers and halt conditions."""
from __future__ import annotations

from config.schemas import RiskConfig


class CircuitBreakers:
    """Evaluate the hard risk latches.

    Each method returns ``True`` when the breaker has tripped. The manager turns
    a tripped breaker into a durable halt and (for route-scoped breakers) pauses
    only that route.
    """

    def __init__(self, config: RiskConfig):
        self.config = config

    def daily_loss_tripped(self, daily_loss: float, starting_equity: float) -> bool:
        if starting_equity <= 0:
            return False
        drawdown_pct = max(0.0, -daily_loss) / starting_equity * 100.0
        return drawdown_pct >= self.config.max_daily_loss_pct

    def rolling_drawdown_tripped(self, equity: float, peak_equity: float) -> bool:
        if peak_equity <= 0:
            return False
        drawdown_pct = max(0.0, (peak_equity - equity) / peak_equity * 100.0)
        return drawdown_pct >= self.config.max_rolling_drawdown_pct

    def consecutive_losses_tripped(self, losses: int) -> bool:
        return losses >= self.config.max_consecutive_losses

    def rolling_pf_tripped(self, rolling_pf: float | None) -> bool:
        if rolling_pf is None:
            return False
        return rolling_pf < self.config.min_rolling_pf

    def slippage_tripped(self, divergence_bps: float) -> bool:
        return divergence_bps > self.config.max_signal_fill_divergence_bps

    @staticmethod
    def rolling_profit_factor(pnls: list[float], window: int) -> float | None:
        """Profit factor over the most recent ``window`` realized trades."""
        if not pnls:
            return None
        recent = pnls[-window:]
        gross_profit = sum(p for p in recent if p > 0)
        gross_loss = -sum(p for p in recent if p < 0)
        if gross_loss > 0:
            return gross_profit / gross_loss
        if gross_profit > 0:
            return float("inf")
        return None
