"""Pre-trade validation: spread, depth, notional, balance, correlation, parity."""
from __future__ import annotations

import math

from config.schemas import BotConfig


class PreTradeValidator:
    """All checks run before any order is submitted.

    Any failure blocks the trade. The validator never mutates state; it only
    inspects the supplied snapshot.
    """

    def __init__(self, config: BotConfig):
        self.config = config

    def validate_spread(self, spread_bps: float) -> tuple[bool, str]:
        if spread_bps is None or not math.isfinite(spread_bps):
            return False, "spread unavailable"
        if spread_bps > self.config.risk.max_spread_bps:
            return False, f"spread {spread_bps:.2f} bps exceeds {self.config.risk.max_spread_bps} bps"
        return True, ""

    def validate_depth(self, amount: float, order_book: dict) -> tuple[bool, str]:
        try:
            bids = order_book.get("bids", [])
            asks = order_book.get("asks", [])
            if not bids or not asks:
                return False, "order book unavailable"
            best_ask = float(asks[0][0])
            cap = best_ask * (1 + self.config.risk.max_slippage_bps / 10000.0)
            available = 0.0
            for price, qty in asks:
                p = float(price)
                q = float(qty)
                if not (math.isfinite(p) and math.isfinite(q)) or p <= 0 or q < 0:
                    return False, "invalid order-book depth"
                if p <= cap:
                    available += q
            if available < amount:
                return False, "insufficient visible depth within slippage limit"
            return True, ""
        except (TypeError, ValueError, IndexError):
            return False, "invalid order book"

    def validate_notional(
        self, amount: float, price: float, limits: dict
    ) -> tuple[bool, str]:
        try:
            notional = float(amount) * float(price)
        except (TypeError, ValueError):
            return False, "invalid notional"
        if not math.isfinite(notional) or notional <= 0:
            return False, "invalid notional"
        min_amount = limits.get("min_amount") or 0
        max_amount = limits.get("max_amount")
        min_cost = limits.get("min_cost") or 0
        max_cost = limits.get("max_cost")
        if not limits.get("active", True):
            return False, "market is not active"
        if amount < min_amount:
            return False, "below minimum order amount"
        if max_amount and amount > max_amount:
            return False, "above maximum order amount"
        if notional < min_cost:
            return False, "below minimum notional"
        if max_cost and notional > max_cost:
            return False, "above maximum notional"
        return True, ""

    def validate_balance(
        self, side: str, amount: float, price: float, free_quote: float, free_base: float
    ) -> tuple[bool, str]:
        if side == "buy" and amount * price > free_quote + 1e-9:
            return False, "insufficient quote balance"
        if side == "sell" and amount > free_base + 1e-9:
            return False, "insufficient base balance"
        return True, ""

    def validate_correlation(self, correlation: float | None) -> tuple[bool, str]:
        if correlation is None:
            return True, ""  # insufficient data is handled by caller policy
        if correlation >= self.config.risk.max_pairwise_correlation:
            return False, f"correlation {correlation:.2f} exceeds {self.config.risk.max_pairwise_correlation}"
        return True, ""

    def validate_price_parity(self, paper_price: float, public_price: float | None) -> tuple[bool, str]:
        if public_price is None or public_price <= 0:
            return False, "public market price unavailable for parity check"
        divergence = abs(paper_price - public_price) / public_price * 100.0
        if divergence > self.config.risk.max_testnet_price_divergence_pct:
            return False, f"paper/public price divergence {divergence:.3f}% exceeds limit"
        return True, ""
