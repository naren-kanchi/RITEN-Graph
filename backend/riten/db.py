"""PostgreSQL access. The API connects only as the least-privilege app role."""
from contextlib import contextmanager
from typing import Any, Iterator, Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import get_settings

_pool: ConnectionPool | None = None


def _configure(conn: psycopg.Connection) -> None:
    # Bounded: a slow query becomes a controlled 503, never a stuck worker thread.
    conn.execute("SET statement_timeout = '10s'")
    conn.commit()


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            get_settings().app_dsn(), min_size=2, max_size=12, timeout=5, open=True,
            kwargs={"row_factory": dict_row, "connect_timeout": 3}, configure=_configure,
            check=ConnectionPool.check_connection)
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def fetch_all(query: str, params: Sequence[Any] | dict | None = None) -> list[dict]:
    with get_pool().connection() as conn:
        return conn.execute(query, params).fetchall()


def fetch_one(query: str, params: Sequence[Any] | dict | None = None) -> dict | None:
    with get_pool().connection() as conn:
        return conn.execute(query, params).fetchone()


@contextmanager
def transaction(user_id: int | None = None) -> Iterator[psycopg.Connection]:
    """Commit on success, roll back on any exception; expose the acting user to audit triggers."""
    with get_pool().connection() as conn:
        with conn.transaction():
            if user_id is not None:
                conn.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))
            yield conn


def data_version() -> str:
    row = fetch_one("SELECT data_version FROM import_batch WHERE status = 'succeeded' ORDER BY batch_id DESC LIMIT 1")
    return row["data_version"] if row else "none"
