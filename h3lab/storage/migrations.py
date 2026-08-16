"""Forward-only schema migrations.

Append a `Migration` to `MIGRATIONS`; never edit an existing one. The applied version
lives in `app_state` so a database always knows how far it has come.

A migration carries SQL, a Python step, or both. The Python step exists for the changes
SQLite cannot express — rewriting a stored config and the digests derived from it needs
the domain model, not an UPDATE.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Callable

from h3lab.storage.db import scalar, transaction

SCHEMA_VERSION_KEY = "schema_version"


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str = ""
    fn: Callable[[sqlite3.Connection], None] | None = None


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


def _rehash_configs(conn: sqlite3.Connection) -> None:
    """Move every stored config off `rife` and onto `interp`, digests included.

    `interp` is a hashed field, so the rename moved every `config_hash` and `recipe_hash`
    ever written. Left alone, a re-queued run would look new, duplicate detection would
    stop matching, and the arena would pool a run against itself under two identities.

    A row whose config will not parse is left exactly as it is. A benchmark result nobody
    can read is still worth more than a tidy schema, and it will be skipped again next time
    rather than lost now.
    """
    from h3lab.domain.config import GenerationConfig, config_hash, recipe_hash

    for table, rehash in (("runs", True), ("presets", False)):
        for row in conn.execute(f"SELECT id, config_json FROM {table}").fetchall():
            try:
                config = GenerationConfig(**json.loads(row["config_json"]))
            except Exception:
                continue
            payload = config.model_dump_json()
            if rehash:
                conn.execute(
                    "UPDATE runs SET config_json = ?, config_hash = ?, recipe_hash = ? "
                    "WHERE id = ?",
                    (payload, config_hash(config), recipe_hash(config), row["id"]),
                )
            else:
                conn.execute(
                    "UPDATE presets SET config_json = ? WHERE id = ?", (payload, row["id"])
                )


def _add_shared_run_linkage(conn: sqlite3.Connection) -> None:
    """Add restart-safe shared-service linkage without rewriting historical identity."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    columns = {
        "shared_submission_json": "TEXT",
        "shared_job_id": "TEXT",
        "shared_provenance_json": "TEXT",
        "shared_event_cursor": "INTEGER",
        "shared_failure_kind": "TEXT",
    }
    for name, kind in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {name} {kind}")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_shared_job "
        "ON runs(shared_job_id) WHERE shared_job_id IS NOT NULL"
    )


MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, name="initial", sql=_V1),
    Migration(version=2, name="rename-rife-to-interp", fn=_rehash_configs),
    # The turbo LoRA and its strength became hashed fields, which moved every digest ever
    # written and left a stored `turbo: true` row silent about which LoRA it used. Re-parsing
    # each config through the current model fills in the file the templates shipped with —
    # the one those runs actually loaded — and recomputes both digests from it.
    Migration(version=3, name="turbo-lora-as-a-setting", fn=_rehash_configs),
    # A turbo run now stores the schedule its LoRA was distilled for rather than whatever the
    # step field held when the toggle was flipped. `steps` is hashed, so every turbo row ever
    # written carries a leftover and a digest computed from it. Re-parsing each config through
    # the current model corrects the value and both digests in place, which is what lets a
    # queue full of turbo runs be repaired instead of thrown away.
    Migration(version=4, name="turbo-steps-follow-the-lora", fn=_rehash_configs),
    Migration(version=5, name="shared-service-run-linkage", fn=_add_shared_run_linkage),
)

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
        if migration.sql:
            conn.executescript(migration.sql)
        with transaction(conn):
            if migration.fn is not None:
                migration.fn(conn)
            conn.execute(
                "INSERT INTO app_state (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (SCHEMA_VERSION_KEY, str(migration.version)),
            )
        version = migration.version
    return version
