from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from h3lab.domain.config import (
    DEFAULT_TURBO_LORA,
    GenerationConfig,
    canonical_form,
    config_diff,
    config_hash,
    derive_label,
    field_display,
    recipe_hash,
)


def test_seed_only_change_keeps_recipe_but_changes_config_hash(base_config):
    other = base_config.merged(seed=43)
    assert recipe_hash(base_config) == recipe_hash(other)
    assert config_hash(base_config) != config_hash(other)


def test_notes_are_not_part_of_config_so_hash_is_pixel_identity(base_config):
    # label/notes live on the run, not the config: the config model forbids them outright.
    with pytest.raises(ValidationError):
        GenerationConfig(**{**base_config.model_dump(), "notes": "hello"})


def test_canonical_form_is_sorted_compact_json_of_hashed_fields_only(base_config):
    text = canonical_form(base_config)
    payload = json.loads(text)
    assert ", " not in text and '": ' not in text
    assert list(payload) == sorted(payload)
    assert "seed" in payload
    assert "seed" not in json.loads(canonical_form(base_config, exclude={"seed"}))


def test_hash_is_stable_across_equivalent_float_spellings(base_config):
    assert config_hash(base_config.merged(mp=0.5)) == config_hash(base_config.merged(mp=0.50))


def test_hash_length_is_32_hex_chars(base_config):
    digest = config_hash(base_config)
    assert len(digest) == 32
    int(digest, 16)


def test_unknown_field_is_rejected_rather_than_silently_dropped(base_config):
    with pytest.raises(ValidationError) as excinfo:
        GenerationConfig(**{**base_config.model_dump(), "schedular": "beta"})
    assert "schedular" in str(excinfo.value)


def test_flf2v_requires_a_first_frame():
    with pytest.raises(ValidationError) as excinfo:
        GenerationConfig(mode="flf2v", prompt="x")
    assert "first_frame" in str(excinfo.value)


def test_t2v_drops_frames_that_leaked_in():
    cfg = GenerationConfig(mode="t2v", prompt="x", first_frame="a.png", last_frame="b.png")
    assert cfg.first_frame == "" and cfg.last_frame == ""


def test_r2v_needs_at_least_one_reference():
    with pytest.raises(ValidationError):
        GenerationConfig(mode="r2v", prompt="x")
    cfg = GenerationConfig(mode="r2v", prompt="x", ref_images=["a.png"])
    assert cfg.ref_images == ("a.png",)


def test_reference_lists_are_clamped_to_official_limits():
    cfg = GenerationConfig(
        mode="r2v",
        prompt="x",
        ref_images=[f"img{i}.png" for i in range(20)],
        ref_videos=[f"vid{i}.mp4" for i in range(10)],
        ref_audios=[f"aud{i}.wav" for i in range(10)],
    )
    assert len(cfg.ref_images) == 9
    assert len(cfg.ref_videos) == 3
    assert len(cfg.ref_audios) == 3


def test_paths_are_reduced_to_basenames():
    cfg = GenerationConfig(
        mode="flf2v",
        prompt="x",
        first_frame=r"C:\Users\me\pics\frame.png",
        diffusion_model="/mnt/models/weights.safetensors",
    )
    assert cfg.first_frame == "frame.png"
    assert cfg.diffusion_model == "weights.safetensors"


def test_the_legacy_rife_flag_is_read_as_an_interpolation_choice():
    """Runs stored before interpolation had three answers still have to load."""
    assert GenerationConfig(mode="t2v", prompt="x", rife=True).interp == "rife"
    assert GenerationConfig(mode="t2v", prompt="x", rife=False).interp == "off"


def test_an_explicit_interpolation_choice_beats_the_legacy_flag():
    cfg = GenerationConfig(mode="t2v", prompt="x", rife=True, interp="film")
    assert cfg.interp == "film"


def test_the_legacy_flag_does_not_survive_as_a_field():
    cfg = GenerationConfig(mode="t2v", prompt="x", rife=True)
    assert "rife" not in cfg.model_dump()
    assert cfg.model_dump()["interp"] == "rife"


