from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from h3lab.domain.config import config_hash
from h3lab.domain.rating import Rating
from h3lab.domain.run import Artifact, RunMetrics
from h3lab.storage import (
    LATEST_VERSION,
    AppState,
    PresetNameTaken,
    PresetRepository,
    RatingRepository,
    RunFilter,
    RunNotFound,
    RunRepository,
    VoteRepository,
    apply_migrations,
    connect,
    current_version,
    open_store,
)
from h3lab.storage.db import transaction
from h3lab.storage.legacy import backfill_previews, import_legacy


@pytest.fixture
def store(tmp_path: Path):
    return open_store(tmp_path / "lab.db")


@pytest.fixture
def runs(store) -> RunRepository:
    return RunRepository(store)


@pytest.fixture
def ratings(store) -> RatingRepository:
    return RatingRepository(store)


@pytest.fixture
def votes(store) -> VoteRepository:
    return VoteRepository(store)


# --- migrations ------------------------------------------------------------


def test_migrating_an_empty_file_creates_every_table(tmp_path: Path):
    conn = connect(tmp_path / "fresh.db")
    assert current_version(conn) == 0
    assert apply_migrations(conn) == LATEST_VERSION
    names = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"runs", "run_tags", "ratings", "votes", "presets", "app_state"} <= names
    conn.close()


def test_migrating_twice_is_a_no_op(tmp_path: Path):
    conn = connect(tmp_path / "again.db")
    first = apply_migrations(conn)
    second = apply_migrations(conn)
    assert first == second == LATEST_VERSION
    conn.close()


def test_rollback_inside_a_transaction_leaves_no_row(tmp_path: Path):
    conn = connect(tmp_path / "rb.db")
    apply_migrations(conn)
    with pytest.raises(RuntimeError):
        with transaction(conn):
            conn.execute("INSERT INTO app_state (key, value) VALUES ('x', '1')")
            raise RuntimeError("boom")
    assert conn.execute("SELECT COUNT(*) FROM app_state WHERE key='x'").fetchone()[0] == 0
    conn.close()


def test_foreign_keys_cascade_a_deleted_run(runs, ratings, votes, base_config):
    a = runs.create(base_config)
    b = runs.create(base_config.merged(seed=2))
    ratings.put(a.id, 7)
    runs.set_tags(a.id, ["keep"])
    votes.add(a.id, b.id, a.id)

    assert runs.delete(a.id) is True
    assert ratings.get(a.id) is None
    assert votes.count() == 0
    assert runs.get(a.id) is None
    assert runs.get(b.id) is not None


# --- run repository --------------------------------------------------------


def test_create_allocates_sequence_label_and_hashes(runs, base_config):
    first = runs.create(base_config)
    second = runs.create(base_config.merged(seed=99))
    assert first.seq == 1 and second.seq == 2
    assert first.label.startswith("#1 ")
    assert first.config_hash == config_hash(base_config)
    assert first.recipe_hash == second.recipe_hash
    assert first.id != second.id
    assert first.status == "queued"


def test_ids_are_unique_across_a_burst(runs, base_config):
    made = [runs.create(base_config.merged(seed=n)) for n in range(25)]
    assert len({run.id for run in made}) == 25
    assert [run.seq for run in made] == list(range(1, 26))


def test_updating_one_run_does_not_touch_a_sibling(runs, base_config):
    keeper = runs.create(base_config)
    runs.update_metrics(keeper.id, RunMetrics(wall_s=200.0, sec_per_it=10.0, steps=20))
    runs.mark_succeeded(keeper.id)

    other = runs.create(base_config.merged(seed=2))
    runs.mark_failed(other.id, "comfy said no")

    # The bug the old whole-suite write caused: a later write clobbering an earlier row.
    reloaded = runs.require(keeper.id)
    assert reloaded.status == "succeeded"
    assert reloaded.metrics.wall_s == 200.0
    assert reloaded.metrics.sec_per_it == 10.0
    assert reloaded.error is None
    assert runs.require(other.id).error == "comfy said no"


def test_claim_next_hands_each_run_to_exactly_one_caller(runs, base_config):
    first = runs.create(base_config)
    second = runs.create(base_config.merged(seed=2))
    claimed = [runs.claim_next(), runs.claim_next()]
    assert {run.id for run in claimed} == {first.id, second.id}
    assert all(run.status == "running" for run in claimed)
    assert runs.claim_next() is None


