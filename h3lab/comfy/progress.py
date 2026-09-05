"""Deriving seconds-per-step from ComfyUI's WebSocket progress events.

ComfyUI does not report a rate; it reports `progress` messages, and it often delivers them
in a burst once a node finishes. Timing the gaps between those messages produces numbers
like 0.008 s/it for a run that actually took forty seconds a step. Every rule below exists
because of that: a node's clock starts once and only from an early event, an implausibly
fast reading is discarded rather than reported, and on a tie the slower reading wins
because a longer wall clock is the harder thing to fake.

The unit is one sigma step in the primary sampler's queued schedule. Wrappers may report
additional internal work, such as Spectrum's capture and replay passes, but that must not
change either the executed step count or the seconds-per-configured-step denominator.
"""

from __future__ import annotations

import base64
import binascii
import json
import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

# A multi-step node cannot finish this fast; below the floor it is burst delivery.
MIN_SECONDS_PER_STEP = 0.05
BURST_STEP_THRESHOLD = 8
MIN_WALL_PER_STEP = 0.15

# The preview override node in every template draws the latent itself and sends the picture as
# JSON with the image base64'd inside. It also switches ComfyUI's own preview off while it
# samples, so on these graphs this message is the only frame a run produces.
PREVIEW_MESSAGE = "kj_preview_override"

# ComfyUI's own previews arrive as binary frames instead, and only when it was started with a
# preview method. Each opens with a 4-byte event type; two of them are pictures: `1` is a 4-byte
# image type followed by the encoded image, and `4` is the same image behind a JSON header that
# names its mime type. Everything else on that socket is not a frame worth showing.
PREVIEW_IMAGE = 1
PREVIEW_IMAGE_WITH_METADATA = 4
IMAGE_TYPES = {1: "image/jpeg", 2: "image/png"}

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
    "MiniMaxH3Studio": "H3 Studio",
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


def primary_sampler_nodes(prompt: Mapping[str, Any]) -> frozenset[str]:
    """Prefer the sampler fed by Studio over optional secondary sampling passes."""
    samplers = sampler_nodes(prompt)
    if len(samplers) <= 1:
        return samplers
    studios = {
        str(node_id)
        for node_id, node in prompt.items()
        if str((node or {}).get("class_type") or "") == "MiniMaxH3Studio"
    }
    direct = {
        node_id
        for node_id in samplers
        if (
            isinstance((prompt[node_id].get("inputs") or {}).get("latent_image"), list)
            and str(prompt[node_id]["inputs"]["latent_image"][0]) in studios
        )
    }
    if direct:
        return frozenset(direct)
    schedulers = {
        str(node_id)
        for node_id, node in prompt.items()
        if str((node or {}).get("class_type") or "") == "BasicScheduler"
    }
    scheduled = {
        node_id
        for node_id in samplers
        if (
            isinstance((prompt[node_id].get("inputs") or {}).get("sigmas"), list)
            and str(prompt[node_id]["inputs"]["sigmas"][0]) in schedulers
        )
    }
    return frozenset(scheduled or samplers)


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and int(value) == value and value > 0:
        return int(value)
    return None


