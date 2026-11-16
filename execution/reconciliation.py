"""Account/position/stop reconciliation."""
from __future__ import annotations

import logging

logger = logging.getLogger("trade_v2.reconciliation")


class Reconciler:
    """Verify local state matches the exchange before allowing entries."""

    def __init__(self, store, risk_manager, exchange):
        self.store = store
        self.risk_manager = risk_manager
        self.exchange = exchange

    def reconcile(self) -> tuple[bool, str]:
        try:
            _balance, open_orders = self.exchange.fetch_account_snapshot()
        except Exception as exc:
            return False, f"account snapshot unavailable ({type(exc).__name__})"

        if self.store.unresolved_orders():
            return False, "unresolved local order intent exists"

        expected_ids = {
            str(pos.stop_order_id) for pos in self.risk_manager.open_positions.values() if pos.stop_order_id
        }
        expected_client_ids = {
            str(pos.stop_client_order_id)
            for pos in self.risk_manager.open_positions.values()
            if pos.stop_client_order_id
        }
        for order in open_orders:
            order_id = str(order.get("id", ""))
            client_id = str(order.get("clientOrderId", ""))
            if order_id not in expected_ids and client_id not in expected_client_ids:
                return False, "unreconciled open exchange order exists"

        for symbol, position in self.risk_manager.open_positions.items():
            if not position.stop_order_id or not position.stop_client_order_id:
                return False, f"tracked position {symbol} has no persisted exchange stop"
        return True, ""