def test_claim_next_is_first_in_first_out(runs, base_config):
    first = runs.create(base_config)
    runs.create(base_config.merged(seed=2))
    assert runs.claim_next().id == first.id


def test_reconcile_turns_a_crashed_run_into_interrupted(runs, base_config):
    runs.create(base_config)
    running = runs.claim_next()
    assert runs.reconcile() == 1
    recovered = runs.require(running.id)
    assert recovered.status == "interrupted"
    assert "restart" in (recovered.error or "")
    assert recovered.finished_at is not None
    assert runs.reconcile() == 0


def test_cancel_queued_clears_the_backlog(runs, base_config):
    runs.create(base_config)
    runs.create(base_config.merged(seed=2))
    assert runs.cancel_queued() == 2
    assert runs.queued_ids() == []


def test_missing_run_raises_run_not_found(runs):
    with pytest.raises(RunNotFound):
        runs.require("NOPE")
    with pytest.raises(RunNotFound):
        runs.mark_succeeded("NOPE")


def test_metrics_and_artifact_round_trip(runs, base_config):
    run = runs.create(base_config)
    runs.update_metrics(
        run.id,
        RunMetrics(wall_s=123.5, sec_per_it=6.2, steps=20, sampler_cached=False, cache_cleared=True),
    )
    runs.attach_artifact(
        run.id,
        Artifact(
            video_path="v.mp4",
            poster_path="p.jpg",
            strip_path="s.jpg",
            width=1280,
            height=720,
            fps=24.0,
            frame_count=120,
            size_bytes=999,
        ),
    )
    reloaded = runs.require(run.id)
    assert reloaded.metrics.sec_per_it == 6.2
    assert reloaded.metrics.it_per_sec == pytest.approx(1 / 6.2)
    assert reloaded.metrics.cache_cleared is True
    assert reloaded.artifact.resolution == "1280×720"
    assert reloaded.artifact.has_video


def test_flags_tags_and_notes_are_editable(runs, base_config):
    run = runs.create(base_config)
    runs.patch_flags(run.id, favourite=True, notes="keeper")
    runs.set_tags(run.id, ["Cyberpunk", " keeper ", "cyberpunk"])
    reloaded = runs.require(run.id)
    assert reloaded.favourite is True
    assert reloaded.notes == "keeper"
    assert reloaded.tags == ("cyberpunk", "keeper")
    assert runs.tags() == ["cyberpunk", "keeper"]


def test_config_is_immutable_after_creation(runs, base_config):
    run = runs.create(base_config)
    with pytest.raises(Exception):
        run.config.steps = 5  # type: ignore[misc]


def test_list_filters_and_paginates(runs, ratings, base_config):
    made = [runs.create(base_config.merged(seed=n)) for n in range(5)]
    runs.mark_succeeded(made[0].id)
    runs.patch_flags(made[1].id, favourite=True)
    runs.patch_flags(made[2].id, archived=True)
    ratings.put(made[3].id, 9)
    runs.set_tags(made[4].id, ["night"])

    assert runs.list(RunFilter(status=("succeeded",))).total == 1
    assert runs.list(RunFilter(favourite=True)).total == 1
    assert runs.list(RunFilter(archived=True)).total == 1
    assert runs.list(RunFilter(archived=None)).total == 5
    assert runs.list(RunFilter(rated=True)).total == 1
    assert runs.list(RunFilter(min_stars=10)).total == 0
    assert runs.list(RunFilter(min_stars=9)).total == 1
    assert runs.list(RunFilter(tag="night")).total == 1
    assert runs.list(RunFilter(mode="flf2v")).total == 4  # the archived one is hidden

    page = runs.list(limit=2, offset=0)
    assert len(page.items) == 2 and page.total == 4
    assert runs.list(limit=2, offset=2).items[0].id not in {r.id for r in page.items}


def test_list_query_matches_label_notes_and_prompt(runs, base_config):
    run = runs.create(base_config.merged(prompt="a lighthouse in fog"))
    runs.patch_flags(run.id, notes="the good one")
    assert runs.list(RunFilter(query="lighthouse")).total == 1
    assert runs.list(RunFilter(query="good one")).total == 1
    assert runs.list(RunFilter(query="nothing here")).total == 0


