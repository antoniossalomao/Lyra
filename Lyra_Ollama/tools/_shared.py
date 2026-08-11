"""tools/_shared.py — sync SurrealDB helpers shared by every domain module
that persists state (reminders, numbers, processes, memory backup...).
"""

from typing import Any

from surreal_client import surreal


def surreal_query(query: str) -> Any:
    """Execute a SurrealQL statement synchronously (tools run outside asyncio)."""
    return surreal.query_sync(query, timeout=15)


def one(r: Any) -> Any:
    """CREATE/UPDATE on a single record always returns a 1-item list — unwrap
    it so callers get the record directly instead of a list."""
    return r[0] if isinstance(r, list) and r else r
