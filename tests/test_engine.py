"""Event bus, artifacts, the runner loop, and the Lab facade."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Iterator

import pytest

from h3lab.comfy.client import ComfyError, PromptRejected
from h3lab.domain.run import Artifact
from h3lab.domain.sweeps import SweepAxis, SweepSpec
from h3lab.engine import artifacts
from h3lab.engine.events import Event, EventBus
from h3lab.engine.lab import Lab
from h3lab.engine.runner import PreflightError, Runner, WorkflowCache, preflight
from h3lab.settings import Settings
from h3lab.storage import open_store
from h3lab.storage.runs import RunFilter, RunRepository

HAS_FFMPEG = shutil.which("ffmpeg") is not None
HAS_FFPROBE = shutil.which("ffprobe") is not None


# --- event bus -------------------------------------------------------------


def test_a_subscriber_receives_published_events():
    bus = EventBus()
    with bus.subscribe() as subscription:
        bus.publish("run.created", run_id="R1", label="one")
        event = subscription.get(timeout=1.0)
    assert event is not None
    assert event.kind == "run.created"
    assert event.run_id == "R1"
    assert event.data["label"] == "one"
    assert event.seq == 1


def test_sequence_numbers_increase_and_are_visible_on_the_bus():
    bus = EventBus()
    bus.publish("heartbeat")
    bus.publish("heartbeat")
    assert bus.last_seq == 2


def test_a_reconnecting_subscriber_replays_what_it_missed():
    bus = EventBus()
    bus.publish("run.created", run_id="R1")
    bus.publish("run.started", run_id="R1")
    bus.publish("run.finished", run_id="R1")
    with bus.subscribe(replay_after=1) as subscription:
        replayed = subscription.drain()
    assert [event.kind for event in replayed] == ["run.started", "run.finished"]


def test_a_stalled_subscriber_drops_old_events_instead_of_blocking():
    bus = EventBus()
    subscription = bus.subscribe()
    subscription._queue.maxsize  # the bound is what makes this safe
    for index in range(subscription._queue.maxsize + 40):
        bus.publish("heartbeat", index=index)
    assert subscription.dropped >= 40
    remaining = subscription.drain()
    # The newest events survive; the oldest are the ones sacrificed.
    assert remaining[-1].data["index"] == subscription._queue.maxsize + 39
    subscription.close()


def test_closing_a_subscription_removes_it_from_the_bus():
    bus = EventBus()
    subscription = bus.subscribe()
    assert bus.subscriber_count == 1
    subscription.close()
    assert bus.subscriber_count == 0


def test_the_replay_buffer_is_bounded():
    bus = EventBus(buffer=10)
    for index in range(50):
        bus.publish("heartbeat", index=index)
    history = bus.history()
    assert len(history) == 10
    assert history[0].data["index"] == 40


def test_an_event_serialises_to_the_sse_wire_format():
    event = Event(seq=7, kind="run.progress", run_id="R1", data={"step": 3, "step_total": 20})
    text = event.to_sse()
    assert text.startswith("id: 7\ndata: {")
    assert text.endswith("\n\n")

    payload = json.loads(text.split("data: ", 1)[1])
    assert payload["seq"] == 7
    assert payload["kind"] == "run.progress"
    assert payload["run_id"] == "R1"
    assert payload["data"] == {"step": 3, "step_total": 20}


def test_a_frame_is_never_given_an_event_name():
    """A named SSE frame does not reach `onmessage`, and `onmessage` is the browser's default.

    This shipped broken: every frame carried `event: <kind>`, so the browser dispatched it to
    a listener named after the kind. The client registers `onmessage` and nothing else, so the
    stream connected, stayed open, reported no errors, and delivered nothing — the page only
    ever changed when something else refetched it.

    The kind travels in the payload, where the client already reads it. Naming the frame as
    well would mean the client had to enumerate every kind, and a kind added later would go
    quietly unheard — which is exactly the failure this replaced.
    """
    for kind in ("run.created", "run.finished", "queue.changed", "heartbeat"):
        frame = Event(seq=1, kind=kind).to_sse()
        assert not any(line.startswith("event:") for line in frame.splitlines()), kind
        assert json.loads(frame.split("data: ", 1)[1])["kind"] == kind


def test_a_payload_key_cannot_shadow_the_stream_position():
    """seq is what a reconnecting client resumes from, so no payload may overwrite it."""
    event = Event(seq=42, kind="run.created", run_id="R1", data={"seq": 1, "kind": "nonsense"})
    payload = json.loads(event.to_sse().split("data: ", 1)[1])
    assert payload["seq"] == 42
    assert payload["kind"] == "run.created"
    assert payload["data"]["seq"] == 1


def test_the_stream_emits_a_heartbeat_when_idle():
    bus = EventBus()
    with bus.subscribe() as subscription:
        stream = subscription.stream(heartbeat_s=0.05)
        assert next(stream).kind == "heartbeat"
        bus.publish("run.created", run_id="R1")
        assert next(stream).kind == "run.created"


# --- artifacts -------------------------------------------------------------


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    """A real two-second clip, so ffprobe has something true to report."""
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg is not installed in this environment")
    destination = tmp_path / "sample.mp4"
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=24:duration=2",
            "-pix_fmt",
            "yuv420p",
            str(destination),
        ],
        capture_output=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0 or not destination.is_file():
        pytest.skip(f"ffmpeg could not synthesise a clip: {result.stderr[:200]!r}")
    return destination


@pytest.mark.skipif(not HAS_FFPROBE, reason="ffprobe is not installed")
def test_probing_a_real_clip_reports_its_shape(sample_video: Path):
    details = artifacts.probe(sample_video)
    assert details.width == 320
    assert details.height == 180
    assert details.fps == pytest.approx(24.0, rel=0.01)
    assert details.duration_s == pytest.approx(2.0, abs=0.2)
    assert details.frame_count == pytest.approx(48, abs=2)


def test_probing_something_that_is_not_a_video_reports_nothing(tmp_path: Path):
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"definitely not a video")
    details = artifacts.probe(broken)
    assert details.width is None
    assert details.frame_count is None


def test_frame_rate_fractions_are_parsed():
    assert artifacts._parse_rate("24000/1001") == pytest.approx(23.976, rel=0.001)
    assert artifacts._parse_rate("24") == 24.0
    assert artifacts._parse_rate("0/0") is None
    assert artifacts._parse_rate(None) is None
    assert artifacts._parse_rate("N/A") is None


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg is not installed")
def test_a_poster_and_filmstrip_are_rendered_from_a_real_clip(sample_video, settings):
    built = artifacts.build("RUN1", sample_video, settings)
    assert built.video_path == "sample.mp4"
    assert built.poster_path == "RUN1.jpg"
    assert built.strip_path == "RUN1.jpg"
    assert (settings.posters_dir / "RUN1.jpg").stat().st_size > 0
    strip = settings.strips_dir / "RUN1.jpg"
    assert strip.stat().st_size > 0
    # A filmstrip is a row of tiles, so it must be much wider than one poster frame.
    strip_shape = artifacts.probe(strip)
    assert strip_shape.width is not None and strip_shape.width > artifacts.POSTER_WIDTH
    assert built.width == 320
    assert built.size_bytes and built.size_bytes > 0


@pytest.mark.skipif(not (HAS_FFMPEG and HAS_FFPROBE), reason="ffmpeg/ffprobe not installed")
def test_the_poster_seek_uses_the_ffprobe_it_was_given(sample_video, tmp_path):
    """`ffprobe` has to travel with `ffmpeg`, not be re-guessed as a bare name.

    The poster is meant to come from a third of the way in, which needs the duration, which
    needs ffprobe. When the configured ffprobe was ignored in favour of the bare name, anyone
    whose ffprobe is off `PATH` silently got frame zero — a black or fade-up frame — for every
    run, with no error to explain it.
    """
    from_probe = tmp_path / "seeked.jpg"
    without_probe = tmp_path / "frame-zero.jpg"
    assert artifacts.make_poster(sample_video, from_probe) is not None
    assert artifacts.make_poster(sample_video, without_probe, ffprobe="nope-not-a-tool")

    # `testsrc` counts up on screen, so a frame from a third in cannot equal frame zero.
    assert from_probe.read_bytes() != without_probe.read_bytes()


def test_a_missing_render_tool_still_produces_a_usable_artifact(tmp_path, settings):
    video = settings.videos_dir / "clip.mp4"
    video.write_bytes(b"pretend video")
    broken = Settings(
        data_dir=settings.data_dir,
        models_dir=settings.models_dir,
        comfy_input_dir=settings.comfy_input_dir,
        ffmpeg="ffmpeg-that-does-not-exist",
        ffprobe="ffprobe-that-does-not-exist",
    )
    built = artifacts.build("RUN2", video, broken)
    assert built.video_path == "clip.mp4"
    assert built.poster_path is None
    assert built.strip_path is None
    assert built.size_bytes == len(b"pretend video")


# --- the runner ------------------------------------------------------------


@pytest.fixture
def runner_setup(lab_settings, stub) -> Iterator[tuple[Runner, RunRepository, EventBus]]:
    store = open_store(lab_settings.db_path)
    runs = RunRepository(store)
    bus = EventBus()
    runner = Runner(runs=runs, settings=lab_settings, events=bus, client=stub)  # type: ignore[arg-type]
    try:
        yield runner, runs, bus
    finally:
        runner.stop(timeout=3.0)


def wait_for(predicate, *, timeout: float = 8.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_preflight_reports_a_missing_input_file(lab_settings, base_config):
    assert preflight(base_config.merged(first_frame="frame.png"), lab_settings) == []
    problems = preflight(base_config.merged(first_frame="absent.png"), lab_settings)
    assert problems == ["absent.png is not in ComfyUI's input folder"]


def test_the_worker_runs_a_queued_run_to_completion(runner_setup, base_config, stub):
    runner, runs, bus = runner_setup
    subscription = bus.subscribe()
    run = runs.create(base_config.merged(first_frame="frame.png"))
    runner.start()

    assert wait_for(lambda: runs.require(run.id).status == "succeeded")
    finished = runs.require(run.id)
    assert finished.metrics.sec_per_it == 8.5
    assert finished.metrics.wall_s == 170.0
    assert finished.metrics.steps == 20
    assert finished.metrics.cache_cleared is True
    assert finished.prompt_id == "stub-1"
    assert finished.artifact.video_path == f"{run.id}.mp4"
    assert (runner._settings.videos_dir / finished.artifact.video_path).is_file()
    assert stub.cache_clears == 1
    assert stub.downloads == ["stub.mp4"]

    kinds = [event.kind for event in subscription.drain()]
    assert "run.started" in kinds
    assert "run.progress" in kinds
    assert "run.finished" in kinds
    subscription.close()


def test_a_rejected_graph_marks_the_run_failed_with_the_reason(runner_setup, base_config, stub):
    runner, runs, _bus = runner_setup
    stub.raise_on_execute = PromptRejected("20.image: Value not in list")
    run = runs.create(base_config.merged(first_frame="frame.png"))
    runner.start()

    assert wait_for(lambda: runs.require(run.id).status == "failed")
    assert "Value not in list" in (runs.require(run.id).error or "")


def test_a_missing_input_file_fails_before_comfy_is_asked(runner_setup, base_config, stub):
    runner, runs, _bus = runner_setup
    run = runs.create(base_config.merged(first_frame="gone.png"))
    runner.start()

    assert wait_for(lambda: runs.require(run.id).status == "failed")
    assert "not in ComfyUI's input folder" in (runs.require(run.id).error or "")
    assert stub.submitted == []


def test_the_worker_survives_a_failing_run_and_continues(runner_setup, base_config, stub):
    runner, runs, _bus = runner_setup
    stub.raise_on_execute = ComfyError("the GPU fell over")
    first = runs.create(base_config.merged(first_frame="frame.png", seed=1))
    runner.start()
    assert wait_for(lambda: runs.require(first.id).status == "failed")

    stub.raise_on_execute = None
    second = runs.create(base_config.merged(first_frame="frame.png", seed=2))
    runner.nudge()
    assert wait_for(lambda: runs.require(second.id).status == "succeeded")
    assert runner.running is True


def test_an_unexpected_error_does_not_end_the_worker(runner_setup, base_config, stub):
    runner, runs, _bus = runner_setup
    stub.raise_on_execute = ZeroDivisionError("something absurd")
    first = runs.create(base_config.merged(first_frame="frame.png", seed=1))
    runner.start()
    assert wait_for(lambda: runs.require(first.id).status == "failed")
    assert "unexpected error" in (runs.require(first.id).error or "")

    stub.raise_on_execute = None
    second = runs.create(base_config.merged(first_frame="frame.png", seed=2))
    runner.nudge()
    assert wait_for(lambda: runs.require(second.id).status == "succeeded")


def test_a_diagnosed_failure_is_not_reported_as_an_unexpected_one(runner_setup, base_config):
    """A preflight refusal is the lab working, not the lab breaking.

    Queueing a run whose first frame is not in ComfyUI's input folder produced "the lab hit an
    unexpected error: …". Seen on a real run card, that reads as a crash and sends you looking
    for a bug, when the message underneath already says exactly which file to go and put where.
    """
    runner, runs, _bus = runner_setup
    run = runs.create(base_config.merged(first_frame="nowhere.png"))
    runner.start()

    assert wait_for(lambda: runs.require(run.id).status == "failed")
    message = runs.require(run.id).error or ""
    assert "nowhere.png is not in ComfyUI's input folder" in message
    assert "unexpected" not in message
    # Still distinguishable from a crash: the worker survived and takes the next run.
    following = runs.create(base_config.merged(first_frame="frame.png"))
    runner.nudge()
    assert wait_for(lambda: runs.require(following.id).status == "succeeded")


def test_pausing_stops_the_worker_taking_new_runs(runner_setup, base_config):
    runner, runs, _bus = runner_setup
    runner.start()
    runner.pause()
    run = runs.create(base_config.merged(first_frame="frame.png"))
    time.sleep(0.6)
    assert runs.require(run.id).status == "queued"
    runner.resume()
    assert wait_for(lambda: runs.require(run.id).status == "succeeded")


def test_a_pause_landing_mid_claim_gives_the_run_back(runner_setup, base_config, stub):
    """The claim and the pause can race; the run must end up queued, not running."""
    runner, runs, _bus = runner_setup
    for index in range(20):
        runner.pause()
        runner.resume()
        run = runs.create(base_config.merged(first_frame="frame.png", seed=index))
        runner.start()
        runner.pause()
        time.sleep(0.05)
        status = runs.require(run.id).status
        assert status in ("queued", "running", "succeeded")
        if status == "queued":
            break
    runner.resume()
    assert wait_for(lambda: not runs.queued_ids())


def test_requeue_only_takes_back_a_running_run(runner_setup, base_config):
    _runner, runs, _bus = runner_setup
    run = runs.create(base_config.merged(first_frame="frame.png"))
    assert runs.requeue(run.id) is None  # still queued, nothing to give back
    claimed = runs.claim_next()
    returned = runs.requeue(claimed.id)
    assert returned is not None
    assert returned.status == "queued"
    assert returned.started_at is None
    runs.mark_succeeded(run.id)
    assert runs.requeue(run.id) is None  # a finished run is never resurrected


def test_cancelling_a_queued_run_never_starts_it(runner_setup, base_config, stub):
    runner, runs, _bus = runner_setup
    runner.pause()
    runner.start()
    run = runs.create(base_config.merged(first_frame="frame.png"))
    assert runner.cancel(run.id) is True
    assert runs.require(run.id).status == "cancelled"
    runner.resume()
    time.sleep(0.4)
    assert stub.submitted == []


def test_cancelling_the_active_run_interrupts_comfy(runner_setup, base_config, stub):
    runner, runs, _bus = runner_setup
    stub.block.clear()  # hold the run inside execute()
    run = runs.create(base_config.merged(first_frame="frame.png"))
    runner.start()
    assert wait_for(lambda: runner.active_run_id == run.id)

    stub.raise_on_execute = ComfyError("interrupted")
    assert runner.cancel(run.id) is True
    assert stub.cancels == 1
    assert wait_for(lambda: runs.require(run.id).status == "cancelled")


def test_restarting_recovers_a_run_left_mid_flight(runner_setup, base_config):
    runner, runs, bus = runner_setup
    runs.create(base_config.merged(first_frame="frame.png"))
    stranded = runs.claim_next()
    assert stranded.status == "running"

    subscription = bus.subscribe()
    runner.start()
    assert wait_for(lambda: runs.require(stranded.id).status == "interrupted")
    assert "restarted" in (runs.require(stranded.id).error or "")
    assert any("recovered" in (event.data.get("text") or "") for event in subscription.drain())
    subscription.close()


def test_the_workflow_cache_reads_each_template_once(lab_settings):
    cache = WorkflowCache(lab_settings)
    first = cache.get("flf2v")
    assert cache.get("flf2v") is first
    cache.invalidate()
    assert cache.get("flf2v") is not first


def test_an_unknown_mode_has_no_template(lab_settings):
    from h3lab.comfy.graph import WorkflowError

    with pytest.raises(WorkflowError):
        WorkflowCache(lab_settings).get("nonsense")


# --- the Lab facade --------------------------------------------------------


@pytest.fixture
def lab(lab_settings, stub) -> Iterator[Lab]:
    made = Lab(lab_settings, client=stub, start_worker=False)  # type: ignore[arg-type]
    try:
        yield made
    finally:
        made.close()


def test_enqueue_creates_a_run_and_announces_it(lab, base_config):
    subscription = lab.events.subscribe()
    views = lab.enqueue(base_config.merged(first_frame="frame.png"))
    assert len(views) == 1
    assert views[0].run.status == "queued"
    kinds = [event.kind for event in subscription.drain()]
    assert "run.created" in kinds and "queue.changed" in kinds
    subscription.close()


def test_enqueue_can_repeat_the_same_config(lab, base_config):
    views = lab.enqueue(base_config.merged(first_frame="frame.png"), count=3)
    assert len({view.run.id for view in views}) == 3
    assert len({view.run.config_hash for view in views}) == 1


def test_a_dry_run_reports_a_buildable_graph_without_queueing(lab, base_config):
    report = lab.dry_run(base_config.merged(first_frame="frame.png"))
    assert report.ok is True
    assert report.problems == []
    assert report.graph is not None
    assert report.graph.nodes > 10
    assert report.graph.missing_links == []
    assert lab.runs.list().total == 0


def test_a_dry_run_names_a_missing_input_file(lab, base_config):
    report = lab.dry_run(base_config.merged(first_frame="absent.png"))
    assert report.ok is False
    assert any("absent.png" in problem for problem in report.problems)


def test_a_dry_run_catches_a_cache_setting_the_node_will_refuse(lab, base_config):
    """The Spectrum node validates cross-field rules itself, but only once it holds the GPU.

    Before this, an impossible combination patched into a perfectly well-formed graph and
    the refusal arrived minutes later as a node error. A dry run answers in milliseconds.
    """
    report = lab.dry_run(
        base_config.merged(
            first_frame="frame.png",
            cache="spectrum",
            cache_preset="custom",
            widgets={"warmup_steps": 6, "bootstrap_first_forecast": True, "degree": 1},
        )
    )
    assert report.ok is False
    assert "bootstrap_first_forecast requires warmup_steps <= 1" in report.problems


def test_a_dry_run_catches_a_resolution_the_node_will_refuse(lab, base_config):
    """Below 0.1 MP the graph submits and is rejected, so the queue slot is wasted for nothing."""
    report = lab.dry_run(base_config.merged(first_frame="frame.png", mp=0.05))
    assert report.ok is False
    assert any("mp must be at least 0.1" in problem for problem in report.problems)


@pytest.mark.parametrize("preset", ["conservative", "moderate", "aggressive"])
def test_every_cache_level_passes_a_dry_run(lab, base_config, preset):
    for family in ("easy", "h3", "spectrum"):
        config = base_config.merged(
            first_frame="frame.png", cache=family, cache_preset=preset, sol_preset=preset
        )
        assert lab.dry_run(config).problems == [], f"{family}/{preset}"


def test_a_dry_run_points_at_the_run_that_already_did_this(lab, base_config):
    config = base_config.merged(first_frame="frame.png")
    existing = lab.enqueue(config)[0]
    assert lab.dry_run(config).duplicate_of == existing.run.id


def test_rerun_queues_the_same_experiment_and_records_the_origin(lab, base_config):
    source = lab.enqueue(base_config.merged(first_frame="frame.png"))[0]
    again = lab.rerun(source.run.id)
    assert again.run.config == source.run.config
    assert again.run.id != source.run.id
    assert source.run.label in again.run.notes


def test_rerun_with_an_override_produces_a_variant(lab, base_config):
    source = lab.enqueue(base_config.merged(first_frame="frame.png"))[0]
    variant = lab.rerun(source.run.id, overrides={"steps": 30})
    assert variant.run.config.steps == 30
    assert variant.run.config_hash != source.run.config_hash
    assert "variant of" in variant.run.notes


def test_a_sweep_preview_marks_what_already_ran(lab, base_config):
    base = base_config.merged(first_frame="frame.png")
    lab.enqueue(base.merged(cache="easy"))
    spec = SweepSpec(base=base, axes=(SweepAxis(field="cache", values=("easy", "spectrum")),))
    report = lab.preview_sweep(spec)
    assert report.count == 2
    assert report.duplicate_count == 1
    assert report.new_count == 1


def test_running_a_sweep_skips_the_duplicates(lab, base_config):
    base = base_config.merged(first_frame="frame.png")
    lab.enqueue(base.merged(cache="easy"))
    spec = SweepSpec(base=base, axes=(SweepAxis(field="cache", values=("easy", "spectrum")),))
    created = lab.run_sweep(spec)
    assert len(created) == 1
    assert created[0].run.config.cache == "spectrum"


def test_a_sweep_can_deliberately_repeat_a_duplicate(lab, base_config):
    base = base_config.merged(first_frame="frame.png")
    lab.enqueue(base.merged(cache="easy"))
    spec = SweepSpec(base=base, axes=(SweepAxis(field="cache", values=("easy",)),))
    assert len(lab.run_sweep(spec, skip_duplicates=False)) == 1


def test_rating_flows_through_to_the_view(lab, base_config):
    view = lab.enqueue(base_config.merged(first_frame="frame.png"))[0]
    rated = lab.rate(view.run.id, 8, {"motion": 4, "adherence": 5})
    assert rated.stars == 8
    assert rated.criteria == {"motion": 4, "adherence": 5}
    assert lab.unrate(view.run.id).stars is None


def test_voting_updates_the_elo_table(lab, base_config):
    first = lab.enqueue(base_config.merged(first_frame="frame.png", seed=1))[0]
    second = lab.enqueue(base_config.merged(first_frame="frame.png", seed=2))[0]
    lab.vote(first.run.id, second.run.id, first.run.id)
    table = lab.elo_table()
    assert table[first.run.id].rating > table[second.run.id].rating
    assert lab.get_run(first.run.id).elo_games == 1


def test_a_duplicate_run_points_at_the_original(lab, base_config):
    config = base_config.merged(first_frame="frame.png")
    first = lab.enqueue(config)[0]
    second = lab.enqueue(config)[0]
    assert lab.get_run(first.run.id).duplicate_of is None
    assert lab.get_run(second.run.id).duplicate_of == first.run.id


def test_the_baseline_pin_round_trips(lab, base_config):
    view = lab.enqueue(base_config.merged(first_frame="frame.png"))[0]
    lab.set_baseline(view.run.id)
    assert lab.get_run(view.run.id).is_baseline is True
    lab.set_baseline(None)
    assert lab.get_run(view.run.id).is_baseline is False


def test_comparing_runs_separates_differences_from_shared_settings(lab, base_config):
    base = base_config.merged(first_frame="frame.png")
    first = lab.enqueue(base.merged(cache="easy"))[0]
    second = lab.enqueue(base.merged(cache="h3"))[0]
    report = lab.compare([first.run.id, second.run.id])
    fields = {item.field for item in report.differences}
    assert "cache" in fields
    assert "Sampler" in report.shared
    assert "Cache" not in report.shared
    assert len(report.runs) == 2


def test_deleting_a_run_removes_its_files(lab, base_config, settings):
    view = lab.enqueue(base_config.merged(first_frame="frame.png"))[0]
    video = lab.settings.videos_dir / f"{view.run.id}.mp4"
    poster = lab.settings.posters_dir / f"{view.run.id}.jpg"
    video.write_bytes(b"x")
    poster.write_bytes(b"y")
    lab.runs.attach_artifact(
        view.run.id, Artifact(video_path=video.name, poster_path=poster.name)
    )
    assert lab.delete_run(view.run.id) is True
    assert not video.exists()
    assert not poster.exists()
    assert lab.runs.get(view.run.id) is None


def test_deleting_an_unknown_run_reports_false(lab):
    assert lab.delete_run("NOPE") is False


def test_a_preset_can_be_saved_from_a_run(lab, base_config):
    view = lab.enqueue(base_config.merged(first_frame="frame.png"))[0]
    preset = lab.save_preset("keeper", run_id=view.run.id)
    assert preset.config == view.run.config
    assert preset.source_run_id == view.run.id


def test_status_summarises_the_lab(lab, base_config):
    lab.enqueue(base_config.merged(first_frame="frame.png"))
    status = lab.status()
    assert status.counts["queued"] == 1
    assert status.total_runs == 1
    assert status.paused is False
    assert "motion" in status.criteria


def _finish(lab, view, *, sec_per_it: float, stars: int | None = None):
    from h3lab.domain.run import RunMetrics

    lab.runs.update_metrics(view.run.id, RunMetrics(wall_s=sec_per_it * 20, sec_per_it=sec_per_it))
    lab.runs.attach_artifact(view.run.id, Artifact(video_path=f"{view.run.id}.mp4"))
    lab.runs.mark_succeeded(view.run.id)
    if stars is not None:
        lab.rate(view.run.id, stars)
    return lab.get_run(view.run.id)


def test_the_leaderboard_ranks_by_the_blended_score(lab, base_config):
    base = base_config.merged(first_frame="frame.png")
    good_slow = _finish(lab, lab.enqueue(base.merged(seed=1))[0], sec_per_it=20.0, stars=10)
    poor_fast = _finish(lab, lab.enqueue(base.merged(seed=2))[0], sec_per_it=4.0, stars=2)
    board = lab.leaderboard()
    assert [entry.view.run.id for entry in board.entries] == [good_slow.run.id, poor_fast.run.id]
    assert board.entries[0].rank == 1
    assert board.considered == 2


def test_weighting_speed_higher_changes_the_order(lab, base_config):
    from h3lab.domain.scoring import ScoreWeights

    base = base_config.merged(first_frame="frame.png")
    good_slow = _finish(lab, lab.enqueue(base.merged(seed=1))[0], sec_per_it=20.0, stars=8)
    ok_fast = _finish(lab, lab.enqueue(base.merged(seed=2))[0], sec_per_it=4.0, stars=7)
    quality_first = lab.leaderboard(weights=ScoreWeights(quality=1, speed=0))
    speed_first = lab.leaderboard(weights=ScoreWeights(quality=0, speed=1))
    assert quality_first.entries[0].view.run.id == good_slow.run.id
    assert speed_first.entries[0].view.run.id == ok_fast.run.id


def test_an_unrated_run_is_marked_rather_than_scored_zero(lab, base_config):
    base = base_config.merged(first_frame="frame.png")
    _finish(lab, lab.enqueue(base.merged(seed=1))[0], sec_per_it=8.0, stars=6)
    _finish(lab, lab.enqueue(base.merged(seed=2))[0], sec_per_it=6.0)
    board = lab.leaderboard()
    assert board.unrated == 1
    assert board.entries[-1].unrated is True


def test_recipes_group_replicates_of_one_experiment(lab, base_config):
    base = base_config.merged(first_frame="frame.png")
    _finish(lab, lab.enqueue(base.merged(seed=1))[0], sec_per_it=8.0, stars=6)
    _finish(lab, lab.enqueue(base.merged(seed=2))[0], sec_per_it=9.0, stars=8)
    _finish(lab, lab.enqueue(base.merged(seed=3, cache="easy"))[0], sec_per_it=5.0, stars=4)
    groups = lab.recipes()
    assert len(groups) == 2
    seeded = next(group for group in groups if group.n == 2)
    assert seeded.mean_stars == 7.0
    assert seeded.mean_sec_per_it == 8.5
    assert len(seeded.run_ids) == 2


def test_insights_are_offered_only_for_axes_that_actually_vary(lab, base_config):
    base = base_config.merged(first_frame="frame.png")
    _finish(lab, lab.enqueue(base.merged(cache="easy"))[0], sec_per_it=9.0, stars=5)
    _finish(lab, lab.enqueue(base.merged(cache="h3"))[0], sec_per_it=6.0, stars=7)
    fields = {axis.field for axis in lab.axes()}
    assert "cache" in fields
    assert "sampler" not in fields


def test_an_insight_reports_marginal_cells_and_a_verdict(lab, base_config):
    base = base_config.merged(first_frame="frame.png")
    for seed in (1, 2, 3):
        _finish(lab, lab.enqueue(base.merged(cache="easy", seed=seed))[0], sec_per_it=9.0, stars=4)
        _finish(lab, lab.enqueue(base.merged(cache="h3", seed=seed))[0], sec_per_it=6.0, stars=8)
    insight = lab.insight("cache")
    assert {cell.value for cell in insight.marginal} == {"easy", "h3"}
    assert insight.quality_verdict.kind == "winner"
    assert insight.quality_verdict.value == "h3"
    assert insight.speed_verdict.value == "h3"
    assert "confounded" in insight.marginal_caveat


def test_the_arena_reads_only_runs_a_voter_could_actually_watch(lab, base_config):
    base = base_config.merged(first_frame="frame.png")
    watchable = _finish(lab, lab.enqueue(base.merged(seed=1))[0], sec_per_it=8.0)
    lab.enqueue(base.merged(seed=2))  # still queued, so nothing to play
    unwatchable = lab.enqueue(base.merged(seed=3))[0]
    lab.runs.mark_succeeded(unwatchable.run.id)  # succeeded, but no artifact
    archived = _finish(lab, lab.enqueue(base.merged(seed=4))[0], sec_per_it=8.0)
    lab.patch(archived.run.id, archived=True)

    assert [item.run_id for item in lab.arena_runs()] == [watchable.run.id]


def test_the_arena_offers_the_one_setting_that_differs(lab, base_config):
    base = base_config.merged(first_frame="frame.png")
    first = _finish(lab, lab.enqueue(base.merged(cache="easy"))[0], sec_per_it=8.0)
    second = _finish(lab, lab.enqueue(base.merged(cache="h3"))[0], sec_per_it=6.0)
    offered = lab.arena_matchup()
    assert offered is not None
    assert {offered.a.run.id, offered.b.run.id} == {first.run.id, second.run.id}
    assert offered.matchup.axis == "cache"
    assert offered.a.run.id == offered.matchup.a_run_id


def test_the_arena_refuses_a_pair_that_is_not_like_for_like(lab, base_config):
    base = base_config.merged(first_frame="frame.png")
    _finish(lab, lab.enqueue(base.merged(cache="easy"))[0], sec_per_it=8.0)
    _finish(lab, lab.enqueue(base.merged(cache="h3", mp=1.0))[0], sec_per_it=6.0)
    assert lab.arena_matchup() is None


def test_arena_standings_replay_the_votes_the_lab_recorded(lab, base_config):
    base = base_config.merged(first_frame="frame.png")
    first = _finish(lab, lab.enqueue(base.merged(cache="easy"))[0], sec_per_it=8.0)
    second = _finish(lab, lab.enqueue(base.merged(cache="h3"))[0], sec_per_it=6.0)
    for _ in range(4):
        lab.vote(first.run.id, second.run.id, second.run.id)

    board = lab.arena_standings()
    cache = next(axis for axis in board.axes if axis.axis == "cache")
    assert [row.key for row in cache.standings] == ["h3", "easy"]
    assert cache.verdict.kind == "winner"
    assert cache.verdict.value == "h3"
    assert board.votes_counted == 4


def test_listing_runs_hides_archived_ones_by_default(lab, base_config):
    base = base_config.merged(first_frame="frame.png")
    kept = lab.enqueue(base.merged(seed=1))[0]
    hidden = lab.enqueue(base.merged(seed=2))[0]
    lab.patch(hidden.run.id, archived=True)
    assert [view.run.id for view in lab.list_runs().items] == [kept.run.id]
    assert lab.list_runs(RunFilter(archived=None)).total == 2


def test_patching_a_run_sets_flags_notes_and_tags(lab, base_config):
    view = lab.enqueue(base_config.merged(first_frame="frame.png"))[0]
    patched = lab.patch(
        view.run.id, favourite=True, notes="the good one", label="hero", tags=["night", "Night"]
    )
    assert patched.run.favourite is True
    assert patched.run.notes == "the good one"
    assert patched.run.label == "hero"
    assert patched.run.tags == ("night",)
    assert lab.tags() == ["night"]
