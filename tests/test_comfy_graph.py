"""Graph patching, checked against the real workflow templates in the repository.

Nothing here names a node id. Ids move every time a workflow is edited; what a node *does*
is what the lab depends on, so that is what these tests assert.
"""

from __future__ import annotations

import pytest

from h3lab.comfy import roles as R
from h3lab.comfy.client import parse_combo
from h3lab.comfy.graph import (
    WorkflowError,
    apply_config,
    build,
    load_workflow,
    missing_links,
    output_filename_prefix,
    referenced_files,
)
from h3lab.comfy.presets import SOL, SPECTRUM, cache_problems, cache_widgets, sol_widgets
from h3lab.comfy.workflow import is_link, read

MODES = ("flf2v", "t2v", "r2v")


@pytest.fixture(scope="module")
def templates() -> dict[str, dict]:
    from tests.conftest import legacy_workflow_path

    return {mode: load_workflow(legacy_workflow_path(mode)) for mode in MODES}


@pytest.fixture(scope="module")
def flf2v_workflow(templates):
    return templates["flf2v"]


@pytest.fixture(scope="module")
def t2v_workflow(templates):
    return templates["t2v"]


@pytest.fixture(scope="module")
def r2v_workflow(templates):
    return templates["r2v"]


class Built:
    """A patched prompt, addressed by role instead of by id."""

    def __init__(self, workflow, config, **kwargs):
        self.prompt, self.graph, self.roles = build(workflow, config, **kwargs)

    def id(self, role: str) -> str | None:
        node_id = self.roles.id(role)
        return node_id if node_id in self.prompt else None

    def has(self, role: str) -> bool:
        return self.id(role) is not None

    def inputs(self, role: str) -> dict:
        node_id = self.id(role)
        assert node_id is not None, f"no {role} in the prompt"
        return self.prompt[node_id]["inputs"]

    def classes(self) -> set[str]:
        return {node["class_type"] for node in self.prompt.values()}

    def source_of(self, role: str, name: str) -> str | None:
        value = self.inputs(role).get(name)
        return str(value[0]) if is_link(value) else None

    def role_of(self, node_id: str | None) -> str | None:
        for role, found in self.roles.found.items():
            if found == node_id:
                return role
        return None

    def model_chain(self) -> list[str]:
        """The model path, as roles, from the loader to the scheduler."""
        order: list[str] = []
        node_id = self.source_of(R.SCHEDULER, "model")
        seen: set[str] = set()
        while node_id and node_id not in seen:
            seen.add(node_id)
            order.append(self.role_of(node_id) or self.prompt[node_id]["class_type"])
            upstream = self.prompt[node_id]["inputs"].get("model")
            node_id = str(upstream[0]) if is_link(upstream) else None
        return list(reversed(order))

    def image_chain(self) -> list[str]:
        """The picture path, as roles, from the decoder to the video node."""
        order: list[str] = []
        node_id = self.id(R.VIDEO_OUT)
        seen: set[str] = set()
        while node_id and node_id not in seen:
            seen.add(node_id)
            order.append(self.role_of(node_id) or self.prompt[node_id]["class_type"])
            upstream = self.prompt[node_id]["inputs"].get("images") or self.prompt[node_id][
                "inputs"
            ].get("image")
            node_id = str(upstream[0]) if is_link(upstream) else None
        return list(reversed(order))


def built(workflow, config, **kwargs) -> Built:
    return Built(workflow, config, **kwargs)


# --- every configuration produces a submittable graph ---------------------


def test_the_default_config_produces_a_graph_with_no_dangling_links(flf2v_workflow, base_config):
    made = built(flf2v_workflow, base_config)
    assert missing_links(made.prompt) == []
    assert made.inputs(R.SCHEDULER)["steps"] == 20


@pytest.mark.parametrize("mode", MODES)
def test_every_mode_produces_a_submittable_graph(templates, mode, base_config):
    config = base_config.merged(mode=mode, ref_images=("ref.png",))
    made = built(templates[mode], config)
    assert missing_links(made.prompt) == []
    assert made.has(R.VIDEO_OUT)
    assert made.has(R.SAMPLER)


@pytest.mark.parametrize("cache", ["none", "spectrum", "easy", "h3"])
@pytest.mark.parametrize("sol", [True, False])
def test_every_cache_and_attention_combination_stays_wired(
    flf2v_workflow, base_config, cache, sol
):
    config = base_config.merged(cache=cache, cache_enabled=cache != "none", sol_attn=sol)
    made = built(flf2v_workflow, config)
    assert missing_links(made.prompt) == []
    alive = [role for role in R.CACHE_ROLES.values() if made.has(role)]
    expected = R.CACHE_ROLES.get(cache) if cache != "none" else None
    assert alive == ([expected] if expected else [])
    assert made.has(R.SOL_ATTN) is sol


