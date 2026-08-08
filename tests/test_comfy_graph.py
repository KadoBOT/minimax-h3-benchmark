"""Graph patching, checked against the real workflow templates in the repository."""

from __future__ import annotations

import pytest

from h3lab.comfy import nodes as N
from h3lab.comfy.client import parse_combo
from h3lab.comfy.graph import (
    WorkflowError,
    apply_config,
    load_workflow,
    missing_links,
    output_filename_prefix,
    referenced_files,
    to_api_prompt,
)
from h3lab.comfy.presets import SOL, SPECTRUM, cache_problems, cache_widgets, sol_widgets
from h3lab.domain.config import GenerationConfig
from h3lab.settings import Settings


@pytest.fixture(scope="module")
def flf2v_workflow():
    return load_workflow(Settings().workflow_path("flf2v"))


@pytest.fixture(scope="module")
def r2v_workflow():
    return load_workflow(Settings().workflow_path("r2v"))


@pytest.fixture(scope="module")
def t2v_workflow():
    return load_workflow(Settings().workflow_path("t2v"))


def build(workflow, config, **kwargs):
    return apply_config(workflow, config, **kwargs)


# --- format conversion -----------------------------------------------------


def test_to_api_prompt_resolves_links_and_widgets():
    workflow = {
        "nodes": [
            {"id": 1, "type": "PrimitiveFloat", "widgets_values": [24.0]},
            {
                "id": 2,
                "type": "BasicScheduler",
                "widgets_values": ["beta57", 20, 1.0],
                "inputs": [{"name": "model", "link": 7}],
            },
            {"id": 3, "type": "Note", "widgets_values": ["ignore me"]},
        ],
        "links": [[7, 1, 0, 2, 0, "MODEL"]],
    }
    prompt = to_api_prompt(workflow)
    assert set(prompt) == {"1", "2"}  # the note is not executable
    assert prompt["1"]["inputs"] == {"value": 24.0}
    assert prompt["2"]["inputs"]["model"] == ["1", 0]
    assert prompt["2"]["inputs"]["scheduler"] == "beta57"
    assert prompt["2"]["inputs"]["steps"] == 20


def test_a_linked_input_is_never_overwritten_by_a_widget_value():
    workflow = {
        "nodes": [
            {"id": 1, "type": "CM_FloatToInt", "widgets_values": [8]},
            {
                "id": 2,
                "type": "BasicScheduler",
                "widgets_values": ["beta57", 20, 1.0],
                "inputs": [{"name": "steps", "link": 5}],
            },
        ],
        "links": [[5, 1, 0, 2, 1, "INT"]],
    }
    prompt = to_api_prompt(workflow)
    assert prompt["2"]["inputs"]["steps"] == ["1", 0]


def test_video_combine_widgets_are_read_as_a_dict():
    workflow = {
        "nodes": [
            {
                "id": 110,
                "type": "VHS_VideoCombine",
                "widgets_values": {
                    "frame_rate": 24,
                    "filename_prefix": "x",
                    "videopreview": {"noise": True},
                },
            }
        ],
        "links": [],
    }
    prompt = to_api_prompt(workflow)
    assert prompt["110"]["inputs"]["frame_rate"] == 24
    assert "videopreview" not in prompt["110"]["inputs"]


def test_parse_combo_handles_both_comfy_shapes():
    assert parse_combo(["COMBO", {"options": ["a", "b"]}]) == ["a", "b"]
    assert parse_combo([["a", "b"], {"default": "a"}]) == ["a", "b"]
    assert parse_combo("euler") == []  # a bare string must not become letters
    assert parse_combo([]) == []


# --- every configuration produces a submittable graph ---------------------


def test_the_default_config_produces_a_graph_with_no_dangling_links(flf2v_workflow, base_config):
    prompt = build(flf2v_workflow, base_config)
    assert missing_links(prompt) == []
    assert prompt[str(N.SCHEDULER)]["inputs"]["steps"] == 20


@pytest.mark.parametrize("cache", ["none", "spectrum", "easy", "h3"])
@pytest.mark.parametrize("sol", [True, False])
def test_every_cache_and_attention_combination_stays_wired(
    flf2v_workflow, base_config, cache, sol
):
    config = base_config.merged(cache=cache, cache_enabled=cache != "none", sol_attn=sol)
    prompt = build(flf2v_workflow, config)
    assert missing_links(prompt) == []
    # Exactly the selected cache node survives.
    alive = [node for node in N.CACHE_NODES if str(node) in prompt]
    expected = N.CACHE_NODE_BY_NAME.get(cache) if cache != "none" else None
    assert alive == ([expected] if expected else [])


