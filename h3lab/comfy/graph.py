"""Turning an editor workflow into an executable ComfyUI prompt for one config.

`apply_config` reads the workflow (see `workflow.py`), works out which node plays which part
(see `roles.py`), and then *thins* the graph instead of rewiring it: every node this run does
not want is switched off, and switching a node off means its consumers are reconnected to
whatever fed it — exactly what ComfyUI's own bypass does. Nothing here knows the order of the
model chain, which is why re-ordering that chain in the editor cannot break it.

What the lab does not own, it does not touch. It asserts every setting represented by the
generation config, including Studio's graph-level feature switches, and leaves unrelated
template nodes in the state the workflow author chose.

Two rules keep a prompt submittable, and both are enforced at the end rather than hoped for:
no input may point at a node that is gone, and nothing may be in the prompt that the chosen
output does not need.
"""

from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from h3lab.comfy import nodes as N
from h3lab.comfy import roles as R
from h3lab.comfy.presets import cache_widgets, sol_widgets
from h3lab.comfy.schema import Schemas, static_schemas
from h3lab.comfy.workflow import Graph, Node, Prompt, is_link, load_workflow, read
from h3lab.comfy.workflow import to_api_prompt as read_api_prompt
from h3lab.domain.config import (
    DEFAULT_ASPECT,
    MAX_REF_AUDIOS,
    MAX_REF_IMAGES,
    MAX_REF_VIDEOS,
    GenerationConfig,
    config_attention,
    resolve_model_filename,
)

__all__ = [
    "STUDIO_CLASS",
    "Prompt",
    "WorkflowError",
    "apply_config",
    "build",
    "build_studio_source",
    "describe",
    "load_workflow",
    "missing_links",
    "output_filename_prefix",
    "referenced_files",
    "repair_studio_video_boundaries",
    "restore_studio_contract",
    "to_api_prompt",
]

DEFAULT_BASE_FPS = 24
DEFAULT_INTERP_FPS = 60

# FILM Net takes a frame count multiplier rather than a target rate. Two is the node's own
# minimum and its default, and the only value the lab offers: the setting exists so a run can
# be compared with and without interpolation, not so the factor can be swept.
FILM_MULTIPLIER = 2
# The unified workflow's GMFSS mode has one fixed 4x frame multiplier.
GMFSS_MULTIPLIER = 4

# Modes ComfyUI gives a node. The lab sets them to say what this run wants.
ALWAYS = 0
MUTED = 2
BYPASSED = 4

REF_FAMILIES: tuple[tuple[str, str, str, int], ...] = (
    ("ref_images", "ref_images", "ref_image", MAX_REF_IMAGES),
    ("ref_videos", "ref_videos", "ref_video", MAX_REF_VIDEOS),
    ("ref_video_audios", "ref_video_audios", "ref_video_audio", MAX_REF_VIDEOS),
    ("ref_audios", "ref_audios", "ref_audio", MAX_REF_AUDIOS),
)

_MEDIA_WIDGETS: tuple[str, ...] = ("image", "file", "audio", "video")

# Where pictures arrive. The lab owns these links, so they are never followed upstream when a
# node is switched on.
_IMAGE_INPUTS: tuple[str, ...] = ("images", "image", "frames")

_LOADER_CLASSES: dict[str, tuple[str, ...]] = {
    "ref_images": ("LoadImage", "LoadImageOutput"),
    "ref_videos": ("LoadVideo", "VHS_LoadVideo"),
    "ref_video_audios": ("LoadAudio",),
    "ref_audios": ("LoadAudio",),
}

_MINTED: dict[str, tuple[str, tuple[str, ...]]] = {
    "ref_images": ("LoadImage", ("IMAGE", "MASK")),
    "ref_videos": ("LoadVideo", ("VIDEO",)),
    "ref_video_audios": ("LoadAudio", ("AUDIO",)),
    "ref_audios": ("LoadAudio", ("AUDIO",)),
}

STUDIO_CLASS = "MiniMaxH3Studio"
STUDIO_MODES: dict[str, str] = {"t2v": "T2V", "flf2v": "FLF2V", "r2v": "R2V"}
_JSON_WIDGETS: frozenset[str] = frozenset({"references", "guides"})


def _studio_widget_value(name: str, value: Any) -> Any:
    """Studio stores references and guides as JSON strings."""
    if name in _JSON_WIDGETS and not isinstance(value, str):
        return json.dumps(value, separators=(",", ":"))
    return value
STUDIO_INTERP: dict[str, str] = {"off": "none", "film": "film", "rife": "rife", "gmfss": "gmfss"}
STUDIO_TURBO_NONE = "none"


class WorkflowError(RuntimeError):
    """The workflow template cannot express the requested configuration."""


# --- small helpers ---------------------------------------------------------


def _basename(value: str) -> str:
    return Path(str(value).replace("\\", "/")).name


def output_filename_prefix(tag: str) -> str:
    safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in tag)[:120]
    return f"h3lab/{safe or 'run'}"


def to_api_prompt(workflow: dict[str, Any], **kwargs: Any) -> Prompt:
    """Flatten an editor workflow into the API prompt shape, unpatched."""
    return read_api_prompt(workflow, **kwargs)


def _h3_tagged(graph: Graph, role: str) -> list[Node]:
    marker = f"[h3s:{role}]"
    return [node for node in graph if marker in node.title.lower()]


