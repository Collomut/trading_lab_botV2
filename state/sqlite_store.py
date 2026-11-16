"""SQLite state store: transactional, WAL mode, single-writer safe."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from state.store import ORDER_TRANSITIONS, TERMINAL_STATES, StateStore

SCHEMA_VERSION = 1


class SQLiteStore(StateStore):
    """Durable single-worker state store.

    Not safe for multiple replicas. Use :class:`state.postgres_store.PostgresStore`
    when more than one writer is required.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    # -- connection helpers -------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    description TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS order_intents (
                    client_order_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    state TEXT NOT NULL,
                    exchange_order_id TEXT,
                    filled TEXT NOT NULL DEFAULT '0',
                    average TEXT,
                    request_json TEXT NOT NULL,
                    response_json TEXT,
                    applied INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE INDEX IF NOT EXISTS audit_events_type_idx ON audit_events (event_type);
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE INDEX IF NOT EXISTS trades_created_idx ON trades (created_at);
                INSERT OR IGNORE INTO schema_migrations (version, description)
                VALUES (1, 'Base schema: state, positions, order_intents, audit_events, trades');
                """
            )

    # -- schema / maintenance ----------------------------------------------
    def get_schema_version(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
            return int(row[0]) if row and row[0] is not None else 0

    def create_backup(self, backup_path: str | None = None) -> str:
        if backup_path is None:
            ts = int(time.time() * 1000)
            backup_path = str(self.path.with_name(f"{self.path.stem}_backup_{ts}.db"))
        backup_path = Path(backup_path)
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, closing(self._connect()) as src, closing(sqlite3.connect(backup_path)) as dst:
            src.backup(dst)
        return str(backup_path)

    def quick_check(self) -> str:
        with closing(self._connect()) as conn:
            return str(conn.execute("PRAGMA quick_check").fetchone()[0])

    # -- key/value state ----------------------------------------------------
    def read_state(self, key: str) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT value_json FROM state WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def write_state(self, key: str, value: dict) -> None:
        encoded = json.dumps(value, allow_nan=False, separators=(",", ":"))
        with self._lock, closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO state(key,value_json) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (key, encoded),
            )
            conn.commit()

    # -- positions ----------------------------------------------------------
    def read_positions(self) -> dict[str, dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT symbol,value_json FROM positions ORDER BY symbol").fetchall()
            return {row["symbol"]: json.loads(row["value_json"]) for row in rows}

    def write_positions(self, positions: dict[str, dict]) -> bool:
        encoded = [
            (symbol, json.dumps(value, allow_nan=False, separators=(",", ":")))
            for symbol, value in positions.items()
        ]
        try:
            with self._lock, closing(self._connect()) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("DELETE FROM positions")
                conn.executemany(
                    "INSERT INTO positions(symbol,value_json) VALUES(?,?)", encoded
                )
                conn.commit()
            return True
        except Exception:
            return False

    # -- order intents ------------------------------------------------------
    def create_order_intent(
        self, client_order_id: str, symbol: str, side: str, amount: str, request: dict
    ) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO order_intents(client_order_id,symbol,side,amount,state,request_json) "
                "VALUES(?,?,?,?,?,?)",
                (
                    client_order_id,
                    symbol,
                    side.upper(),
                    str(amount),
                    "PENDING",
                    json.dumps(request, allow_nan=False),
                ),
            )
            conn.commit()

    def update_order(self, client_order_id: str, state: str, **kwargs) -> None:
        row = self.get_order(client_order_id)
        if not row:
            raise ValueError(f"Unknown order intent {client_order_id}")
        if state not in ORDER_TRANSITIONS.get(row["state"], set()):
            raise ValueError(
                f"Invalid order transition {row['state']} -> {state} for {client_order_id}"
            )
        exchange_order_id = kwargs.get("exchange_order_id")
        filled = kwargs.get("filled")
        average = kwargs.get("average")
        response = kwargs.get("response")
        with self._lock, closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE order_intents SET state=?, "
                "exchange_order_id=COALESCE(?,exchange_order_id), "
                "filled=COALESCE(?,filled), average=COALESCE(?,average), "
                "response_json=COALESCE(?,response_json), "
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE client_order_id=?",
                (
                    state,
                    str(exchange_order_id) if exchange_order_id is not None else None,
                    str(filled) if filled is not None else None,
                    str(average) if average is not None else None,
                    json.dumps(response, allow_nan=False) if response is not None else None,
                    client_order_id,
                ),
            )
            conn.commit()

    def get_order(self, client_order_id: str) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM order_intents WHERE client_order_id=?", (client_order_id,)
            ).fetchone()
            return dict(row) if row else None

    def is_known_client_order(self, client_order_id: str) -> bool:
        if not client_order_id:
            return False
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT 1 FROM order_intents WHERE client_order_id=?", (client_order_id,)
            ).fetchone()
            return row is not None

    def mark_order_applied(self, client_order_id: str) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "UPDATE order_intents SET applied=1, "
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE client_order_id=? AND state IN "
                "('FILLED','PARTIAL_CLOSED','CANCELED','REJECTED','EXPIRED')",
                (client_order_id,),
            )
            if conn.total_changes != 1:
                raise ValueError("Only terminal orders can be marked applied")

    def unresolved_orders(self) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM order_intents WHERE "
                "state NOT IN ('FILLED','PARTIAL_CLOSED','CANCELED','REJECTED','EXPIRED') "
                "OR applied=0 ORDER BY created_at"
            ).fetchall()
            return [dict(row) for row in rows]

    # -- audit events -------------------------------------------------------
    def append_event(self, event_type: str, details: dict) -> None:
        encoded = json.dumps(details, allow_nan=False, separators=(",", ":"))
        with self._lock, closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO audit_events(event_type,details_json) VALUES(?,?)",
                (event_type, encoded),
            )
            if event_type == "market_check":
                conn.execute(
                    "DELETE FROM audit_events WHERE event_type='market_check' AND id NOT IN "
                    "(SELECT id FROM audit_events WHERE event_type='market_check' "
                    "ORDER BY id DESC LIMIT 20000)"
                )
            conn.commit()

    def list_events(
        self,
        limit: int = 100,
        *,
        event_type: str | None = None,
        exclude_event_type: str | None = None,
    ) -> list[dict]:
        limit = max(1, min(int(limit), 2000))
        where = ""
        params: list = []
        if event_type is not None:
            where = " WHERE event_type=?"
            params.append(event_type)
        elif exclude_event_type is not None:
            where = " WHERE event_type<>?"
            params.append(exclude_event_type)
        params.append(limit)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT id,event_type,details_json,created_at FROM audit_events{where} "
                "ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "event_type": row["event_type"],
                    "details": json.loads(row["details_json"]),
                    "created_at": row["created_at"],
                }
                for row in rows
            ]

    # -- trades -------------------------------------------------------------
    def append_trade(self, trade: dict) -> None:
        payload = json.dumps(trade, allow_nan=False, separators=(",", ":"))
        source_id = "runtime:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
        created_at = str(trade.get("timestamp") or datetime.now(timezone.utc).isoformat())
        with self._lock, closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR IGNORE INTO trades(source_id,payload,created_at) VALUES(?,?,?)",
                (source_id, payload, created_at),
            )
            conn.commit()

    def list_trades(self, limit: int = 5000) -> list[dict]:
        limit = max(1, min(int(limit), 20000))
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT payload FROM trades ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [json.loads(row["payload"]) for row in reversed(rows)]
