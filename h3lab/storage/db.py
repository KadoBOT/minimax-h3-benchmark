"""SQLite connection handling and transactions.

A connection per operation. With WAL enabled and a busy timeout, SQLite handles the
lab's write volume (a handful per second at most) without any pooling, and it removes the
whole class of bugs that comes from sharing a connection across the HTTP threads and the
queue worker.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

BUSY_TIMEOUT_MS = 10_000

ConnectionFactory = Callable[[], sqlite3.Connection]


def connect(path: Path | str) -> sqlite3.Connection:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(target),
        timeout=BUSY_TIMEOUT_MS / 1000,
        isolation_level=None,  # explicit transactions only
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    return conn


def factory_for(path: Path | str) -> ConnectionFactory:
    def make() -> sqlite3.Connection:
        return connect(path)

    return make


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """`BEGIN IMMEDIATE` so two writers queue instead of failing halfway through."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


@contextmanager
def session(make: ConnectionFactory) -> Iterator[sqlite3.Connection]:
    conn = make()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def writing(make: ConnectionFactory) -> Iterator[sqlite3.Connection]:
    with session(make) as conn, transaction(conn):
        yield conn


def scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    return row[0]