@pytest.mark.parametrize("turbo", [True, False])
@pytest.mark.parametrize("interp", ["off", "film", "rife"])
@pytest.mark.parametrize("upscaler", [True, False])
@pytest.mark.parametrize("clean_vram", [True, False])
def test_every_toggle_combination_stays_wired(
    flf2v_workflow, base_config, turbo, interp, upscaler, clean_vram
):
    config = base_config.merged(
        turbo=turbo, interp=interp, upscaler=upscaler, clean_vram=clean_vram
    )
    made = built(flf2v_workflow, config)
    assert missing_links(made.prompt) == []
    assert made.inputs(R.SCHEDULER)["steps"] == (4 if turbo else 20)
    assert made.has(R.UPSCALER) is upscaler
    assert made.has(R.RIFE) is (interp == "rife")
    assert made.has(R.FILM) is (interp == "film")
    assert made.has(R.CLEAN_VRAM) is clean_vram


# --- the model chain -------------------------------------------------------


def test_the_model_chain_reaches_the_scheduler_and_the_guider(flf2v_workflow, base_config):
    made = built(flf2v_workflow, base_config)
    chain = made.model_chain()
    assert chain[0] == R.DIFFUSION_LOADER
    assert made.source_of(R.SCHEDULER, "model") == made.source_of(R.GUIDER, "model")
    assert R.SOL_ATTN in chain
    assert R.CACHE_SPECTRUM in chain


def test_the_template_decides_the_order_of_the_chain_not_the_lab(templates, base_config):
    """The r2v template patches attention in the other order and adds two more nodes.

    Reordering the chain in the editor used to produce a prompt wired the way the lab
    imagined it instead of the way the template said.
    """
    flf2v = built(templates["flf2v"], base_config).model_chain()
    r2v = built(
        templates["r2v"], base_config.merged(mode="r2v", ref_images=("ref.png",))
    ).model_chain()
    assert flf2v.index(R.SOL_ATTN) < flf2v.index(R.SAGE_ATTN)
    assert r2v.index(R.SAGE_ATTN) < r2v.index(R.SOL_ATTN)
    assert "MiniMaxChunkFeedForward" in r2v


def test_turbo_puts_the_lora_in_the_chain_and_leaves_it_out_otherwise(
    flf2v_workflow, base_config
):
    on = built(flf2v_workflow, base_config.merged(turbo=True))
    assert on.model_chain()[:2] == [R.DIFFUSION_LOADER, R.TURBO_LORA]

    off = built(flf2v_workflow, base_config)
    assert R.TURBO_LORA not in off.model_chain()
    assert not off.has(R.TURBO_LORA)


def test_the_optional_lora_slot_is_never_part_of_a_benchmark(flf2v_workflow, base_config):
    made = built(flf2v_workflow, base_config)
    assert not made.has(R.OPTIONAL_LORA)
    assert missing_links(made.prompt) == []


def test_turning_the_attention_patch_off_removes_it_from_the_chain(flf2v_workflow, base_config):
    made = built(flf2v_workflow, base_config.merged(sol_attn=False))
    assert not made.has(R.SOL_ATTN)
    assert R.SAGE_ATTN in made.model_chain()


def test_a_named_safetensor_reaches_the_unet_loader(flf2v_workflow, base_config):
    config = base_config.merged(diffusion_model="minimax_h3_fl2va_pruned_int8_convrot.safetensors")
    made = built(flf2v_workflow, config)
    assert (
        made.inputs(R.DIFFUSION_LOADER)["unet_name"]
        == "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
    )


def test_a_gguf_model_asks_for_a_loader_this_template_does_not_have(
    flf2v_workflow, base_config
):
    config = base_config.merged(diffusion_model="MiniMax-H3-FL2VA-Q4_K_M.gguf")
    with pytest.raises(WorkflowError, match="GGUF loader"):
        apply_config(flf2v_workflow, config)


def _plain(config, **overrides):
    """A config the small hand-built workflows below can express."""
    return config.merged(
        mode="t2v", cache="none", cache_enabled=False, sol_attn=False, **overrides
    )


def test_a_gguf_model_selects_the_other_loader_when_the_template_has_one(base_config):
    made = built(_two_loader_workflow(), _plain(base_config, diffusion_model="m.gguf"))
    assert made.inputs(R.GGUF_LOADER)["model_name"] == "m.gguf"
    assert not made.has(R.DIFFUSION_LOADER)
    assert made.source_of(R.CONDITIONING, "clip") == made.id(R.GGUF_CLIP_LOADER)
    assert missing_links(made.prompt) == []


def test_a_safetensors_model_keeps_the_plain_loader_and_encoder(base_config):
    made = built(_two_loader_workflow(), _plain(base_config))
    assert made.has(R.DIFFUSION_LOADER)
    assert not made.has(R.GGUF_LOADER)
    assert made.source_of(R.CONDITIONING, "clip") == made.id(R.CLIP_LOADER)


