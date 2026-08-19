"""The worker that turns queued runs into finished runs.

One thread owns execution. It claims a run atomically, executes it, and records the result
row by row. The loop is written so that no failure can end it: an unexpected exception marks
that run failed and the worker moves to the next one. A worker that dies silently is how the
previous tool ended up with runs stuck in `running` forever.
"""

from __future__ import annotations

import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from h3lab.comfy.client import ComfyClient, ComfyError, PromptRejected
from h3lab.comfy.editor import run_provenance, to_editor_workflow
from h3lab.comfy.graph import WorkflowError, load_workflow
from h3lab.comfy.progress import Preview, ProgressTracker
from h3lab.comfy.schema import SchemaCache
from h3lab.comfy.studio import StudioContractError, prepare_prompt
from h3lab.domain.config import GenerationConfig
from h3lab.domain.run import Artifact, Run, RunMetrics
from h3lab.engine import artifacts
from h3lab.engine.events import EventBus
from h3lab.settings import Settings
from h3lab.storage.runs import RunNotFound, RunRepository

IDLE_SLEEP_S = 0.4
PREPARE_RETRY_S = 1.0
PROGRESS_MIN_INTERVAL_S = 0.35
STARTUP_REASON = "interrupted: the lab restarted while this run was in flight"

class PreflightError(RuntimeError):
    """The run cannot possibly succeed, and we know before asking ComfyUI."""


# Failures the lab already has a sentence for. Everything else is a bug until proven otherwise.
DIAGNOSED = (
    PreflightError,
    WorkflowError,
    StudioContractError,
    ComfyError,
    RunNotFound,
    FileNotFoundError,
)


class WorkflowCache:
    """Templates, read once per version of the file on disk.

    A template is parsed once and held, because re-reading a 130 kB export for every run of a
    sweep is waste, and re-parsing it *during* one would let an edit change what a finished
    benchmark claims to have run.

    But the file being edited is the normal case here — the templates are worked on in ComfyUI
    and re-exported — and a cache that never looks again means the lab keeps benchmarking a
    graph that no longer exists on disk until somebody remembers to restart it. So the file's
    mtime and size are checked on the way in: unchanged is a cache hit, changed is a reload and
    an announcement, and either way a run holds one graph from start to finish.
    """

    def __init__(self, settings: Settings, *, events: EventBus | None = None) -> None:
        self._settings = settings
        self._events = events
        self._lock = threading.Lock()
        self._loaded: dict[str, dict[str, Any]] = {}
        self._stamps: dict[str, tuple[int, int]] = {}

    @staticmethod
    def _stamp(path: Path) -> tuple[int, int]:
        info = path.stat()
        return (info.st_mtime_ns, info.st_size)

    def get(self, mode: str) -> dict[str, Any]:
        path = self._settings.workflow_path(mode)
        if not path.is_file():
            raise WorkflowError(f"no workflow template for mode {mode!r} at {path}")
        try:
            stamp = self._stamp(path)
        except OSError:
            # A file we cannot stat may still read; treat it as changed rather than refuse.
            stamp = None

        with self._lock:
            cached = self._loaded.get(mode)
            if cached is not None and stamp is not None and self._stamps.get(mode) == stamp:
                return cached
            known = mode in self._loaded

        loaded = load_workflow(path)
        with self._lock:
            self._loaded[mode] = loaded
            if stamp is None:
                self._stamps.pop(mode, None)
            else:
                self._stamps[mode] = stamp
        if known and self._events is not None:
            self._events.publish(
                "lab.message",
                text=f"the {mode} workflow changed on disk and was reloaded",
                mode=mode,
                path=str(path),
            )
        return loaded

    def invalidate(self) -> None:
        with self._lock:
            self._loaded.clear()
            self._stamps.clear()

    @property
    def path(self) -> Path:
        """The template currently used for every mode (unified) or t2v."""
        return self._settings.workflow_path("t2v")


def preflight(
    config: GenerationConfig,
    settings: Settings,
    _client: ComfyClient | None = None,
) -> list[str]:
    """Check only files the consumer must transport into ComfyUI."""
    problems: list[str] = []
    input_dir = settings.comfy_input_dir
    if config.media_files and input_dir.is_dir():
        for name in config.media_files:
            if not (input_dir / name).is_file():
                problems.append(f"{name} is not in ComfyUI's input folder")
    return problems


