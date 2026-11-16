"""PostgreSQL state store (optional).

Requires ``DATABASE_URL`` and the ``psycopg`` package. The schema mirrors the
SQLite store; the two backends expose an identical interface so the rest of the
system is storage-agnostic.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone

from state.store import ORDER_TRANSITIONS, StateStore

try:  # pragma: no cover - import guarded so SQLite-only installs still work
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover
    psycopg = None  # type: ignore
    dict_row = None  # type: ignore

try:  # pragma: no cover - psycopg_pool ships as a separate distribution
    from psycopg_pool import ConnectionPool
except Exception:  # pragma: no cover
    ConnectionPool = None  # type: ignore


POSTGRES_INSTALL_HINT = (
    "install it with `pip install 'psycopg[binary,pool]>=3.2'` "
    "or `pip install -e '.[postgres]'`"
)


def missing_dependencies() -> list[str]:
    """Return the Postgres driver packages that cannot be imported."""
    missing = []
    if psycopg is None or dict_row is None:
        missing.append("psycopg")
    if ConnectionPool is None:
        missing.append("psycopg_pool")
    return missing


class PostgresStore(StateStore):
    def __init__(self, database_url: str, *, min_size: int = 1, max_size: int = 4):
        missing = missing_dependencies()
        if missing:  # pragma: no cover
            raise RuntimeError(
                f"Postgres store unavailable: missing {', '.join(missing)}. "
                f"Set DATABASE_URL only when the driver is installed; {POSTGRES_INSTALL_HINT}."
            )
        self.database_url = database_url
        self._pool = ConnectionPool(
            conninfo=database_url, min_size=min_size, max_size=max_size, open=True
        )
        self._initialize()

    @contextmanager
    def _conn(self):
        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            yield conn

    def _initialize(self) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    description TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value_json JSONB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY,
                    value_json JSONB NOT NULL
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
                    request_json JSONB NOT NULL,
                    response_json JSONB,
                    applied INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id BIGSERIAL PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    details_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS audit_events_type_idx ON audit_events (event_type);
                CREATE TABLE IF NOT EXISTS trades (
                    id BIGSERIAL PRIMARY KEY,
                    source_id TEXT NOT NULL UNIQUE,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                INSERT INTO schema_migrations (version, description)
                VALUES (1, 'Base schema') ON CONFLICT (version) DO NOTHING;
                """
            )
            conn.commit()

    # -- key/value ----------------------------------------------------------
    def read_state(self, key: str) -> dict | None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT value_json FROM state WHERE key=%s", (key,))
            row = cur.fetchone()
            return row["value_json"] if row else None

    def write_state(self, key: str, value: dict) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO state(key,value_json) VALUES(%s,%s) "
                "ON CONFLICT (key) DO UPDATE SET value_json=EXCLUDED.value_json",
                (key, json.dumps(value, allow_nan=False)),
            )
            conn.commit()

    # -- positions ----------------------------------------------------------
    def read_positions(self) -> dict[str, dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT symbol,value_json FROM positions ORDER BY symbol")
            return {row["symbol"]: row["value_json"] for row in cur.fetchall()}

    def write_positions(self, positions: dict[str, dict]) -> bool:
        try:
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute("DELETE FROM positions")
                for symbol, value in positions.items():
                    cur.execute(
                        "INSERT INTO positions(symbol,value_json) VALUES(%s,%s)",
                        (symbol, json.dumps(value, allow_nan=False)),
                    )
                conn.commit()
            return True
        except Exception:
            return False

    # -- order intents ------------------------------------------------------
    def create_order_intent(
        self, client_order_id: str, symbol: str, side: str, amount: str, request: dict
    ) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO order_intents(client_order_id,symbol,side,amount,state,request_json) "
                "VALUES(%s,%s,%s,%s,%s,%s)",
                (client_order_id, symbol, side.upper(), str(amount), "PENDING", json.dumps(request)),
            )
            conn.commit()

    def update_order(self, client_order_id: str, state: str, **kwargs) -> None:
        row = self.get_order(client_order_id)
        if not row or state not in ORDER_TRANSITIONS.get(row["state"], set()):
            raise ValueError("Invalid or missing order-state transition")
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE order_intents SET state=%s, "
                "exchange_order_id=COALESCE(%s,exchange_order_id), "
                "filled=COALESCE(%s,filled), average=COALESCE(%s,average), "
                "response_json=COALESCE(%s,response_json), updated_at=now() "
                "WHERE client_order_id=%s",
                (
                    state,
                    kwargs.get("exchange_order_id"),
                    kwargs.get("filled"),
                    kwargs.get("average"),
                    json.dumps(kwargs.get("response")) if kwargs.get("response") is not None else None,
                    client_order_id,
                ),
            )
            conn.commit()

    def get_order(self, client_order_id: str) -> dict | None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM order_intents WHERE client_order_id=%s", (client_order_id,))
            return cur.fetchone()

    def is_known_client_order(self, client_order_id: str) -> bool:
        return self.get_order(client_order_id) is not None

    def mark_order_applied(self, client_order_id: str) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE order_intents SET applied=1, updated_at=now() "
                "WHERE client_order_id=%s AND state IN "
                "('FILLED','PARTIAL_CLOSED','CANCELED','REJECTED','EXPIRED')",
                (client_order_id,),
            )
            if cur.rowcount != 1:
                raise ValueError("Only terminal orders can be marked applied")
            conn.commit()

    def unresolved_orders(self) -> list[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM order_intents WHERE "
                "state NOT IN ('FILLED','PARTIAL_CLOSED','CANCELED','REJECTED','EXPIRED') "
                "OR applied=0 ORDER BY created_at"
            )
            return list(cur.fetchall())

    # -- audit --------------------------------------------------------------
    def append_event(self, event_type: str, details: dict) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO audit_events(event_type,details_json) VALUES(%s,%s)",
                (event_type, json.dumps(details, allow_nan=False)),
            )
            if event_type == "market_check":
                cur.execute(
                    "DELETE FROM audit_events WHERE event_type='market_check' AND id NOT IN "
                    "(SELECT id FROM audit_events WHERE event_type='market_check' "
                    "ORDER BY id DESC LIMIT 20000)"
                )
            conn.commit()

    def list_events(self, limit=100, *, event_type=None, exclude_event_type=None) -> list[dict]:
        limit = max(1, min(int(limit), 2000))
        where = ""
        params: list = []
        if event_type is not None:
            where = " WHERE event_type=%s"
            params.append(event_type)
        elif exclude_event_type is not None:
            where = " WHERE event_type<>%s"
            params.append(exclude_event_type)
        params.append(limit)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT id,event_type,details_json,created_at FROM audit_events{where} "
                "ORDER BY id DESC LIMIT %s",
                params,
            )
            return [
                {
                    "id": row["id"],
                    "event_type": row["event_type"],
                    "details": row["details_json"],
                    "created_at": row["created_at"].isoformat(),
                }
                for row in cur.fetchall()
            ]

    # -- trades -------------------------------------------------------------
    def append_trade(self, trade: dict) -> None:
        payload = json.dumps(trade, allow_nan=False)
        source_id = "runtime:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
        created_at = str(trade.get("timestamp") or datetime.now(timezone.utc).isoformat())
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO trades(source_id,payload,created_at) VALUES(%s,%s,%s) "
                "ON CONFLICT (source_id) DO NOTHING",
                (source_id, payload, created_at),
            )
            conn.commit()

    def list_trades(self, limit: int = 5000) -> list[dict]:
        limit = max(1, min(int(limit), 20000))
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT payload FROM trades ORDER BY id DESC LIMIT %s", (limit,))
            rows = cur.fetchall()
        return [row["payload"] for row in reversed(rows)]

    # -- maintenance --------------------------------------------------------
    def create_backup(self, backup_path: str | None = None) -> str:  # pragma: no cover
        raise NotImplementedError("Use provider-level backups for Postgres")

    def quick_check(self) -> str:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return "ok"
