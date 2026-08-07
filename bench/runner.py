"""Orchestrate benchmark runs: one generation per cell, progressive store updates.

Protocol (truthful metrics)
---------------------------
Per cell (interactive Run or legacy matrix):

1. **Optional graph-cache clear** — forces a real re-exec if the same graph was
   just submitted (does **not** unload VRAM / disable Easy/Spectrum/H3).
2. **Single generation** — record ``timed_s`` (full pipeline wall) and
   ``sec_per_it`` (sampler wall ÷ steps; also shown as it/s = 1/sec_per_it).

No second "warmup" gen. First-run cold model load is part of ``timed_s``.
"""

from __future__ import annotations

import time
import traceback
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from bench import store
from bench.comfy import ComfyClient, ComfyError
from bench.constants import NODE_SAMPLER_ADV, WORKFLOW_PATH
from bench.matrix import build_quality_runs, build_scale_runs, build_speed_runs, pick_fastest
from bench.models import PhaseState, Run, RunConfig, Suite, empty_suite
from bench.workflow import apply_config, load_ui_workflow


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_legacy_phases(suite: Suite) -> None:
    """Compat for legacy run_all only (interactive path uses flat suite.runs)."""
    for name in ("speed", "quality", "scale"):
        if name not in suite.phases:
            suite.phases[name] = PhaseState()