def test_sorting_puts_missing_values_last(runs, base_config):
    slow = runs.create(base_config.merged(seed=1))
    fast = runs.create(base_config.merged(seed=2))
    runs.create(base_config.merged(seed=3))  # never timed
    runs.update_metrics(slow.id, RunMetrics(sec_per_it=20.0))
    runs.update_metrics(fast.id, RunMetrics(sec_per_it=5.0))
    order = [run.id for run in runs.list(sort="fastest").items]
    assert order[0] == fast.id and order[1] == slow.id


def test_duplicate_detection_uses_the_config_hash(runs, base_config):
    first = runs.create(base_config)
    second = runs.create(base_config)
    assert runs.duplicates(second.config_hash, exclude_id=second.id) == [first.id]
    assert runs.hashes()[first.config_hash] == first.id


def test_status_counts_summarise_the_table(runs, base_config):
    runs.mark_succeeded(runs.create(base_config).id)
    runs.create(base_config.merged(seed=2))
    assert runs.status_counts() == {"succeeded": 1, "queued": 1}


# --- judgement -------------------------------------------------------------


def test_rating_upsert_replaces_rather_than_duplicating(runs, ratings, base_config):
    run = runs.create(base_config)
    ratings.put(run.id, 5)
    ratings.put(run.id, 8, {"motion": 4})
    stored = ratings.get(run.id)
    assert stored.stars == 8
    assert stored.criteria == {"motion": 4}
    assert list(ratings.all_map()) == [run.id]
    assert ratings.stars_map() == {run.id: 8}


def test_rating_an_unknown_run_is_refused(ratings):
    with pytest.raises(RunNotFound):
        ratings.put("NOPE", 5)


def test_deleting_a_rating_reports_whether_it_existed(runs, ratings, base_config):
    run = runs.create(base_config)
    ratings.put(run.id, 5)
    assert ratings.delete(run.id) is True
    assert ratings.delete(run.id) is False


def test_votes_reject_self_comparison_and_a_foreign_winner(runs, votes, base_config):
    a = runs.create(base_config)
    b = runs.create(base_config.merged(seed=2))
    with pytest.raises(ValueError):
        votes.add(a.id, a.id, a.id)
    with pytest.raises(ValueError):
        votes.add(a.id, b.id, "SOMEONE_ELSE")
    with pytest.raises(RunNotFound):
        votes.add(a.id, "NOPE", None)


def test_elo_is_derived_from_the_stored_vote_log(runs, votes, base_config):
    a = runs.create(base_config)
    b = runs.create(base_config.merged(seed=2))
    votes.add(a.id, b.id, a.id)
    table = votes.elo()
    assert table[a.id].rating == pytest.approx(1512.0)
    assert table[b.id].rating == pytest.approx(1488.0)
    assert votes.for_run(a.id)[0].winner == a.id


def test_deleting_a_vote_removes_its_effect(runs, votes, base_config):
    a = runs.create(base_config)
    b = runs.create(base_config.merged(seed=2))
    vote = votes.add(a.id, b.id, a.id)
    assert votes.delete(vote.id) is True
    assert votes.elo() == {}


# --- presets and state -----------------------------------------------------


def test_presets_are_named_uniquely_and_can_be_overwritten(store, base_config):
    presets = PresetRepository(store)
    presets.create("night ride", base_config)
    with pytest.raises(PresetNameTaken):
        presets.create("night ride", base_config)
    presets.create("night ride", base_config.merged(steps=30), replace=True)
    assert len(presets.list()) == 1
    assert presets.get_by_name("night ride").config.steps == 30


def test_preset_needs_a_name(store, base_config):
    with pytest.raises(ValueError):
        PresetRepository(store).create("   ", base_config)


def test_preset_round_trips_the_config_and_can_be_deleted(store, base_config):
    presets = PresetRepository(store)
    saved = presets.create("keeper", base_config, source_run_id="RUN1")
    loaded = presets.get(saved.id)
    assert loaded.config == base_config
    assert loaded.source_run_id == "RUN1"
    assert presets.delete(saved.id) is True
    assert presets.get(saved.id) is None


