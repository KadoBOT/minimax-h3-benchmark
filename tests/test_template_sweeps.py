import pytest

from h3lab.comfy.studio import studio_inputs
from h3lab.comfy.template_sweeps import make_template_resolver
from h3lab.domain.config import CURRENT_TEMPLATE_ID, config_hash
from h3lab.domain.sweeps import SweepAxis, SweepSpec, expand


CATALOG = {
    "version": 1,
    "managed_keys": [
        "steps",
        "scheduler",
        "sampler_name",
        "turbo",
        "cache",
        "attn",
        "upscale_rtx",
    ],
    "categories": [{"id": "essentials", "name": "Essentials"}],
    "templates": [
        {
            "id": "essentials/balanced",
            "name": "Balanced",
            "requirements": [],
            "values": {
                "steps": 20,
                "scheduler": "simple",
                "sampler_name": "euler",
                "turbo": False,
                "cache": True,
                "attn": "sol",
                "upscale_rtx": False,
            },
        },
        {
            "id": "essentials/turbo",
            "name": "Turbo",
            "requirements": [
                {
                    "kind": "input_not",
                    "key": "turbo_lora",
                    "value": "none",
                    "message": "Select a Turbo LoRA first.",
                }
            ],
            "values": {
                "steps": 4,
                "scheduler": "simple",
                "sampler_name": "euler",
                "turbo": True,
                "cache": True,
                "attn": "sol",
                "upscale_rtx": False,
            },
        },
        {
            "id": "finishing/rtx",
            "name": "RTX",
            "requirements": [
                {
                    "kind": "capability",
                    "key": "upscale_rtx",
                    "value": True,
                    "message": "RTX upscaling is unavailable.",
                }
            ],
            "values": {
                "steps": 20,
                "scheduler": "simple",
                "sampler_name": "euler",
                "turbo": False,
                "cache": True,
                "attn": "sol",
                "upscale_rtx": True,
            },
        },
    ],
}


def manifest(*, rtx=True):
    return {
        "template_catalog": CATALOG,
        "capabilities": {"upscale_rtx": rtx},
    }


def template_spec(base_config, *template_ids, axes=()):
    return SweepSpec(
        base=base_config,
        axes=(
            SweepAxis(field="template", values=template_ids),
            *axes,
        ),
    )


def test_template_axis_expands_current_and_packaged_values(base_config):
    spec = template_spec(
        base_config,
        CURRENT_TEMPLATE_ID,
        "essentials/balanced",
    )
    resolver = make_template_resolver(manifest(), spec)
    current, balanced = expand(spec, template_resolver=resolver)

    assert studio_inputs(current)["steps"] == base_config.steps
    assert studio_inputs(balanced)["steps"] == 20
    assert studio_inputs(balanced)["scheduler"] == "simple"
    assert studio_inputs(balanced)["sampler_name"] == "euler"
    assert balanced.prompt == base_config.prompt
    assert balanced.mode == base_config.mode
    assert balanced.duration_s == base_config.duration_s
    assert balanced.aspect_ratio == base_config.aspect_ratio
    assert balanced.seed == base_config.seed
    assert config_hash(current) == config_hash(base_config)
    assert '"source":"sweep"' in current.widgets["h3s_ui"]
    assert '"template_id":"essentials/balanced"' in balanced.widgets["h3s_ui"]


def test_template_axis_applies_before_a_non_overlapping_axis(base_config):
    spec = template_spec(
        base_config,
        "essentials/balanced",
        axes=(SweepAxis(field="mp", values=(0.5, 1.0)),),
    )
    configs = expand(spec, template_resolver=make_template_resolver(manifest(), spec))

    assert [config.mp for config in configs] == [0.5, 1.0]
    assert all(config.steps == 20 for config in configs)


@pytest.mark.parametrize(
    ("field", "values"),
    [
        ("steps", (10, 20)),
        ("turbo_lora", ("a.safetensors", "b.safetensors")),
        ("cache_preset", ("conservative", "moderate")),
        ("sol_preset", ("conservative", "moderate")),
        ("sla", (False, True)),
    ],
)
def test_template_axis_rejects_managed_and_dependent_axes(
    base_config,
    field,
    values,
):
    spec = template_spec(
        base_config,
        "essentials/balanced",
        axes=(SweepAxis(field=field, values=values),),
    )

    with pytest.raises(ValueError, match=field):
        make_template_resolver(manifest(), spec)


def test_template_axis_rejects_an_unknown_id(base_config):
    spec = template_spec(base_config, "missing/template")

    with pytest.raises(ValueError, match="missing/template"):
        make_template_resolver(manifest(), spec)


def test_template_axis_rejects_an_unmet_input_requirement(base_config):
    spec = template_spec(base_config, "essentials/turbo")
    resolver = make_template_resolver(manifest(), spec)

    with pytest.raises(ValueError, match="Turbo LoRA"):
        expand(spec, template_resolver=resolver)


def test_template_axis_rejects_an_unmet_capability(base_config):
    spec = template_spec(base_config, "finishing/rtx")
    resolver = make_template_resolver(manifest(rtx=False), spec)

    with pytest.raises(ValueError, match="RTX upscaling"):
        expand(spec, template_resolver=resolver)


def test_template_axis_requires_a_catalog_resolver(base_config):
    spec = template_spec(base_config, "essentials/balanced")

    with pytest.raises(ValueError, match="template catalog"):
        expand(spec)
