"""Durable local projection of jobs owned by the shared SDUI service."""

from __future__ import annotations

import hashlib
import os
import threading
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from time import monotonic
from typing import Any

from h3lab.comfy.progress import Preview
from h3lab.domain.run import TERMINAL_STATUSES, Artifact, Run, RunMetrics
from h3lab.engine import artifacts
from h3lab.engine.events import EventBus
from h3lab.settings import Settings
from h3lab.shared.client import (
    SharedProtocolError,
    SharedServiceClient,
    SharedServiceError,
    SharedServiceUnavailable,
    SharedSubmissionUncertain,
)
from h3lab.shared.contracts import (
    GenerationDocument,
    JobSubmission,
    PublicJob,
    PublicJobEvent,
)
from h3lab.shared.projection import materialize_submission, project_h3_submission
from h3lab.storage.runs import RunRepository


class SharedRequestConflict(ValueError):
    """One browser idempotency key was reused for different work."""


class SharedEventGap(RuntimeError):
    """The observer must reconnect from its durable cursor before proceeding."""


@dataclass(slots=True)
class _LiveState:
    queue_remaining: int | None = None
    node_id: str | None = None
    preview_url: str | None = None
    preview_sequence: int | None = None


@dataclass(slots=True)
class _ProgressSample:
    at: datetime
    value: float
    node_id: str | None
    elapsed: float = 0.0
    iterations: float = 0.0


def _run_id(request_key: str, index: int) -> str:
    if (
        not request_key
        or len(request_key) > 200
        or any(ord(char) < 32 for char in request_key)
    ):
        raise ValueError("idempotency key must be 1-200 characters without controls")
    keyed = request_key if index == 0 else f"{request_key}:{index}"
    return hashlib.sha256(f"h3lab-shared-v1:{keyed}".encode()).hexdigest()[:26]


