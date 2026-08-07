from bench.presets import expand_presets
from bench.models import RunConfig


def test_moderate_matches_empty_widgets_merge():
    cfg = RunConfig(cache="easy", cache_preset="moderate", sol_attn=True, sol_preset="moderate")
    w = expand_presets(cfg)
    assert "reuse_threshold" in w or w == {} or "tau" in w
    # moderate must return concrete numbers for the active cache + sol
    assert w.get("reuse_threshold") == 0.2  # EasyCache workflow default from v3


def test_aggressive_easy_and_sol():
    cfg = RunConfig(cache="easy", cache_preset="aggressive", sol_attn=True, sol_preset="aggressive")
    w = expand_presets(cfg)
    assert w["reuse_threshold"] == 0.35
    assert w["tau"] == 1.8


def test_custom_uses_cfg_widgets_only():
    cfg = RunConfig(
        cache="h3",
        cache_preset="custom",
        sol_attn=True,
        sol_preset="custom",
        widgets={"reuse_threshold": 0.07, "tau": 1.2},
    )
    w = expand_presets(cfg)
    assert w["reuse_threshold"] == 0.07
    assert w["tau"] == 1.2


def test_cache_disabled_skips_cache_keys():
    cfg = RunConfig(cache_enabled=False, cache_preset="aggressive", sol_attn=False)
    w = expand_presets(cfg)
    assert "warmup_steps" not in w
    assert "tau" not in w