def test_baseline_pin_round_trips_and_clears(store):
    state = AppState(store)
    assert state.baseline_run_id is None
    state.set_baseline("RUN9")
    assert state.baseline_run_id == "RUN9"
    state.set_baseline(None)
    assert state.baseline_run_id is None


# --- legacy import ---------------------------------------------------------


LEGACY_SCHEMA = """
CREATE TABLE runs (
    id TEXT PRIMARY KEY, phase TEXT, status TEXT, config_json TEXT,
    warmup_s REAL, timed_s REAL, sec_per_it REAL, sampler_cached INTEGER,
    graph_cache_cleared INTEGER, video_path TEXT, prompt_id TEXT, error TEXT,
    started_at TEXT, finished_at TEXT, rating INTEGER, excluded INTEGER,
    sort_order INTEGER
);
"""

LEGACY_CONFIG = {
    "model_path": "safetensor",
    "quant": "nvfp4",
    "diffusion_model": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    "mode": "flf2v",
    "first_frame": "frame.jpeg",
    "last_frame": "",
    "ref_images": [],
    "ref_videos": [],
    "ref_video_audios": [],
    "ref_audios": [],
    "ref_image_size": "match",
    "prompt": "a courier",
    "aspect_ratio": "16:9 (Widescreen)",
    "turbo": False,
    "rife": False,
    "upscaler": False,
    "clean_vram": False,
    "cache_enabled": True,
    "cache": "spectrum",
    "cache_preset": "custom",
    "sol_attn": True,
    "sol_preset": "custom",
    "widgets": {"tau": 1.5},
    "scheduler": "beta57",
    "sampler": "euler",
    "steps": 20,
    "mp": 0.5,
    "duration_s": 5.0,
    "seed": 42,
    "cache_variant": None,
    "sol_variant": None,
}


def _write_legacy_db(path: Path, videos_dir: Path) -> None:
    videos_dir.mkdir(parents=True, exist_ok=True)
    (videos_dir / "run_001.mp4").write_bytes(b"not really a video")
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    rows = [
        (
            "run_001_int8_spectrum_solon",
            "manual",
            "done",
            json.dumps(LEGACY_CONFIG),
            None,
            197.66,
            8.14,
            0,
            1,
            "videos/run_001.mp4",
            "pid-1",
            None,
            None,
            None,
            9,
            0,
            0,
        ),
        (
            "run_002_int8_h3_solon",
            "manual",
            "done",
            json.dumps({**LEGACY_CONFIG, "cache": "h3", "seed": 43}),
            None,
            250.0,
            12.5,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            1,
            1,
        ),
        (
            "run_003_int8_spectrum_solon",
            "manual",
            "failed",
            json.dumps({**LEGACY_CONFIG, "seed": 44}),
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "comfy exploded",
            None,
            None,
            None,
            0,
            2,
        ),
        (
            "run_004_refs",
            "manual",
            "timing",
            json.dumps({**LEGACY_CONFIG, "mode": "r2v", "seed": 45}),
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            0,
            3,
        ),
    ]
    conn.executemany(
        "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def test_legacy_import_maps_every_field(tmp_path, settings, store):
    legacy_db = tmp_path / "benchmark.db"
    legacy_videos = tmp_path / "legacy-videos"
    _write_legacy_db(legacy_db, legacy_videos)

    runs = RunRepository(store)
    ratings = RatingRepository(store)
    state = AppState(store)

    report = import_legacy(
        legacy_db,
        runs=runs,
        ratings=ratings,
        state=state,
        settings=settings,
        legacy_videos_dir=legacy_videos,
    )

    assert report.runs_imported == 4
    assert report.ratings_imported == 1
    assert report.videos_copied == 1
    assert report.skipped == []

    everything = runs.all(RunFilter(archived=None))
    assert len(everything) == 4
    # Provenance is recorded in the notes, so the label stays the same shape as a native run's.
    by_source = {run.notes.removeprefix("imported from "): run for run in everything}
    assert all(run.label.startswith("#") and "←" not in run.label for run in everything)

    done = by_source["run_001_int8_spectrum_solon"]
    assert done.status == "succeeded"
    assert done.metrics.wall_s == pytest.approx(197.66)
    assert done.metrics.sec_per_it == pytest.approx(8.14)
    assert done.metrics.cache_cleared is True
    assert done.artifact.video_path == f"{done.id}.mp4"
    assert (settings.videos_dir / done.artifact.video_path).is_file()
    assert ratings.get(done.id).stars == 9
    assert "imported" in done.tags
    # Legacy-only fields must not survive into the config.
    assert not hasattr(done.config, "model_path")

    excluded = by_source["run_002_int8_h3_solon"]
    assert excluded.archived is True

    failed = by_source["run_003_int8_spectrum_solon"]
    assert failed.status == "failed"
    assert failed.error == "comfy exploded"

    orphan = by_source["run_004_refs"]
    assert orphan.status == "interrupted"
    # A reference run with no references left is kept as a text-to-video timing record.
    assert orphan.config.mode == "t2v"


def test_legacy_import_is_idempotent(tmp_path, settings, store):
    legacy_db = tmp_path / "benchmark.db"
    legacy_videos = tmp_path / "legacy-videos"
    _write_legacy_db(legacy_db, legacy_videos)

    runs = RunRepository(store)
    ratings = RatingRepository(store)
    state = AppState(store)
    kwargs = dict(
        runs=runs, ratings=ratings, state=state, settings=settings, legacy_videos_dir=legacy_videos
    )

    first = import_legacy(legacy_db, **kwargs)
    second = import_legacy(legacy_db, **kwargs)

    assert first.runs_imported == 4
    assert second.runs_imported == 0
    assert second.already_present == 4
    assert len(runs.all(RunFilter(archived=None))) == 4


def _synthesise_clip(destination: Path) -> None:
    """A real clip, because a poster of fake bytes proves nothing."""
    import shutil
    import subprocess

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is not installed in this environment")
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         "testsrc=size=320x180:rate=24:duration=2", "-pix_fmt", "yuv420p", str(destination)],
        capture_output=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0 or not destination.is_file():
        pytest.skip(f"ffmpeg could not synthesise a clip: {result.stderr[:200]!r}")