@pytest.mark.parametrize("turbo", [True, False])
@pytest.mark.parametrize("rife", [True, False])
@pytest.mark.parametrize("upscaler", [True, False])
@pytest.mark.parametrize("clean_vram", [True, False])
def test_every_toggle_combination_stays_wired(
    flf2v_workflow, base_config, turbo, rife, upscaler, clean_vram
):
    config = base_config.merged(
        turbo=turbo, rife=rife, upscaler=upscaler, clean_vram=clean_vram
    )
    prompt = build(flf2v_workflow, config)
    assert missing_links(prompt) == []
    assert prompt[str(N.SCHEDULER)]["inputs"]["steps"] == (4 if turbo else 20)


# --- the model chain -------------------------------------------------------


def _chain(prompt) -> list[str]:
    """Walk the model links backwards from the scheduler."""
    order: list[str] = []
    node = prompt[str(N.SCHEDULER)]["inputs"]["model"][0]
    seen: set[str] = set()
    while node and node not in seen:
        seen.add(node)
        order.append(node)
        upstream = prompt[node]["inputs"].get("model")
        node = upstream[0] if isinstance(upstream, list) else None
    return list(reversed(order))


def test_the_model_chain_ends_at_the_scheduler_and_guider(flf2v_workflow, base_config):
    prompt = build(flf2v_workflow, base_config)
    chain = _chain(prompt)
    assert chain[0] == str(N.UNET)
    assert prompt[str(N.SCHEDULER)]["inputs"]["model"] == prompt[str(N.GUIDER)]["inputs"]["model"]
    # Sage attention always stays in the chain, even with the Sol patch active.
    assert str(N.SAGE_ATTN) in chain
    assert str(N.SOL_ATTN) in chain
    assert chain.index(str(N.SOL_ATTN)) < chain.index(str(N.SAGE_ATTN))
    assert chain.index(str(N.SAGE_ATTN)) < chain.index(str(N.SIGMA_SHIFT))
    assert chain[-1] == str(N.SPECTRUM)


def test_turbo_puts_the_lora_first_in_the_chain(flf2v_workflow, base_config):
    prompt = build(flf2v_workflow, base_config.merged(turbo=True))
    chain = _chain(prompt)
    assert chain[:2] == [str(N.UNET), str(N.TURBO_LORA)]


def test_turning_the_attention_patch_off_removes_it_from_the_chain(flf2v_workflow, base_config):
    prompt = build(flf2v_workflow, base_config.merged(sol_attn=False))
    assert str(N.SOL_ATTN) not in prompt
    assert str(N.SAGE_ATTN) in _chain(prompt)


def test_a_gguf_model_selects_the_other_loader(flf2v_workflow, base_config):
    config = base_config.merged(diffusion_model="MiniMax-H3-FL2VA-Q4_K_M.gguf")
    prompt = build(flf2v_workflow, config)
    assert str(N.UNET) not in prompt
    assert prompt[str(N.GGUF_UNET)]["inputs"]["model_name"] == "MiniMax-H3-FL2VA-Q4_K_M.gguf"
    assert _chain(prompt)[0] == str(N.GGUF_UNET)
    assert missing_links(prompt) == []


@pytest.mark.parametrize("mode", ["t2v", "flf2v", "r2v"])
def test_a_gguf_model_keeps_the_text_encoder_the_template_paired_with_it(mode, base_config):
    """The lab used to overwrite this with a hardcoded filename that was not even an encoder.

    `MiniMax-Remover-Q8_0.gguf` is an object-removal model, and it was not installed here at
    all, so every GGUF run died at validation with `clip_name: Value not in list`. Which text
    encoder goes with which quantised model is a pairing only the template knows.
    """
    workflow = load_workflow(Settings().workflow_path(mode))
    saved = next(item for item in workflow["nodes"] if int(item["id"]) == int(N.GGUF_CLIP))
    expected = saved["widgets_values"][0]

    prompt = build(workflow, base_config.merged(diffusion_model="MiniMax-H3-FL2VA-Q4_K_M.gguf"))
    assert prompt[str(N.GGUF_CLIP)]["inputs"]["clip_name"] == expected