def test_a_gguf_model_keeps_the_text_encoder_the_template_paired_with_it(base_config):
    """Which text encoder goes with which quantised model is knowledge only the template has.

    The lab used to overwrite it with a hardcoded filename that was not even an encoder, and
    every GGUF run died at validation with `clip_name: Value not in list`.
    """
    made = built(_two_loader_workflow(), _plain(base_config, diffusion_model="m.gguf"))
    assert made.inputs(R.GGUF_CLIP_LOADER)["clip_name"] == "paired_encoder.gguf"


def _two_loader_workflow() -> dict:
    """The smallest workflow with a choice of loader, for the paths the templates dropped."""
    nodes = [
        {"id": 1, "type": "UNETLoader", "widgets_values": ["a.safetensors", "default"]},
        {"id": 2, "type": "CLIPLoader", "widgets_values": ["enc.safetensors", "minimax"]},
        {"id": 3, "type": "GGUFLoaderKJ", "widgets_values": ["b.gguf"]},
        {"id": 4, "type": "CLIPLoaderGGUF", "widgets_values": ["paired_encoder.gguf", "minimax"]},
        {
            "id": 5,
            "type": "MiniMaxH3ImageToVideo",
            "title": "MS_INPUT_CONDITIONING",
            "widgets_values": ["prompt", 512, 512, 21],
            "inputs": [{"name": "clip", "type": "CLIP", "link": 1}],
            "outputs": [{"name": "CONDITIONING", "type": "CONDITIONING"}, {"name": "LATENT", "type": "LATENT"}],
        },
        {
            "id": 6,
            "type": "BasicScheduler",
            "title": "MS_INPUT_STEPS",
            "widgets_values": ["simple", 20, 1.0],
            "inputs": [{"name": "model", "type": "MODEL", "link": 2}],
            "outputs": [{"name": "SIGMAS", "type": "SIGMAS"}],
        },
        {
            "id": 8,
            "type": "BasicGuider",
            "inputs": [
                {"name": "model", "type": "MODEL", "link": 3},
                {"name": "conditioning", "type": "CONDITIONING", "link": 4},
            ],
            "outputs": [{"name": "GUIDER", "type": "GUIDER"}],
        },
        {
            "id": 10,
            "type": "SamplerCustomAdvanced",
            "inputs": [
                {"name": "guider", "type": "GUIDER", "link": 5},
                {"name": "sigmas", "type": "SIGMAS", "link": 6},
                {"name": "latent_image", "type": "LATENT", "link": 7},
            ],
            "outputs": [{"name": "output", "type": "LATENT"}],
        },
        {
            "id": 12,
            "type": "VAEDecode",
            "inputs": [{"name": "samples", "type": "LATENT", "link": 8}],
            "outputs": [{"name": "IMAGE", "type": "IMAGE"}],
        },
        {
            "id": 13,
            "type": "VHS_VideoCombine",
            "title": "MS_OUTPUT_VIDEO",
            "widgets_values": {"frame_rate": 24, "filename_prefix": "x"},
            "inputs": [{"name": "images", "type": "IMAGE", "link": 9}],
        },
    ]
    links = [
        [1, 2, 0, 5, 0, "CLIP"],
        [2, 1, 0, 6, 0, "MODEL"],
        [3, 1, 0, 8, 0, "MODEL"],
        [4, 5, 0, 8, 1, "CONDITIONING"],
        [5, 8, 0, 10, 0, "GUIDER"],
        [6, 6, 0, 10, 1, "SIGMAS"],
        [7, 5, 1, 10, 2, "LATENT"],
        [8, 10, 0, 12, 0, "LATENT"],
        [9, 12, 0, 13, 0, "IMAGE"],
    ]
    return {"nodes": nodes, "links": links}


def test_a_workflow_without_a_sampler_is_rejected_with_a_clear_message(base_config):
    workflow = {"nodes": [{"id": 1, "type": "UNETLoader", "widgets_values": ["a", "default"]}]}
    with pytest.raises(WorkflowError, match="sampler"):
        apply_config(workflow, base_config)


def test_the_error_names_every_part_the_lab_could_not_find(base_config):
    with pytest.raises(WorkflowError) as failure:
        apply_config({"nodes": [], "links": []}, base_config)
    message = str(failure.value)
    assert "conditioning" in message and "video_out" in message
    assert "MS_ROLE:" in message  # tells the user how to fix it


# --- the turbo LoRA --------------------------------------------------------


def test_the_turbo_lora_file_and_strength_reach_the_node(flf2v_workflow, base_config):
    config = base_config.merged(
        turbo=True, turbo_lora="other_turbo_8step.safetensors", turbo_lora_strength=0.6
    )
    made = built(flf2v_workflow, config)
    inputs = made.inputs(R.TURBO_LORA)
    assert inputs["lora_name"] == "other_turbo_8step.safetensors"
    assert inputs["strength"] == 0.6
    assert "strength_model" not in inputs  # the node renamed it; we must not write the old name


