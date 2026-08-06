"""Orchestrate benchmark phases: warmup + timed cells, progressive store updates."""

from __future__ import annotations

import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from bench import store
from bench.comfy import ComfyClient
from bench.constants import WORKFLOW_PATH
from bench.matrix import build_quality_runs, build_scale_runs, build_speed_runs, pick_fastest
from bench.models import Run, Suite, empty_suite
from bench.workflow import apply_config, load_ui_workflow


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    def _emit(self, suite: Suite) -> None:
        store.save_suite(suite)
        if self.on_update:
            self.on_update(suite)

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

    def _execute_cell(self, suite: Suite, phase: str, run: Run) -> None:
        suite.current = {"phase": phase, "run_id": run.id, "stage": "warmup"}
        run.status = "warmup"
        run.started_at = _now()
        run.error = None
        self._emit(suite)

        # Never enable clean VRAM — apply_config already omits NODE_CLEAN_VRAM.
        prompt = apply_config(self.ui, run.config)
        try:
            pid, warm_s, _hist = self.comfy.run_prompt(prompt)
            run.warmup_s = warm_s
            run.prompt_id = pid
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
            pid, timed_s, hist = self.comfy.run_prompt(prompt)
            run.prompt_id = pid
            run.timed_s = timed_s
            vid = self.comfy.find_first_video(hist)
            if vid:
                fn, sub, typ = vid
                dest = store.video_dest(run.id, Path(fn).suffix or ".mp4")
                self.comfy.download_output_file(fn, sub, typ, dest)
                run.video_path = f"videos/{dest.name}"
            run.status = "done"
            run.finished_at = _now()
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
            if self._should_skip(run):
                continue
            self._execute_cell(suite, phase, run)
        suite.phases[phase].status = "done"
        self._emit(suite)

    def run_all(self, suite: Suite | None = None) -> Suite:
        suite = self.init_suite(suite)
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