def restore_studio_contract(graph: Graph, contract: Graph) -> None:
    """Restore contract role hints while keeping the live graph authoritative."""
    contract_nodes = list(contract)
    tagged = [
        (
            source,
            re.findall(r"\[H3S:[^\]]+\]", source.title, flags=re.IGNORECASE),
        )
        for source in contract_nodes
    ]
    tagged = [(source, tags) for source, tags in tagged if tags]
    contract_ids = {node.id for node in contract_nodes}
    used: set[str] = set()
    pending: list[tuple[Node, list[str]]] = []

    def without_tags(title: str) -> str:
        return re.sub(
            r"\s*\[H3S:[^\]]+\]", "", title, flags=re.IGNORECASE
        ).strip()

    def base_title(title: str) -> str:
        return " ".join(without_tags(title).split()).casefold()

    def apply(target: Node, tags: list[str]) -> None:
        target.title = f"{without_tags(target.title)} {' '.join(tags)}".strip()
        used.add(target.id)

    for source, tags in tagged:
        target = graph.get(source.id)
        if (
            target is not None
            and target.class_type == source.class_type
            and target.id not in used
        ):
            apply(target, tags)
        else:
            pending.append((source, tags))

    for source, tags in pending:
        same_class = [
            node
            for node in graph
            if node.class_type == source.class_type and node.id not in used
        ]
        wanted_title = base_title(source.title)
        title_matches = [
            node for node in same_class if base_title(node.title) == wanted_title
        ]
        new_nodes = [node for node in same_class if node.id not in contract_ids]
        if len(title_matches) == 1:
            apply(title_matches[0], tags)
        elif len(new_nodes) == 1:
            apply(new_nodes[0], tags)


def repair_studio_video_boundaries(graph: Graph) -> None:
    """Restore links hidden by cyclic editor subgraph boundaries."""
    dual_branches: list[tuple[Node, str]] = []
    for selector in _h3_tagged(graph, "select/dual"):
        for _name, source_id, _slot in selector.links():
            source = graph.get(source_id)
            if source is None:
                continue
            for role in ("dual/pass1", "dual/pass2"):
                if f"[h3s:{role}]" in source.title.lower():
                    dual_branches.append((source, role))
    if dual_branches:
        for node in graph:
            for role in ("dual/pass1", "dual/pass2"):
                node.title = node.title.replace(f"[H3S:{role}]", "").strip()
        for source, role in dual_branches:
            source.title = f"{source.title} [H3S:{role}]".strip()
            if "[h3s:clean-vram]" in source.title.lower():
                links = list(source.links())
                if len(links) == 1:
                    upstream = graph.get(links[0][1])
                    if upstream is not None:
                        upstream.title = f"{upstream.title} [H3S:{role}]".strip()

    none = _h3_tagged(graph, "interpolation/none")
    post_grade = _h3_tagged(graph, "post-grade")
    source = post_grade[0] if post_grade else (none[0] if none else None)
    if source is None:
        return

    for value in ("film", "rife", "gmfss"):
        for node in _h3_tagged(graph, f"interpolation/{value}"):
            for name in _IMAGE_INPUTS:
                if name in node.input_types:
                    node.inputs[name] = [source.id, 0]
                    break

    for selector in _h3_tagged(graph, "select/interpolation"):
        sources = [
            graph.get(upstream)
            for name, upstream, _slot in selector.links()
            if name.startswith("any_")
        ]
        if any(
            candidate is not None
            and "[h3s:interpolation/none]" in candidate.title.lower()
            for candidate in sources
        ):
            continue
        for index in range(1, 10):
            name = f"any_{index:02d}"
            if name not in selector.inputs:
                selector.inputs[name] = [source.id, 0]
                break


# --- the patch -------------------------------------------------------------


