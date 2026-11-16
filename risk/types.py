"""Shared domain types for the risk and execution layers."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

EXIT_POLICIES = {"model_exit", "fixed_rr", "risk_managed"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Position:
    """A live (paper or real) long position."""

    symbol: str
    side: str
    entry_price: float
    amount: float
    entry_time: str
    stop_loss_price: float
    take_profit_price: float | None
    order_id: str = ""
    stop_order_id: str = ""
    stop_client_order_id: str = ""
    entry_fee_quote: float = 0.0
    highest_price: float = 0.0
    break_even_activated: bool = False
    exit_policy: str = "risk_managed"
    route: str = "legacy"
    regime: str = ""
    accounting_complete: bool = True
    simulated: bool = False
    entry_index: int = 0
    bars_held: int = 0
    atr_at_entry: float = 0.0

    @property
    def cost_basis(self) -> float:
        return self.entry_price * self.amount

    def unrealized_pnl(self, price: float) -> float:
        if self.side != "long":
            return 0.0
        return (price - self.entry_price) * self.amount

    def unrealized_pnl_pct(self, price: float) -> float:
        if self.entry_price <= 0:
            return 0.0
        if self.side != "long":
            return 0.0
        return (price - self.entry_price) / self.entry_price * 100.0

    def r_multiple(self, price: float) -> float | None:
        """Current price expressed in initial-risk (R) units."""
        risk_per_unit = self.entry_price - self.stop_loss_price if self.entry_price > self.stop_loss_price else 0.0
        if risk_per_unit <= 0:
            return None
        return (price - self.entry_price) / risk_per_unit

    def should_stop_loss(self, price: float) -> bool:
        return price <= self.stop_loss_price

    def should_take_profit(self, price: float) -> bool:
        return self.take_profit_price is not None and price >= self.take_profit_price

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Position":
        return cls(**data)


@dataclass
class TradeRecord:
    """A completed round-trip trade with full attribution."""

    symbol: str
    side: str
    entry_price: float
    exit_price: float
    amount: float
    entry_time: str
    exit_time: str
    pnl: float | None
    pnl_pct: float | None
    reason: str
    fee: float | None = 0.0
    accounting_complete: bool = True
    strategy: str = ""
    route: str = "legacy"
    regime: str = ""
    r_multiple: float | None = None
    order_id: str = ""
    simulated: bool = False

    @property
    def is_winner(self) -> bool:
        return self.accounting_complete and self.pnl is not None and self.pnl > 0

    def to_dict(self) -> dict:
        return asdict(self)


def is_finite_positive(value) -> bool:
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False