def test_a_turbo_run_without_a_named_lora_uses_the_default(flf2v_workflow, base_config):
    made = built(flf2v_workflow, base_config.merged(turbo=True))
    assert made.inputs(R.TURBO_LORA)["lora_name"].endswith(".safetensors")


def test_the_step_count_follows_the_lora_the_run_selected(flf2v_workflow, base_config):
    four = built(flf2v_workflow, base_config.merged(turbo=True, turbo_lora="turbo_4step.safetensors"))
    eight = built(
        flf2v_workflow, base_config.merged(turbo=True, turbo_lora="turbo_8step.safetensors")
    )
    assert four.inputs(R.SCHEDULER)["steps"] == 4
    assert eight.inputs(R.SCHEDULER)["steps"] == 8


def test_two_turbo_loras_differ_only_in_the_lora_node(flf2v_workflow, base_config):
    first = built(
        flf2v_workflow, base_config.merged(turbo=True, turbo_lora="a_4step.safetensors")
    )
    second = built(
        flf2v_workflow, base_config.merged(turbo=True, turbo_lora="b_4step.safetensors")
    )
    differing = [
        node_id
        for node_id in first.prompt
        if first.prompt[node_id] != second.prompt.get(node_id)
    ]
    assert differing == [first.id(R.TURBO_LORA)]


def test_a_workflow_without_a_turbo_node_says_so(base_config):
    with pytest.raises(WorkflowError, match="turbo LoRA"):
        apply_config(_two_loader_workflow(), _plain(base_config, turbo=True))


# --- widget routing --------------------------------------------------------


def test_cache_and_attention_windows_do_not_cross_contaminate(flf2v_workflow, base_config):
    config = base_config.merged(
        cache="easy",
        cache_enabled=True,
        cache_preset="conservative",
        sol_attn=True,
        sol_preset="aggressive",
    )
    made = built(flf2v_workflow, config)
    cache_node = made.inputs(R.CACHE_EASY)
    sol_node = made.inputs(R.SOL_ATTN)
    # Both families own a start_percent; each must keep its own value.
    assert cache_node["start_percent"] == 0.3
    assert sol_node["start_percent"] == 0.1
    assert sol_node["tau"] == 1.8
    assert "tau" not in cache_node
    assert "reuse_threshold" not in sol_node


def test_a_named_level_expands_to_its_table_values(base_config):
    config = base_config.merged(cache="spectrum", cache_preset="aggressive", sol_attn=False)
    assert cache_widgets(config).items() >= SPECTRUM["aggressive"].items()
    assert sol_widgets(config) == {}


@pytest.mark.parametrize("family", ["easy", "h3", "spectrum"])
@pytest.mark.parametrize("preset", ["conservative", "moderate", "aggressive"])
def test_every_named_level_is_one_the_node_will_accept(base_config, family, preset):
    """A named level must be runnable, because the node only complains once it has the GPU.

    `SpectrumApplyMiniMaxH3` validates cross-field rules inside the node, minutes into a
    run, as a node error rather than a wiring problem — so `missing_links` can never catch
    it.
    """
    config = base_config.merged(cache=family, cache_preset=preset)
    assert cache_problems(cache_widgets(config), family=family) == []


def test_the_spectrum_levels_track_the_nodes_own_presets(base_config):
    """The endpoints are the node's `CONSERVATIVE_PRESET` and `AGGRESSIVE_PRESET` verbatim."""
    conservative = cache_widgets(base_config.merged(cache="spectrum", cache_preset="conservative"))
    aggressive = cache_widgets(base_config.merged(cache="spectrum", cache_preset="aggressive"))

    assert conservative["degree"] == 1
    assert conservative["blend_weight"] == 0.5
    assert conservative["warmup_steps"] == 1
    assert conservative["bootstrap_first_forecast"] is True

    assert aggressive["degree"] == 4
    assert aggressive["blend_weight"] == 0.75
    assert aggressive["flex_window"] == 3.0
    assert aggressive["warmup_steps"] == 5
    assert aggressive["bootstrap_first_forecast"] is False


def test_a_stronger_level_forecasts_more_of_the_run(base_config):
    """`blend_weight` is how much of each step comes from the forecast, so it must rise."""
    weights = [
        cache_widgets(base_config.merged(cache="spectrum", cache_preset=preset))["blend_weight"]
        for preset in ("conservative", "moderate", "aggressive")
    ]
    assert weights == sorted(weights)
    assert weights[0] < weights[-1]


def test_a_higher_degree_fit_keeps_enough_history_to_solve(base_config):
    """The node needs `max_history >= degree + 1` points before the fit is solvable."""
    for preset in ("conservative", "moderate", "aggressive"):
        widgets = cache_widgets(base_config.merged(cache="spectrum", cache_preset=preset))
        assert widgets["max_history"] >= widgets["degree"] + 1


