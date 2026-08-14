"""Saved configs and small pieces of lab state."""

from __future__ import annotations

import json
import sqlite3

from pydantic import BaseModel, ConfigDict

from h3lab.domain.config import GenerationConfig
from h3lab.domain.ids import new_id
from h3lab.storage.db import ConnectionFactory, scalar, session, transaction
from h3lab.storage.runs import utc_now

BASELINE_KEY = "baseline_run_id"


class Preset(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    config: GenerationConfig
    source_run_id: str | None = None
    created_at: str


class PresetNameTaken(ValueError):
    pass


class PresetRepository:
    def __init__(self, connect: ConnectionFactory) -> None:
        self._connect = connect

    def create(
        self,
        name: str,
        config: GenerationConfig,
        *,
        source_run_id: str | None = None,
        replace: bool = False,
    ) -> Preset:
        clean = name.strip()
        if not clean:
            raise ValueError("a preset needs a name")
        preset = Preset(
            id=new_id(),
            name=clean,
            config=config,
            source_run_id=source_run_id,
            created_at=utc_now(),
        )
        payload = json.dumps(config.model_dump(mode="json"), ensure_ascii=False)
        with session(self._connect) as conn, transaction(conn):
            if replace:
                conn.execute("DELETE FROM presets WHERE name = ?", (clean,))
            try:
                conn.execute(
                    "INSERT INTO presets (id, name, config_json, source_run_id, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (preset.id, preset.name, payload, preset.source_run_id, preset.created_at),
                )
            except sqlite3.IntegrityError as exc:
                raise PresetNameTaken(
                    f"a preset named {clean!r} already exists; save under another name "
                    "or overwrite it"
                ) from exc
        return preset

    def list(self) -> list[Preset]:
        with session(self._connect) as conn:
            rows = conn.execute("SELECT * FROM presets ORDER BY created_at DESC").fetchall()
        return [self._row(row) for row in rows]

    def get(self, preset_id: str) -> Preset | None:
        with session(self._connect) as conn:
            row = conn.execute("SELECT * FROM presets WHERE id = ?", (preset_id,)).fetchone()
        return self._row(row) if row else None

    def get_by_name(self, name: str) -> Preset | None:
        with session(self._connect) as conn:
            row = conn.execute("SELECT * FROM presets WHERE name = ?", (name.strip(),)).fetchone()
        return self._row(row) if row else None

    def delete(self, preset_id: str) -> bool:
        with session(self._connect) as conn, transaction(conn):
            cursor = conn.execute("DELETE FROM presets WHERE id = ?", (preset_id,))
            return cursor.rowcount > 0

    @staticmethod
    def _row(row: sqlite3.Row) -> Preset:
        return Preset(
            id=row["id"],
            name=row["name"],
            config=GenerationConfig(**json.loads(row["config_json"])),
            source_run_id=row["source_run_id"],
            created_at=row["created_at"],
        )


class AppState:
    def __init__(self, connect: ConnectionFactory) -> None:
        self._connect = connect

    def get(self, key: str) -> str | None:
        with session(self._connect) as conn:
            return scalar(conn, "SELECT value FROM app_state WHERE key = ?", (key,))

    def set(self, key: str, value: str | None) -> None:
        with session(self._connect) as conn, transaction(conn):
            if value is None:
                conn.execute("DELETE FROM app_state WHERE key = ?", (key,))
                return
            conn.execute(
                "INSERT INTO app_state (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    @property
    def baseline_run_id(self) -> str | None:
        return self.get(BASELINE_KEY)

    def set_baseline(self, run_id: str | None) -> None:
        self.set(BASELINE_KEY, run_id)

    def mark_legacy_imported(self, legacy_id: str, run_id: str | None) -> None:
        with session(self._connect) as conn, transaction(conn):
            conn.execute(
                "INSERT INTO legacy_imports (legacy_id, run_id, imported_at) VALUES (?, ?, ?) "
                "ON CONFLICT(legacy_id) DO UPDATE SET run_id = excluded.run_id",
                (legacy_id, run_id, utc_now()),
            )

    def legacy_imported(self) -> set[str]:
        with session(self._connect) as conn:
            rows = conn.execute("SELECT legacy_id FROM legacy_imports").fetchall()
        return {row["legacy_id"] for row in rows}
