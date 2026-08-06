"""Orchestrate benchmark phases: warmup + timed cells, progressive store updates."""

from __future__ import annotations

import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from bench import store
from bench.comfy import ComfyClient, ComfyError
from bench.constants import NODE_SAMPLER_ADV, WORKFLOW_PATH
from bench.matrix import build_quality_runs, build_scale_runs, build_speed_runs, pick_fastest
from bench.models import Run, Suite, empty_suite
from bench.workflow import apply_config, load_ui_workflow


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Timed runs faster than this almost certainly hit a full execution-cache (warmup reuse).
_SUSPICIOUSLY_FAST_S = 2.0


class BenchmarkRunner:
    def __init__(
        self,
        comfy: ComfyClient,
        workflow_path: Path = WORKFLOW_PATH,
        resume: bool = False,
        retry_failed: bool = False,
        on_update: Callable[[Suite], None] | None = None,
    ):
        self.comfy = comfy
        self.workflow_path = workflow_path
        self.resume = resume
        self.retry_failed = retry_failed
        self.on_update = on_update
        self.ui = load_ui_workflow(workflow_path)
        self._abort = False

    def request_abort(self) -> None:
        """Signal cooperative abort and cancel active ComfyUI work."""
        self._abort = True
        try:
            self.comfy.cancel_all()
        except Exception:
            pass

    def _emit(self, suite: Suite) -> None:
        store.save_suite(suite)
        if self.on_update:
            self.on_update(suite)

    def _check_abort(self) -> None:
        if self._abort:
            raise KeyboardInterrupt("benchmark aborted")

    def init_suite(self, existing: Suite | None = None) -> Suite:
        if existing and self.resume:
            suite = existing
            suite.status = "running"
            if not suite.phases["speed"].runs:
                suite.phases["speed"].runs = build_speed_runs()
            self._emit(suite)
            return suite
        suite = empty_suite(str(uuid4())[:8], self.comfy.base_url)
        suite.status = "running"
        suite.started_at = _now()
        suite.phases["speed"].runs = build_speed_runs()
        suite.phases["speed"].status = "pending"
        suite.phases["quality"].status = "pending"
        suite.phases["scale"].status = "pending"
        self._emit(suite)
        return suite

    def _should_skip(self, run: Run) -> bool:
        if run.status == "done" and self.resume:
            return True
        if run.status == "failed" and self.resume and not self.retry_failed:
            return True
        return False

    def _run_once(
        self,
        run: Run,
        *,
        stage: str,
        cache_bust: int,
        suite: Suite | None = None,
        phase: str | None = None,
    ) -> tuple[str, float, dict, float | None]:
        """Build prompt for stage and execute.

        Returns prompt_id, elapsed, history, sec_per_it.
        """
        self._check_abort()
        prompt = apply_config(
            self.ui,
            run.config,
            output_tag=f"{run.id}_{stage}",
            cache_bust=cache_bust,
        )

        last_emit = [0.0]

        def on_live(snap: dict) -> None:
            # Throttle JSON writes — frequent emits only refresh the header, but
            # still rewrite benchmark.json; keep this to ~2s.
            now = time.perf_counter()
            if now - last_emit[0] < 2.0 and snap.get("progress_value") not in (
                None,
                snap.get("progress_max"),
            ):
                return
            last_emit[0] = now
            if suite is None:
                return
            detail_parts = []
            if snap.get("node_label"):
                detail_parts.append(str(snap["node_label"]))
            if snap.get("progress"):
                detail_parts.append(str(snap["progress"]))
            if snap.get("sec_per_it") is not None:
                detail_parts.append(f"{snap['sec_per_it']:.2f}s/it")
            suite.current = {
                "phase": phase or run.phase,
                "run_id": run.id,
                "stage": stage if stage != "timed_retry" else "timing",
                "node": snap.get("node"),
                "node_label": snap.get("node_label"),
                "progress": snap.get("progress"),
                "sec_per_it": snap.get("sec_per_it"),
                "detail": " · ".join(detail_parts) if detail_parts else None,
            }
            # Live UI update without rewriting the whole run list status each time
            # is fine — current is what the header shows.
            self._emit(suite)

        return self.comfy.run_prompt(prompt, on_live=on_live if suite is not None else None)

    def _timed_with_cache_guard(
        self, run: Run, *, suite: Suite, phase: str
    ) -> tuple[str, float, dict, float | None]:
        """Run timed generation; clear execution cache and retry if result is a cache hit."""
        # Clear node cache so timed is a real re-run (same seed as warmup).
        try:
            self.comfy.clear_execution_cache()
        except ComfyError as e:
            # Still attempt; cache_bust widgets may be enough.
            print(f"warning: execution cache clear failed: {e}")

        pid, timed_s, hist, sec_per_it = self._run_once(
            run, stage="timed", cache_bust=1, suite=suite, phase=phase
        )

        sampler_cached = self.comfy.was_node_cached(hist, NODE_SAMPLER_ADV)
        if sampler_cached or timed_s < _SUSPICIOUSLY_FAST_S:
            print(
                f"warning: timed run for {run.id} looks cached "
                f"(timed_s={timed_s:.3f}, sampler_cached={sampler_cached}); "
                "clearing cache and retrying once"
            )
            try:
                self.comfy.clear_execution_cache()
            except ComfyError:
                pass
            pid, timed_s, hist, sec_per_it = self._run_once(
                run,
                stage="timed_retry",
                cache_bust=2,
                suite=suite,
                phase=phase,
            )
            if self.comfy.was_node_cached(hist, NODE_SAMPLER_ADV) or timed_s < _SUSPICIOUSLY_FAST_S:
                raise ComfyError(
                    f"timed run still appears fully cached after retry "
                    f"(timed_s={timed_s:.3f}). Start ComfyUI with --cache-none "
                    "or install PRO_ClearCacheNode / easy clearCacheAll."
                )
        return pid, timed_s, hist, sec_per_it

    def _execute_cell(self, suite: Suite, phase: str, run: Run) -> None:
        suite.current = {"phase": phase, "run_id": run.id, "stage": "warmup"}
        run.status = "warmup"
        run.started_at = _now()
        run.error = None
        self._emit(suite)

        # Never enable clean VRAM — apply_config already omits NODE_CLEAN_VRAM.
        try:
            self._check_abort()
            pid, warm_s, _hist, _warm_it = self._run_once(
                run, stage="warmup", cache_bust=0, suite=suite, phase=phase
            )
            run.warmup_s = warm_s
            run.prompt_id = pid
        except KeyboardInterrupt:
            run.status = "failed"
            run.error = "aborted during warmup"
            run.finished_at = _now()
            suite.current = None
            self._emit(suite)
            raise
        except Exception as e:
            run.status = "failed"
            run.error = f"warmup: {e}\n{traceback.format_exc()}"
            run.finished_at = _now()
            suite.current = None
            self._emit(suite)
            return

        suite.current = {"phase": phase, "run_id": run.id, "stage": "timing"}
        run.status = "timing"
        self._emit(suite)

        try:
            self._check_abort()
            pid, timed_s, hist, sec_per_it = self._timed_with_cache_guard(
                run, suite=suite, phase=phase
            )
            run.prompt_id = pid
            run.timed_s = timed_s
            run.sec_per_it = sec_per_it
            suite.current = {
                "phase": phase,
                "run_id": run.id,
                "stage": "saving",
                "detail": "downloading video",
            }
            self._emit(suite)
            vid = self.comfy.find_first_video(hist)
            if vid:
                fn, sub, typ = vid
                dest = store.video_dest(run.id, Path(fn).suffix or ".mp4")
                self.comfy.download_output_file(fn, sub, typ, dest)
                run.video_path = f"videos/{dest.name}"
            run.status = "done"
            run.finished_at = _now()
        except KeyboardInterrupt:
            run.status = "failed"
            run.error = "aborted during timed run"
            run.finished_at = _now()
            suite.current = None
            self._emit(suite)
            raise
        except Exception as e:
            run.status = "failed"
            run.error = f"timed: {e}\n{traceback.format_exc()}"
            run.finished_at = _now()
        suite.current = None
        self._emit(suite)

    def run_phase(self, suite: Suite, phase: str) -> None:
        suite.phases[phase].status = "running"
        self._emit(suite)
        for run in suite.phases[phase].runs:
            self._check_abort()
            if self._should_skip(run):
                continue
            self._execute_cell(suite, phase, run)
        suite.phases[phase].status = "done"
        self._emit(suite)

    def run_all(self, suite: Suite | None = None) -> Suite:
        suite = self.init_suite(suite)
        try:
            # Phase 1 — speed
            self.run_phase(suite, "speed")
            base = pick_fastest(suite.phases["speed"].runs)
            if base is None:
                suite.status = "completed"
                suite.base_config = None
                self._emit(suite)
                return suite
            suite.base_config = base.to_dict()
            self._emit(suite)

            # Phase 2 — quality (populate from base if empty)
            if not suite.phases["quality"].runs:
                suite.phases["quality"].runs = build_quality_runs(base)
            self.run_phase(suite, "quality")

            # Phase 3 — scale
            if not suite.phases["scale"].runs:
                suite.phases["scale"].runs = build_scale_runs(base)
            self.run_phase(suite, "scale")

            suite.status = "completed"
            suite.current = None
            self._emit(suite)
            return suite
        except KeyboardInterrupt:
            suite.status = "aborted"
            suite.current = None
            self._emit(suite)
            raise
