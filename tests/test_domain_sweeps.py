from h3lab.domain.config import config_attention
from h3lab.domain.sweeps import SweepSpec, expand


def test_attention_is_a_sweep_axis_with_mutually_exclusive_results(base_config):
    spec = SweepSpec(
        base=base_config,
        axes=({"field": "attn", "values": ("off", "sol", "comfy_kitchen")},),
    )
    configs = expand(spec)
    assert [config_attention(config) for config in configs] == [
        "off",
        "sol",
        "comfy_kitchen",
    ]
    assert [config.sol_attn for config in configs] == [False, True, False]


def test_unknown_component_input_is_not_accepted_as_a_sweep_axis(base_config):
    try:
        SweepSpec(
            base=base_config,
            axes=({"field": "future_component_knob", "values": (1, 2)},),
        )
    except ValueError as exc:
        assert "unknown config field" in str(exc)
    else:
        raise AssertionError("unknown sweep axis was accepted")