def test_a_named_safetensor_reaches_the_unet_loader(flf2v_workflow, base_config):
    config = base_config.merged(diffusion_model="minimax_h3_fl2va_pruned_int8_convrot.safetensors")
    prompt = build(flf2v_workflow, config)
    assert (
        prompt[str(N.UNET)]["inputs"]["unet_name"]
        == "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
    )


def test_a_workflow_missing_the_sage_node_is_rejected_with_a_clear_message(
    flf2v_workflow, base_config
):
    stripped = {
        "nodes": [
            node for node in flf2v_workflow["nodes"] if node["id"] != N.SAGE_ATTN
        ],
        "links": flf2v_workflow["links"],
    }
    with pytest.raises(WorkflowError, match="Sage attention"):
        build(stripped, base_config)


# --- widget routing --------------------------------------------------------


def test_cache_and_attention_windows_do_not_cross_contaminate(flf2v_workflow, base_config):
    config = base_config.merged(
        cache="easy",
        cache_enabled=True,
        cache_preset="conservative",
        sol_attn=True,
        sol_preset="aggressive",
    )
    prompt = build(flf2v_workflow, config)
    cache_node = prompt[str(N.EASY_CACHE)]["inputs"]
    sol_node = prompt[str(N.SOL_ATTN)]["inputs"]
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
    it. The upgraded node also moved the goalposts: its own aggressive preset raises
    `warmup_steps` to 5 and `degree` to 4 together, where the old table walked warmup 1/2/3
    with `degree` pinned at 1 and tripped `bootstrap_first_forecast requires warmup_steps <= 1`.
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
    """`max_steps` counts consecutive block-stack skips: INT, 1..10.

    The table used to hold 0.5 and 0.75, which are neither integers nor inside the node's
    range — the conservative and moderate H3 levels could not have run as written.
    """
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
    """Coercing a widget would make the recorded config differ from the one that ran.

    That is the one failure this lab cannot tolerate: every comparison it draws assumes the
    stored config is what the GPU saw. So an impossible request is named instead of fixed.
    """
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


@pytest.mark.parametrize("mode", ["t2v", "flf2v", "r2v"])
def test_the_template_leaves_the_spectrum_node_at_its_shipped_defaults(mode):
    """Two saved widgets drifted from the node and neither belonged to a benchmark.

    `debug: true` logged every step of every run, and `history_storage: 'vram'` parked the
    forecast history on the same card as a video model. Both are widgets the lab never sets
    from a preset, so whatever the template holds is what runs — the template has to be
    the node's own default, not a leftover from someone's debugging session.
    """
    workflow = load_workflow(Settings().workflow_path(mode))
    node = next(item for item in workflow["nodes"] if int(item["id"]) == int(N.SPECTRUM))
    saved = node["widgets_values"]

    assert saved[9] is False, "debug should be off"
    assert saved[10] == "system_ram", "history belongs in system RAM, not beside the model"


def test_custom_widgets_override_a_named_level(base_config):
    config = base_config.merged(sol_preset="moderate", widgets={"tau": 9.5})
    assert sol_widgets(config)["tau"] == 9.5
    assert sol_widgets(config)["start_percent"] == SOL["moderate"]["start_percent"]


def test_widget_keys_a_node_does_not_know_are_not_written(flf2v_workflow, base_config):
    config = base_config.merged(widgets={"nonsense_key": 1, "tau": 1.2})
    prompt = build(flf2v_workflow, config)
    assert "nonsense_key" not in prompt[str(N.SOL_ATTN)]["inputs"]
    assert prompt[str(N.SOL_ATTN)]["inputs"]["tau"] == 1.2


# --- media wiring ----------------------------------------------------------


def test_flf2v_wires_the_first_frame_and_omits_the_last_when_unset(flf2v_workflow, base_config):
    prompt = build(flf2v_workflow, base_config)
    assert prompt[str(N.LOAD_FIRST_FRAME)]["inputs"]["image"] == base_config.first_frame
    assert "first_frame" in prompt[str(N.CONDITIONING)]["inputs"]
    assert "last_frame" not in prompt[str(N.CONDITIONING)]["inputs"]
    assert str(N.LOAD_LAST_FRAME) not in prompt


def test_flf2v_wires_a_last_frame_when_given(flf2v_workflow, base_config):
    prompt = build(flf2v_workflow, base_config.merged(last_frame="end.png"))
    assert prompt[str(N.LOAD_LAST_FRAME)]["inputs"]["image"] == "end.png"
    assert "last_frame" in prompt[str(N.CONDITIONING)]["inputs"]
    assert missing_links(prompt) == []


