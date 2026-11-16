"""Persisted risk state: daily loss, rolling peak, route losses, halt status."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from state.store import StateStore

STATE_KEY = "risk_state"


class RiskState:
    """Durable risk bookkeeping.

    Field semantics:
      * ``daily_loss``  — realized P&L for the current UTC day (negative = loss).
      * ``daily_starting_equity`` — equity at the first observation of the day.
      * ``rolling_peak_equity`` — high-water mark used for drawdown.
      * ``consecutive_losses`` — global legacy streak.
      * ``route_losses`` — per-route loss streak.
      * ``route_halted`` — per-route halt reason (empty = active).
      * ``halted`` / ``halt_reason`` — global halt latch.
    """

    def __init__(self, store: StateStore):
        self.store = store
        self._date = datetime.now(timezone.utc).date().isoformat()
        self.daily_loss = 0.0
        self.daily_starting_equity = 0.0
        self.rolling_peak_equity = 0.0
        self.consecutive_losses = 0
        self.route_losses: dict[str, int] = {}
        self.route_halted: dict[str, str] = {}
        self.halted = False
        self.halt_reason = ""
        self.equity_basis = "bot_managed_v1"
        self._load()

    # -- persistence --------------------------------------------------------
    def _load(self) -> None:
        data = self.store.read_state(STATE_KEY)
        if not isinstance(data, dict):
            return
        try:
            stored_date = str(data.get("date", ""))
            today = datetime.now(timezone.utc).date().isoformat()
            self.daily_loss = float(data.get("daily_loss", 0.0))
            self.daily_starting_equity = float(data.get("daily_starting_equity", 0.0))
            self.rolling_peak_equity = float(data.get("rolling_peak_equity", 0.0))
            self.consecutive_losses = int(data.get("consecutive_losses", 0))
            route_losses = data.get("route_losses", {})
            route_halted = data.get("route_halted", {})
            if isinstance(route_losses, dict):
                self.route_losses = {str(k): int(v) for k, v in route_losses.items() if int(v) >= 0}
            if isinstance(route_halted, dict):
                self.route_halted = {str(k): str(v)[:500] for k, v in route_halted.items() if v}
            self.halted = bool(data.get("halted", False))
            self.halt_reason = str(data.get("halt_reason", ""))
            self.equity_basis = str(data.get("equity_basis", self.equity_basis))
            if stored_date != today:
                # Daily anchors reset; safety halts persist across day boundaries.
                self.daily_loss = 0.0
                self.daily_starting_equity = 0.0
                self._date = today
                if self.halted and self._is_daily_reset_halt(self.halt_reason):
                    self.halted = False
                    self.halt_reason = ""
        except (TypeError, ValueError):
            # Corrupt state must fail closed.
            self.halted = True
            self.halt_reason = "Risk state is unreadable; operator reconciliation required"

    def persist(self) -> None:
        self.store.write_state(
            STATE_KEY,
            {
                "date": datetime.now(timezone.utc).date().isoformat(),
                "daily_loss": self.daily_loss,
                "daily_starting_equity": self.daily_starting_equity,
                "rolling_peak_equity": self.rolling_peak_equity,
                "consecutive_losses": self.consecutive_losses,
                "route_losses": self.route_losses,
                "route_halted": self.route_halted,
                "halted": self.halted,
                "halt_reason": self.halt_reason,
                "equity_basis": self.equity_basis,
            },
        )

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _is_daily_reset_halt(reason: str) -> bool:
        return reason.startswith(("Daily loss limit reached", "Daily equity drawdown limit reached"))

    def reset_daily_if_needed(self) -> bool:
        today = datetime.now(timezone.utc).date().isoformat()
        if today == self._date:
            return False
        self.daily_loss = 0.0
        self.daily_starting_equity = 0.0
        self._date = today
        if self.halted and self._is_daily_reset_halt(self.halt_reason):
            self.halted = False
            self.halt_reason = ""
        self.persist()
        return True

    def observe_equity(self, equity: float) -> None:
        """Update the daily anchor and rolling high-water mark."""
        if not math.isfinite(equity) or equity <= 0:
            return
        if self.daily_starting_equity <= 0:
            self.daily_starting_equity = equity
        self.rolling_peak_equity = max(self.rolling_peak_equity, equity)

    def record_trade_pnl(self, pnl: float, route: str) -> None:
        self.daily_loss += pnl
        if route == "legacy":
            self.consecutive_losses = self.consecutive_losses + 1 if pnl < 0 else 0
        self.route_losses[route] = self.route_losses.get(route, 0) + 1 if pnl < 0 else 0
