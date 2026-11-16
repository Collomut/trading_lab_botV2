"""Backtest performance metrics."""
from __future__ import annotations

import math

import numpy as np


class BacktestMetrics:
    """Compute the required comparison metrics from a trade list + equity curve."""

    def __init__(self, trades: list[dict], equity_curve: list[float], initial_balance: float):
        self.trades = [t for t in trades if t.get("pnl") is not None]
        self.equity_curve = list(equity_curve) or [initial_balance]
        self.initial_balance = float(initial_balance)

    # -- core ---------------------------------------------------------------
    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def winners(self) -> list[dict]:
        return [t for t in self.trades if t["pnl"] > 0]

    @property
    def losers(self) -> list[dict]:
        return [t for t in self.trades if t["pnl"] < 0]

    @property
    def gross_profit(self) -> float:
        return float(sum(t["pnl"] for t in self.winners))

    @property
    def gross_loss(self) -> float:
        return float(-sum(t["pnl"] for t in self.losers))

    @property
    def total_pnl(self) -> float:
        return float(sum(t["pnl"] for t in self.trades))

    @property
    def profit_factor(self) -> float | None:
        gp = self.gross_profit
        gl = self.gross_loss
        if gl > 0:
            return gp / gl
        if gp > 0:
            return float("inf")
        return None

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return len(self.winners) / len(self.trades) * 100.0

    @property
    def avg_win(self) -> float:
        return self.gross_profit / len(self.winners) if self.winners else 0.0

    @property
    def avg_loss(self) -> float:
        return -self.gross_loss / len(self.losers) if self.losers else 0.0

    @property
    def payoff_ratio(self) -> float | None:
        if self.avg_loss == 0:
            return None
        return self.avg_win / abs(self.avg_loss)

    @property
    def expectancy(self) -> float:
        if not self.trades:
            return 0.0
        wr = self.win_rate / 100.0
        return wr * self.avg_win + (1 - wr) * self.avg_loss

    @property
    def breakeven_win_rate(self) -> float | None:
        """Win rate required for zero expectancy at the observed payoff ratio."""
        if self.avg_win <= 0 or self.avg_loss >= 0:
            return None
        return abs(self.avg_loss) / (self.avg_win + abs(self.avg_loss)) * 100.0

    @property
    def worst_trade(self) -> float:
        return float(min((t["pnl"] for t in self.trades), default=0.0))

    @property
    def best_trade(self) -> float:
        return float(max((t["pnl"] for t in self.trades), default=0.0))

    @property
    def max_loss_streak(self) -> int:
        streak = best = 0
        for t in self.trades:
            if t["pnl"] < 0:
                streak += 1
                best = max(best, streak)
            else:
                streak = 0
        return best

    @property
    def tail_loss_95(self) -> float:
        """95th-percentile loss magnitude (positive number)."""
        losses = [-t["pnl"] for t in self.trades if t["pnl"] < 0]
        if not losses:
            return 0.0
        return float(np.percentile(losses, 95))

    # -- equity-curve based ------------------------------------------------
    @property
    def max_drawdown_pct(self) -> float:
        peak = self.equity_curve[0]
        max_dd = 0.0
        for equity in self.equity_curve:
            peak = max(peak, equity)
            if peak > 0:
                dd = (peak - equity) / peak * 100.0
                max_dd = max(max_dd, dd)
        return max_dd

    @property
    def total_return_pct(self) -> float:
        if self.initial_balance <= 0:
            return 0.0
        return (self.equity_curve[-1] - self.initial_balance) / self.initial_balance * 100.0

    @property
    def sharpe_ratio(self) -> float | None:
        if len(self.equity_curve) < 3:
            return None
        returns = np.diff(self.equity_curve) / np.asarray(self.equity_curve[:-1])
        if returns.std() == 0:
            return None
        # Annualize assuming hourly bars is not safe for arbitrary timeframes; report per-bar.
        return float(returns.mean() / returns.std() * math.sqrt(len(returns)))

    @property
    def calmar_ratio(self) -> float | None:
        mdd = self.max_drawdown_pct
        if mdd <= 0:
            return None
        return self.total_return_pct / mdd

    def to_dict(self) -> dict:
        return {
            "total_trades": self.total_trades,
            "winners": len(self.winners),
            "losers": len(self.losers),
            "gross_profit": round(self.gross_profit, 4),
            "gross_loss": round(self.gross_loss, 4),
            "total_pnl": round(self.total_pnl, 4),
            "profit_factor": round(self.profit_factor, 4) if isinstance(self.profit_factor, float) and math.isfinite(self.profit_factor) else self.profit_factor,
            "win_rate": round(self.win_rate, 2),
            "avg_win": round(self.avg_win, 4),
            "avg_loss": round(self.avg_loss, 4),
            "payoff_ratio": round(self.payoff_ratio, 4) if self.payoff_ratio is not None else None,
            "expectancy": round(self.expectancy, 4),
            "breakeven_win_rate": round(self.breakeven_win_rate, 2) if self.breakeven_win_rate is not None else None,
            "worst_trade": round(self.worst_trade, 4),
            "best_trade": round(self.best_trade, 4),
            "max_loss_streak": self.max_loss_streak,
            "tail_loss_95": round(self.tail_loss_95, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 3),
            "total_return_pct": round(self.total_return_pct, 3),
            "sharpe_ratio": round(self.sharpe_ratio, 3) if self.sharpe_ratio is not None else None,
            "calmar_ratio": round(self.calmar_ratio, 3) if self.calmar_ratio is not None else None,
        }