def test_the_h3_skip_budget_is_a_whole_number_of_steps(base_config):
    """`max_steps` counts consecutive block-stack skips: INT, 1..10."""
    for preset in ("conservative", "moderate", "aggressive"):
        budget = cache_widgets(base_config.merged(cache="h3", cache_preset=preset))["max_steps"]
        assert isinstance(budget, int)
        assert 1 <= budget <= 10


def test_a_stronger_easy_level_caches_over_a_wider_window(base_config):
    """Aggressive used to open later and close earlier than moderate, caching less."""
    spans = []
    for preset in ("conservative", "moderate", "aggressive"):
        widgets = cache_widgets(base_config.merged(cache="easy", cache_preset=preset))
        spans.append(widgets["end_percent"] - widgets["start_percent"])
    assert spans == sorted(spans)


def test_an_illegal_custom_combination_is_reported_not_quietly_rewritten(base_config):
    """Coercing a widget would make the recorded config differ from the one that ran."""
    config = base_config.merged(
        cache="spectrum",
        cache_preset="custom",
        widgets={"warmup_steps": 4, "bootstrap_first_forecast": True, "degree": 1},
    )
    widgets = cache_widgets(config)

    assert widgets["warmup_steps"] == 4
    assert widgets["bootstrap_first_forecast"] is True
    assert cache_problems(widgets, family="spectrum") == [
        "bootstrap_first_forecast requires warmup_steps <= 1"
    ]


def test_the_bootstrap_also_needs_a_straight_line_fit(base_config):
    config = base_config.merged(
        cache="spectrum",
        cache_preset="custom",
        widgets={"degree": 3, "bootstrap_first_forecast": True, "warmup_steps": 0},
    )
    assert cache_problems(cache_widgets(config), family="spectrum") == [
        "bootstrap_first_forecast requires degree == 1"
    ]


@pytest.mark.parametrize(
    ("widgets", "expected"),
    [
        ({"blend_weight": 1.4}, "blend_weight must be between 0 and 1"),
        ({"degree": 0}, "degree must be a whole number of 1 or more"),
        ({"window_size": 0.5}, "window_size must be 1 or more"),
        ({"ridge_lambda": -0.2}, "ridge_lambda must be 0 or more"),
        ({"max_history": 3, "degree": 4}, "max_history must be at least 5 for degree 4"),
        ({"history_storage": "disk"}, "history_storage must be system_ram or vram"),
    ],
)
def test_a_widget_outside_the_nodes_range_is_named(base_config, widgets, expected):
    config = base_config.merged(cache="spectrum", cache_preset="custom", widgets=widgets)
    assert expected in cache_problems(cache_widgets(config), family="spectrum")


def test_a_family_with_no_cross_field_rules_still_gets_range_checks(base_config):
    config = base_config.merged(
        cache="h3", cache_preset="custom", widgets={"max_steps": 40, "reuse_threshold": 2.0}
    )
    problems = cache_problems(cache_widgets(config), family="h3")
    assert "max_steps must be between 1 and 10" in problems
    assert "reuse_threshold must be between 0 and 1" in problems


@pytest.mark.parametrize("mode", MODES)
def test_the_template_leaves_the_spectrum_node_at_its_shipped_defaults(templates, mode):
    """Two saved widgets drifted from the node and neither belonged to a benchmark.

    `debug: true` logged every step of every run, and `history_storage: 'vram'` parked the
    forecast history on the same card as a video model. Both are widgets the lab never sets
    from a preset, so whatever the template holds is what runs.
    """
    graph = read(templates[mode])
    node = R.resolve(graph).node(graph, R.CACHE_SPECTRUM)
    assert node is not None
    assert node.inputs["debug"] is False, "debug should be off"
    assert node.inputs["history_storage"] == "system_ram"


def test_custom_widgets_override_a_named_level(base_config):
    config = base_config.merged(sol_preset="moderate", widgets={"tau": 9.5})
    assert sol_widgets(config)["tau"] == 9.5
    assert sol_widgets(config)["start_percent"] == SOL["moderate"]["start_percent"]


def test_widget_keys_a_node_does_not_know_are_not_written(flf2v_workflow, base_config):
    config = base_config.merged(widgets={"nonsense_key": 1, "tau": 1.2})
    made = built(flf2v_workflow, config)
    assert "nonsense_key" not in made.inputs(R.SOL_ATTN)
    assert made.inputs(R.SOL_ATTN)["tau"] == 1.2


def test_parse_combo_handles_both_comfy_shapes():
    assert parse_combo(["COMBO", {"options": ["a", "b"]}]) == ["a", "b"]
    assert parse_combo([["a", "b"], {"default": "a"}]) == ["a", "b"]
    assert parse_combo("euler") == []  # a bare string must not become letters
    assert parse_combo([]) == []


