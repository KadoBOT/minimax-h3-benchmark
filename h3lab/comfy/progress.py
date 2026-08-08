"""Deriving seconds-per-step from ComfyUI's WebSocket progress events.

ComfyUI does not report a rate; it reports `progress` messages, and it often delivers them
in a burst once a node finishes. Timing the gaps between those messages produces numbers
like 0.008 s/it for a run that actually took forty seconds a step. Every rule below exists
because of that: a node's clock starts once and only from an early event, an implausibly
fast reading is discarded rather than reported, and on a tie the slower reading wins
because a longer wall clock is the harder thing to fake.

The unit is the same one ComfyUI's own tqdm bar prints, so the numbers are comparable with
what the console shows.
"""

from __future__ import annotations

import threading
import time
from typing import Any

# The advanced sampler node in the MiniMax H3 graphs. Its readings are the ones worth
# preferring when several nodes report the same step count.
PREFERRED_SAMPLER_NODES = frozenset({"10"})

# A multi-step node cannot finish this fast; below the floor it is burst delivery.
MIN_SECONDS_PER_STEP = 0.05
BURST_STEP_THRESHOLD = 8
MIN_WALL_PER_STEP = 0.15

NODE_LABELS: dict[str, str] = {
    "1": "UNET",
    "2": "CLIP",
    "3": "Video VAE",
    "4": "Audio VAE",
    "5": "Conditioning",
    "6": "Scheduler",
    "7": "Sampler select",
    "8": "Guider",
    "10": "Sampler",
    "12": "Audio decode",
    "15": "EasyCache",
    "20": "Load image",
    "91": "Sage attention",
    "92": "Sol attention",
    "95": "Interp FPS",
    "96": "RIFE",
    "97": "Clean VRAM",
    "98": "Resolution",
    "102": "Duration",
    "103": "Frame math",
    "107": "Prompt",
    "110": "Video combine",
    "111": "Upscaler",
    "118": "Seed",
    "119": "Noise",
    "122": "Spectrum",
    "123": "Sigma shift",
    "125": "VAE decode",
    "128": "H3 cache",
    "130": "GGUF UNET",
    "131": "GGUF CLIP",
}


def node_label(node_id: str | int | None) -> str | None:
    if node_id is None:
        return None
    key = str(node_id)
    return NODE_LABELS.get(key, f"node {key}")


class ProgressTracker:
    """Accumulates progress events and reports the best trustworthy rate."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.current_node: str | None = None
        self.step: int | None = None
        self.step_total: int | None = None
        self._entered_at: dict[str, float] = {}
        self._max_steps: dict[str, int] = {}
        self._finalized: set[str] = set()
        self._best_rate: float | None = None
        self._best_steps: int = 0
        self._live_rate: float | None = None

    # --- plausibility ------------------------------------------------------

    @staticmethod
    def is_plausible(duration_s: float, steps: int) -> bool:
        if steps <= 0 or duration_s <= 0:
            return False
        if steps >= BURST_STEP_THRESHOLD:
            if duration_s < max(1.0, MIN_WALL_PER_STEP * steps):
                return False
            if duration_s / steps < MIN_SECONDS_PER_STEP:
                return False
        return True

    def _consider(self, node: str, ended_at: float) -> None:
        entered = self._entered_at.get(node)
        steps = self._max_steps.get(node) or 0
        if entered is None or steps <= 0:
            return
        duration = ended_at - entered
        if not self.is_plausible(duration, steps):
            return
        candidate = duration / steps
        more_steps = steps > self._best_steps
        # On an equal step count keep the slower reading: burst finalisation is what makes
        # a reading too fast, never too slow.
        same_steps_slower = (
            steps == self._best_steps
            and self._best_rate is not None
            and candidate > self._best_rate
        )
        if self._best_rate is None or more_steps or same_steps_slower:
            self._best_rate = candidate
            self._best_steps = steps
        elif node in PREFERRED_SAMPLER_NODES and steps >= self._best_steps:
            self._best_rate = candidate
            self._best_steps = steps

    def _finalize(self, node: str, ended_at: float) -> None:
        if node in self._finalized:
            self._consider(node, ended_at)
            return
        self._consider(node, ended_at)
        entered = self._entered_at.get(node)
        steps = self._max_steps.get(node, 0)
        if entered is None or steps <= 0:
            return
        duration = ended_at - entered
        if self.is_plausible(duration, steps) or duration >= 1.0:
            self._finalized.add(node)

    # --- events ------------------------------------------------------------

    def on_progress(self, data: dict[str, Any]) -> None:
        try:
            value = int(data.get("value"))
            maximum = int(data.get("max"))
        except (TypeError, ValueError):
            return
        if maximum <= 0:
            return
        now = time.perf_counter()
        raw_node = data.get("node")
        with self._lock:
            node = str(raw_node) if raw_node is not None else self.current_node
            if node is None:
                return
            # Start the clock once, and only from an event early enough to mean "beginning".
            # A late burst event would otherwise start the clock at the end of the work.
            if node not in self._entered_at and value <= 1:
                self._entered_at[node] = now
            self.current_node = node
            self.step = value
            self.step_total = maximum
            self._max_steps[node] = max(self._max_steps.get(node, 0), maximum)
            entered = self._entered_at.get(node)
            if entered is not None and value > 0 and now > entered:
                elapsed = now - entered
                if self.is_plausible(elapsed, max(value, 1)) or value < BURST_STEP_THRESHOLD:
                    self._live_rate = elapsed / value
            # Deliberately not finalising on value == max: a burst reaches max with almost
            # no wall clock. Finalisation happens when execution leaves the node.

    def on_executing(self, data: dict[str, Any]) -> None:
        now = time.perf_counter()
        raw = data.get("node")
        with self._lock:
            previous = self.current_node
            if previous is not None and (raw is None or str(raw) != previous):
                self._finalize(previous, now)
                self.step = None
                self.step_total = None
            if raw is None:
                self.current_node = None
                return
            node = str(raw)
            self.current_node = node
            if node not in self._entered_at:
                self._entered_at[node] = now

    # --- reading -----------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            node = self.current_node
            step = self.step
            total = self.step_total
            rate = self._best_rate if self._best_rate is not None else self._live_rate
        out: dict[str, Any] = {"node": node, "node_label": node_label(node)}
        if step is not None and total is not None:
            out["step"] = step
            out["step_total"] = total
        if rate is not None and rate > 0:
            out["sec_per_it"] = round(rate, 3)
        return out

    def sec_per_it(self) -> float | None:
        """The final rate, or ``None`` when no reading survived the plausibility rules."""
        now = time.perf_counter()
        with self._lock:
            if self.current_node is not None:
                self._finalize(self.current_node, now)
            for node in list(self._entered_at):
                self._consider(node, now)
            best = self._best_rate
            steps = self._best_steps
            live = self._live_rate
        if best is not None and best > 0 and steps >= 1:
            return best
        # A live estimate is only worth reporting if it is not itself burst-shaped.
        if live is not None and live >= MIN_SECONDS_PER_STEP:
            return live
        return None

    def steps_seen(self) -> int | None:
        with self._lock:
            return self._best_steps or None
