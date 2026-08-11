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
from typing import Any, Iterable, Mapping

# A multi-step node cannot finish this fast; below the floor it is burst delivery.
MIN_SECONDS_PER_STEP = 0.05
BURST_STEP_THRESHOLD = 8
MIN_WALL_PER_STEP = 0.15

# Sampler classes: the nodes whose reading is worth preferring when several report the same
# step count. Kept beside the role rules that name the same classes.
SAMPLER_CLASSES = ("SamplerCustomAdvanced", "KSampler", "KSamplerAdvanced")

# Short words for the classes whose own names are the least readable. Everything else is
# labelled with its class name, which is already the truest thing we can say about a node.
CLASS_LABELS: dict[str, str] = {
    "UNETLoader": "Diffusion model",
    "OTUNetLoaderW8A8": "Diffusion model",
    "CheckpointLoaderSimple": "Checkpoint",
    "GGUFLoaderKJ": "GGUF model",
    "UnetLoaderGGUF": "GGUF model",
    "CLIPLoader": "Text encoder",
    "CLIPLoaderKJ": "Text encoder",
    "CLIPLoaderGGUF": "GGUF text encoder",
    "VAELoader": "VAE",
    "MiniMaxH3ImageToVideo": "Conditioning",
    "MiniMaxH3TextToVideo": "Conditioning",
    "MiniMaxH3ReferenceToVideo": "Conditioning",
    "MiniMaxH3TurboLoRA": "Turbo LoRA",
    "LoraLoaderModelOnly": "LoRA",
    "LoraLoader": "LoRA",
    "BasicScheduler": "Scheduler",
    "KSamplerSelect": "Sampler select",
    "BasicGuider": "Guider",
    "CFGGuider": "Guider",
    "SamplerCustomAdvanced": "Sampler",
    "KSampler": "Sampler",
    "KSamplerAdvanced": "Sampler",
    "RandomNoise": "Noise",
    "DisableNoise": "Noise",
    "VAEDecode": "VAE decode",
    "VAEDecodeTiled": "VAE decode",
    "VAEDecodeAudio": "Audio decode",
    "RIFEInterpolation": "RIFE",
    "FrameInterpolate": "FILM",
    "FrameInterpolationModelLoader": "FILM model",
    "RTXVideoSuperResolution": "Upscaler",
    "ImageUpscaleWithModel": "Upscaler",
    "VHS_VideoCombine": "Video out",
    "SaveVideo": "Video out",
    "LoadImage": "Load image",
    "LoadImageOutput": "Load image",
    "easy cleanGpuUsed": "Free VRAM",
    "PathchSageAttentionKJ": "Sage attention",
    "PatchSageAttentionKJ": "Sage attention",
    "SolAttnPatch": "Sol attention",
}


def class_label(class_type: str | None) -> str | None:
    if not class_type:
        return None
    return CLASS_LABELS.get(class_type, class_type)


def labels_for(prompt: Mapping[str, Any]) -> dict[str, str]:
    """A readable name per node id, taken from what each node is.

    ComfyUI reports progress by id, and an id is the least stable thing in a workflow: folding
    the pipeline into a subgraph turned node 10 into `169:10`, and a table keyed by id started
    calling every node "node 169:10". The class travels with the node through any edit.
    """
    labels: dict[str, str] = {}
    for node_id, node in prompt.items():
        label = class_label(str((node or {}).get("class_type") or ""))
        if label:
            labels[str(node_id)] = label
    return labels


def sampler_nodes(prompt: Mapping[str, Any]) -> frozenset[str]:
    return frozenset(
        str(node_id)
        for node_id, node in prompt.items()
        if str((node or {}).get("class_type") or "") in SAMPLER_CLASSES
    )


def node_label(node_id: str | int | None, labels: Mapping[str, str] | None = None) -> str | None:
    if node_id is None:
        return None
    key = str(node_id)
    return (labels or {}).get(key, f"node {key}")


class ProgressTracker:
    """Accumulates progress events and reports the best trustworthy rate."""

    def __init__(
        self,
        labels: Mapping[str, str] | None = None,
        *,
        preferred: Iterable[str] = (),
    ) -> None:
        self.labels: dict[str, str] = dict(labels or {})
        self.preferred: frozenset[str] = frozenset(preferred)
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

    @classmethod
    def of(cls, prompt: Mapping[str, Any] | None) -> ProgressTracker:
        """A tracker that can name the nodes of the graph about to run."""
        if not prompt:
            return cls()
        return cls(labels_for(prompt), preferred=sampler_nodes(prompt))

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
        elif node in self.preferred and steps >= self._best_steps:
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
        out: dict[str, Any] = {"node": node, "node_label": node_label(node, self.labels)}
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
