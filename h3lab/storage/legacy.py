"""One-shot import of the previous benchmark's SQLite store.

Reads the old database without writing to it, so it is safe to run while the previous
tool is still up. Keyed on the legacy run id, so importing twice adds nothing.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from h3lab.domain.config import LEGACY_FIELD_ALIASES, GenerationConfig
from h3lab.domain.run import Artifact, RunMetrics, RunStatus
from h3lab.settings import Settings
from h3lab.storage.judgement import RatingRepository
from h3lab.storage.library import AppState
from h3lab.storage.runs import RunFilter, RunRepository

# Fields the previous config carried that the current one does not model. The loader
# derived model_path/quant from the filename, so nothing is lost by dropping them.
DROPPED_FIELDS = frozenset({"model_path", "quant", "cache_variant", "sol_variant", "phase"})

STATUS_MAP: dict[str, RunStatus] = {
    "done": "succeeded",
    "failed": "failed",
    "aborted": "cancelled",
    "queued": "interrupted",
    "warmup": "interrupted",
    "timing": "interrupted",
}


class ImportReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    runs_imported: int = 0
    ratings_imported: int = 0
    videos_copied: int = 0
    previews_built: int = 0
    already_present: int = 0
    skipped: list[str] = []

    @property
    def total_seen(self) -> int:
        return self.runs_imported + self.already_present + len(self.skipped)


def _config_from_legacy(raw: dict) -> GenerationConfig:
    data = {key: value for key, value in raw.items() if key not in DROPPED_FIELDS}
    # Legacy aliases are kept and translated by the model. Dropping them here would lose the
    # setting silently, which is worse than the rename it survived.
    known = set(GenerationConfig.model_fields) | LEGACY_FIELD_ALIASES
    data = {key: value for key, value in data.items() if key in known and value is not None}
    try:
        return GenerationConfig(**data)
    except ValidationError:
        # A reference run whose media list did not survive is still worth keeping as a
        # timing record; text-to-video is the honest description of what we can replay.
        repaired = dict(data)
        if repaired.get("mode") == "r2v":
            repaired["mode"] = "t2v"
        repaired.pop("first_frame", None)
        repaired.pop("last_frame", None)
        if repaired.get("mode") == "flf2v":
            repaired["mode"] = "t2v"
        return GenerationConfig(**repaired)


def backfill_previews(runs: RunRepository, settings: Settings) -> int:
    """Derive the poster and filmstrip for any run that has a video but no previews.

    Imported runs arrive as bare videos, and a run that finished while ffmpeg was missing has
    the same gap. Without this they are invisible in the one view built for scanning fifty
    near-identical clips at once. Safe to call repeatedly: a run with a strip is left alone.
    """
    # Imported here rather than at module scope: `h3lab.engine` pulls in the Lab facade, which
    # imports this module, so a top-level import would close a cycle.
    from h3lab.engine import artifacts

    if not (artifacts.tool_available(settings.ffmpeg) and artifacts.tool_available(settings.ffprobe)):
        return 0

    built = 0
    # `archived=None` because the default filter hides archived rows, and an archived run is
    # hidden, not incomplete — un-archiving it must not reveal a video with no preview.
    for run in runs.all(RunFilter(archived=None, with_video=True)):
        artifact = run.artifact
        if not artifact.video_path or artifact.strip_path:
            continue
        video = settings.videos_dir / artifact.video_path
        if not video.is_file():
            continue
        runs.attach_artifact(run.id, artifacts.build(run.id, video, settings))
        built += 1
    return built


def _open_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _legacy_rows(path: Path) -> list[sqlite3.Row]:
    conn = _open_readonly(path)
    try:
        return conn.execute("SELECT * FROM runs ORDER BY sort_order ASC, id ASC").fetchall()
    finally:
        conn.close()


def import_legacy(
    legacy_db: Path,
    *,
    runs: RunRepository,
    ratings: RatingRepository,
    state: AppState,
    settings: Settings,
    legacy_videos_dir: Path | None = None,
) -> ImportReport:
    if not Path(legacy_db).is_file():
        return ImportReport()

    source_videos = Path(legacy_videos_dir or Path(legacy_db).parent / "videos")
    settings.ensure_dirs()
    seen = state.legacy_imported()

    imported = 0
    rated = 0
    copied = 0
    already = 0
    skipped: list[str] = []

    for row in _legacy_rows(legacy_db):
        legacy_id = str(row["id"])
        if legacy_id in seen:
            already += 1
            continue
        try:
            config = _config_from_legacy(json.loads(row["config_json"] or "{}"))
        except (ValidationError, json.JSONDecodeError) as exc:
            skipped.append(f"{legacy_id}: unusable config ({exc.__class__.__name__})")
            state.mark_legacy_imported(legacy_id, None)
            continue

        status = STATUS_MAP.get(str(row["status"]), "interrupted")
        run = runs.create(config, status="queued")
        # Provenance goes in the notes and the tag, not the label: labels are what every list
        # and comparison reads, and appending a legacy id makes them wrap and hides the setting.
        runs.patch_flags(
            run.id,
            archived=bool(row["excluded"]),
            notes=f"imported from {legacy_id}",
        )
        runs.set_tags(run.id, ["imported"])
        runs.update_metrics(
            run.id,
            RunMetrics(
                wall_s=row["timed_s"],
                sec_per_it=row["sec_per_it"],
                steps=config.effective_steps,
                sampler_cached=(
                    None if row["sampler_cached"] is None else bool(row["sampler_cached"])
                ),
                cache_cleared=(
                    None
                    if row["graph_cache_cleared"] is None
                    else bool(row["graph_cache_cleared"])
                ),
            ),
        )

        video_name = row["video_path"]
        if video_name:
            source = source_videos / Path(str(video_name)).name
            if source.is_file():
                destination = settings.videos_dir / f"{run.id}{source.suffix or '.mp4'}"
                shutil.copy2(source, destination)
                copied += 1
                runs.attach_artifact(run.id, Artifact(video_path=destination.name))

        error = row["error"]
        runs.finish(run.id, status, error=(str(error) if error else None))

        stars = row["rating"]
        if stars is not None:
            try:
                ratings.put(run.id, int(stars))
                rated += 1
            except (ValueError, TypeError):
                pass

        state.mark_legacy_imported(legacy_id, run.id)
        imported += 1

    return ImportReport(
        runs_imported=imported,
        ratings_imported=rated,
        videos_copied=copied,
        # Runs from an earlier import land here too, so one command makes old data legible.
        previews_built=backfill_previews(runs, settings),
        already_present=already,
        skipped=skipped,
    )
