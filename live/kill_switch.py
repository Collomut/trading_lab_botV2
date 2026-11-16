"""Automatic and manual trading halts."""
from __future__ import annotations

import logging

logger = logging.getLogger("trade_v2.kill_switch")


class KillSwitch:
    def __init__(self, risk_manager, config):
        self.risk = risk_manager
        self.config = config

    def rolling_profit_factor(self) -> float | None:
        pnls = [t.pnl for t in self.risk.trade_history if t.pnl is not None]
        return self.risk.breakers.rolling_profit_factor(pnls, self.config.risk.rolling_pf_window)

    def evaluate(self, equity: float) -> tuple[bool, str]:
        """Return ``(halted, reason)`` after evaluating all soft breakers."""
        self.risk.monitor_equity(equity)
        pf = self.rolling_profit_factor()
        if pf is not None and self.risk.breakers.rolling_pf_tripped(pf):
            return True, f"Rolling profit factor {pf:.2f} below {self.config.risk.min_rolling_pf}"
        if self.risk.state.halted:
            return True, self.risk.state.halt_reason
        return False, ""

    def emergency_stop(self, reason: str = "Emergency stop requested by operator") -> None:
        self.risk.halt(reason)

    def manual_resume(self, *, account_clean: bool, reconciled: bool) -> bool:
        """Resume only after the operator confirms a clean, reconciled, flat account."""
        if not account_clean or not reconciled:
            return False
        if self.risk.open_positions:
            return False
        if self.risk.store.unresolved_orders():
            return False
        return self.risk.resume()