def _linked_node(
    prompt: Mapping[str, Any], value: Any
) -> tuple[Mapping[str, Any], int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    node = prompt.get(str(value[0]))
    slot = _positive_int(value[1]) if value[1] != 0 else 0
    if not isinstance(node, Mapping) or slot is None:
        return None
    return node, slot


def _step_value(prompt: Mapping[str, Any], value: Any) -> int | None:
    direct = _positive_int(value)
    if direct is not None:
        return direct
    linked = _linked_node(prompt, value)
    if linked is None:
        return None
    node, _slot = linked
    inputs = node.get("inputs") or {}
    for name in ("steps", "value"):
        found = _step_value(prompt, inputs.get(name))
        if found is not None:
            return found
    return None


def _schedule_steps(
    prompt: Mapping[str, Any], value: Any, seen: set[str]
) -> int | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    node_id = str(value[0])
    if node_id in seen:
        return None
    node = prompt.get(node_id)
    if not isinstance(node, Mapping):
        return None
    seen.add(node_id)
    inputs = node.get("inputs") or {}
    class_type = str(node.get("class_type") or "")
    if class_type == "SplitSigmas":
        total = _schedule_steps(prompt, inputs.get("sigmas"), seen)
        split = _step_value(prompt, inputs.get("step"))
        if split is None:
            return None
        if value[1] == 0:
            return min(total, split) if total is not None else split
        if value[1] == 1 and total is not None:
            return max(total - split, 0) or None
        return None
    steps = _step_value(prompt, inputs.get("steps"))
    if steps is not None:
        return steps
    return _schedule_steps(prompt, inputs.get("sigmas"), seen)


def primary_schedule_steps(
    prompt: Mapping[str, Any], samplers: Iterable[str] | None = None
) -> int | None:
    """Resolve the primary sampler's actual sigma count from the queued graph."""
    found: set[int] = set()
    for node_id in samplers if samplers is not None else primary_sampler_nodes(prompt):
        node = prompt.get(str(node_id))
        if not isinstance(node, Mapping):
            continue
        inputs = node.get("inputs") or {}
        steps = _step_value(prompt, inputs.get("steps"))
        if steps is None:
            steps = _schedule_steps(prompt, inputs.get("sigmas"), set())
        if steps is not None:
            found.add(steps)
    return next(iter(found)) if len(found) == 1 else None


@dataclass(frozen=True, slots=True)
class Preview:
    """The newest picture ComfyUI drew of the latent it is sampling."""

    data: bytes
    content_type: str
    seq: int


def decode_preview(frame: bytes) -> tuple[bytes, str] | None:
    """A preview image out of a binary WebSocket frame, or ``None`` if it is not one."""
    if len(frame) < 8:
        return None
    event = int.from_bytes(frame[:4], "big")
    if event == PREVIEW_IMAGE:
        return frame[8:], IMAGE_TYPES.get(int.from_bytes(frame[4:8], "big"), "image/jpeg")
    if event == PREVIEW_IMAGE_WITH_METADATA:
        length = int.from_bytes(frame[4:8], "big")
        try:
            metadata = json.loads(frame[8 : 8 + length])
        except (json.JSONDecodeError, UnicodeDecodeError):
            metadata = {}
        kind = metadata.get("image_type") if isinstance(metadata, dict) else None
        return frame[8 + length :], str(kind or "image/jpeg")
    return None


def decode_preview_message(data: Mapping[str, Any]) -> tuple[bytes, str] | None:
    """A preview out of the override node's message, or ``None`` if it holds none.

    Usually not a still. The templates wire the clip's frame count into the node, so every step
    comes back as the whole latent decoded and encoded together — an MP4 where NVENC is present
    and an animated WebP otherwise. The media type travels with it and decides nothing here; it
    is what the browser is told when it asks for the frame.
    """
    raw = data.get("image")
    if not isinstance(raw, str) or not raw:
        return None
    kind = str(data.get("mime") or "image/jpeg")
    if not kind.startswith(("image/", "video/")):
        return None
    try:
        image = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return None
    return (image, kind) if image else None


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
        scheduled_steps: int | None = None,
    ) -> None:
        self.labels: dict[str, str] = dict(labels or {})
        self.preferred: frozenset[str] = frozenset(preferred)
        self.scheduled_steps = scheduled_steps
        self._lock = threading.Lock()
        self.current_node: str | None = None
        self.step: int | None = None
        self.step_total: int | None = None
        self._entered_at: dict[str, float] = {}
        self._max_steps: dict[str, int] = {}
        self._finalized: set[str] = set()
        self._best_rate: float | None = None
        self._best_steps: int = 0
        self._best_preferred = False
        self._live_rate: float | None = None
        self._preview: Preview | None = None

    @classmethod
    def of(cls, prompt: Mapping[str, Any] | None) -> ProgressTracker:
        """A tracker that can name the nodes of the graph about to run."""
        if not prompt:
            return cls()
        preferred = primary_sampler_nodes(prompt)
        return cls(
            labels_for(prompt),
            preferred=preferred,
            scheduled_steps=primary_schedule_steps(prompt, preferred),
        )

    # --- plausibility ------------------------------------------------------

    @staticmethod
    def is_plausible(duration_s: float, steps: float) -> bool:
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
        reported_steps = self._max_steps.get(node) or 0
        if entered is None or reported_steps <= 0:
            return
        steps = (
            self.scheduled_steps
            if node in self.preferred and self.scheduled_steps is not None
            else reported_steps
        )
        duration = ended_at - entered
        if not self.is_plausible(duration, steps):
            return
        candidate = duration / steps
        preferred = node in self.preferred
        preferred_over_fallback = preferred and not self._best_preferred
        same_priority = preferred == self._best_preferred
        more_steps = steps > self._best_steps
        # On an equal step count keep the slower reading: burst finalisation is what makes
        # a reading too fast, never too slow.
        same_steps_slower = (
            steps == self._best_steps
            and self._best_rate is not None
            and candidate > self._best_rate
        )
        if (
            self._best_rate is None
            or preferred_over_fallback
            or (same_priority and (more_steps or same_steps_slower))
        ):
            self._best_rate = candidate
            self._best_steps = steps
            self._best_preferred = preferred

    def _finalize(self, node: str, ended_at: float) -> None:
        if node in self._finalized:
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
            rate_step = float(value)
            if node in self.preferred and self.scheduled_steps is not None:
                rate_step = value * self.scheduled_steps / maximum
                self.step = min(
                    self.scheduled_steps,
                    max(1, round(rate_step)) if value > 0 else 0,
                )
                self.step_total = self.scheduled_steps
            else:
                self.step = value
                self.step_total = maximum
            self._max_steps[node] = max(self._max_steps.get(node, 0), maximum)
            entered = self._entered_at.get(node)
            if entered is not None and rate_step > 0 and now > entered:
                elapsed = now - entered
                if (
                    self.is_plausible(elapsed, max(rate_step, 1))
                    or rate_step < BURST_STEP_THRESHOLD
                ):
                    self._live_rate = elapsed / rate_step
            # Deliberately not finalising on value == max: a burst reaches max with almost
            # no wall clock. Finalisation happens when execution leaves the node.

    def on_preview(self, frame: bytes) -> bool:
        """Keep the newest picture out of a binary frame. Returns whether it held one."""
        return self._keep(decode_preview(frame))

    def on_preview_message(self, data: Mapping[str, Any]) -> bool:
        """Keep the newest picture the override node sent. Returns whether it held one."""
        return self._keep(decode_preview_message(data))

    def _keep(self, decoded: tuple[bytes, str] | None) -> bool:
        if decoded is None or not decoded[0]:
            return False
        data, content_type = decoded
        with self._lock:
            seq = (self._preview.seq if self._preview else 0) + 1
            self._preview = Preview(data=data, content_type=content_type, seq=seq)
        return True

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
            if node in self._finalized:
                self._finalized.remove(node)
                self._max_steps.pop(node, None)
                self._entered_at[node] = now
            elif node not in self._entered_at:
                self._entered_at[node] = now

    # --- reading -----------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            node = self.current_node
            step = self.step
            total = self.step_total
            rate = self._best_rate if self._best_rate is not None else self._live_rate
            preview = self._preview
        out: dict[str, Any] = {"node": node, "node_label": node_label(node, self.labels)}
        if step is not None and total is not None:
            out["step"] = step
            out["step_total"] = total
        if rate is not None and rate > 0:
            out["sec_per_it"] = round(rate, 3)
        # The count and the media type, never the bytes: this goes out on the event bus, which
        # keeps a replay buffer for reconnecting browsers. The number tells them a new frame
        # exists and the type tells them what to put it in; they fetch it if they are looking.
        if preview is not None:
            out["preview_seq"] = preview.seq
            out["preview_mime"] = preview.content_type
        return out

    def preview(self) -> Preview | None:
        with self._lock:
            return self._preview

    def sec_per_it(self) -> float | None:
        """The final rate, or ``None`` when no reading survived the plausibility rules."""
        now = time.perf_counter()
        with self._lock:
            if self.current_node is not None:
                self._consider(self.current_node, now)
            for node in list(self._entered_at):
                if node != self.current_node and node not in self._finalized:
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