def test_a_full_path_is_reduced_to_a_filename(flf2v_workflow, base_config):
    config = base_config.merged(first_frame=r"C:\Users\me\pictures\shot.png")
    prompt = build(flf2v_workflow, config)
    assert prompt[str(N.LOAD_FIRST_FRAME)]["inputs"]["image"] == "shot.png"


def test_text_to_video_drops_every_media_loader(t2v_workflow, base_config):
    prompt = build(t2v_workflow, base_config.merged(mode="t2v"))
    assert str(N.LOAD_FIRST_FRAME) not in prompt
    assert "first_frame" not in prompt[str(N.CONDITIONING)]["inputs"]
    assert referenced_files(prompt) == []
    assert missing_links(prompt) == []


def test_reference_mode_wires_one_loader_per_reference(r2v_workflow, base_config):
    config = base_config.merged(
        mode="r2v",
        ref_images=("a.png", "b.png"),
        ref_videos=("clip.mp4",),
        ref_audios=("voice.wav",),
    )
    prompt = build(r2v_workflow, config)
    conditioning = prompt[str(N.CONDITIONING)]["inputs"]
    assert conditioning["ref_images.ref_image_0"] == [str(N.REF_IMAGE_BASE), 0]
    assert conditioning["ref_images.ref_image_1"] == [str(N.REF_IMAGE_BASE + 1), 0]
    assert conditioning["ref_videos.ref_video_0"] == [str(N.REF_VIDEO_COMPONENTS_BASE), 0]
    assert conditioning["ref_audios.ref_audio_0"] == [str(N.REF_AUDIO_BASE), 0]
    # An unused third image slot must not survive as an orphan loader.
    assert str(N.REF_IMAGE_BASE + 2) not in prompt
    assert missing_links(prompt) == []
    assert set(referenced_files(prompt)) == {"a.png", "b.png", "clip.mp4", "voice.wav"}


def test_a_reference_video_defaults_to_its_own_soundtrack(r2v_workflow, base_config):
    config = base_config.merged(mode="r2v", ref_videos=("clip.mp4",))
    prompt = build(r2v_workflow, config)
    conditioning = prompt[str(N.CONDITIONING)]["inputs"]
    # Slot 1 of GetVideoComponents is the audio track of that same video.
    assert conditioning["ref_video_audios.ref_video_audio_0"] == [
        str(N.REF_VIDEO_COMPONENTS_BASE),
        1,
    ]


def test_an_explicit_soundtrack_overrides_the_video_audio(r2v_workflow, base_config):
    config = base_config.merged(
        mode="r2v", ref_videos=("clip.mp4",), ref_video_audios=("score.wav",)
    )
    prompt = build(r2v_workflow, config)
    conditioning = prompt[str(N.CONDITIONING)]["inputs"]
    assert conditioning["ref_video_audios.ref_video_audio_0"] == [
        str(N.REF_VIDEO_AUDIO_BASE),
        0,
    ]
    # The override id must never collide with a standalone audio loader.
    assert N.REF_VIDEO_AUDIO_BASE != N.REF_AUDIO_BASE
    assert prompt[str(N.REF_VIDEO_AUDIO_BASE)]["inputs"]["audio"] == "score.wav"


def test_reference_mode_keeps_the_audio_vae_for_conditioning(r2v_workflow, base_config):
    config = base_config.merged(mode="r2v", ref_images=("a.png",))
    prompt = build(r2v_workflow, config)
    assert str(N.VAE_AUDIO) in prompt
    assert prompt[str(N.CONDITIONING)]["inputs"]["audio_vae"] == [str(N.VAE_AUDIO), 0]


def test_keyframe_modes_drop_the_audio_vae(flf2v_workflow, base_config):
    prompt = build(flf2v_workflow, base_config)
    assert str(N.VAE_AUDIO) not in prompt
    assert str(N.VAE_DECODE_AUDIO) not in prompt


# --- output path -----------------------------------------------------------


def test_the_video_node_never_receives_an_audio_input(flf2v_workflow, base_config):
    prompt = build(flf2v_workflow, base_config)
    combine = prompt[str(N.VIDEO_COMBINE)]["inputs"]
    assert "audio" not in combine
    assert combine["trim_to_audio"] is False