# --- media wiring ----------------------------------------------------------


def test_flf2v_wires_the_first_frame_and_omits_the_last_when_unset(flf2v_workflow, base_config):
    made = built(flf2v_workflow, base_config)
    assert made.inputs(R.FIRST_FRAME)["image"] == base_config.first_frame
    assert "first_frame" in made.inputs(R.CONDITIONING)
    assert "last_frame" not in made.inputs(R.CONDITIONING)
    assert not made.has(R.LAST_FRAME)


def test_flf2v_wires_a_last_frame_when_given(flf2v_workflow, base_config):
    made = built(flf2v_workflow, base_config.merged(last_frame="end.png"))
    assert made.inputs(R.LAST_FRAME)["image"] == "end.png"
    assert "last_frame" in made.inputs(R.CONDITIONING)
    assert missing_links(made.prompt) == []


def test_a_keyframe_reaches_the_conditioning_through_the_resize_the_template_added(
    flf2v_workflow, base_config
):
    """The template fits each frame to the canvas first. That node has to stay in the path."""
    made = built(flf2v_workflow, base_config.merged(last_frame="end.png"))
    for name, role in (("first_frame", R.FIRST_FRAME), ("last_frame", R.LAST_FRAME)):
        source = made.source_of(R.CONDITIONING, name)
        assert source is not None
        assert made.prompt[source]["class_type"] == "ImageScale"
        assert made.prompt[source]["inputs"]["image"] == [made.id(role), 0]


def test_a_full_path_is_reduced_to_a_filename(flf2v_workflow, base_config):
    config = base_config.merged(first_frame=r"C:\Users\me\pictures\shot.png")
    made = built(flf2v_workflow, config)
    assert made.inputs(R.FIRST_FRAME)["image"] == "shot.png"


def test_text_to_video_drops_every_media_loader(t2v_workflow, base_config):
    made = built(t2v_workflow, base_config.merged(mode="t2v"))
    assert not made.has(R.FIRST_FRAME)
    assert "first_frame" not in made.inputs(R.CONDITIONING)
    assert referenced_files(made.prompt) == []
    assert missing_links(made.prompt) == []


def test_reference_mode_wires_one_loader_per_reference(r2v_workflow, base_config):
    config = base_config.merged(
        mode="r2v",
        ref_images=("a.png", "b.png"),
        ref_videos=("clip.mp4",),
        ref_audios=("voice.wav",),
    )
    made = built(r2v_workflow, config)
    conditioning = made.inputs(R.CONDITIONING)
    images = [
        made.prompt[str(conditioning[f"ref_images.ref_image_{index}"][0])]
        for index in range(2)
    ]
    assert [node["inputs"]["image"] for node in images] == ["a.png", "b.png"]
    assert "ref_images.ref_image_2" not in conditioning
    video = made.prompt[str(conditioning["ref_videos.ref_video_0"][0])]
    assert video["class_type"] == "GetVideoComponents"
    assert made.prompt[str(video["inputs"]["video"][0])]["inputs"]["file"] == "clip.mp4"
    audio = made.prompt[str(conditioning["ref_audios.ref_audio_0"][0])]
    assert audio["inputs"]["audio"] == "voice.wav"
    assert missing_links(made.prompt) == []
    assert set(referenced_files(made.prompt)) == {"a.png", "b.png", "clip.mp4", "voice.wav"}


def test_an_unused_reference_loader_does_not_survive_as_an_orphan(r2v_workflow, base_config):
    config = base_config.merged(mode="r2v", ref_images=("a.png",))
    made = built(r2v_workflow, config)
    loaders = [
        node for node in made.prompt.values() if node["class_type"] in ("LoadImage", "LoadVideo")
    ]
    assert len(loaders) == 1
    assert loaders[0]["inputs"]["image"] == "a.png"


def test_a_reference_video_defaults_to_its_own_soundtrack(r2v_workflow, base_config):
    config = base_config.merged(mode="r2v", ref_videos=("clip.mp4",))
    made = built(r2v_workflow, config)
    conditioning = made.inputs(R.CONDITIONING)
    # Slot 1 of GetVideoComponents is the audio track of that same video.
    assert conditioning["ref_video_audios.ref_video_audio_0"] == [
        conditioning["ref_videos.ref_video_0"][0],
        1,
    ]


def test_an_explicit_soundtrack_overrides_the_video_audio(r2v_workflow, base_config):
    config = base_config.merged(
        mode="r2v", ref_videos=("clip.mp4",), ref_video_audios=("score.wav",)
    )
    made = built(r2v_workflow, config)
    conditioning = made.inputs(R.CONDITIONING)
    source = str(conditioning["ref_video_audios.ref_video_audio_0"][0])
    assert made.prompt[source]["class_type"] == "LoadAudio"
    assert made.prompt[source]["inputs"]["audio"] == "score.wav"
    assert source != str(conditioning["ref_videos.ref_video_0"][0])