def test_interpolation_is_part_of_a_config_identity(base_config):
    assert config_hash(base_config.merged(interp="film")) != config_hash(base_config)
    assert config_hash(base_config.merged(interp="film")) != config_hash(
        base_config.merged(interp="rife")
    )


def test_an_unknown_interpolation_is_rejected(base_config):
    with pytest.raises(ValidationError):
        base_config.merged(interp="dain")


def test_the_studio_api_dialect_is_accepted_as_a_config(base_config):
    """A payload that speaks MiniMaxH3Studio names still becomes a lab config."""
    cfg = base_config.merged(
        duration=6.5,
        megapixels=0.9,
        sampler_name="euler",
        interpolation="none",
        mode="T2V",
        pass2_steps=7,
        dual=True,
    )
    assert cfg.duration_s == 6.5
    assert cfg.mp == 0.9
    assert cfg.sampler == "euler"
    assert cfg.interp == "off"
    assert cfg.mode == "t2v"
    assert cfg.widgets["pass2_steps"] == 7
    assert cfg.widgets["dual"] is True


def test_guides_count_as_media_the_input_folder_must_hold(base_config):
    cfg = base_config.merged(widgets={"guides": '[{"time": 0.8, "image": "beat.png"}]'})
    assert "beat.png" in cfg.media_files


def test_cache_none_and_cache_disabled_are_one_truth(base_config):
    assert base_config.merged(cache="none").cache_enabled is False
    assert base_config.merged(cache_enabled=False).cache == "none"


def test_turbo_forces_the_four_step_schedule(base_config):
    assert base_config.merged(steps=30).effective_steps == 30
    assert base_config.merged(steps=30, turbo=True).effective_steps == 4


def test_a_turbo_run_samples_at_the_step_count_its_lora_was_distilled_for(base_config):
    """A distilled LoRA is trained for one schedule and says so in its filename.

    Sampling an 8-step LoRA at four steps measures the mismatch rather than the LoRA, which
    is the one thing a benchmark comparing two of them must not do.
    """
    eight = base_config.merged(turbo=True, turbo_lora="minimax_h3_turbo_8step.safetensors")
    assert eight.effective_steps == 8
    six = base_config.merged(turbo=True, turbo_lora="MiniMax-H3-Turbo-6-Step.safetensors")
    assert six.effective_steps == 6


def test_a_turbo_run_stores_the_step_count_it_will_sample_at(base_config):
    """The field a person reads and the number the sampler is given are one number.

    `steps` is hashed, contested in the arena and printed on the run page, so a turbo run that
    kept whatever was in the box before the toggle was flipped advertises a schedule it will
    not use.
    """
    turbo = base_config.merged(steps=16, turbo=True)
    assert turbo.steps == turbo.effective_steps == 4

    eight = base_config.merged(
        steps=16, turbo=True, turbo_lora="minimax_h3_turbo_8step.safetensors"
    )
    assert eight.steps == eight.effective_steps == 8


def test_two_turbo_runs_of_one_lora_are_one_experiment_whatever_the_step_box_held(base_config):
    """The mirror of the rule that clears the LoRA when turbo is off."""
    from_twenty = base_config.merged(steps=20, turbo=True)
    from_eight = base_config.merged(steps=8, turbo=True)
    assert config_hash(from_twenty) == config_hash(from_eight)
    assert config_diff([from_twenty, from_eight]) == []


def test_a_version_number_in_a_lora_name_is_not_read_as_a_step_count(base_config):
    """`turbo_v4_step600` is version four at training step 600, not a four-step schedule."""
    config = base_config.merged(
        turbo=True, turbo_lora="minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors"
    )
    assert config.effective_steps == 4, "the lab's own default, not the 600"


def test_a_turbo_run_always_names_the_lora_it_used(base_config):
    """"" means the default file, and identity cannot be spelled two ways."""
    named = base_config.merged(turbo=True)
    assert named.turbo_lora == DEFAULT_TURBO_LORA
    assert named.turbo_lora_file == DEFAULT_TURBO_LORA
    assert config_hash(named) == config_hash(base_config.merged(turbo=True, turbo_lora=DEFAULT_TURBO_LORA))


