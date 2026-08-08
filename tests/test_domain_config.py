from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from h3lab.domain.config import (
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


def test_cache_none_and_cache_disabled_are_one_truth(base_config):
    assert base_config.merged(cache="none").cache_enabled is False
    assert base_config.merged(cache_enabled=False).cache == "none"


def test_turbo_forces_the_four_step_schedule(base_config):
    assert base_config.merged(steps=30).effective_steps == 30
    assert base_config.merged(steps=30, turbo=True).effective_steps == 4


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