def test_reference_mode_keeps_the_audio_vae_for_conditioning(r2v_workflow, base_config):
    config = base_config.merged(mode="r2v", ref_images=("a.png",))
    made = built(r2v_workflow, config)
    assert made.source_of(R.CONDITIONING, "audio_vae") == made.id(R.AUDIO_VAE)


def test_keyframe_modes_drop_the_audio_path(flf2v_workflow, base_config):
    made = built(flf2v_workflow, base_config)
    assert not made.has(R.VAE_DECODE_AUDIO)
    assert not made.has(R.AUDIO_VAE)


def test_a_reference_run_needs_a_template_that_takes_references(t2v_workflow, base_config):
    config = base_config.merged(mode="r2v", ref_images=("a.png",))
    with pytest.raises(WorkflowError, match="reference"):
        apply_config(t2v_workflow, config)


def test_more_references_than_the_template_has_slots_still_run(r2v_workflow, base_config):
    """A template with fewer loaders than the run asks for gets the missing ones minted."""
    trimmed = _drop_ref_slots(r2v_workflow, keep=1)
    config = base_config.merged(mode="r2v", ref_images=("a.png", "b.png", "c.png"))
    made = built(trimmed, config)
    conditioning = made.inputs(R.CONDITIONING)
    names = [
        made.prompt[str(conditioning[f"ref_images.ref_image_{index}"][0])]["inputs"]["image"]
        for index in range(3)
    ]
    assert names == ["a.png", "b.png", "c.png"]
    assert missing_links(made.prompt) == []


def _drop_ref_slots(workflow: dict, *, keep: int) -> dict:
    """The r2v template with all but *keep* reference image slots unwired."""
    import copy

    trimmed = copy.deepcopy(workflow)
    for definition in (trimmed.get("definitions") or {}).get("subgraphs") or []:
        for node in definition.get("nodes") or []:
            if node.get("type") != "MiniMaxH3ReferenceToVideo":
                continue
            node["inputs"] = [
                slot
                for slot in node.get("inputs") or []
                if not (
                    str(slot.get("name", "")).startswith("ref_images.ref_image_")
                    and int(str(slot["name"]).rsplit("_", 1)[1]) >= keep
                )
            ]
    return trimmed


# --- output path -----------------------------------------------------------


def test_the_video_node_never_receives_an_audio_input(flf2v_workflow, base_config):
    made = built(flf2v_workflow, base_config)
    combine = made.inputs(R.VIDEO_OUT)
    assert "audio" not in combine
    assert combine["trim_to_audio"] is False


def test_the_picture_path_keeps_the_grade_the_template_added(flf2v_workflow, base_config):
    made = built(flf2v_workflow, base_config)
    chain = made.image_chain()
    assert chain[0] == R.VAE_DECODE
    assert chain[-1] == R.VIDEO_OUT
    assert "ImageApplyLUT+" in chain
    assert "Glow" not in chain  # the template ships the bloom bypassed


def test_rife_and_the_upscaler_are_inserted_in_order(flf2v_workflow, base_config):
    made = built(flf2v_workflow, base_config.merged(interp="rife", upscaler=True))
    chain = made.image_chain()
    assert chain.index(R.VAE_DECODE) < chain.index(R.RIFE) < chain.index(R.UPSCALER)
    assert chain[-1] == R.VIDEO_OUT


@pytest.mark.parametrize("mode", MODES)
def test_film_interpolation_sits_between_the_decode_and_the_combine(templates, mode, base_config):
    config = base_config.merged(interp="film", mode=mode, ref_images=("ref.png",))
    made = built(templates[mode], config)
    chain = made.image_chain()
    assert chain.index(R.VAE_DECODE) < chain.index(R.FILM)
    assert made.source_of(R.FILM, "interp_model") == made.id(R.FILM_LOADER)
    assert made.inputs(R.FILM)["multiplier"] == 2
    assert made.inputs(R.FILM_LOADER)["model_name"] == "film_net_fp16.safetensors"
    assert made.inputs(R.VIDEO_OUT)["frame_rate"] == 48
    assert not made.has(R.RIFE)
    assert missing_links(made.prompt) == []


def test_only_the_chosen_interpolator_survives(flf2v_workflow, base_config):
    rife = built(flf2v_workflow, base_config.merged(interp="rife"))
    assert not rife.has(R.FILM) and not rife.has(R.FILM_LOADER)

    off = built(flf2v_workflow, base_config)
    for role in (R.RIFE, R.FILM, R.FILM_LOADER, R.INTERP_FPS):
        assert not off.has(role)


def test_the_frame_rate_follows_the_interpolation_setting(flf2v_workflow, base_config):
    rates = {
        value: built(flf2v_workflow, base_config.merged(interp=value)).inputs(R.VIDEO_OUT)[
            "frame_rate"
        ]
        for value in ("off", "film", "rife")
    }
    assert rates == {"off": 24, "film": 48, "rife": 60}