def test_turning_turbo_off_forgets_the_lora_so_two_such_runs_are_one_experiment(base_config):
    plain = base_config.merged(turbo=False, turbo_lora="anything_4step.safetensors")
    assert plain.turbo_lora == ""
    assert plain.turbo_lora_file == ""
    assert config_hash(plain) == config_hash(base_config.merged(turbo=False))


def test_the_lora_and_its_strength_are_part_of_a_runs_identity(base_config):
    first = base_config.merged(turbo=True, turbo_lora="minimax_h3_turbo_a_4step.safetensors")
    second = base_config.merged(turbo=True, turbo_lora="minimax_h3_turbo_b_4step.safetensors")
    weaker = first.merged(turbo_lora_strength=0.6)

    assert len({config_hash(first), config_hash(second), config_hash(weaker)}) == 3
    assert {item.field for item in config_diff([first, second])} == {"turbo_lora"}
    assert {item.field for item in config_diff([first, weaker])} == {"turbo_lora_strength"}


def test_switching_turbo_on_reads_as_one_change_not_three(base_config):
    """The LoRA and its strength are derived from `turbo`, so they are not reported twice."""
    fields = {
        item.field
        for item in config_diff([base_config.merged(turbo=False), base_config.merged(turbo=True)])
    }
    assert fields == {"turbo"}


def test_a_lora_is_stored_as_a_bare_filename(base_config):
    config = base_config.merged(turbo=True, turbo_lora="E:/AI/Models/loras/minimax_h3_x.safetensors")
    assert config.turbo_lora == "minimax_h3_x.safetensors"


def test_the_label_names_the_lora_a_turbo_run_used(base_config):
    label = derive_label(7, base_config.merged(turbo=True, turbo_lora="minimax_h3_turbo_8step.safetensors"))
    assert "turbo/8step" in label
    assert "8st" in label

    stronger = derive_label(
        7,
        base_config.merged(
            turbo=True, turbo_lora="minimax_h3_turbo_8step.safetensors", turbo_lora_strength=0.5
        ),
    )
    assert "turbo/8step@0.5" in stronger


def test_blank_prompt_is_rejected(base_config):
    with pytest.raises(ValidationError):
        base_config.merged(prompt="   ")


def test_config_diff_lists_only_differing_fields(base_config):
    other = base_config.merged(cache="h3", steps=25)
    fields = {d.field for d in config_diff([base_config, other])}
    assert fields == {"cache", "steps"}


def test_config_diff_of_one_config_is_empty(base_config):
    assert config_diff([base_config]) == []


def test_field_display_renders_for_humans():
    assert field_display("turbo", True) == "on"
    assert field_display("turbo", False) == "off"
    assert field_display("ref_images", ()) == "—"
    assert field_display("ref_images", ("a.png", "b.png")) == "a.png, b.png"
    assert field_display("duration_s", 5.0) == "5s"
    assert field_display("mp", 0.5) == "0.5 MP"


def test_label_is_readable_and_carries_the_sequence(base_config):
    label = derive_label(12, base_config)
    assert label.startswith("#12 ")
    assert "spectrum/mod" in label
    assert "sol/mod" in label
    assert "20st" in label


def test_label_marks_non_default_mode(t2v_config):
    assert "t2v" in derive_label(3, t2v_config)


def test_out_of_range_numbers_are_rejected(base_config):
    with pytest.raises(ValidationError):
        base_config.merged(steps=0)
    with pytest.raises(ValidationError):
        base_config.merged(steps=500)
    with pytest.raises(ValidationError):
        base_config.merged(mp=99)
    with pytest.raises(ValidationError):
        base_config.merged(seed=-1)


def test_bounds_stay_wide_enough_to_reload_a_run_that_already_happened():
    """A config is a storage format, so its bounds can widen but must never narrow.

    Tightening `mp` to the `ResolutionSelector` node's 0.1 floor looked like a tidy fix and
    made every stored run below it unreadable — `runs.list()` raised, which took the whole
    lab down, because a run's row cannot be parsed back into the model that wrote it. What a
    particular ComfyUI install will accept is a preflight question; the model's job is to
    record faithfully what was asked for. See `preflight` for the node's real limits.
    """
    assert GenerationConfig(mode="t2v", prompt="x", mp=0.05).mp == 0.05
