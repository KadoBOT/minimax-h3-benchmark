"""Durable state. Row-level writes only; nothing here rewrites a table."""

from __future__ import annotations

from pathlib import Path

from h3lab.storage.db import ConnectionFactory, connect, factory_for, session, transaction
from h3lab.storage.judgement import RatingRepository, VoteRepository
from h3lab.storage.library import AppState, Preset, PresetNameTaken, PresetRepository
from h3lab.storage.legacy import ImportReport, import_legacy
from h3lab.storage.migrations import LATEST_VERSION, apply_migrations, current_version
from h3lab.storage.runs import Page, RunFilter, RunNotFound, RunRepository, SortKey

__all__ = [
    "AppState",
    "ConnectionFactory",
    "ImportReport",
    "LATEST_VERSION",
    "Page",
    "Preset",
    "PresetNameTaken",
    "PresetRepository",
    "RatingRepository",
    "RunFilter",
    "RunNotFound",
    "RunRepository",
    "SortKey",
    "VoteRepository",
    "apply_migrations",
    "connect",
    "current_version",
    "factory_for",
    "import_legacy",
    "open_store",
    "session",
    "transaction",
]


def open_store(db_path: Path | str) -> ConnectionFactory:
    """Migrate the database at *db_path* and return a factory for further connections."""
    make = factory_for(db_path)
    conn = make()
    try:
        apply_migrations(conn)
    finally:
        conn.close()
    return make