class _Patch:
    """One workflow being fitted to one config."""

    def __init__(
        self,
        workflow: dict[str, Any],
        config: GenerationConfig,
        *,
        output_tag: str,
        schemas: Schemas,
        contract_workflow: dict[str, Any] | None = None,
    ) -> None:
        self.config = config
        self.output_tag = output_tag
        self.schemas = schemas
        self.graph = read(workflow, widget_names=schemas.widget_names)
        if contract_workflow is not None:
            restore_studio_contract(
                self.graph,
                read(contract_workflow, widget_names=schemas.widget_names),
            )
        self.roles = R.resolve(self.graph)
        self.minted = 0
        missing = self.roles.missing()
        if missing:
            raise WorkflowError(
                "this workflow is missing "
                + ", ".join(sorted(missing))
                + " — the lab cannot tell which node does that job. Tag the node's title "
                "(for example MS_ROLE:sampler) or check `h3lab check`."
            )

    # -- access

    def node(self, role: str) -> Node | None:
        return self.roles.node(self.graph, role)

    def need(self, role: str) -> Node:
        node = self.node(role)
        if node is None:
            raise WorkflowError(f"this workflow has no {role.replace('_', ' ')}")
        return node

    def value_of(self, role: str, default: Any) -> Any:
        node = self.node(role)
        if node is None:
            return default
        value = node.inputs.get("value")
        return default if value is None or is_link(value) else value

    # -- writing

    def is_studio(self) -> bool:
        node = self.node(R.CONDITIONING)
        return node is not None and node.class_type == STUDIO_CLASS

    def driven_by_studio(self, node: Node | None, name: str) -> bool:
        """True when *name* is already a link from MiniMaxH3Studio.

        Studio owns those widgets. Replacing the link with a literal would disconnect
        the engine from the API the run is supposed to speak.
        """
        if node is None or not self.is_studio():
            return False
        studio = self.need(R.CONDITIONING)
        value = node.inputs.get(name)
        return is_link(value) and str(value[0]) == studio.id

    def accepts(self, node: Node, name: str) -> bool:
        """Does this node have an input called *name*?

        A dynamic input counts either way round: the saved node carries
        `ref_images.ref_image_0` where the schema declares `ref_images`.
        """
        if name in node.inputs or name in node.input_types:
            return True
        if any(key.startswith(f"{name}.") for key in node.inputs):
            return True
        schema = self.schemas.get(node.class_type)
        if schema is not None:
            return schema.knows(name)
        static = N.WIDGET_ORDER.get(node.class_type)
        if static:
            return name in static
        # Nothing authoritative to check against; ComfyUI is the judge.
        return not self.schemas

    def set(self, node: Node | None, name: str, value: Any) -> None:
        """Write a literal, replacing whatever the editor had wired into that input."""
        if node is None or self.driven_by_studio(node, name):
            return
        node.inputs[name] = value

    def set_known(self, node: Node | None, values: dict[str, Any]) -> None:
        """Write only the inputs this node actually has."""
        if node is None:
            return
        for name, value in values.items():
            if self.driven_by_studio(node, name):
                continue
            if self.accepts(node, name):
                node.inputs[name] = value

    def set_first(self, node: Node | None, names: Sequence[str], value: Any) -> bool:
        """Write to the first of *names* the node knows. Node packs rename widgets."""
        if node is None:
            return False
        for name in names:
            if name in node.inputs:
                if self.driven_by_studio(node, name):
                    return True
                node.inputs[name] = value
                return True
        for name in names:
            if self.accepts(node, name):
                if self.driven_by_studio(node, name):
                    return True
                node.inputs[name] = value
                return True
        return False

    def connect(self, target: Node | None, name: str, source: Node | None, slot: int = 0) -> None:
        if target is None or source is None:
            return
        target.inputs[name] = [source.id, slot]

    def enable(self, role: str, wanted: bool, *, cut: bool = False) -> Node | None:
        """State whether this run uses the node playing *role*."""
        node = self.node(role)
        if node is None:
            return None
        node.mode = ALWAYS if wanted else (MUTED if cut else BYPASSED)
        return node

    def wake_settings(self, node: Node | None, *, ignore: Sequence[str] = (), depth: int = 4) -> None:
        """Bring the values a switched-on node reads on with it.

        A template parks a whole group off at once: RIFE and the node holding the frame rate
        it should resample to. Switching RIFE on and leaving that behind submits a graph that
        interpolates to whatever ComfyUI defaults to. The picture inputs are excluded because
        the lab decides where those come from.
        """
        if node is None or depth <= 0:
            return
        for name, source, _slot in node.links():
            if name in ignore:
                continue
            upstream = self.graph.get(source)
            if upstream is None or not upstream.disabled:
                continue
            upstream.mode = ALWAYS
            self.wake_settings(upstream, depth=depth - 1)

    def mint(self, node_id: str, class_type: str, output_types: tuple[str, ...]) -> Node:
        node = self.graph.get(node_id)
        if node is None:
            node = self.graph.add(
                Node(id=node_id, class_type=class_type, inputs={}, output_types=output_types)
            )
            self.minted += 1
        node.mode = ALWAYS
        return node

    # -- the run

    def build(self) -> Prompt:
        if self.is_studio():
            self.wire_studio()
        self.wire_scalars()
        self.wire_schedule()
        self.wire_mode()
        self.wire_model_chain()
        self.wire_video_path()
        self.thin()
        self.keep_only_what_the_output_needs()
        prompt = self.graph.prompt()
        self.schemas.fill_defaults(prompt)
        return prompt

    def build_studio_source(self) -> Prompt:
        if not self.is_studio():
            return self.build()
        self.wire_studio()
        self.wire_studio_scalars()
        self.wire_studio_model_chain()
        self.repair_studio_video_boundaries()
        self.retain_studio_graph()
        prompt = self.graph.prompt()
        self.schemas.fill_defaults(prompt)
        return prompt

    def wire_studio(self) -> None:
        """Write the MiniMaxH3Studio API. Engine nodes stay linked to its outputs."""
        config = self.config
        studio = self.need(R.CONDITIONING)
        references = {
            "images": list(config.ref_images),
            "videos": list(config.ref_videos),
            "video_audios": list(config.ref_video_audios),
            "audios": list(config.ref_audios),
        }
        mapped = {
            "mode": STUDIO_MODES[config.mode],
            "prompt": config.prompt,
            "duration": config.duration_s,
            "aspect_ratio": config.aspect_ratio or DEFAULT_ASPECT,
            "megapixels": config.mp,
            "ref_image_size": config.ref_image_size,
            "first_frame": config.first_frame,
            "last_frame": config.last_frame,
            "references": json.dumps(references, separators=(",", ":")),
            "steps": config.effective_steps,
            "turbo": config.turbo,
            "turbo_lora": config.turbo_lora_file or STUDIO_TURBO_NONE,
            "scheduler": config.scheduler,
            "sampler_name": config.sampler,
            "cache": config.cache_active,
            "upscale_ltx": False,
            "upscale_rtx": config.upscaler,
            "seed_mode": "fixed",
            "seed": config.seed,
            "interpolation": STUDIO_INTERP.get(config.interp, config.interp),
            "clean_vram": config.clean_vram,
            "sol_attn": config.sol_attn,
            # An empty lab run must not inherit the template's storyboard.
            "guides": _studio_widget_value("guides", config.widgets.get("guides", "[]")),
        }
        extras = {
            name: _studio_widget_value(name, value)
            for name, value in config.widgets.items()
            if name not in mapped
        }
        # seed_mode and upscale_ltx have lab defaults but live only on the studio node.
        for name in ("seed_mode", "upscale_ltx"):
            if name in extras:
                mapped[name] = extras[name]
        # First-class config fields win; extras fill every other studio widget so a new
        # API knob does not need a lab mapping to reach the graph.
        self.set_known(studio, {**extras, **mapped})

    # -- scalars

    def wire_scalars(self) -> None:
        config = self.config
        conditioning = self.need(R.CONDITIONING)
        self.set(conditioning, "prompt", config.prompt)

        scheduler = self.need(R.SCHEDULER)
        self.set(scheduler, "scheduler", config.scheduler)
        # A literal replaces whatever step plumbing the editor used, so the run's step count
        # is the one recorded in the config and the plumbing prunes itself away.
        self.set(scheduler, "steps", config.effective_steps)
        self.set(self.node(R.SAMPLER_SELECT), "sampler_name", config.sampler)

        noise = self.node(R.NOISE)
        if noise is not None and self.accepts(noise, "noise_seed"):
            self.set(noise, "noise_seed", config.seed)
        self.set_first(self.node(R.SEED), ("seed",), config.seed)

        resolution = self.node(R.RESOLUTION)
        self.set_known(
            resolution,
            {
                "aspect_ratio": config.aspect_ratio or DEFAULT_ASPECT,
                "megapixels": config.mp,
            },
        )
        # Duration feeds the frame-count maths the template owns, so it is written to the
        # primitive rather than onto the conditioning's `length`.
        self.set_first(self.node(R.DURATION), ("value",), config.duration_s)

        video = self.need(R.VIDEO_OUT)
        self.set_known(
            video,
            {
                "filename_prefix": output_filename_prefix(self.output_tag),
                "frame_rate": self.frame_rate(),
                "trim_to_audio": False,
            },
        )

    def wire_studio_scalars(self) -> None:
        config = self.config
        conditioning = self.need(R.CONDITIONING)
        self.set(conditioning, "prompt", config.prompt)

        scheduler = self.need(R.SCHEDULER)
        self.set(scheduler, "scheduler", config.scheduler)
        self.set(scheduler, "steps", config.effective_steps)
        self.set(self.node(R.SAMPLER_SELECT), "sampler_name", config.sampler)

        noise = self.node(R.NOISE)
        if noise is not None and self.accepts(noise, "noise_seed"):
            self.set(noise, "noise_seed", config.seed)
        self.set_first(self.node(R.SEED), ("seed",), config.seed)

        self.set_known(
            self.node(R.RESOLUTION),
            {
                "aspect_ratio": config.aspect_ratio or DEFAULT_ASPECT,
                "megapixels": config.mp,
            },
        )
        self.set_first(self.node(R.DURATION), ("value",), config.duration_s)
        self.set_known(
            self.need(R.VIDEO_OUT),
            {
                "filename_prefix": output_filename_prefix(self.output_tag),
                "trim_to_audio": False,
            },
        )

    def frame_rate(self) -> Any:
        """What to tell the muxer, given how many frames the interpolator will hand it.

        RIFE resamples to a target rate it is told, so the video node is told the same
        number. FILM multiplies the frames it is given, so the rate multiplies with them —
        writing the base rate instead would produce a correct file that plays at half speed.
        """
        if self.config.interp == "rife":
            return self.value_of(R.INTERP_FPS, DEFAULT_INTERP_FPS)
        base = self.value_of(R.BASE_FPS, DEFAULT_BASE_FPS)
        if self.config.interp == "film":
            return base * FILM_MULTIPLIER
        if self.config.interp == "gmfss":
            return base * GMFSS_MULTIPLIER
        return base

    def wire_schedule(self) -> None:
        """The configured step count is the complete primary sampling schedule."""
        sampler = self.need(R.SAMPLER)
        current = sampler.inputs.get("sigmas")
        seen: set[str] = set()
        while is_link(current):
            node_id = str(current[0])
            if node_id in seen:
                break
            seen.add(node_id)
            source = self.graph.get(node_id)
            if source is None:
                break
            if source.class_type == "SplitSigmas":
                source.mode = BYPASSED
            current = source.inputs.get("sigmas")

    # -- media

    def wire_mode(self) -> None:
        if self.is_studio():
            return
        if self.config.mode == "r2v":
            self.wire_references()
        elif self.config.mode == "t2v":
            self.wire_text_only()
        else:
            self.wire_keyframes()

    def _clear_refs(self) -> None:
        conditioning = self.need(R.CONDITIONING)
        for name in list(conditioning.inputs):
            if name.split(".", 1)[0] in {family for family, _, _, _ in REF_FAMILIES}:
                del conditioning.inputs[name]

    def wire_keyframes(self) -> None:
        conditioning = self.need(R.CONDITIONING)
        self._clear_refs()

        first = self.node(R.FIRST_FRAME)
        if first is None:
            raise WorkflowError(
                "this workflow has no first-frame loader, so it cannot run a first/last "
                "frame generation"
            )
        first.mode = ALWAYS
        self.set_first(first, _MEDIA_WIDGETS, _basename(self.config.first_frame))
        self.feed(conditioning, "first_frame", first)

        last = self.node(R.LAST_FRAME)
        if self.config.last_frame and last is not None:
            last.mode = ALWAYS
            self.set_first(last, _MEDIA_WIDGETS, _basename(self.config.last_frame))
            self.feed(conditioning, "last_frame", last)
        else:
            conditioning.inputs.pop("last_frame", None)
            if last is not None:
                last.mode = MUTED

    def wire_text_only(self) -> None:
        conditioning = self.need(R.CONDITIONING)
        self._clear_refs()
        for name in ("first_frame", "last_frame"):
            conditioning.inputs.pop(name, None)
        for role in (R.FIRST_FRAME, R.LAST_FRAME):
            node = self.node(role)
            if node is not None:
                node.mode = MUTED

    def wire_references(self) -> None:
        config = self.config
        conditioning = self.need(R.CONDITIONING)
        if not self.accepts(conditioning, "ref_images"):
            raise WorkflowError(
                f"the conditioning node in this workflow ({conditioning.class_type}) takes no "
                "reference images, so it cannot run a reference generation"
            )
        for name in ("first_frame", "last_frame"):
            conditioning.inputs.pop(name, None)
        for role in (R.FIRST_FRAME, R.LAST_FRAME):
            node = self.node(role)
            if node is not None and node.id not in self._ref_sources():
                node.mode = MUTED

        if self.accepts(conditioning, "audio_vae"):
            self.connect(conditioning, "audio_vae", self.node(R.AUDIO_VAE))
        self.set_known(conditioning, {"ref_image_size": config.ref_image_size})

        video_audios = list(config.ref_video_audios[:MAX_REF_VIDEOS])
        for family, prefix, item, limit in REF_FAMILIES:
            if family == "ref_video_audios":
                continue
            names = list(getattr(config, family)[:limit])
            self.wire_ref_family(conditioning, family, prefix, item, names)
            if family == "ref_videos":
                self.wire_video_audio(conditioning, len(names), video_audios)

    def _ref_sources(self) -> set[str]:
        conditioning = self.need(R.CONDITIONING)
        found: set[str] = set()
        for name, value in conditioning.inputs.items():
            if name.split(".", 1)[0] in {family for family, _, _, _ in REF_FAMILIES} and is_link(
                value
            ):
                found.add(str(value[0]))
                found.update(node.id for node in R.ancestors(self.graph, str(value[0])))
        return found

    def wire_ref_family(
        self,
        conditioning: Node,
        family: str,
        prefix: str,
        item: str,
        names: list[str],
    ) -> None:
        for index in range(self.slot_count(conditioning, prefix, item, len(names))):
            slot = f"{prefix}.{item}_{index}"
            name = names[index] if index < len(names) else ""
            loaders = self.loaders_for(conditioning, slot, family)
            if not name:
                conditioning.inputs.pop(slot, None)
                for loader in loaders:
                    loader.mode = MUTED
                continue
            if loaders:
                for loader in loaders:
                    loader.mode = ALWAYS
                self.set_first(loaders[-1], _MEDIA_WIDGETS, _basename(name))
            else:
                self.mint_ref_chain(conditioning, slot, family, index, name)

    def mint_ref_chain(
        self, conditioning: Node, slot: str, family: str, index: int, name: str
    ) -> None:
        """Supply a loader the template does not have — or has left unwired.

        A run with more references than the workflow has slots still has to run, and a slot
        whose loader lost its link in the editor is the same problem from the other end.
        """
        class_type, outputs = _MINTED[family]
        loader = self.mint(f"h3:{family}_{index}", class_type, outputs)
        self.set_first(loader, _MEDIA_WIDGETS, _basename(name))
        if family != "ref_videos":
            self.connect(conditioning, slot, loader)
            return
        # A reference video reaches the conditioning as frames, never as a video.
        components = self.components_for(conditioning, slot, index)
        self.connect(components, "video", loader)
        self.connect(conditioning, slot, components)

    def components_for(self, conditioning: Node, slot: str, index: int) -> Node:
        current = conditioning.inputs.get(slot)
        if is_link(current):
            existing = self.graph.get(str(current[0]))
            if existing is not None and existing.class_type == "GetVideoComponents":
                existing.mode = ALWAYS
                return existing
        return self.mint(
            f"h3:ref_video_components_{index}",
            "GetVideoComponents",
            ("IMAGE", "AUDIO", "FLOAT", "INT"),
        )

    def wire_video_audio(
        self, conditioning: Node, video_count: int, overrides: list[str]
    ) -> None:
        """A reference video's soundtrack, unless the run supplies a separate file."""
        slots = self.slot_count(
            conditioning, "ref_video_audios", "ref_video_audio", max(video_count, len(overrides))
        )
        for index in range(slots):
            slot = f"ref_video_audios.ref_video_audio_{index}"
            override = overrides[index] if index < len(overrides) else ""
            if override:
                loaders = [
                    node
                    for node in self.loaders_for(conditioning, slot, "ref_video_audios")
                    if node.class_type == "LoadAudio"
                ]
                if loaders:
                    for loader in loaders:
                        loader.mode = ALWAYS
                    self.set_first(loaders[-1], _MEDIA_WIDGETS, _basename(override))
                else:
                    self.mint_ref_chain(
                        conditioning, slot, "ref_video_audios", index, override
                    )
            elif index >= video_count:
                conditioning.inputs.pop(slot, None)

    def slot_count(self, conditioning: Node, prefix: str, item: str, wanted: int) -> int:
        existing = 0
        while f"{prefix}.{item}_{existing}" in conditioning.inputs:
            existing += 1
        return max(existing, wanted)

    def loaders_for(self, conditioning: Node, slot: str, family: str) -> list[Node]:
        """The chain behind one reference slot: everything up to and including the loader.

        The loader comes last, because that is the node the filename belongs on. Whatever
        sits between it and the conditioning (a `GetVideoComponents`, a resize) has to come
        alive with it.
        """
        value = conditioning.inputs.get(slot)
        if not is_link(value):
            return []
        source = self.graph.get(str(value[0]))
        if source is None:
            return []
        chain = [source, *R.ancestors(self.graph, source.id)]
        wanted = _LOADER_CLASSES[family]
        found = [index for index, node in enumerate(chain) if node.class_type in wanted]
        if not found:
            return []
        return chain[: found[-1] + 1]

    def feed(self, target: Node, name: str, source: Node) -> None:
        """Make sure *target.name* is fed by *source*, through whatever sits between them."""
        current = target.inputs.get(name)
        reachable = {node.id for node in R.descendants(self.graph, source.id)} | {source.id}
        if is_link(current) and str(current[0]) in reachable:
            return
        tail = source
        while True:
            consumers = [
                node for node, _name, _slot in self.graph.consumers(tail.id) if node.id != target.id
            ]
            if len(consumers) != 1:
                break
            tail = consumers[0]
        self.connect(target, name, tail)

    # -- model chain

    def wire_model_chain(self) -> None:
        config = self.config
        loader = self.pick_model_loader()
        self.set_first(
            loader,
            ("unet_name", "model_name", "ckpt_name", "clip_name", "base_model"),
            resolve_model_filename(config.diffusion_model),
        )

        turbo = self.enable(R.TURBO_LORA, config.turbo)
        if config.turbo:
            if turbo is None:
                raise WorkflowError(
                    "this workflow has no turbo LoRA node, so it cannot run with turbo on"
                )
            named = self.set_first(turbo, ("lora_name", "lora"), config.turbo_lora_file)
            strength = self.set_first(
                turbo,
                ("strength", "strength_model", "lora_strength"),
                config.turbo_lora_strength,
            )
            if not (named and strength):
                raise WorkflowError(
                    f"the turbo LoRA node ({turbo.class_type}) has no input for the LoRA file "
                    "or its strength, so the lab cannot choose one"
                )

        # The optional LoRA slot is never part of a benchmark. Studio's remaining
        # LoraLoaderModelOnly is the reference LoRA the engine needs, so leave it.
        if not self.is_studio():
            self.enable(R.OPTIONAL_LORA, False)

        attention = config_attention(config)
        for node in _h3_tagged(self.graph, "attn/sol"):
            node.mode = ALWAYS if attention == "sol" else BYPASSED
        for node in _h3_tagged(self.graph, "attn/comfy-kitchen"):
            node.mode = ALWAYS if attention == "comfy_kitchen" else BYPASSED
        sol = self.enable(R.SOL_ATTN, attention == "sol")
        if attention == "sol":
            self.set_known(sol, sol_widgets(config))

        wanted_cache = R.CACHE_ROLES.get(config.cache) if config.cache_active else None
        if (
            wanted_cache
            and self.node(wanted_cache) is None
            and self.is_studio()
            and self.node(R.CACHE_SPECTRUM) is not None
        ):
            wanted_cache = R.CACHE_SPECTRUM
        for name, role in R.CACHE_ROLES.items():
            node = self.enable(role, role == wanted_cache)
            if role == wanted_cache:
                if node is None:
                    raise WorkflowError(
                        f"this workflow has no {name} cache node, so it cannot run with that "
                        "cache selected"
                    )
                self.set_known(node, cache_widgets(config))

    def wire_studio_model_chain(self) -> None:
        config = self.config
        loader = self.pick_model_loader()
        self.set_first(
            loader,
            ("unet_name", "model_name", "ckpt_name", "clip_name", "base_model"),
            resolve_model_filename(config.diffusion_model),
        )

        turbo = self.node(R.TURBO_LORA)
        if config.turbo and turbo is not None:
            self.set_first(turbo, ("lora_name", "lora"), config.turbo_lora_file)
            self.set_first(
                turbo,
                ("strength", "strength_model", "lora_strength"),
                config.turbo_lora_strength,
            )

        self.set_known(self.node(R.SOL_ATTN), sol_widgets(config))

        cache_classes = {
            "spectrum": "SpectrumApplyMiniMaxH3",
            "easy": "EasyCache",
            "h3": "UC_MiniMaxH3Cache",
        }
        wanted = config.cache if config.cache != "none" else "spectrum"
        selected_type = cache_classes[wanted]
        selected = [
            node
            for node in self.graph
            if node.class_type == selected_type
        ]
        if not selected and self.is_studio():
            selected_type = cache_classes["spectrum"]
            selected = [
                node for node in self.graph
                if node.class_type == selected_type
            ]
        if config.cache_active and not selected:
            raise WorkflowError(
                f"this workflow has no {wanted} cache node, so it cannot run with that "
                "cache selected"
            )
        cache_types = set(cache_classes.values())
        for node in list(self.graph):
            if node.class_type not in cache_types:
                continue
            if node.class_type != selected_type:
                self.drop(node, pass_through=True)
            else:
                self.set_known(node, cache_widgets(config))

    def repair_studio_video_boundaries(self) -> None:
        repair_studio_video_boundaries(self.graph)

    def retain_studio_graph(self) -> None:
        video = self.need(R.VIDEO_OUT)
        keep = {video.id, *(node.id for node in R.ancestors(self.graph, video.id))}
        for node in self.graph:
            if "[h3s:" not in node.title.lower():
                continue
            keep.add(node.id)
            keep.update(parent.id for parent in R.ancestors(self.graph, node.id))
        for node_id in list(self.graph.nodes):
            if node_id not in keep:
                self.graph.remove(node_id)

    def pick_model_loader(self) -> Node:
        gguf = self.node(R.GGUF_LOADER)
        plain = self.node(R.DIFFUSION_LOADER)
        if plain is None and gguf is None:
            raise WorkflowError("this workflow has no diffusion model loader")
        if self.config.uses_gguf:
            if gguf is None:
                raise WorkflowError(
                    f"{self.config.diffusion_model} needs a GGUF loader and this workflow has "
                    "none"
                )
            self.swap(gguf, plain)
            self.swap(self.node(R.GGUF_CLIP_LOADER), self.node(R.CLIP_LOADER))
            return gguf
        self.swap(plain, gguf)
        self.swap(self.node(R.CLIP_LOADER), self.node(R.GGUF_CLIP_LOADER))
        assert plain is not None
        plain.mode = ALWAYS
        return plain

    def swap(self, keep: Node | None, drop: Node | None) -> None:
        """Use *keep* wherever the workflow used *drop*.

        A template wires one loader into the chain and parks the alternative beside it. Which
        one is wired is the template's business, so the chosen node inherits the other's
        consumers rather than assuming it already has them.
        """
        if keep is None:
            return
        keep.mode = ALWAYS
        if drop is None or drop.id == keep.id:
            return
        for consumer, name, slot in self.graph.consumers(drop.id):
            consumer.inputs[name] = [keep.id, slot]
        drop.mode = MUTED

    # -- video path

    def wire_video_path(self) -> None:
        config = self.config
        self.enable(R.CLEAN_VRAM, config.clean_vram)
        self.enable(R.CLEAN_TEXT_ENCODER, config.clean_vram)

        rife = self.enable(R.RIFE, config.interp == "rife")
        film = self.enable(R.FILM, config.interp == "film")
        gmfss = self.enable(R.GMFSS, config.interp == "gmfss")
        self.enable(R.FILM_LOADER, config.interp == "film")
        if config.interp == "film" and film is not None:
            self.set_known(film, {"multiplier": FILM_MULTIPLIER})

        chosen = {"rife": rife, "film": film, "gmfss": gmfss}.get(config.interp)
        if config.interp != "off" and chosen is None:
            raise WorkflowError(
                f"this workflow has no {config.interp.upper()} node, so it cannot interpolate"
            )

        grade_enabled = bool(config.widgets.get("post_grade", False))
        grades = _h3_tagged(self.graph, "post-grade")
        for node in grades:
            node.mode = ALWAYS if grade_enabled else BYPASSED
        if grade_enabled and not grades:
            raise WorkflowError("this workflow has no post-grade node")

        ltx_enabled = bool(config.widgets.get("upscale_ltx", False))
        ltx_nodes = _h3_tagged(self.graph, "upscale/ltx/on")
        for node in ltx_nodes:
            node.mode = ALWAYS if ltx_enabled else BYPASSED
        if ltx_enabled and not ltx_nodes:
            raise WorkflowError("this workflow has no LTX upscaler")
        if ltx_enabled:
            self.wake_settings(ltx_nodes[0], depth=16)

        # The template keeps both interpolators parked beside the picture path with only one
        # of them wired in. Which one a run uses is a benchmark axis, so the lab places it.
        after = self.need(R.VAE_DECODE)
        if ltx_enabled:
            after = ltx_nodes[0]
        if chosen is not None:
            self.wake_settings(chosen, ignore=_IMAGE_INPUTS)
            self.put_on_image_path(chosen, after=after)
            after = chosen
        else:
            self.skip_parked_interpolation()

        upscaler = self.enable(R.UPSCALER, config.upscaler)
        if upscaler is not None and config.upscaler:
            self.wake_settings(upscaler, ignore=_IMAGE_INPUTS)
            self.put_on_image_path(upscaler, after=after)
            after = upscaler

        if not self.reaches_output(after):
            # Parked upscale / grade / interp subgraphs often lose their boundary
            # image link when flattened. The muxer still has to see the pictures.
            self.connect(self.need(R.VIDEO_OUT), "images", after)

        # Some Studio workflows contain several cleanup points. The tag is the shared
        # contract; role resolution intentionally picks only one node per role.
        for node in _h3_tagged(self.graph, "clean-vram"):
            node.mode = ALWAYS if config.clean_vram else BYPASSED

        # Video-only output. MiniMax audio latents frequently contain NaN or +Inf, which makes
        # the ffmpeg AAC mux fail after the picture track is already written — losing the whole
        # file. De-rope still needs pass one's decoded audio as its second-pass init.
        derope = bool(config.widgets.get("derope", False))
        self.enable(R.VAE_DECODE_AUDIO, derope, cut=not derope)
        self.need(R.VIDEO_OUT).inputs.pop("audio", None)

    def reaches_output(self, node: Node) -> bool:
        video = self.node(R.VIDEO_OUT)
        if video is None:
            return False
        if node.id == video.id:
            return True
        return any(found.id == video.id for found in R.descendants(self.graph, node.id))

    def skip_parked_interpolation(self) -> None:
        """When no interpolator runs, do not let their switch eat the picture path.

        The unified graph parks RIFE/FILM/GMFSS behind an Any Switch. Thinning those
        nodes leaves the switch holding only the fps primitive, and everything upstream
        — including MiniMaxH3Studio — is then pruned as unused.
        """
        source: Node | None = None
        switches: list[Node] = []
        interpolators = {
            "RIFEInterpolation",
            "RIFE VFI",
            "FrameInterpolate",
            "GMFSS Fortuna VFI",
        }
        for node in self.graph:
            if node.class_type not in interpolators:
                continue
            for name in _IMAGE_INPUTS:
                value = node.inputs.get(name)
                if is_link(value):
                    found = self.graph.get(str(value[0]))
                    if found is not None:
                        source = found
                    break
            for consumer, _name, _slot in self.graph.consumers(node.id):
                if "Switch" in consumer.class_type:
                    switches.append(consumer)
        if source is None:
            return
        seen: set[str] = set()
        for switch in switches:
            if switch.id in seen:
                continue
            seen.add(switch.id)
            for consumer, name, slot in self.graph.consumers(switch.id):
                if slot == 0:
                    consumer.inputs[name] = [source.id, 0]

    def put_on_image_path(self, node: Node, *, after: Node) -> None:
        """Splice *node* in immediately downstream of *after*, if it is not already in.

        Everything that read the pictures from *after* reads them from *node* instead. Nodes
        the template left switched off stay in the path here and are thinned out later, so
        the order the template chose survives.

        Always write the picture input. Unified interpolators reach the muxer through a
        switch but lose their subgraph image link when flattened.
        """
        self.set_first(node, ("images", "image", "frames"), [after.id, 0])
        if self.reaches_output(node):
            return
        target: tuple[Node, str] | None = None
        for consumer, name, slot in self.graph.consumers(after.id):
            if slot == 0 and consumer.id != node.id and self.reaches_output(consumer):
                target = (consumer, name)
                break
        if target is None:
            video = self.node(R.VIDEO_OUT)
            self.connect(video, "images", node)
            return
        consumer, name = target
        consumer.inputs[name] = [node.id, 0]

    # -- thinning and pruning

    def thin(self) -> None:
        """Remove every switched-off node, reconnecting what depended on it.

        A bypassed node hands its consumers whatever fed it, matched by slot type — the rule
        ComfyUI itself uses. A muted node hands them nothing.
        """
        for node in list(self.graph):
            if node.mode == BYPASSED:
                self.drop(node, pass_through=True)
            elif node.mode == MUTED:
                self.drop(node, pass_through=False)

    def drop(self, node: Node, *, pass_through: bool) -> None:
        for consumer, name, slot in self.graph.consumers(node.id):
            replacement = self.pass_through_source(node, slot) if pass_through else None
            if replacement is None:
                consumer.inputs.pop(name, None)
            else:
                consumer.inputs[name] = list(replacement)
        self.graph.remove(node.id)

    def pass_through_source(self, node: Node, slot: int) -> list[Any] | None:
        wanted = ""
        if slot < len(node.output_types):
            wanted = node.output_types[slot]
        if not wanted:
            wanted = self.schemas.output_type(node.class_type, slot)
        links = list(node.links())
        if wanted:
            for name, source, source_slot in links:
                if node.input_types.get(name) == wanted:
                    return [source, source_slot]
        # A wildcard slot (`easy cleanGpuUsed`) declares no useful type; with one input there
        # is only one thing it could have been passing through.
        if len(links) == 1:
            return [links[0][1], links[0][2]]
        return None

    def keep_only_what_the_output_needs(self) -> None:
        """Drop everything the chosen output does not depend on.

        ComfyUI validates every output node in a prompt as a graph root, so a save node the
        run does not want fails the submission even though nothing reads from it.
        """
        video = self.node(R.VIDEO_OUT)
        if video is None:
            raise WorkflowError("this workflow has no video output node left after patching")
        if "images" not in video.inputs:
            raise WorkflowError(
                "nothing reaches the video output node; the image path in this workflow is "
                "broken"
            )
        keep = {video.id}
        queue: deque[str] = deque([video.id])
        while queue:
            node = self.graph.get(queue.popleft())
            if node is None:
                continue
            for _name, source, _slot in node.links():
                if source not in keep:
                    keep.add(source)
                    queue.append(source)
        for node_id in list(self.graph.nodes):
            if node_id not in keep:
                self.graph.remove(node_id)