class SharedRunner:
    """Submits once, then reconciles local benchmark rows from shared jobs."""

    def __init__(
        self,
        *,
        runs: RunRepository,
        events: EventBus,
        client: SharedServiceClient,
        settings: Settings,
        max_observers: int = 4,
        reconcile_interval_s: float = 1.0,
    ) -> None:
        if max_observers < 1:
            raise ValueError("max_observers must be positive")
        self._runs = runs
        self._events = events
        self._client = client
        self._settings = settings
        self._lock = threading.RLock()
        self._observer_lock = threading.Lock()
        self._max_observers = max_observers
        self._reconcile_interval_s = reconcile_interval_s
        self._stop = threading.Event()
        self._supervisor: threading.Thread | None = None
        self._observers: dict[str, threading.Thread] = {}
        self._live: dict[str, _LiveState] = {}
        self._progress: dict[str, _ProgressSample] = {}
        self._artifact_locks: dict[str, threading.Lock] = {}
        self._running = False
        self._paused = False
        self._last_error: str | None = None

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._running = True
        self.reconcile()
        self._schedule_observers()
        self._supervisor = threading.Thread(
            target=self._supervise,
            name="h3lab-shared-supervisor",
            daemon=True,
        )
        self._supervisor.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        self._running = False
        deadline = monotonic() + max(0.0, timeout)
        supervisor = self._supervisor
        if supervisor is not None:
            supervisor.join(timeout=max(0.0, deadline - monotonic()))
        self._supervisor = None
        with self._observer_lock:
            observers = list(self._observers.values())
        for observer in observers:
            observer.join(timeout=max(0.0, deadline - monotonic()))

    def nudge(self) -> None:
        if self.running:
            self._schedule_observers()

    @property
    def running(self) -> bool:
        return self._running and not self._stop.is_set()

    @property
    def observer_count(self) -> int:
        with self._observer_lock:
            return len(self._observers)

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def active_run_id(self) -> str | None:
        active = next(
            (
                run.id
                for run in self._runs.all()
                if run.shared_submission is not None and run.status == "running"
            ),
            None,
        )
        return active

    def preview(self, run_id: str) -> Preview | None:
        with self._lock:
            state = self._live.get(run_id)
            if (
                state is None
                or state.preview_url is None
                or state.preview_sequence is None
            ):
                return None
            url = state.preview_url
            sequence = state.preview_sequence
        content = self._client.read_content(url, maximum_bytes=16 * 1024 * 1024)
        content_type = content.headers.get("content-type", "")
        if content.status_code != 200 or not content_type.startswith(
            ("image/", "video/")
        ):
            return None
        return Preview(data=content.body, content_type=content_type, seq=sequence)

    def pause(self) -> None:
        self._paused = True
        self._events.publish("queue.changed", paused=True)

    def resume(self) -> None:
        self._paused = False
        self._events.publish("queue.changed", paused=False)
        self.reconcile()

    def status(self) -> dict[str, Any]:
        queued = sum(
            1
            for run in self._runs.all()
            if run.shared_submission is not None and run.status == "queued"
        )
        return {
            "worker_alive": self.running,
            "paused": self.paused,
            "active_run_id": self.active_run_id,
            "queued": queued,
            # Never disclose the separately deployed shared-service origin to browsers.
            "comfy_url": "",
            "last_error": self._last_error,
        }

    def enqueue(
        self,
        document: GenerationDocument,
        requested: JobSubmission,
        *,
        request_key: str,
        count: int = 1,
    ) -> list[Run]:
        if count < 1 or count > 64:
            raise ValueError("count must be between 1 and 64")
        made: list[Run] = []
        with self._lock:
            for index in range(count):
                run_id = _run_id(request_key, index)
                existing = self._runs.get(run_id)
                candidate = requested
                if (
                    existing is not None
                    and existing.shared_submission is not None
                    and requested.input.get("seed") is None
                ):
                    candidate = requested.model_copy(
                        update={
                            "input": {
                                **requested.input,
                                "seed": existing.shared_submission.input.get("seed"),
                            }
                        }
                    )
                exact = materialize_submission(document, candidate)
                config = project_h3_submission(exact)

                if existing is not None:
                    if existing.shared_submission != exact:
                        raise SharedRequestConflict(
                            "idempotency key was already used for a different submission"
                        )
                    made.append(existing)
                    continue

                run = self._runs.create(
                    config,
                    run_id=run_id,
                    shared_submission=exact,
                )
                self._events.publish(
                    "run.created",
                    run_id=run.id,
                    label=run.label,
                    run_seq=run.seq,
                    status=run.status,
                )
                try:
                    run = self._submit(run)
                except SharedServiceError:
                    # A typed HTTP response proves no ambiguous successful create needs
                    # recovering. Do not leave a benchmark row for work that never existed.
                    self._runs.delete(run.id)
                    self._events.publish("run.deleted", run_id=run.id)
                    raise
                made.append(run)
        self._events.publish("queue.changed")
        self.nudge()
        return made

    def reconcile(self) -> int:
        if self._paused:
            return 0
        recovered = 0
        with self._lock:
            for run in self._runs.all():
                if run.shared_submission is None or run.status in TERMINAL_STATUSES:
                    continue
                try:
                    if run.shared_job_id is None:
                        self._submit(run)
                    else:
                        self._apply_job(run, self._client.get_job(run.shared_job_id))
                    recovered += 1
                except SharedSubmissionUncertain as exc:
                    self._last_error = str(exc)
                    self._runs.set_shared_failure(run.id, "submission_uncertain")
                except Exception as exc:  # noqa: BLE001 - one bad job cannot block recovery
                    self._last_error = str(exc)
        return recovered

    def _supervise(self) -> None:
        while not self._stop.wait(self._reconcile_interval_s):
            try:
                self.reconcile()
                self._schedule_observers()
            except Exception as exc:  # noqa: BLE001 - recovery must survive one bad cycle
                self._last_error = str(exc)

    def _schedule_observers(self) -> None:
        if not self.running:
            return
        candidates = [
            run
            for run in self._runs.all()
            if run.shared_job_id is not None
            and run.shared_submission is not None
            and run.status not in TERMINAL_STATUSES
        ]
        with self._observer_lock:
            self._observers = {
                run_id: thread
                for run_id, thread in self._observers.items()
                if thread.is_alive()
            }
            slots = self._max_observers - len(self._observers)
            for run in candidates:
                if slots <= 0:
                    break
                if run.id in self._observers:
                    continue
                observer = threading.Thread(
                    target=self._observe_forever,
                    args=(run.id,),
                    name=f"h3lab-shared-{run.id[:8]}",
                    daemon=True,
                )
                self._observers[run.id] = observer
                observer.start()
                slots -= 1

    def _observe_forever(self, run_id: str) -> None:
        try:
            while not self._stop.is_set():
                run = self._runs.get(run_id)
                if (
                    run is None
                    or run.shared_job_id is None
                    or run.status in TERMINAL_STATUSES
                ):
                    return
                try:
                    self.observe_once(run_id)
                except SharedEventGap as exc:
                    self._last_error = str(exc)
                    self._events.publish(
                        "lab.message",
                        run_id=run_id,
                        text=str(exc),
                        retryable=True,
                    )
                except (SharedServiceUnavailable, SharedProtocolError) as exc:
                    self._last_error = str(exc)
                    self._events.publish(
                        "lab.message",
                        run_id=run_id,
                        text="shared job observation disconnected; reconnecting",
                        retryable=True,
                    )
                if self._stop.wait(min(0.5, self._reconcile_interval_s)):
                    return
        finally:
            with self._observer_lock:
                current = self._observers.get(run_id)
                if current is threading.current_thread():
                    self._observers.pop(run_id, None)

    def observe_once(self, run_id: str) -> int:
        run = self._runs.require(run_id)
        if run.shared_job_id is None:
            raise ValueError("shared run has no linked job")
        processed = 0
        for event in self._client.iter_events(
            run.shared_job_id,
            after_sequence=run.shared_event_cursor,
        ):
            if self._stop.is_set():
                break
            current = self._runs.require(run_id)
            cursor = current.shared_event_cursor or 0
            if event.job_id != current.shared_job_id:
                raise SharedProtocolError("shared event belongs to a different job")
            if event.sequence <= cursor:
                continue
            if event.sequence != cursor + 1:
                raise SharedEventGap(
                    f"shared event sequence jumped from {cursor} to {event.sequence}; replaying"
                )
            self._apply_event(current, event)
            self._runs.set_shared_event_cursor(run_id, event.sequence)
            processed += 1
            if self._runs.require(run_id).status in TERMINAL_STATUSES:
                break
        latest = self._runs.require(run_id)
        if latest.status not in TERMINAL_STATUSES and latest.shared_job_id is not None:
            self._apply_job(latest, self._client.get_job(latest.shared_job_id))
        return processed

    def _apply_event(self, run: Run, event: PublicJobEvent) -> None:
        kind = event.type
        at = event.at.isoformat()
        if kind in {"accepted", "queued"}:
            self._runs.sync_shared_status(run.id, "queued")
        elif kind in {"running", "started"}:
            was_queued = run.status == "queued"
            self._runs.sync_shared_status(run.id, "running", observed_at=at)
            if was_queued:
                self._events.publish("run.started", run_id=run.id, status="running")
        elif kind in {"cancelling", "collecting"}:
            self._runs.sync_shared_status(run.id, "running", observed_at=at)
            self._events.publish("run.updated", run_id=run.id, status=kind)
        elif kind in {
            "succeeded",
            "failed",
            "cancelled",
            "interrupted",
            "collection_failed",
        }:
            if run.shared_job_id is not None:
                self._apply_job(
                    run,
                    self._client.get_job(run.shared_job_id),
                    observed_at=at,
                )
        elif kind == "status":
            remaining = _integer(event.data.get("queueRemaining"), minimum=0)
            with self._lock:
                self._live.setdefault(run.id, _LiveState()).queue_remaining = remaining
            self._events.publish(
                "run.progress",
                run_id=run.id,
                stage="preparing",
                queue_remaining=remaining,
            )
        elif kind == "executing":
            node_id = _optional_string(event.data.get("nodeId"))
            with self._lock:
                self._live.setdefault(run.id, _LiveState()).node_id = node_id
            self._events.publish(
                "run.progress",
                run_id=run.id,
                stage="sampling",
                node=node_id,
            )
        elif kind == "progress":
            self._apply_progress(run, event)
        elif kind == "log":
            message = event.data.get("message")
            level = event.data.get("level")
            if isinstance(message, str) and message:
                self._events.publish(
                    "run.log",
                    run_id=run.id,
                    level=level if isinstance(level, str) else "info",
                    message=message[:8_000],
                    at=at,
                )
        elif kind == "preview":
            sequence = _integer(event.data.get("sequence"), minimum=1)
            url = event.data.get("url")
            expected = (
                None
                if run.shared_job_id is None
                else f"/v1/jobs/{run.shared_job_id}/preview"
            )
            if sequence is not None and url == expected:
                with self._lock:
                    state = self._live.setdefault(run.id, _LiveState())
                    state.preview_sequence = sequence
                    state.preview_url = expected
                self._events.publish(
                    "run.preview",
                    run_id=run.id,
                    sequence=sequence,
                    available=True,
                )

    def _apply_progress(self, run: Run, event: PublicJobEvent) -> None:
        value = _number(event.data.get("value"))
        maximum = _number(event.data.get("maximum"))
        node_id = _optional_string(event.data.get("nodeId"))
        if value is None or maximum is None or maximum <= 0:
            return
        value = min(maximum, max(0.0, value))
        self._events.publish(
            "run.progress",
            run_id=run.id,
            stage="sampling",
            node=node_id,
            step=value,
            step_total=maximum,
            fraction=value / maximum,
        )

        expected_steps = run.config.effective_steps
        if maximum != expected_steps:
            return
        with self._lock:
            previous = self._progress.get(run.id)
            sample = _ProgressSample(at=event.at, value=value, node_id=node_id)
            if (
                previous is not None
                and previous.node_id == node_id
                and value > previous.value
                and event.at > previous.at
            ):
                sample.elapsed = (
                    previous.elapsed + (event.at - previous.at).total_seconds()
                )
                sample.iterations = previous.iterations + (value - previous.value)
            elif previous is not None and previous.node_id == node_id:
                sample.elapsed = previous.elapsed
                sample.iterations = previous.iterations
            self._progress[run.id] = sample
        seconds_per_iteration = (
            sample.elapsed / sample.iterations if sample.iterations > 0 else None
        )
        self._runs.update_metrics(
            run.id,
            RunMetrics(
                wall_s=run.metrics.wall_s,
                sec_per_it=seconds_per_iteration or run.metrics.sec_per_it,
                steps=expected_steps,
                sampler_cached=None,
                cache_cleared=None,
            ),
        )

    def _submit(self, run: Run) -> Run:
        if run.shared_submission is None:
            raise ValueError("shared runner received a legacy run")
        try:
            created = self._client.create_job(
                run.shared_submission,
                idempotency_key=run.id,
            )
        except SharedSubmissionUncertain:
            self._runs.set_shared_failure(run.id, "submission_uncertain")
            raise
        linked = self._runs.set_shared_job(
            run.id,
            created.job.id,
            created.job.provenance,
        )
        return self._apply_job(linked, created.job)

    def _apply_job(
        self,
        run: Run,
        job: PublicJob,
        *,
        observed_at: str | None = None,
    ) -> Run:
        if job.provenance is not None and run.shared_provenance != job.provenance:
            run = self._runs.set_shared_job(run.id, job.id, job.provenance)
        observed_at = observed_at or job.updated_at.isoformat()
        if job.state in {"accepted", "queued"}:
            return self._runs.sync_shared_status(run.id, "queued")
        if job.state in {"running", "cancelling", "collecting"}:
            updated = self._runs.sync_shared_status(
                run.id,
                "running",
                observed_at=observed_at,
            )
            self._events.publish("run.updated", run_id=run.id, status="running")
            return updated
        if job.state == "succeeded":
            return self._finish_succeeded(run, job, observed_at=observed_at)

        error = job.failure.detail if job.failure is not None else None
        status = job.state
        updated = self._runs.sync_shared_status(
            run.id,
            status,
            error=error,
            observed_at=observed_at,
        )
        wall_s = _wall_seconds(updated.started_at, updated.finished_at)
        if wall_s is not None:
            updated = self._runs.update_metrics(
                run.id,
                updated.metrics.model_copy(update={"wall_s": wall_s}),
            )
        with self._lock:
            self._live.pop(run.id, None)
            self._progress.pop(run.id, None)
        self._events.publish("run.finished", run_id=run.id, status=status, error=error)
        self._events.publish("queue.changed")
        return updated

    def _finish_succeeded(
        self,
        run: Run,
        job: PublicJob,
        *,
        observed_at: str,
    ) -> Run:
        with self._lock:
            artifact_lock = self._artifact_locks.setdefault(run.id, threading.Lock())
        with artifact_lock:
            return self._finish_succeeded_locked(
                run,
                job,
                observed_at=observed_at,
            )

    def _finish_succeeded_locked(
        self,
        run: Run,
        job: PublicJob,
        *,
        observed_at: str,
    ) -> Run:
        current = self._runs.require(run.id)
        existing = (
            self._settings.videos_dir / current.artifact.video_path
            if current.artifact.video_path
            else None
        )
        if existing is not None and existing.is_file():
            updated = self._runs.sync_shared_status(
                run.id,
                "succeeded",
                observed_at=observed_at,
            )
            return self._finish_metrics_and_publish(updated, "succeeded", None)

        self._runs.sync_shared_status(
            run.id,
            "running",
            observed_at=observed_at,
        )
        self._events.publish("run.updated", run_id=run.id, status="collecting")
        try:
            artifact = self._import_artifact(run.id, job)
            self._runs.attach_artifact(run.id, artifact)
            self._runs.set_shared_failure(run.id, None)
            updated = self._runs.sync_shared_status(
                run.id,
                "succeeded",
                observed_at=observed_at,
            )
            return self._finish_metrics_and_publish(updated, "succeeded", None)
        except Exception as exc:  # noqa: BLE001 - collection failure remains retryable
            message = f"shared video could not be imported: {exc}"
            self._runs.set_shared_failure(run.id, "local_artifact_import_failed")
            updated = self._runs.sync_shared_status(
                run.id,
                "collection_failed",
                error=message[:4_000],
                observed_at=observed_at,
            )
            return self._finish_metrics_and_publish(
                updated,
                "collection_failed",
                message,
            )

    def _finish_metrics_and_publish(
        self,
        run: Run,
        status: str,
        error: str | None,
    ) -> Run:
        wall_s = _wall_seconds(run.started_at, run.finished_at)
        if wall_s is not None:
            run = self._runs.update_metrics(
                run.id,
                run.metrics.model_copy(update={"wall_s": wall_s}),
            )
        with self._lock:
            self._live.pop(run.id, None)
            self._progress.pop(run.id, None)
        self._events.publish("run.finished", run_id=run.id, status=status, error=error)
        self._events.publish("queue.changed")
        return run

    def _import_artifact(self, run_id: str, job: PublicJob) -> Artifact:
        artifact = job.artifact
        if artifact is None:
            raise ValueError("succeeded shared job has no managed video")
        suffixes = {
            "video/mp4": {".mp4", ".m4v"},
            "video/webm": {".webm"},
            "video/quicktime": {".mov"},
            "video/x-matroska": {".mkv"},
        }
        suffix = os.path.splitext(artifact.filename)[1].lower()
        if artifact.mime not in suffixes or suffix not in suffixes[artifact.mime]:
            raise ValueError("managed video MIME and filename are not supported")

        destination = self._settings.videos_dir / f"{run_id}{suffix}"
        for stale in self._settings.videos_dir.glob(f".{run_id}.*.part"):
            with suppress(OSError):
                stale.unlink()
        temporary = self._settings.videos_dir / (
            f".{run_id}.{threading.get_ident()}.part"
        )
        self._settings.videos_dir.mkdir(parents=True, exist_ok=True)
        stream = self._client.open_content(
            artifact.content_url,
            maximum_bytes=artifact.size,
        )
        try:
            if stream.status_code != 200:
                raise ValueError(f"managed video returned HTTP {stream.status_code}")
            mime = (
                stream.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            )
            if mime != artifact.mime:
                raise ValueError("managed video Content-Type does not match metadata")
            length = stream.headers.get("content-length")
            if length is not None and int(length) != artifact.size:
                raise ValueError("managed video Content-Length does not match metadata")
            etag = stream.headers.get("etag", "")
            expected_digest = (
                etag[1:-1] if len(etag) >= 2 and etag[:1] == etag[-1:] == '"' else ""
            )
            if not expected_digest.startswith("sha256:"):
                raise ValueError("managed video has no strong SHA-256 ETag")

            digest = hashlib.sha256()
            size = 0
            with temporary.open("xb") as target:
                for chunk in stream.iter_bytes():
                    size += len(chunk)
                    if size > artifact.size:
                        raise ValueError("managed video exceeds its declared size")
                    digest.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            actual_digest = f"sha256:{digest.hexdigest()}"
            if size != artifact.size:
                raise ValueError("managed video size does not match metadata")
            if actual_digest != expected_digest:
                raise ValueError("managed video digest does not match its ETag")

            built = artifacts.build(run_id, temporary, self._settings)
            os.replace(temporary, destination)
            return built.model_copy(update={"video_path": destination.name})
        finally:
            stream.close()
            with suppress(OSError):
                temporary.unlink()

    def cancel(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if (
            run is None
            or run.shared_submission is None
            or run.status in TERMINAL_STATUSES
            or run.shared_job_id is None
        ):
            return False
        updated = self._client.cancel_job(run.shared_job_id)
        self._apply_job(run, updated)
        return True

    def retry_collection(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if (
            run is None
            or run.shared_submission is None
            or run.status != "collection_failed"
            or run.shared_job_id is None
        ):
            return False
        if run.shared_failure_kind == "local_artifact_import_failed":
            updated = self._client.get_job(run.shared_job_id)
            if updated.state != "succeeded":
                return False
        else:
            updated = self._client.retry_collection(run.shared_job_id)
        self._apply_job(run, updated)
        self.nudge()
        return True

    def cancel_all(self) -> int:
        count = 0
        for run in self._runs.all():
            if self.cancel(run.id):
                count += 1
        return count


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _integer(value: object, *, minimum: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        return None
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) and len(value) <= 256 else None


def _wall_seconds(started_at: str | None, finished_at: str | None) -> float | None:
    if started_at is None or finished_at is None:
        return None
    try:
        elapsed = datetime.fromisoformat(finished_at) - datetime.fromisoformat(
            started_at
        )
    except ValueError:
        return None
    seconds = elapsed.total_seconds()
    return round(seconds, 3) if seconds >= 0 else None


__all__ = ["SharedEventGap", "SharedRequestConflict", "SharedRunner"]
