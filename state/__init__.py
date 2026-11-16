"""State persistence package."""
from state.store import ORDER_TRANSITIONS, TERMINAL_STATES, StateStore

__all__ = ["ORDER_TRANSITIONS", "TERMINAL_STATES", "StateStore", "build_store"]


def build_store(database_url: str = "", sqlite_path: str = "data/state.sqlite3"):
    """Return a Postgres store when ``database_url`` is set, else SQLite."""
    if database_url:
        from state.postgres_store import PostgresStore

        return PostgresStore(database_url)
    from state.sqlite_store import SQLiteStore

    return SQLiteStore(sqlite_path)