# --- entry points ----------------------------------------------------------


def build(
    workflow: dict[str, Any],
    config: GenerationConfig,
    *,
    output_tag: str = "run",
    schemas: Schemas | None = None,
) -> tuple[Prompt, Graph, R.Roles]:
    """The prompt, plus the patched graph and roles behind it (for export and reports)."""
    patch = _Patch(
        workflow,
        config,
        output_tag=output_tag,
        schemas=schemas if schemas is not None else static_schemas(),
    )
    prompt = patch.build()
    return prompt, patch.graph, patch.roles


def build_studio_source(
    workflow: dict[str, Any],
    config: GenerationConfig,
    *,
    output_tag: str = "run",
    schemas: Schemas | None = None,
    contract_workflow: dict[str, Any] | None = None,
) -> tuple[Prompt, Graph, R.Roles]:
    patch = _Patch(
        workflow,
        config,
        output_tag=output_tag,
        schemas=schemas if schemas is not None else static_schemas(),
        contract_workflow=contract_workflow,
    )
    prompt = patch.build_studio_source()
    return prompt, patch.graph, patch.roles


def apply_config(
    workflow: dict[str, Any],
    config: GenerationConfig,
    *,
    output_tag: str = "run",
    schemas: Schemas | None = None,
) -> Prompt:
    """Build an executable prompt for exactly this configuration.

    *output_tag* only affects the output filename. It must never touch a sampling input,
    or two runs of the same configuration would stop being comparable.

    *schemas* is the installed ComfyUI's own description of its nodes. Without it the widget
    order saved in the workflow is trusted as-is, which is right for a graph the lab only
    inspects and not quite enough for one it submits.
    """
    prompt, _graph, _roles = build(
        workflow, config, output_tag=output_tag, schemas=schemas
    )
    return prompt


