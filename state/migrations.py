"""Schema migration helpers.

The base schema is created in :meth:`SQLiteStore._initialize`. This module
provides a single entry point so future migrations can be added without callers
needing to know which backend is in use.
"""
from __future__ import annotations

from state.store import StateStore


def run_migrations(store: StateStore) -> int:
    """Run pending migrations and return the number applied.

    Version 1 is created at store construction. Future migrations should be
    appended here guarded by ``get_schema_version`` where the backend supports it.
    """
    version = getattr(store, "get_schema_version", None)
    if callable(version):
        return version()
    return 0