def test_the_editors_spare_export_nodes_never_reach_the_prompt(flf2v_workflow, base_config):
    """The template saves a master export, an audio stem and a final frame. A run wants one file."""
    made = built(flf2v_workflow, base_config)
    assert [node["class_type"] for node in made.prompt.values()].count("VHS_VideoCombine") == 1
    assert "SaveImage" not in made.classes()
    assert "SaveAudio" not in made.classes()


def test_the_output_tag_only_changes_the_filename(flf2v_workflow, base_config):
    first = built(flf2v_workflow, base_config, output_tag="one").prompt
    second = built(flf2v_workflow, base_config, output_tag="two").prompt
    differing = [node_id for node_id in first if first[node_id] != second[node_id]]
    assert len(differing) == 1
    assert first[differing[0]]["class_type"] == "VHS_VideoCombine"


def test_an_output_tag_cannot_escape_the_output_folder():
    assert output_filename_prefix("../../etc/passwd") == "h3lab/______etc_passwd"
    assert output_filename_prefix("") == "h3lab/run"
    assert "/" not in output_filename_prefix("a/b")[len("h3lab/") :]


# --- sampling inputs -------------------------------------------------------


def test_the_seed_reaches_the_noise_node(flf2v_workflow, base_config):
    made = built(flf2v_workflow, base_config.merged(seed=777))
    assert made.inputs(R.NOISE)["noise_seed"] == 777


def test_sampling_choices_reach_their_nodes(flf2v_workflow, base_config):
    config = base_config.merged(
        scheduler="karras", sampler="dpmpp_2m", steps=33, mp=1.25, duration_s=7.5
    )
    made = built(flf2v_workflow, config)
    assert made.inputs(R.SCHEDULER)["scheduler"] == "karras"
    assert made.inputs(R.SCHEDULER)["steps"] == 33
    assert made.inputs(R.SAMPLER_SELECT)["sampler_name"] == "dpmpp_2m"
    assert made.inputs(R.RESOLUTION)["megapixels"] == 1.25
    assert made.inputs(R.DURATION)["value"] == 7.5


def test_the_frame_count_is_still_computed_by_the_template(flf2v_workflow, base_config):
    """Duration is written to the primitive, not onto the conditioning's length.

    The 17n+5 rule the template encodes is the model's, not the lab's; overwriting `length`
    with a literal would silently drop it.
    """
    made = built(flf2v_workflow, base_config.merged(duration_s=6.0))
    length = made.inputs(R.CONDITIONING)["length"]
    assert is_link(length)
    assert made.prompt[str(length[0])]["class_type"] == "ComfyMathExpression"
    assert made.inputs(R.DURATION)["value"] == 6.0


def test_the_prompt_text_reaches_the_conditioning(flf2v_workflow, base_config):
    made = built(flf2v_workflow, base_config.merged(prompt="a single red balloon"))
    assert made.inputs(R.CONDITIONING)["prompt"] == "a single red balloon"


def test_two_identical_configs_produce_identical_graphs(flf2v_workflow, base_config):
    assert apply_config(flf2v_workflow, base_config, output_tag="x") == apply_config(
        flf2v_workflow, base_config, output_tag="x"
    )


def test_clean_vram_inserts_both_cleanup_nodes(flf2v_workflow, base_config):
    made = built(flf2v_workflow, base_config.merged(clean_vram=True))
    assert made.source_of(R.VAE_DECODE, "samples") == made.id(R.CLEAN_VRAM)
    assert made.source_of(R.CLEAN_VRAM, "anything") == made.id(R.SAMPLER)
    assert made.source_of(R.GUIDER, "conditioning") == made.id(R.CLEAN_TEXT_ENCODER)
    assert missing_links(made.prompt) == []


def test_without_clean_vram_the_decoder_reads_the_sampler_directly(flf2v_workflow, base_config):
    made = built(flf2v_workflow, base_config)
    assert made.source_of(R.VAE_DECODE, "samples") == made.id(R.SAMPLER)
    assert made.source_of(R.GUIDER, "conditioning") == made.id(R.CONDITIONING)
    assert not made.has(R.CLEAN_VRAM)


# --- surviving a changed workflow -----------------------------------------


def test_the_same_workflow_renumbered_produces_the_same_prompt(flf2v_workflow, base_config):
    from tests.test_comfy_roles import _renumber

    original = apply_config(flf2v_workflow, base_config, output_tag="x")
    moved = apply_config(_renumber(flf2v_workflow, offset=7000), base_config, output_tag="x")
    assert len(moved) == len(original)
    assert sorted(node["class_type"] for node in moved.values()) == sorted(
        node["class_type"] for node in original.values()
    )
    assert missing_links(moved) == []