def missing_links(prompt: Prompt) -> list[str]:
    """Every input still pointing at an absent node. Should be empty after `apply_config`."""
    alive = set(prompt)
    problems: list[str] = []
    for node_id, node in prompt.items():
        for name, value in node["inputs"].items():
            if is_link(value) and value[0] not in alive:
                problems.append(f"{node_id}.{name} → {value[0]} (absent)")
    return sorted(problems)


def referenced_files(prompt: Prompt) -> list[str]:
    """Input media the prompt expects ComfyUI to already have."""
    found: list[str] = []
    for node in prompt.values():
        inputs = node.get("inputs") or {}
        for key in _MEDIA_WIDGETS:
            value = inputs.get(key)
            if isinstance(value, str) and value:
                found.append(value)
        if node.get("class_type") == STUDIO_CLASS:
            found.extend(_studio_media_names(inputs))
    return sorted(set(found))


def _studio_media_names(inputs: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("first_frame", "last_frame"):
        value = inputs.get(key)
        if isinstance(value, str) and value.strip():
            names.append(value)
    raw_refs = inputs.get("references")
    if isinstance(raw_refs, str) and raw_refs.strip():
        try:
            payload = json.loads(raw_refs)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            for group in payload.values():
                if isinstance(group, list):
                    names.extend(
                        name for name in group if isinstance(name, str) and name.strip()
                    )
    raw_guides = inputs.get("guides")
    if isinstance(raw_guides, str) and raw_guides.strip():
        try:
            clips = json.loads(raw_guides)
        except json.JSONDecodeError:
            clips = None
        if isinstance(clips, list):
            for clip in clips:
                if not isinstance(clip, dict):
                    continue
                for key in ("image", "audio"):
                    value = clip.get(key)
                    if isinstance(value, str) and value.strip():
                        names.append(value)
    return names


def describe(prompt: Prompt) -> dict[str, Any]:
    return {
        "nodes": len(prompt),
        "classes": sorted({node["class_type"] for node in prompt.values()}),
        "missing_links": missing_links(prompt),
        "files": referenced_files(prompt),
    }


def node_ids(prompt: Prompt) -> Iterable[str]:
    return prompt.keys()
