"""Fill normalization and fee accounting (fail-closed on ambiguity)."""
from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation


class FillNormalizer:
    """Convert exchange order responses into reconciled fills.

    Missing or malformed fee data returns ``None`` so callers halt for review
    instead of silently assuming zero commission.
    """

    @staticmethod
    def extract_fees(order: dict) -> list[dict] | None:
        if not isinstance(order, dict):
            return None
        fees = order.get("fees")
        if fees is None:
            fee = order.get("fee")
            fees = [fee] if isinstance(fee, dict) else None
        if not fees:
            fills = (order.get("info") or {}).get("fills")
            if isinstance(fills, list) and fills:
                fees = [
                    {"currency": f.get("commissionAsset"), "cost": f.get("commission")}
                    for f in fills
                ]
        if not fees:
            return None
        if not isinstance(fees, list) or any(not isinstance(f, dict) for f in fees):
            return None
        return fees

    @staticmethod
    def net_base_filled(order: dict, symbol: str) -> Decimal | None:
        base = symbol.split("/")[0]
        fees = FillNormalizer.extract_fees(order)
        if not fees:
            return None
        try:
            filled = Decimal(str(order.get("filled")))
            base_fee = sum(
                (Decimal(str(f.get("cost") or 0)) for f in fees if f.get("currency") == base),
                Decimal("0"),
            )
            net = filled - base_fee
            return net if net.is_finite() and net > 0 else None
        except (InvalidOperation, TypeError, ValueError, AttributeError):
            return None

    @staticmethod
    def fee_quote_cost(
        order: dict,
        symbol: str,
        fill_price: float,
        third_asset_prices: dict[str, float] | None = None,
    ) -> float | None:
        base, quote = symbol.split("/", 1)
        fees = FillNormalizer.extract_fees(order)
        if not fees:
            return None
        third = third_asset_prices or {}
        total = Decimal("0")
        try:
            price = Decimal(str(fill_price))
            if not price.is_finite() or price <= 0:
                return None
            for fee in fees:
                if fee.get("cost") is None:
                    return None
                cost = Decimal(str(fee["cost"] or 0))
                currency = fee.get("currency")
                if not cost.is_finite() or cost < 0:
                    return None
                if currency == quote:
                    total += cost
                elif currency == base:
                    total += cost * price
                elif currency in third:
                    p = third[currency]
                    if p is None or not math.isfinite(float(p)) or float(p) <= 0:
                        return None
                    total += cost * Decimal(str(p))
                else:
                    return None
            result = float(total)
            return result if math.isfinite(result) else None
        except (InvalidOperation, TypeError, ValueError):
            return None

    @staticmethod
    def is_confirmed_full_fill(order: dict, requested_amount: float) -> bool:
        if not isinstance(order, dict) or str(order.get("status", "")).lower() != "closed":
            return False
        try:
            filled = Decimal(str(order.get("filled")))
            requested = Decimal(str(requested_amount))
            return (
                filled.is_finite()
                and requested.is_finite()
                and filled > 0
                and requested > 0
                and filled >= requested * Decimal("0.99999999")
            )
        except (InvalidOperation, TypeError, ValueError):
            return False

    @staticmethod
    def is_terminal_zero_fill(order: dict) -> bool:
        if not isinstance(order, dict) or str(order.get("status", "")).lower() not in {
            "closed",
            "canceled",
            "rejected",
            "expired",
        }:
            return False
        try:
            filled = Decimal(str(order.get("filled") or 0))
            return filled.is_finite() and filled == 0
        except (InvalidOperation, TypeError, ValueError):
            return False

    @classmethod
    def resolve_fee_quote_cost(cls, order: dict, symbol: str, fill_price: float, exchange=None) -> float | None:
        """Use order fees first, then verified per-fill fees. Never assume zero."""
        fees = cls.extract_fees(order)
        third: dict[str, float] = {}
        if fees and exchange is not None:
            base, quote = symbol.split("/", 1)
            for f in fees:
                cur = f.get("currency")
                if cur and cur not in (base, quote):
                    try:
                        p = exchange.get_current_price(f"{cur}/{quote}")
                        if p is not None and p > 0:
                            third[cur] = float(p)
                    except Exception:
                        pass
        cost = cls.fee_quote_cost(order, symbol, fill_price, third)
        if cost is not None:
            return cost
        order_id = order.get("id") or (order.get("info") or {}).get("orderId")
        filled_value = order.get("filled")
        if exchange is None or not order_id or filled_value is None:
            return None
        try:
            expected = Decimal(str(filled_value))
            if not expected.is_finite() or expected <= 0:
                return None
            fills = exchange.fetch_order_trades(str(order_id), symbol)
        except Exception:
            return None
        if not isinstance(fills, list) or not fills:
            return None
        total_filled = Decimal("0")
        aggregated: dict[str, Decimal] = {}
        try:
            for fill in fills:
                if not isinstance(fill, dict):
                    return None
                amount = Decimal(str(fill.get("amount")))
                if not amount.is_finite() or amount <= 0:
                    return None
                total_filled += amount
                fill_fees = fill.get("fees")
                if fill_fees is None:
                    fee = fill.get("fee")
                    fill_fees = [fee] if isinstance(fee, dict) else None
                if not isinstance(fill_fees, list) or not fill_fees:
                    return None
                for fee in fill_fees:
                    if not isinstance(fee, dict) or fee.get("currency") is None or fee.get("cost") is None:
                        return None
                    cur = str(fee["currency"])
                    c = Decimal(str(fee["cost"]))
                    if not c.is_finite() or c < 0:
                        return None
                    aggregated[cur] = aggregated.get(cur, Decimal("0")) + c
            tolerance = max(Decimal("0.0000000001"), expected * Decimal("0.00000001"))
            if abs(total_filled - expected) > tolerance or not aggregated:
                return None
        except (InvalidOperation, TypeError, ValueError):
            return None
        verified = {"fees": [{"currency": c, "cost": str(v)} for c, v in aggregated.items()]}
        base, quote = symbol.split("/", 1)
        third = {}
        if exchange is not None:
            for c in aggregated:
                if c not in (base, quote):
                    try:
                        p = exchange.get_current_price(f"{c}/{quote}")
                        if p is not None and p > 0:
                            third[c] = float(p)
                    except Exception:
                        pass
        return cls.fee_quote_cost(verified, symbol, fill_price, third)
