"""Run persistence. Every mutation targets one row.

The old store rewrote every run on every progress tick, which is what let a stale queued
row overwrite a finished one. Nothing here writes a row it was not asked to write.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Annotated, Any, Iterable, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

from h3lab.domain.config import GenerationConfig, config_hash, derive_label, recipe_hash
from h3lab.domain.ids import new_id
from h3lab.domain.run import Artifact, Run, RunMetrics, RunStatus
from h3lab.storage.db import ConnectionFactory, scalar, session, transaction

SortKey = Literal[
    "recent",
    "oldest",
    "seq",
    "fastest",
    "slowest",
    "stars",
    "label",
]

_COLUMNS = (
    "id, seq, label, status, mode, config_json, config_hash, recipe_hash, "
    "wall_s, sec_per_it, steps, sampler_cached, cache_cleared, prompt_id, error, "
    "video_path, poster_path, strip_path, width, height, fps, frame_count, size_bytes, "
    "favourite, archived, notes, created_at, started_at, finished_at"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunFilter(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: tuple[RunStatus, ...] = ()
    mode: str | None = None
    favourite: bool | None = None
    archived: bool | None = False
    rated: bool | None = None
    with_video: bool | None = None
    tag: str | None = None
    config_hash: str | None = None
    recipe_hash: str | None = None
    ids: tuple[str, ...] = ()
    query: str | None = None
    min_stars: Annotated[int, Field(ge=1, le=10)] | None = None


class Page(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[Run]
    total: int
    limit: int
    offset: int


class RunNotFound(KeyError):
    pass


def _bool_col(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


def row_to_run(row: sqlite3.Row, tags: tuple[str, ...] = ()) -> Run:
    config = GenerationConfig(**json.loads(row["config_json"]))
    return Run(
        id=row["id"],
        seq=int(row["seq"]),
        label=row["label"] or "",
        status=row["status"],
        config=config,
        config_hash=row["config_hash"],
        recipe_hash=row["recipe_hash"],
        metrics=RunMetrics(
            wall_s=row["wall_s"],
            sec_per_it=row["sec_per_it"],
            steps=row["steps"],
            sampler_cached=None if row["sampler_cached"] is None else bool(row["sampler_cached"]),
            cache_cleared=None if row["cache_cleared"] is None else bool(row["cache_cleared"]),
        ),
        artifact=Artifact(
            video_path=row["video_path"],
            poster_path=row["poster_path"],
            strip_path=row["strip_path"],
            width=row["width"],
            height=row["height"],
            fps=row["fps"],
            frame_count=row["frame_count"],
            size_bytes=row["size_bytes"],
        ),
        prompt_id=row["prompt_id"],
        error=row["error"],
        favourite=bool(row["favourite"]),
        archived=bool(row["archived"]),
        notes=row["notes"] or "",
        tags=tags,
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def _where(filter_: RunFilter) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if filter_.status:
        clauses.append(f"r.status IN ({','.join('?' * len(filter_.status))})")
        params.extend(filter_.status)
    if filter_.mode:
        clauses.append("r.mode = ?")
        params.append(filter_.mode)
    if filter_.favourite is not None:
        clauses.append("r.favourite = ?")
        params.append(_bool_col(filter_.favourite))
    if filter_.archived is not None:
        clauses.append("r.archived = ?")
        params.append(_bool_col(filter_.archived))
    if filter_.with_video is True:
        clauses.append("r.video_path IS NOT NULL")
    elif filter_.with_video is False:
        clauses.append("r.video_path IS NULL")
    if filter_.rated is True:
        clauses.append("EXISTS (SELECT 1 FROM ratings g WHERE g.run_id = r.id)")
    elif filter_.rated is False:
        clauses.append("NOT EXISTS (SELECT 1 FROM ratings g WHERE g.run_id = r.id)")
    if filter_.min_stars is not None:
        clauses.append(
            "EXISTS (SELECT 1 FROM ratings g WHERE g.run_id = r.id AND g.stars >= ?)"
        )
        params.append(filter_.min_stars)
    if filter_.tag:
        clauses.append("EXISTS (SELECT 1 FROM run_tags t WHERE t.run_id = r.id AND t.tag = ?)")
        params.append(filter_.tag)
    if filter_.config_hash:
        clauses.append("r.config_hash = ?")
        params.append(filter_.config_hash)
    if filter_.recipe_hash:
        clauses.append("r.recipe_hash = ?")
        params.append(filter_.recipe_hash)
    if filter_.ids:
        clauses.append(f"r.id IN ({','.join('?' * len(filter_.ids))})")
        params.extend(filter_.ids)
    if filter_.query:
        needle = f"%{filter_.query.lower()}%"
        clauses.append(
            "(LOWER(r.label) LIKE ? OR LOWER(r.notes) LIKE ? "
            "OR LOWER(r.config_json) LIKE ? OR LOWER(r.id) LIKE ?)"
        )
        params.extend([needle, needle, needle, needle])

    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


_ORDER_BY: dict[SortKey, str] = {
    "recent": "r.created_at DESC, r.seq DESC",
    "oldest": "r.created_at ASC, r.seq ASC",
    "seq": "r.seq DESC",
    "fastest": "r.sec_per_it IS NULL, r.sec_per_it ASC",
    "slowest": "r.sec_per_it IS NULL, r.sec_per_it DESC",
    "stars": (
        "(SELECT g.stars FROM ratings g WHERE g.run_id = r.id) IS NULL, "
        "(SELECT g.stars FROM ratings g WHERE g.run_id = r.id) DESC, r.seq DESC"
    ),
    "label": "r.label ASC",
}


class RunRepository:
    def __init__(self, connect: ConnectionFactory) -> None:
        self._connect = connect

    # --- creation ----------------------------------------------------------

    def create(self, config: GenerationConfig, *, status: RunStatus = "queued") -> Run:
        """Allocate id, seq, and label in one transaction so a burst cannot collide."""
        run_id = new_id()
        created = utc_now()
        payload = json.dumps(config.model_dump(mode="json"), ensure_ascii=False)
        with session(self._connect) as conn, transaction(conn):
            next_seq = int(scalar(conn, "SELECT COALESCE(MAX(seq), 0) + 1 FROM runs") or 1)
            label = derive_label(next_seq, config)
            conn.execute(
                """
                INSERT INTO runs (
                    id, seq, label, status, mode, config_json, config_hash, recipe_hash,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    next_seq,
                    label,
                    status,
                    config.mode,
                    payload,
                    config_hash(config),
                    recipe_hash(config),
                    created,
                ),
            )
        return self.require(run_id)

    def create_many(self, configs: Iterable[GenerationConfig]) -> list[Run]:
        return [self.create(config) for config in configs]

    # --- reading -----------------------------------------------------------

    def get(self, run_id: str) -> Run | None:
        with session(self._connect) as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM runs r WHERE r.id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            return row_to_run(row, self._tags(conn, run_id))

    def require(self, run_id: str) -> Run:
        run = self.get(run_id)
        if run is None:
            raise RunNotFound(run_id)
        return run

    def list(
        self,
        filter_: RunFilter | None = None,
        *,
        sort: SortKey = "recent",
        limit: int = 100,
        offset: int = 0,
    ) -> Page:
        filter_ = filter_ or RunFilter()
        where, params = _where(filter_)
        order = _ORDER_BY.get(sort, _ORDER_BY["recent"])
        with session(self._connect) as conn:
            total = int(scalar(conn, f"SELECT COUNT(*) FROM runs r{where}", tuple(params)) or 0)
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM runs r{where} ORDER BY {order} LIMIT ? OFFSET ?",
                (*params, max(0, limit), max(0, offset)),
            ).fetchall()
            tag_map = self._tags_for_many(conn, [row["id"] for row in rows])
            items = [row_to_run(row, tag_map.get(row["id"], ())) for row in rows]
        return Page(items=items, total=total, limit=limit, offset=offset)

    def all(self, filter_: RunFilter | None = None) -> list[Run]:
        return self.list(filter_, limit=1_000_000).items

    def hashes(self) -> dict[str, str]:
        """config_hash -> earliest run id, for duplicate detection and sweep previews."""
        with session(self._connect) as conn:
            rows = conn.execute(
                "SELECT config_hash, id FROM runs ORDER BY seq ASC"
            ).fetchall()
        out: dict[str, str] = {}
        for row in rows:
            out.setdefault(row["config_hash"], row["id"])
        return out

    def duplicates(self, digest: str, *, exclude_id: str | None = None) -> list[str]:
        with session(self._connect) as conn:
            rows = conn.execute(
                "SELECT id FROM runs WHERE config_hash = ? AND id != ? ORDER BY seq ASC",
                (digest, exclude_id or ""),
            ).fetchall()
        return [row["id"] for row in rows]

    def tags(self) -> list[str]:
        with session(self._connect) as conn:
            rows = conn.execute(
                "SELECT tag, COUNT(*) AS n FROM run_tags GROUP BY tag ORDER BY n DESC, tag ASC"
            ).fetchall()
        return [row["tag"] for row in rows]

    def status_counts(self) -> dict[str, int]:
        with session(self._connect) as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS n FROM runs GROUP BY status").fetchall()
        return {row["status"]: int(row["n"]) for row in rows}

    def _tags(self, conn: sqlite3.Connection, run_id: str) -> tuple[str, ...]:
        rows = conn.execute(
            "SELECT tag FROM run_tags WHERE run_id = ? ORDER BY tag", (run_id,)
        ).fetchall()
        return tuple(row["tag"] for row in rows)

    def _tags_for_many(
        self, conn: sqlite3.Connection, run_ids: Sequence[str]
    ) -> dict[str, tuple[str, ...]]:
        if not run_ids:
            return {}
        placeholders = ",".join("?" * len(run_ids))
        rows = conn.execute(
            f"SELECT run_id, tag FROM run_tags WHERE run_id IN ({placeholders}) ORDER BY tag",
            tuple(run_ids),
        ).fetchall()
        grouped: dict[str, list[str]] = {}
        for row in rows:
            grouped.setdefault(row["run_id"], []).append(row["tag"])
        return {key: tuple(value) for key, value in grouped.items()}

    # --- queue -------------------------------------------------------------

    def claim_next(self) -> Run | None:
        """Atomically take the oldest queued run. Two callers never get the same row."""
        started = utc_now()
        with session(self._connect) as conn, transaction(conn):
            row = conn.execute(
                "SELECT id FROM runs WHERE status = 'queued' ORDER BY created_at ASC, seq ASC "
                "LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            claimed = conn.execute(
                "UPDATE runs SET status = 'running', started_at = ?, error = NULL "
                "WHERE id = ? AND status = 'queued'",
                (started, row["id"]),
            )
            if claimed.rowcount == 0:
                return None
            run_id = row["id"]
        return self.get(run_id)

    def requeue(self, run_id: str) -> Run | None:
        """Put a claimed run back, as if it had never been taken.

        Guarded on the current status so a finished run can never be resurrected by a late
        caller. Returns ``None`` when the run was not there to give back.
        """
        with session(self._connect) as conn, transaction(conn):
            cursor = conn.execute(
                "UPDATE runs SET status = 'queued', started_at = NULL, error = NULL "
                "WHERE id = ? AND status = 'running'",
                (run_id,),
            )
            if cursor.rowcount == 0:
                return None
        return self.get(run_id)

    def queued_ids(self) -> list[str]:
        with session(self._connect) as conn:
            rows = conn.execute(
                "SELECT id FROM runs WHERE status = 'queued' ORDER BY created_at ASC, seq ASC"
            ).fetchall()
        return [row["id"] for row in rows]

    def running(self) -> list[Run]:
        return self.all(RunFilter(status=("running",), archived=None))

    def reconcile(self, *, reason: str = "interrupted: the lab restarted") -> int:
        """Runs left mid-flight by a crash become `interrupted` instead of eternal."""
        finished = utc_now()
        with session(self._connect) as conn, transaction(conn):
            cursor = conn.execute(
                "UPDATE runs SET status = 'interrupted', "
                "error = COALESCE(NULLIF(error, ''), ?), "
                "finished_at = COALESCE(finished_at, ?) "
                "WHERE status = 'running'",
                (reason, finished),
            )
            return cursor.rowcount

    def cancel_queued(self, *, reason: str = "cancelled: the queue was cleared") -> int:
        finished = utc_now()
        with session(self._connect) as conn, transaction(conn):
            cursor = conn.execute(
                "UPDATE runs SET status = 'cancelled', "
                "error = COALESCE(NULLIF(error, ''), ?), "
                "finished_at = COALESCE(finished_at, ?) "
                "WHERE status = 'queued'",
                (reason, finished),
            )
            return cursor.rowcount

    # --- run lifecycle -----------------------------------------------------

    def _update(self, run_id: str, assignments: dict[str, Any]) -> Run:
        if not assignments:
            return self.require(run_id)
        columns = ", ".join(f"{name} = ?" for name in assignments)
        with session(self._connect) as conn, transaction(conn):
            cursor = conn.execute(
                f"UPDATE runs SET {columns} WHERE id = ?",
                (*assignments.values(), run_id),
            )
            if cursor.rowcount == 0:
                raise RunNotFound(run_id)
        return self.require(run_id)

    def set_prompt_id(self, run_id: str, prompt_id: str) -> Run:
        return self._update(run_id, {"prompt_id": prompt_id})

    def update_metrics(self, run_id: str, metrics: RunMetrics) -> Run:
        return self._update(
            run_id,
            {
                "wall_s": metrics.wall_s,
                "sec_per_it": metrics.sec_per_it,
                "steps": metrics.steps,
                "sampler_cached": _bool_col(metrics.sampler_cached),
                "cache_cleared": _bool_col(metrics.cache_cleared),
            },
        )

    def attach_artifact(self, run_id: str, artifact: Artifact) -> Run:
        return self._update(
            run_id,
            {
                "video_path": artifact.video_path,
                "poster_path": artifact.poster_path,
                "strip_path": artifact.strip_path,
                "width": artifact.width,
                "height": artifact.height,
                "fps": artifact.fps,
                "frame_count": artifact.frame_count,
                "size_bytes": artifact.size_bytes,
            },
        )

    def finish(self, run_id: str, status: RunStatus, *, error: str | None = None) -> Run:
        return self._update(
            run_id,
            {"status": status, "error": error, "finished_at": utc_now()},
        )

    def mark_succeeded(self, run_id: str) -> Run:
        return self.finish(run_id, "succeeded", error=None)

    def mark_failed(self, run_id: str, error: str) -> Run:
        return self.finish(run_id, "failed", error=error)

    def mark_cancelled(self, run_id: str, *, reason: str = "cancelled") -> Run:
        return self.finish(run_id, "cancelled", error=reason)

    # --- user edits --------------------------------------------------------

    def patch_flags(
        self,
        run_id: str,
        *,
        favourite: bool | None = None,
        archived: bool | None = None,
        notes: str | None = None,
        label: str | None = None,
    ) -> Run:
        assignments: dict[str, Any] = {}
        if favourite is not None:
            assignments["favourite"] = _bool_col(favourite)
        if archived is not None:
            assignments["archived"] = _bool_col(archived)
        if notes is not None:
            assignments["notes"] = notes
        if label is not None and label.strip():
            assignments["label"] = label.strip()
        return self._update(run_id, assignments)

    def set_tags(self, run_id: str, tags: Iterable[str]) -> Run:
        clean = sorted({tag.strip().lower() for tag in tags if tag and tag.strip()})
        with session(self._connect) as conn, transaction(conn):
            exists = scalar(conn, "SELECT 1 FROM runs WHERE id = ?", (run_id,))
            if exists is None:
                raise RunNotFound(run_id)
            conn.execute("DELETE FROM run_tags WHERE run_id = ?", (run_id,))
            conn.executemany(
                "INSERT INTO run_tags (run_id, tag) VALUES (?, ?)",
                [(run_id, tag) for tag in clean],
            )
        return self.require(run_id)

    def delete(self, run_id: str) -> bool:
        with session(self._connect) as conn, transaction(conn):
            cursor = conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
            return cursor.rowcount > 0
