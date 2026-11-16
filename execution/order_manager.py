"""Order lifecycle with idempotency and reconciliation journaling."""
from __future__ import annotations

import hashlib
import logging
from decimal import Decimal, InvalidOperation

from state.store import TERMINAL_STATES, StateStore

logger = logging.getLogger("trade_v2.orders")

_STATUS_MAP = {
    "closed": "FILLED",
    "open": "OPEN",
    "new": "OPEN",
    "partially_filled": "PARTIALLY_FILLED",
    "canceled": "CANCELED",
    "rejected": "REJECTED",
    "expired": "EXPIRED",
}


class OrderManager:
    def __init__(self, store: StateStore, exchange):
        self.store = store
        self.exchange = exchange

    @staticmethod
    def client_order_id(symbol: str, side: str, decision_key: str) -> str:
        digest = hashlib.sha256(f"{symbol}|{side}|{decision_key}".encode()).hexdigest()[:28]
        return f"cb{digest}"

    def submit_market(self, symbol: str, side: str, amount, decision_key: str):
        """Submit a market order, journaling intent and every known outcome.

        Returns ``(order, client_order_id)``. Raises ``RuntimeError`` when the
        outcome is ambiguous so the caller must halt and reconcile.
        """
        try:
            amount_decimal = Decimal(str(amount))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("Order amount must be a finite positive decimal") from exc
        if not amount_decimal.is_finite() or amount_decimal <= 0:
            raise ValueError("Order amount must be a finite positive decimal")

        client_id = self.client_order_id(symbol, side, str(decision_key))
        self.store.create_order_intent(
            client_id, symbol, side, format(amount_decimal, "f"),
            {"symbol": symbol, "side": side, "amount": format(amount_decimal, "f")},
        )
        self.store.update_order(client_id, "SUBMITTED")
        try:
            submit = self.exchange.place_market_buy if side == "buy" else self.exchange.place_market_sell
            order = submit(symbol, format(amount_decimal, "f"), client_id)
        except Exception as submit_error:
            self.store.update_order(client_id, "UNKNOWN")
            try:
                order = self.exchange.fetch_order_by_client_id(client_id, symbol)
                if not order:
                    raise RuntimeError("order not returned by reconciliation")
            except Exception as reconcile_error:
                raise RuntimeError("Order submission outcome unknown; operator reconciliation required") from submit_error

        if not order:
            self.store.update_order(client_id, "REJECTED", response={"result": "rejected_without_order"})
            self.store.mark_order_applied(client_id)
            return None, client_id

        state = _STATUS_MAP.get(str(order.get("status", "")).lower(), "UNKNOWN")
        filled = order.get("filled") or 0
        if state in {"OPEN", "PARTIALLY_FILLED"}:
            order_id = str(order.get("id") or "")
            if not order_id:
                state = "UNKNOWN"
            else:
                self.exchange.cancel_order(order_id, symbol)
                try:
                    order = self.exchange.fetch_order(order_id, symbol)
                    state = _STATUS_MAP.get(str(order.get("status", "")).lower(), "UNKNOWN")
                    filled = order.get("filled") or 0
                except Exception:
                    state = "UNKNOWN"
            if state in {"OPEN", "PARTIALLY_FILLED"} and Decimal(str(filled)) > 0:
                state = "PARTIALLY_FILLED"
        if state in {"FILLED", "CANCELED", "EXPIRED"} and Decimal(str(filled)) > 0 and Decimal(str(filled)) < amount_decimal * Decimal("0.99999999"):
            state = "PARTIAL_CLOSED"
        average = order.get("average") or order.get("price")
        self.store.update_order(
            client_id, state, exchange_order_id=order.get("id"), filled=filled, average=average, response=order
        )
        return order, client_id

    def mark_applied(self, client_id: str) -> None:
        try:
            self.store.mark_order_applied(client_id)
        except Exception:
            logger.warning("Could not mark order %s applied", client_id)
