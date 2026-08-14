"""Threaded PostgreSQL connection pool.

Workers share a small pool of long-lived connections instead of opening a fresh
TCP connection per query. Two pools exist internally: one that returns dict rows
(``RealDictCursor``, used by ``app/db/database.py``) and one returning plain
tuples (used by ``app/db/unified_store.py``).

Connections are obtained with ``get_connection()`` and MUST be released via
``close()`` (the returned wrapper returns the real connection to its pool).
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from psycopg2 import pool as _pg_pool

logger = logging.getLogger("db.pool")

DB_POOL_MIN = int(os.environ.get("DB_POOL_MIN", "1"))
DB_POOL_MAX = int(os.environ.get("DB_POOL_MAX", "10"))
DB_CONNECT_TIMEOUT = int(os.environ.get("DB_CONNECT_TIMEOUT", "10"))

_pools: dict[str, _pg_pool.ThreadedConnectionPool] = {}
_lock = threading.Lock()


class PooledConnection:
    """Wraps a pooled connection so ``close()`` returns it to the pool safely."""

    def __init__(self, conn: Any, pool: _pg_pool.ThreadedConnectionPool):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_pool", pool)
        object.__setattr__(self, "_returned", False)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def __setattr__(self, name: str, value: Any) -> None:
        # Forward connection attributes (e.g. `autocommit`) to the real conn;
        # only private wrapper state lives on the wrapper itself.
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._conn, name, value)

    def cursor(self):
        return self._conn.cursor()

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self) -> None:
        if self._returned:
            return
        self._returned = True
        conn = self._conn
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            if conn.closed:
                self._pool.putconn(conn, close=True)
            else:
                self._pool.putconn(conn)
        except Exception:
            # A broken connection must not be returned to the pool; discard it.
            try:
                self._pool.putconn(conn, close=True)
            except Exception:
                logger.warning("Could not return connection to the DB pool", exc_info=True)

    def __enter__(self) -> PooledConnection:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is required for this environment. Supabase-only mode "
            "does not support the old local SQLite fallback."
        )
    return url


def _get_pool(cursor_factory: type | None = None) -> _pg_pool.ThreadedConnectionPool:
    key = cursor_factory.__name__ if cursor_factory else "default"
    with _lock:
        pool = _pools.get(key)
        if pool is None:
            url = _database_url()
            logger.info(
                "Creating DB pool (%s) min=%s max=%s ...",
                key,
                DB_POOL_MIN,
                DB_POOL_MAX,
            )
            pool = _pg_pool.ThreadedConnectionPool(
                DB_POOL_MIN,
                DB_POOL_MAX,
                url,
                cursor_factory=cursor_factory,
                connect_timeout=DB_CONNECT_TIMEOUT,
            )
            _pools[key] = pool
        return pool


def get_connection(cursor_factory: type | None = None) -> PooledConnection:
    """Return a pooled connection (dict rows when ``RealDictCursor``)."""
    pool = _get_pool(cursor_factory)
    return PooledConnection(pool.getconn(), pool)


def close_pool() -> None:
    with _lock:
        for key, pool in list(_pools.items()):
            try:
                pool.closeall()
            except Exception:
                logger.warning("Error closing DB pool '%s'", key, exc_info=True)
            _pools.pop(key, None)