# Absolute floor: anything under this is almost certainly a graph-cache hit.
_SUSPICIOUSLY_FAST_ABS_S = 2.0


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

    def clear_abort(self) -> None:
        """Allow new runs after an abort (queue worker / next POST)."""
        self._abort = False

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
            _ensure_legacy_phases(suite)
            if not suite.phases["speed"].runs:
                suite.phases["speed"].runs = build_speed_runs()
            # Ensure protocol text is present on older result files
            if "protocol" not in (suite.baseline or {}):
                from bench.models import BENCHMARK_PROTOCOL

                suite.baseline = {**(suite.baseline or {}), "protocol": BENCHMARK_PROTOCOL}
            self._emit(suite)
            return suite
        suite = empty_suite(str(uuid4())[:8], self.comfy.base_url)
        suite.status = "running"
        suite.started_at = _now()
        _ensure_legacy_phases(suite)
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

    def _looks_like_graph_cache_hit(self, hist: dict, timed_s: float) -> bool:
        """True when the gen likely skipped real sampling (graph output cache)."""
        if self.comfy.was_node_cached(hist, NODE_SAMPLER_ADV):
            return True
        if timed_s < _SUSPICIOUSLY_FAST_ABS_S:
            return True
        return False

    def _run_once(
        self,
        run: Run,
        *,
        stage: str,
        suite: Suite | None = None,
        phase: str | None = None,
    ) -> tuple[str, float, dict, float | None]:
        """Build prompt for stage and execute.

        Warmup and timed share the same sampling graph; only output filename differs.
        """
        self._check_abort()
        prompt = apply_config(
            self.ui,
            run.config,
            output_tag=f"{run.id}_{stage}",
        )

        last_emit = [0.0]

        def on_live(snap: dict) -> None:
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
            ui_stage = "timing" if stage.startswith("timed") else stage
            suite.current = {
                "phase": phase or run.phase,
                "run_id": run.id,
                "stage": ui_stage,
                "node": snap.get("node"),
                "node_label": snap.get("node_label"),
                "progress": snap.get("progress"),
                "sec_per_it": snap.get("sec_per_it"),
                "detail": " · ".join(detail_parts) if detail_parts else None,
            }
            self._emit(suite)

        return self.comfy.run_prompt(prompt, on_live=on_live if suite is not None else None)

    def _single_pass(
        self, run: Run, *, suite: Suite, phase: str
    ) -> tuple[str, float, dict, float | None, bool, bool]:
        """Clear graph cache once, run one gen, optional single retry on cache hit.

        Returns:
            prompt_id, timed_s, hist, sec_per_it, sampler_cached, graph_cache_cleared
        """
        cleared = False
        suite.current = {
            "phase": phase,
            "run_id": run.id,
            "stage": "clear_graph_cache",
            "detail": "clear Comfy execution cache (not VRAM / not model caches)",
        }
        self._emit(suite)
        try:
            self.comfy.clear_execution_cache()
            cleared = True
        except ComfyError as e:
            print(
                f"warning: graph execution cache clear failed for {run.id}: {e}. "
                "Result may be invalid if Comfy reuses prior node outputs."
            )

        pid, timed_s, hist, sec_per_it = self._run_once(
            run, stage="timed", suite=suite, phase=phase
        )
        sampler_cached = self.comfy.was_node_cached(hist, NODE_SAMPLER_ADV)

        if self._looks_like_graph_cache_hit(hist, timed_s):
            print(
                f"warning: run for {run.id} looks like a graph-cache hit "
                f"(timed_s={timed_s:.3f}, sampler_cached={sampler_cached}); "
                "clearing execution cache once more and retrying"
            )
            try:
                self.comfy.clear_execution_cache()
                cleared = True
            except ComfyError:
                pass
            pid, timed_s, hist, sec_per_it = self._run_once(
                run, stage="timed_retry", suite=suite, phase=phase
            )
            sampler_cached = self.comfy.was_node_cached(hist, NODE_SAMPLER_ADV)
            if self._looks_like_graph_cache_hit(hist, timed_s):
                raise ComfyError(
                    f"run still looks graph-cached after retry "
                    f"(timed_s={timed_s:.3f}). Install PRO_ClearCacheNode / "
                    "easy clearCacheAll, or start ComfyUI with --cache-none."
                )

        return pid, timed_s, hist, sec_per_it, sampler_cached, cleared

    def _execute_cell(self, suite: Suite, phase: str, run: Run) -> None:
        """One generation per cell (no warmup)."""
        suite.current = {"phase": phase, "run_id": run.id, "stage": "timing"}
        run.status = "timing"
        run.started_at = _now()
        run.error = None
        run.warmup_s = None
        run.sampler_cached = None
        run.graph_cache_cleared = None
        self._emit(suite)

        try:
            self._check_abort()
            (
                pid,
                timed_s,
                hist,
                sec_per_it,
                sampler_cached,
                cleared,
            ) = self._single_pass(run, suite=suite, phase=phase)
            run.prompt_id = pid
            run.timed_s = timed_s
            run.sec_per_it = sec_per_it
            run.sampler_cached = sampler_cached
            run.graph_cache_cleared = cleared
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
            run.status = "aborted"
            run.error = "aborted during run"
            run.finished_at = _now()
            suite.current = None
            self._emit(suite)
            raise
        except Exception as e:
            run.status = "failed"
            run.error = f"run: {e}\n{traceback.format_exc()}"
            run.finished_at = _now()
        suite.current = None
        self._emit(suite)

    def ensure_suite(self, existing: Suite | None = None) -> Suite:
        """Return existing suite (already migrated via store) or create an idle empty suite."""
        if existing:
            return existing
        s = empty_suite(str(uuid4())[:8], self.comfy.base_url)
        s.status = "idle"
        self._emit(s)
        return s

    def _next_run_id(self, suite: Suite, cfg: RunConfig) -> str:
        n = len(suite.all_runs()) + 1
        if cfg.diffusion_model:
            stem = Path(cfg.diffusion_model).stem
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)[:40]
            path = safe or ("gguf" if cfg.model_path == "gguf" else cfg.quant)
        else:
            path = "gguf" if cfg.model_path == "gguf" else cfg.quant
        cache = "none" if not cfg.cache_enabled else cfg.cache
        sol = "solon" if cfg.sol_attn else "soloff"
        return f"run_{n:03d}_{path}_{cache}_{sol}"

    def enqueue_run(
        self, suite: Suite, cfg: RunConfig, *, run_id: str | None = None
    ) -> Run:
        """Append a queued run (no execution). Safe to call while another run is active."""
        from bench.presets import expand_presets

        cfg = deepcopy(cfg)
        resolved = expand_presets(cfg)
        if cfg.cache_preset != "custom" or cfg.sol_preset != "custom":
            cfg.widgets = {**(cfg.widgets or {}), **resolved}

        rid = run_id or self._next_run_id(suite, cfg)
        run = Run(id=rid, phase="manual", status="queued", config=cfg)
        suite.runs.append(run)
        if not suite.started_at:
            suite.started_at = _now()
        # Stay "running" if something is already in flight; else mark pending queue
        if suite.status != "running":
            suite.status = "running"
        self._emit(suite)
        return run

    def process_run(self, suite: Suite, run: Run) -> Run:
        """Execute a previously enqueued run (single generation)."""
        self.clear_abort()
        suite.status = "running"
        self._emit(suite)
        try:
            self._execute_cell(suite, "manual", run)
            if run.status == "aborted":
                suite.status = "aborted"
            # leave suite.status to the queue worker when more jobs remain
        except KeyboardInterrupt:
            run.status = "aborted"
            run.error = run.error or "aborted"
            run.finished_at = run.finished_at or _now()
            suite.status = "aborted"
            suite.current = None
            self._emit(suite)
            raise
        suite.current = None
        self._emit(suite)
        return run

    def run_one(
        self, suite: Suite, cfg: RunConfig, *, run_id: str | None = None
    ) -> Run:
        """Enqueue and immediately process one run (tests / single-shot)."""
        run = self.enqueue_run(suite, cfg, run_id=run_id)
        try:
            self.process_run(suite, run)
        finally:
            if suite.status != "aborted" and not any(
                r.status in ("queued", "warmup", "timing") for r in suite.all_runs()
            ):
                suite.status = "idle"
                self._emit(suite)
        return run

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
        """Legacy auto Phase 1–3 matrix. Product path is ``run_one`` / interactive UI."""
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
