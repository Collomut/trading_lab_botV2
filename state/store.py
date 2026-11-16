"""Abstract state store interface."""
from __future__ import annotations

from abc import ABC, abstractmethod

# Order-state machine shared by the store and the order manager.
ORDER_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"SUBMITTED", "UNKNOWN", "REJECTED"},
    "SUBMITTED": {
        "UNKNOWN",
        "OPEN",
        "PARTIALLY_FILLED",
        "PARTIAL_CLOSED",
        "FILLED",
        "CANCELED",
        "REJECTED",
        "EXPIRED",
    },
    "UNKNOWN": {
        "UNKNOWN",
        "OPEN",
        "PARTIALLY_FILLED",
        "PARTIAL_CLOSED",
        "FILLED",
        "CANCELED",
        "REJECTED",
        "EXPIRED",
    },
    "OPEN": {
        "UNKNOWN",
        "OPEN",
        "PARTIALLY_FILLED",
        "PARTIAL_CLOSED",
        "FILLED",
        "CANCELED",
        "REJECTED",
        "EXPIRED",
    },
    "PARTIALLY_FILLED": {
        "UNKNOWN",
        "PARTIALLY_FILLED",
        "PARTIAL_CLOSED",
        "FILLED",
        "CANCELED",
        "REJECTED",
        "EXPIRED",
    },
}
TERMINAL_STATES = {"FILLED", "PARTIAL_CLOSED", "CANCELED", "REJECTED", "EXPIRED"}


class StateStore(ABC):
    """Persistence contract implemented by SQLite and Postgres backends."""

    # ---- key/value state ----
    @abstractmethod
    def read_state(self, key: str) -> dict | None: ...

    @abstractmethod
    def write_state(self, key: str, value: dict) -> None: ...

    # ---- positions (replaces the whole set atomically) ----
    @abstractmethod
    def read_positions(self) -> dict[str, dict]: ...

    @abstractmethod
    def write_positions(self, positions: dict[str, dict]) -> bool: ...

    # ---- order intents / state machine ----
    @abstractmethod
    def create_order_intent(
        self, client_order_id: str, symbol: str, side: str, amount: str, request: dict
    ) -> None: ...

    @abstractmethod
    def update_order(self, client_order_id: str, state: str, **kwargs) -> None: ...

    @abstractmethod
    def get_order(self, client_order_id: str) -> dict | None: ...

    @abstractmethod
    def is_known_client_order(self, client_order_id: str) -> bool: ...

    @abstractmethod
    def mark_order_applied(self, client_order_id: str) -> None: ...

    @abstractmethod
    def unresolved_orders(self) -> list[dict]: ...

    # ---- audit events ----
    @abstractmethod
    def append_event(self, event_type: str, details: dict) -> None: ...

    @abstractmethod
    def list_events(
        self,
        limit: int = 100,
        *,
        event_type: str | None = None,
        exclude_event_type: str | None = None,
    ) -> list[dict]: ...

    # ---- trades ----
    @abstractmethod
    def append_trade(self, trade: dict) -> None: ...

    @abstractmethod
    def list_trades(self, limit: int = 5000) -> list[dict]: ...

    # ---- maintenance ----
    @abstractmethod
    def create_backup(self, backup_path: str | None = None) -> str: ...

    @abstractmethod
    def quick_check(self) -> str: ...