class Runner:
    """Owns the execution thread and the ComfyUI conversation for the active run."""

    def __init__(
        self,
        *,
        runs: RunRepository,
        settings: Settings,
        events: EventBus,
        client: ComfyClient | None = None,
        workflows: WorkflowCache | None = None,
        clear_cache_between_runs: bool = True,
    ) -> None:
        self._runs = runs
        self._settings = settings
        self._events = events
        self._client = client or ComfyClient(
            settings.comfy_url, run_timeout_s=settings.comfy_timeout_s
        )
        self._workflows = workflows or WorkflowCache(settings)
        self._schemas = SchemaCache(self._client)
        self._clear_cache = clear_cache_between_runs

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._active_run_id: str | None = None
        self._tracker: ProgressTracker | None = None
        self._cancelling: set[str] = set()
        self._last_progress_at = 0.0
        self._last_error: str | None = None

    def schemas(self):
        """The installed node descriptions, or empty when ComfyUI cannot be reached."""
        return self._schemas.get()

    # --- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        recovered = self._runs.reconcile(reason=STARTUP_REASON)
        if recovered:
            self._events.publish("lab.message", text=f"recovered {recovered} interrupted run(s)")
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="h3lab-runner", daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def nudge(self) -> None:
        """Tell the worker a run was just queued so it does not wait out its idle sleep."""
        self._wake.set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    @property
    def active_run_id(self) -> str | None:
        with self._lock:
            return self._active_run_id

    def preview(self, run_id: str) -> Preview | None:
        """The newest frame ComfyUI has drawn for the run in flight.

        Only ever the active run, and only in memory: a preview is a progress indicator, not a
        result. What a finished run is worth keeping is its video, and that is already saved.
        """
        with self._lock:
            if run_id != self._active_run_id:
                return None
            tracker = self._tracker
        return tracker.preview() if tracker is not None else None

    def pause(self) -> None:
        self._paused.set()
        self._events.publish("queue.changed", paused=True)

    def resume(self) -> None:
        self._paused.clear()
        self._wake.set()
        self._events.publish("queue.changed", paused=False)

    def status(self) -> dict[str, Any]:
        return {
            "worker_alive": self.running,
            "paused": self.paused,
            "active_run_id": self.active_run_id,
            "queued": len(self._runs.queued_ids()),
            "comfy_url": self._settings.comfy_url,
            "last_error": self._last_error,
        }

    # --- cancellation ------------------------------------------------------

    def cancel(self, run_id: str) -> bool:
        """Stop a run. Queued runs are cancelled outright; the active one is interrupted."""
        with self._lock:
            active = self._active_run_id
            if active == run_id:
                self._cancelling.add(run_id)
        if active == run_id:
            self._client.cancel_all()
            return True
        try:
            run = self._runs.require(run_id)
        except RunNotFound:
            return False
        if run.status != "queued":
            return False
        self._runs.mark_cancelled(run_id, reason="cancelled before it started")
        self._events.publish("run.updated", run_id=run_id, status="cancelled")
        self._events.publish("queue.changed")
        return True

    def cancel_all(self) -> int:
        count = self._runs.cancel_queued()
        active = self.active_run_id
        if active:
            self.cancel(active)
            count += 1
        self._events.publish("queue.changed")
        return count

    def _cancel_requested(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._cancelling

    # --- the loop ----------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._paused.is_set():
                self._wake.wait(timeout=IDLE_SLEEP_S)
                self._wake.clear()
                continue
            run = self._claim()
            if run is None:
                self._wake.wait(timeout=IDLE_SLEEP_S)
                self._wake.clear()
                continue
            try:
                self._execute(run)
            except DIAGNOSED as exc:
                # These already say what is wrong and what to do about it. Wrapping them in
                # "unexpected error" would send the reader hunting for a bug in the lab
                # instead of reading the sentence that names the file or the node.
                self._fail(run.id, str(exc) or type(exc).__name__)
            except BaseException as exc:  # noqa: BLE001 - the loop must outlive any failure
                self._fail(run.id, f"the lab hit an unexpected error: {exc}")
                self._last_error = traceback.format_exc(limit=6)
            finally:
                with self._lock:
                    self._active_run_id = None
                    self._tracker = None
                    self._cancelling.discard(run.id)

    def _claim(self) -> Run | None:
        if self._paused.is_set() or self._stop.is_set():
            return None
        try:
            run = self._runs.claim_next()
        except Exception as exc:  # noqa: BLE001 - a storage hiccup must not kill the worker
            self._last_error = f"could not claim a run: {exc}"
            return None
        if run is None:
            return None
        # A pause or stop that landed while the claim was in flight must still be honoured,
        # so hand the run straight back rather than starting work nobody asked for.
        if self._paused.is_set() or self._stop.is_set():
            self._runs.requeue(run.id)
            return None
        with self._lock:
            self._active_run_id = run.id
            self._last_progress_at = 0.0
        self._events.publish(
            "run.started", run_id=run.id, label=run.label, seq=run.seq, status="running"
        )
        self._events.publish("queue.changed")
        return run

    # --- one run -----------------------------------------------------------

    def _execute(self, run: Run) -> None:
        config = run.config
        problems = preflight(config, self._settings, self._client)
        if problems:
            raise PreflightError("; ".join(problems))

        workflow = self._workflows.get(config.mode)
        try:
            prepared = prepare_prompt(
                self._client,
                workflow,
                config,
                schemas=self._schemas.get(),
            )
        except StudioContractError:
            raise
        except ComfyError as exc:
            self._runs.requeue(run.id)
            self._last_error = str(exc)
            self._events.publish("run.updated", run_id=run.id, status="queued")
            self._events.publish("queue.changed")
            self._stop.wait(PREPARE_RETRY_S)
            return
        prompt = prepared.prompt
        editor = to_editor_workflow(workflow, prompt, provenance=run_provenance(run))

        if self._clear_cache:
            # Without this, ComfyUI can replay the previous identical graph's outputs in
            # about no time, and the recorded duration would describe a cache hit.
            self._client.clear_execution_cache()

        if self._cancel_requested(run.id):
            self._runs.mark_cancelled(run.id, reason="cancelled before it was submitted")
            self._events.publish("run.finished", run_id=run.id, status="cancelled")
            return

        tracker = ProgressTracker.of(prompt)
        with self._lock:
            self._tracker = tracker

        try:
            outcome = self._client.execute(
                prompt,
                on_live=self._progress_for(run.id),
                workflow=editor,
                tracker=tracker,
            )
        except PromptRejected as exc:
            # A rejection is what an install that changed under us looks like: a node pack
            # updated, a widget renamed. Drop the cached schemas so the next run asks again.
            self._schemas.invalidate()
            self._fail(run.id, f"ComfyUI rejected the graph — {exc}")
            return
        except ComfyError as exc:
            if self._cancel_requested(run.id):
                self._runs.mark_cancelled(run.id, reason="cancelled while running")
                self._events.publish("run.finished", run_id=run.id, status="cancelled")
                return
            self._fail(run.id, str(exc))
            return

        self._runs.set_prompt_id(run.id, outcome.prompt_id)
        self._runs.update_metrics(
            run.id,
            RunMetrics(
                wall_s=round(outcome.wall_s, 3),
                sec_per_it=outcome.sec_per_it,
                steps=outcome.steps or run.config.effective_steps,
                sampler_cached=None,
                cache_cleared=self._clear_cache,
            ),
        )

        artifact = self._collect_output(run.id, outcome.history)
        if artifact is None:
            self._fail(run.id, "ComfyUI completed without a video output")
            return
        self._runs.attach_artifact(run.id, artifact)

        finished = self._runs.mark_succeeded(run.id)
        self._events.publish(
            "run.finished",
            run_id=run.id,
            status="succeeded",
            sec_per_it=finished.metrics.sec_per_it,
            wall_s=finished.metrics.wall_s,
            video_path=finished.artifact.video_path,
            poster_path=finished.artifact.poster_path,
        )
        self._events.publish("queue.changed")

    def _collect_output(self, run_id: str, history: dict[str, Any]) -> Artifact | None:
        located = ComfyClient.find_video(history)
        if located is None:
            return None
        filename, subfolder, folder_type = located
        suffix = Path(filename).suffix or ".mp4"
        destination = self._settings.videos_dir / f"{run_id}{suffix}"
        try:
            self._client.download(filename, subfolder, folder_type, destination)
        except ComfyError:
            # The run itself succeeded; losing the copy is worth reporting, not failing.
            self._events.publish(
                "lab.message", run_id=run_id, text=f"could not download {filename}"
            )
            return None
        try:
            return artifacts.build(run_id, destination, self._settings)
        except Exception:  # noqa: BLE001 - a preview is never worth failing a result over
            return Artifact(video_path=destination.name)

    def _progress_for(self, run_id: str) -> Callable[[dict[str, Any]], None]:
        def publish(snapshot: dict[str, Any]) -> None:
            now = time.monotonic()
            # Progress arrives per step; a browser does not need every one of them.
            if now - self._last_progress_at < PROGRESS_MIN_INTERVAL_S:
                return
            self._last_progress_at = now
            self._events.publish("run.progress", run_id=run_id, **snapshot)

        return publish

    def _fail(self, run_id: str, message: str) -> None:
        try:
            self._runs.mark_failed(run_id, message[:4000])
        except RunNotFound:
            return
        self._last_error = message
        self._events.publish("run.finished", run_id=run_id, status="failed", error=message)
        self._events.publish("queue.changed")