def test_a_run_with_a_video_but_no_previews_gets_them_backfilled(runs, settings, base_config):
    """The gap imported runs arrive with: real video on disk, nothing to show for it."""
    run = runs.create(base_config)
    _synthesise_clip(settings.videos_dir / f"{run.id}.mp4")
    runs.attach_artifact(run.id, Artifact(video_path=f"{run.id}.mp4"))
    assert runs.require(run.id).artifact.strip_path is None

    assert backfill_previews(runs, settings) == 1

    healed = runs.require(run.id).artifact
    assert healed.strip_path == f"{run.id}.jpg"
    assert healed.poster_path == f"{run.id}.jpg"
    assert (settings.strips_dir / healed.strip_path).is_file()
    assert (settings.posters_dir / healed.poster_path).is_file()
    # The probe runs too, so the list can report a resolution without opening the file.
    assert (healed.width, healed.height) == (320, 180)

    # A second pass has nothing left to do, so the command stays cheap to repeat.
    assert backfill_previews(runs, settings) == 0


def test_backfill_leaves_a_run_with_no_video_alone(runs, settings, base_config):
    runs.create(base_config)
    assert backfill_previews(runs, settings) == 0


def test_an_archived_run_still_gets_its_previews(runs, settings, base_config):
    """Archived means hidden, not half-imported.

    The legacy importer maps the old `excluded` flag onto `archived`, and the default run
    filter hides archived rows — so the one imported run that had been excluded was the one
    run that never got a poster. Un-archiving it would have shown a placeholder for a video
    that was sitting on disk the whole time.
    """
    run = runs.create(base_config)
    _synthesise_clip(settings.videos_dir / f"{run.id}.mp4")
    runs.attach_artifact(run.id, Artifact(video_path=f"{run.id}.mp4"))
    runs.patch_flags(run.id, archived=True)

    assert backfill_previews(runs, settings) == 1
    assert runs.require(run.id).artifact.strip_path == f"{run.id}.jpg"


def test_legacy_import_of_a_missing_file_is_harmless(tmp_path, settings, store):
    report = import_legacy(
        tmp_path / "nope.db",
        runs=RunRepository(store),
        ratings=RatingRepository(store),
        state=AppState(store),
        settings=settings,
    )
    assert report.runs_imported == 0
