"""Finding the nodes that matter, in a workflow whose ids are not promises.

Every id in a saved workflow is an accident of how it was edited. Fold the pipeline into a
subgraph and node 1 becomes `169:1`; rebuild a branch and the numbers move again. So the lab
asks what a node *is* rather than where it sits, using, in order:

1. the title — `MS_INPUT_DURATION` and friends, the convention the templates already use,
   plus `MS_ROLE:NAME` as an explicit override for anything the guesses get wrong;
2. the class, when only one node of that class is in the graph;
3. the wiring — the VAE feeding the video decoder is the video VAE, whatever it is called;
4. the id the node had when the lab was written, as a last resort.

Nothing here mutates the graph. A role that cannot be found is reported, not invented, so
`h3lab check` can say which part of a workflow the lab no longer recognises.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from h3lab.comfy.workflow import Graph, Node

# --- role names ------------------------------------------------------------

DIFFUSION_LOADER = "diffusion_loader"
GGUF_LOADER = "gguf_loader"
CLIP_LOADER = "clip_loader"
GGUF_CLIP_LOADER = "gguf_clip_loader"
CONDITIONING = "conditioning"
VIDEO_VAE = "video_vae"
AUDIO_VAE = "audio_vae"

SCHEDULER = "scheduler"
SAMPLER_SELECT = "sampler_select"
GUIDER = "guider"
SAMPLER = "sampler"
NOISE = "noise"
SEED = "seed"

RESOLUTION = "resolution"
FRAME_COUNT = "frame_count"
DURATION = "duration"
BASE_FPS = "base_fps"
INTERP_FPS = "interp_fps"

FIRST_FRAME = "first_frame"
LAST_FRAME = "last_frame"

TURBO_LORA = "turbo_lora"
OPTIONAL_LORA = "optional_lora"
SOL_ATTN = "sol_attn"
SAGE_ATTN = "sage_attn"
SIGMA_SHIFT = "sigma_shift"
CACHE_SPECTRUM = "cache_spectrum"
CACHE_EASY = "cache_easy"
CACHE_H3 = "cache_h3"

VAE_DECODE = "vae_decode"
VAE_DECODE_AUDIO = "vae_decode_audio"
RIFE = "rife"
FILM = "film"
FILM_LOADER = "film_loader"
UPSCALER = "upscaler"
CLEAN_VRAM = "clean_vram"
CLEAN_TEXT_ENCODER = "clean_text_encoder"
VIDEO_OUT = "video_out"

# Roles the lab cannot build a prompt without.
ESSENTIAL: tuple[str, ...] = (
    DIFFUSION_LOADER,
    CONDITIONING,
    SCHEDULER,
    GUIDER,
    SAMPLER,
    VAE_DECODE,
    VIDEO_OUT,
)

CACHE_ROLES: dict[str, str] = {
    "spectrum": CACHE_SPECTRUM,
    "easy": CACHE_EASY,
    "h3": CACHE_H3,
}

# The one tag that means exactly what it says, for a workflow the guesses get wrong.
OVERRIDE_PREFIX = "MS_ROLE:"


# --- graph walking ---------------------------------------------------------


def ancestors(
    graph: Graph, node_id: str, *, input_name: str | None = None, depth: int = 24
) -> list[Node]:
    """Every node upstream of *node_id*, nearest first."""
    start = graph.get(node_id)
    if start is None:
        return []
    seen: set[str] = {start.id}
    found: list[Node] = []
    queue: deque[tuple[Node, int]] = deque()
    for name, source, _slot in start.links():
        if input_name is not None and name != input_name:
            continue
        node = graph.get(source)
        if node is not None and node.id not in seen:
            seen.add(node.id)
            queue.append((node, 1))
    while queue:
        node, distance = queue.popleft()
        found.append(node)
        if distance >= depth:
            continue
        for _name, source, _slot in node.links():
            upstream = graph.get(source)
            if upstream is not None and upstream.id not in seen:
                seen.add(upstream.id)
                queue.append((upstream, distance + 1))
    return found


def descendants(graph: Graph, node_id: str, *, depth: int = 24) -> list[Node]:
    """Every node downstream of *node_id*, nearest first."""
    seen: set[str] = {str(node_id)}
    found: list[Node] = []
    queue: deque[tuple[str, int]] = deque([(str(node_id), 0)])
    while queue:
        current, distance = queue.popleft()
        if distance >= depth:
            continue
        for node, _name, _slot in graph.consumers(current):
            if node.id in seen:
                continue
            seen.add(node.id)
            found.append(node)
            queue.append((node.id, distance + 1))
    return found


def branch_tail(graph: Graph, node_id: str) -> Node | None:
    """The last node of a straight run of single consumers starting at *node_id*."""
    current = graph.get(node_id)
    while current is not None:
        consumers = graph.consumers(current.id)
        if len(consumers) != 1:
            return current
        current = consumers[0][0]
    return None


def _first(nodes: Iterable[Node], classes: Sequence[str]) -> Node | None:
    wanted = set(classes)
    for node in nodes:
        if node.class_type in wanted:
            return node
    return None


# --- rules -----------------------------------------------------------------

Pick = Callable[[Graph, list[Node], dict[str, str]], "Node | None"]


@dataclass(frozen=True, slots=True)
class Rule:
    role: str
    classes: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    legacy: tuple[int, ...] = ()
    pick: Pick | None = None


def _by_id(graph: Graph, node_id: str | None) -> Node | None:
    return graph.get(node_id) if node_id else None


def _pick_video_vae(graph: Graph, candidates: list[Node], found: dict[str, str]) -> Node | None:
    decoder = _by_id(graph, found.get(VAE_DECODE))
    if decoder is not None:
        vae = _first(ancestors(graph, decoder.id, input_name="vae"), [n.class_type for n in candidates])
        if vae is not None:
            return vae
    conditioning = _by_id(graph, found.get(CONDITIONING))
    if conditioning is not None:
        return _first(ancestors(graph, conditioning.id, input_name="vae"), ("VAELoader",))
    return candidates[0] if len(candidates) == 1 else None


def _pick_audio_vae(graph: Graph, candidates: list[Node], found: dict[str, str]) -> Node | None:
    conditioning = _by_id(graph, found.get(CONDITIONING))
    if conditioning is not None:
        vae = _first(ancestors(graph, conditioning.id, input_name="audio_vae"), ("VAELoader",))
        if vae is not None:
            return vae
    decoder = _by_id(graph, found.get(VAE_DECODE_AUDIO))
    if decoder is not None:
        vae = _first(ancestors(graph, decoder.id, input_name="vae"), ("VAELoader",))
        if vae is not None:
            return vae
    video = found.get(VIDEO_VAE)
    rest = [node for node in candidates if node.id != video]
    return rest[0] if len(rest) == 1 else None


def _pick_first_frame(graph: Graph, candidates: list[Node], found: dict[str, str]) -> Node | None:
    conditioning = _by_id(graph, found.get(CONDITIONING))
    if conditioning is None or "first_frame" not in conditioning.inputs:
        return None
    return _first(
        ancestors(graph, conditioning.id, input_name="first_frame"),
        [node.class_type for node in candidates],
    )


def _pick_last_frame(graph: Graph, candidates: list[Node], found: dict[str, str]) -> Node | None:
    conditioning = _by_id(graph, found.get(CONDITIONING))
    if conditioning is None or "last_frame" not in conditioning.inputs:
        return None
    taken = found.get(FIRST_FRAME)
    return _first(
        [
            node
            for node in ancestors(graph, conditioning.id, input_name="last_frame")
            if node.id != taken
        ],
        [node.class_type for node in candidates],
    )


def _pick_frame_count(graph: Graph, candidates: list[Node], found: dict[str, str]) -> Node | None:
    conditioning = _by_id(graph, found.get(CONDITIONING))
    if conditioning is None:
        return None
    return _first(
        ancestors(graph, conditioning.id, input_name="length"),
        [node.class_type for node in candidates],
    )


def _through(graph: Graph, node: Node | None, input_name: str, classes: Sequence[str]) -> Node | None:
    if node is None:
        return None
    return _first(ancestors(graph, node.id, input_name=input_name), classes)


def _pick_duration(graph: Graph, candidates: list[Node], found: dict[str, str]) -> Node | None:
    """The frame count is duration × fps; `values.a` is the duration side of it."""
    expression = _by_id(graph, found.get(FRAME_COUNT))
    classes = [node.class_type for node in candidates]
    direct = _through(graph, expression, "values.a", classes)
    if direct is not None:
        return direct
    conditioning = _by_id(graph, found.get(CONDITIONING))
    return _through(graph, conditioning, "length", classes)


def _pick_base_fps(graph: Graph, candidates: list[Node], found: dict[str, str]) -> Node | None:
    expression = _by_id(graph, found.get(FRAME_COUNT))
    taken = {found.get(DURATION)}
    node = _through(graph, expression, "values.b", [n.class_type for n in candidates])
    return node if node is not None and node.id not in taken else None


def _pick_interp_fps(graph: Graph, candidates: list[Node], found: dict[str, str]) -> Node | None:
    rife = _by_id(graph, found.get(RIFE))
    taken = {found.get(DURATION), found.get(BASE_FPS)}
    node = _through(graph, rife, "target_fps", [n.class_type for n in candidates])
    return node if node is not None and node.id not in taken else None


def _pick_clean_text_encoder(
    graph: Graph, candidates: list[Node], found: dict[str, str]
) -> Node | None:
    conditioning = found.get(CONDITIONING)
    if conditioning is None:
        return None
    for node in candidates:
        if any(source == conditioning for _name, source, _slot in node.links()):
            return node
    return None


def _pick_clean_vram(graph: Graph, candidates: list[Node], found: dict[str, str]) -> Node | None:
    sampler = found.get(SAMPLER)
    taken = found.get(CLEAN_TEXT_ENCODER)
    for node in candidates:
        if node.id == taken:
            continue
        if any(source == sampler for _name, source, _slot in node.links()):
            return node
    rest = [node for node in candidates if node.id != taken]
    return rest[0] if len(rest) == 1 else None


def _pick_video_out(graph: Graph, candidates: list[Node], found: dict[str, str]) -> Node | None:
    live = [node for node in candidates if not node.disabled]
    return (live or candidates)[0] if candidates else None


# The order is the resolution order: a rule may use what earlier rules found.
RULES: tuple[Rule, ...] = (
    Rule(
        CONDITIONING,
        (
            "MiniMaxH3Studio",
            "MiniMaxH3ImageToVideo",
            "MiniMaxH3ReferenceToVideo",
            "MiniMaxH3TextToVideo",
        ),
        tags=("MS_INPUT_CONDITIONING",),
        legacy=(5,),
    ),
    Rule(SAMPLER, ("SamplerCustomAdvanced", "KSampler", "KSamplerAdvanced"), legacy=(10,)),
    Rule(GUIDER, ("BasicGuider", "CFGGuider"), legacy=(8,)),
    Rule(SCHEDULER, ("BasicScheduler",), tags=("MS_INPUT_STEPS",), legacy=(6,)),
    Rule(SAMPLER_SELECT, ("KSamplerSelect",), legacy=(7,)),
    Rule(NOISE, ("RandomNoise", "DisableNoise"), legacy=(119,)),
    Rule(SEED, ("Seed (rgthree)", "easy seed", "Seed"), legacy=(118, 212)),
    Rule(
        DIFFUSION_LOADER,
        ("UNETLoader", "OTUNetLoaderW8A8", "CheckpointLoaderSimple"),
        tags=("MS_INPUT_TRANSFORMER",),
        legacy=(1, 124),
    ),
    Rule(
        GGUF_LOADER,
        ("GGUFLoaderKJ", "UnetLoaderGGUF", "UnetLoaderGGUFAdvanced"),
        legacy=(130,),
    ),
    Rule(CLIP_LOADER, ("CLIPLoader", "CLIPLoaderKJ"), legacy=(2,)),
    Rule(GGUF_CLIP_LOADER, ("CLIPLoaderGGUF", "DualCLIPLoaderGGUF"), legacy=(131,)),
    Rule(VAE_DECODE, ("VAEDecode", "VAEDecodeTiled"), legacy=(125,)),
    Rule(VAE_DECODE_AUDIO, ("VAEDecodeAudio",), legacy=(12,)),
    Rule(VIDEO_VAE, ("VAELoader",), tags=("MS_VAE_VIDEO",), pick=_pick_video_vae, legacy=(3,)),
    Rule(AUDIO_VAE, ("VAELoader",), tags=("MS_VAE_AUDIO",), pick=_pick_audio_vae, legacy=(4,)),
    Rule(RESOLUTION, ("ResolutionSelector",), tags=("MS_INPUT_RESOLUTION",), legacy=(98,)),
    Rule(
        FRAME_COUNT,
        ("ComfyMathExpression", "MathExpression|pysssss"),
        tags=("MS_FRAME_COUNT",),
        pick=_pick_frame_count,
        legacy=(103,),
    ),
    Rule(
        DURATION,
        ("PrimitiveFloat", "PrimitiveInt"),
        tags=("MS_INPUT_DURATION",),
        pick=_pick_duration,
        legacy=(102,),
    ),
    Rule(
        RIFE,
        ("RIFEInterpolation", "RIFE VFI"),
        tags=("MS_INTERP_RIFE",),
        legacy=(96,),
    ),
    Rule(FILM, ("FrameInterpolate",), tags=("MS_INTERP_FILM",), legacy=(167,)),
    Rule(FILM_LOADER, ("FrameInterpolationModelLoader",), legacy=(166,)),
    Rule(
        BASE_FPS,
        ("PrimitiveFloat", "PrimitiveInt"),
        tags=("MS_INPUT_BASE_FPS",),
        pick=_pick_base_fps,
        legacy=(108,),
    ),
    Rule(
        INTERP_FPS,
        ("PrimitiveFloat", "PrimitiveInt"),
        tags=("MS_INPUT_INTERP_FPS",),
        pick=_pick_interp_fps,
        legacy=(95,),
    ),
    Rule(
        FIRST_FRAME,
        ("LoadImage", "LoadImageOutput"),
        tags=("MS_INPUT_FIRST_FRAME",),
        pick=_pick_first_frame,
        legacy=(20,),
    ),
    Rule(
        LAST_FRAME,
        ("LoadImage", "LoadImageOutput"),
        tags=("MS_INPUT_LAST_FRAME",),
        pick=_pick_last_frame,
        legacy=(145,),
    ),
    Rule(TURBO_LORA, ("MiniMaxH3TurboLoRA",), tags=("MS_TURBO_LORA",), legacy=(155,)),
    Rule(
        OPTIONAL_LORA,
        ("LoraLoaderModelOnly", "LoraLoader"),
        tags=("MS_OPTIONAL_LORA",),
        legacy=(148,),
    ),
    Rule(SOL_ATTN, ("SolAttnPatch",), legacy=(92,)),
    Rule(SAGE_ATTN, ("PathchSageAttentionKJ", "PatchSageAttentionKJ"), legacy=(91,)),
    Rule(SIGMA_SHIFT, ("MiniMaxH3SigmaShift", "ModelSamplingSD3"), legacy=(123,)),
    Rule(CACHE_SPECTRUM, ("SpectrumApplyMiniMaxH3",), tags=("MS_CACHE_1_SPECTRUM",), legacy=(122,)),
    Rule(CACHE_EASY, ("EasyCache",), tags=("MS_CACHE_2_EASYCACHE",), legacy=(15,)),
    Rule(CACHE_H3, ("UC_MiniMaxH3Cache",), tags=("MS_CACHE_3_H3",), legacy=(128,)),
    Rule(
        UPSCALER,
        ("RTXVideoSuperResolution", "ImageUpscaleWithModel"),
        tags=("MS_UPSCALER",),
        legacy=(111,),
    ),
    Rule(
        CLEAN_TEXT_ENCODER,
        ("easy cleanGpuUsed",),
        tags=("MS_CLEAN_TEXT_ENCODER",),
        pick=_pick_clean_text_encoder,
        legacy=(144,),
    ),
    Rule(
        CLEAN_VRAM,
        ("easy cleanGpuUsed",),
        tags=("MS_CLEAN_VRAM",),
        pick=_pick_clean_vram,
        legacy=(97,),
    ),
    Rule(
        VIDEO_OUT,
        ("VHS_VideoCombine", "SaveVideo", "SaveWEBM"),
        tags=("MS_OUTPUT_VIDEO",),
        pick=_pick_video_out,
        legacy=(110,),
    ),
)

ROLES: tuple[str, ...] = tuple(rule.role for rule in RULES)


# --- resolution ------------------------------------------------------------


@dataclass(slots=True)
class Roles:
    """Which node plays each part in one workflow."""

    found: dict[str, str] = field(default_factory=dict)
    how: dict[str, str] = field(default_factory=dict)
    ambiguous: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def __contains__(self, role: object) -> bool:
        return str(role) in self.found

    def id(self, role: str) -> str | None:
        return self.found.get(role)

    def node(self, graph: Graph, role: str) -> Node | None:
        node_id = self.found.get(role)
        return graph.get(node_id) if node_id else None

    def missing(self, roles: Iterable[str] = ESSENTIAL) -> list[str]:
        return [role for role in roles if role not in self.found]

    def report(self, graph: Graph) -> list[dict[str, object]]:
        """One row per role, for `h3lab check` and the API."""
        rows: list[dict[str, object]] = []
        for role in ROLES:
            node = self.node(graph, role)
            rows.append(
                {
                    "role": role,
                    "node": node.id if node else None,
                    "class_type": node.class_type if node else None,
                    "title": node.title if node else "",
                    "how": self.how.get(role, ""),
                    "essential": role in ESSENTIAL,
                    "ambiguous": list(self.ambiguous.get(role, ())),
                }
            )
        return rows


def _title_of(node: Node) -> str:
    return node.title.strip().upper().replace(" ", "_")


def _overrides(graph: Graph) -> dict[str, str]:
    """`MS_ROLE:DURATION` in a title beats every guess in this module."""
    found: dict[str, str] = {}
    for node in graph:
        title = _title_of(node)
        marker = title.find(OVERRIDE_PREFIX)
        if marker < 0:
            continue
        name = title[marker + len(OVERRIDE_PREFIX) :].split()[0].strip().lower()
        if name in ROLES and name not in found:
            found[name] = node.id
    return found


def _tagged(candidates: list[Node], tags: Sequence[str]) -> list[Node]:
    for tag in tags:
        exact = [node for node in candidates if _title_of(node) == tag]
        if len(exact) == 1:
            return exact
        partial = [node for node in candidates if tag in _title_of(node)]
        if len(partial) == 1:
            return partial
    return []


def resolve(graph: Graph) -> Roles:
    """Work out which node plays each role in *graph*."""
    roles = Roles()
    overrides = _overrides(graph)
    taken: set[str] = set(overrides.values())
    for role, node_id in overrides.items():
        roles.found[role] = node_id
        roles.how[role] = "title override"

    for rule in RULES:
        if rule.role in roles.found:
            continue
        candidates = [
            node
            for node in graph
            if node.class_type in rule.classes and node.id not in taken
        ]
        if not candidates:
            continue

        chosen: Node | None = None
        how = ""

        tagged = _tagged(candidates, rule.tags)
        if tagged:
            chosen, how = tagged[0], "title"
        elif rule.pick is not None:
            chosen = rule.pick(graph, candidates, roles.found)
            how = "wiring"
        elif len(candidates) == 1:
            chosen, how = candidates[0], "class"
        else:
            legacy = [node for node in candidates if node.local_id in rule.legacy]
            if len(legacy) == 1:
                chosen, how = legacy[0], "legacy id"
            else:
                live = [node for node in candidates if not node.disabled] or candidates
                chosen, how = live[0], "first of class"
                roles.ambiguous[rule.role] = tuple(node.id for node in candidates)

        # A rule with a `pick` is authoritative: when the wiring says this graph has no such
        # node, an id that once meant something is not evidence that it does.
        if chosen is None:
            continue
        roles.found[rule.role] = chosen.id
        roles.how[rule.role] = how
        taken.add(chosen.id)

    return roles