def test_rife_and_upscaler_are_inserted_in_order(flf2v_workflow, base_config):
    prompt = build(flf2v_workflow, base_config.merged(rife=True, upscaler=True))
    assert prompt[str(N.RIFE)]["inputs"]["images"] == [str(N.VAE_DECODE), 0]
    assert prompt[str(N.UPSCALER)]["inputs"]["images"] == [str(N.RIFE), 0]
    assert prompt[str(N.VIDEO_COMBINE)]["inputs"]["images"] == [str(N.UPSCALER), 0]


def test_the_frame_rate_follows_the_interpolation_setting(flf2v_workflow, base_config):
    plain = build(flf2v_workflow, base_config)
    interpolated = build(flf2v_workflow, base_config.merged(rife=True))
    assert plain[str(N.VIDEO_COMBINE)]["inputs"]["frame_rate"] == 24
    assert interpolated[str(N.VIDEO_COMBINE)]["inputs"]["frame_rate"] == 60


def test_editor_only_nodes_never_reach_the_prompt(flf2v_workflow, base_config):
    prompt = build(flf2v_workflow, base_config)
    for node_id in N.EDITOR_ONLY_NODES:
        assert str(node_id) not in prompt


def test_the_output_tag_only_changes_the_filename(flf2v_workflow, base_config):
    first = build(flf2v_workflow, base_config, output_tag="one")
    second = build(flf2v_workflow, base_config, output_tag="two")
    prefix_key = "filename_prefix"
    assert first[str(N.VIDEO_COMBINE)]["inputs"][prefix_key] != (
        second[str(N.VIDEO_COMBINE)]["inputs"][prefix_key]
    )
    for node_id in first:
        if node_id == str(N.VIDEO_COMBINE):
            continue
        assert first[node_id] == second[node_id]


def test_an_output_tag_cannot_escape_the_output_folder():
    assert output_filename_prefix("../../etc/passwd") == "h3lab/______etc_passwd"
    assert output_filename_prefix("") == "h3lab/run"
    assert "/" not in output_filename_prefix("a/b")[len("h3lab/") :]


# --- sampling inputs -------------------------------------------------------


def test_seed_reaches_both_seed_nodes(flf2v_workflow, base_config):
    prompt = build(flf2v_workflow, base_config.merged(seed=777))
    assert prompt[str(N.SEED)]["inputs"]["seed"] == 777
    noise = prompt[str(N.NOISE)]["inputs"]["noise_seed"]
    # Either linked from the seed node, or the literal when the template has no link.
    assert noise == [str(N.SEED), 0] or noise == 777


def test_sampling_choices_reach_their_nodes(flf2v_workflow, base_config):
    config = base_config.merged(
        scheduler="karras", sampler="dpmpp_2m", steps=33, mp=1.25, duration_s=7.5
    )
    prompt = build(flf2v_workflow, config)
    assert prompt[str(N.SCHEDULER)]["inputs"]["scheduler"] == "karras"
    assert prompt[str(N.SCHEDULER)]["inputs"]["steps"] == 33
    assert prompt[str(N.SAMPLER_SELECT)]["inputs"]["sampler_name"] == "dpmpp_2m"
    assert prompt[str(N.RESOLUTION)]["inputs"]["megapixels"] == 1.25
    assert prompt[str(N.DURATION)]["inputs"]["value"] == 7.5


def test_the_prompt_text_reaches_the_prompt_node(flf2v_workflow, base_config):
    prompt = build(flf2v_workflow, base_config.merged(prompt="a single red balloon"))
    assert prompt[str(N.PROMPT)]["inputs"]["value"] == "a single red balloon"


def test_two_identical_configs_produce_identical_graphs(flf2v_workflow, base_config):
    assert build(flf2v_workflow, base_config, output_tag="x") == build(
        flf2v_workflow, base_config, output_tag="x"
    )


def test_clean_vram_inserts_both_cleanup_nodes(flf2v_workflow, base_config):
    prompt = build(flf2v_workflow, base_config.merged(clean_vram=True))
    assert prompt[str(N.VAE_DECODE)]["inputs"]["samples"] == [str(N.CLEAN_VRAM), 0]
    assert prompt[str(N.CLEAN_VRAM)]["inputs"]["anything"] == [str(N.SAMPLER), 0]
    assert prompt[str(N.GUIDER)]["inputs"]["conditioning"] == [str(N.CLEAN_TEXT_ENCODER), 0]
    assert missing_links(prompt) == []
