"""Forward-only schema migrations.

Append a `Migration` to `MIGRATIONS`; never edit an existing one. The applied version
lives in `app_state` so a database always knows how far it has come.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from h3lab.storage.db import scalar, transaction

SCHEMA_VERSION_KEY = "schema_version"


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str


_V1 = """
CREATE TABLE IF NOT EXISTS app_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id             TEXT PRIMARY KEY,
    seq            INTEGER NOT NULL UNIQUE,
    label          TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'queued',
    mode           TEXT NOT NULL DEFAULT 'flf2v',
    config_json    TEXT NOT NULL,
    config_hash    TEXT NOT NULL,
    recipe_hash    TEXT NOT NULL,

    wall_s         REAL,
    sec_per_it     REAL,
    steps          INTEGER,
    sampler_cached INTEGER,
    cache_cleared  INTEGER,

    prompt_id      TEXT,
    error          TEXT,

    video_path     TEXT,
    poster_path    TEXT,
    strip_path     TEXT,
    width          INTEGER,
    height         INTEGER,
    fps            REAL,
    frame_count    INTEGER,
    size_bytes     INTEGER,

    favourite      INTEGER NOT NULL DEFAULT 0,
    archived       INTEGER NOT NULL DEFAULT 0,
    notes          TEXT NOT NULL DEFAULT '',

    created_at     TEXT NOT NULL,
    started_at     TEXT,
    finished_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_status      ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_config_hash ON runs(config_hash);
CREATE INDEX IF NOT EXISTS idx_runs_recipe_hash ON runs(recipe_hash);
CREATE INDEX IF NOT EXISTS idx_runs_seq         ON runs(seq);
CREATE INDEX IF NOT EXISTS idx_runs_visible     ON runs(archived, favourite);
CREATE INDEX IF NOT EXISTS idx_runs_created     ON runs(created_at);

CREATE TABLE IF NOT EXISTS run_tags (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    tag    TEXT NOT NULL,
    PRIMARY KEY (run_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_run_tags_tag ON run_tags(tag);

CREATE TABLE IF NOT EXISTS ratings (
    run_id        TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    stars         INTEGER NOT NULL,
    criteria_json TEXT NOT NULL DEFAULT '{}',
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS votes (
    id         TEXT PRIMARY KEY,
    run_a      TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    run_b      TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    winner     TEXT,
    axis       TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_votes_created ON votes(created_at);
CREATE INDEX IF NOT EXISTS idx_votes_run_a   ON votes(run_a);
CREATE INDEX IF NOT EXISTS idx_votes_run_b   ON votes(run_b);

CREATE TABLE IF NOT EXISTS presets (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    config_json   TEXT NOT NULL,
    source_run_id TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS legacy_imports (
    legacy_id  TEXT PRIMARY KEY,
    run_id     TEXT,
    imported_at TEXT NOT NULL
);
"""


MIGRATIONS: tuple[Migration, ...] = (Migration(version=1, name="initial", sql=_V1),)

LATEST_VERSION = max(migration.version for migration in MIGRATIONS)


def _ensure_state_table(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT)")


def current_version(conn: sqlite3.Connection) -> int:
    _ensure_state_table(conn)
    raw = scalar(conn, "SELECT value FROM app_state WHERE key = ?", (SCHEMA_VERSION_KEY,))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Bring *conn* up to `LATEST_VERSION`. Idempotent; returns the resulting version."""
    version = current_version(conn)
    for migration in sorted(MIGRATIONS, key=lambda m: m.version):
        if migration.version <= version:
            continue
        # executescript commits any open transaction, so it cannot sit inside one.
        # Every statement is CREATE ... IF NOT EXISTS, which makes a half-applied
        # migration safe to re-run.
        conn.executescript(migration.sql)
        with transaction(conn):
            conn.execute(
                "INSERT INTO app_state (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (SCHEMA_VERSION_KEY, str(migration.version)),
            )
        version = migration.version
    return version
