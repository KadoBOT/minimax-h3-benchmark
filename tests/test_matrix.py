from bench.matrix import build_quality_runs, build_scale_runs, build_speed_runs
from bench.models import RunConfig


def test_speed_core_includes_none_and_three_caches():
    runs = build_speed_runs()
    caches = {r.config.cache for r in runs if r.config.cache_variant is None and r.config.sol_variant is None}
    # core cells have no variants
    core = [r for r in runs if not r.config.cache_variant and not r.config.sol_variant]
    core_caches = {r.config.cache for r in core}
    assert core_caches == {"none", "spectrum", "easy", "h3"}
    assert len(core) == 16  # 4*2*2
    assert any(r.config.cache_variant == "easy_aggressive" for r in runs)
    assert len(runs) == 24  # 16 + 8 variants


def test_quality_one_factor():
    base = RunConfig(cache="easy", quant="nvfp4", sol_attn=True)
    runs = build_quality_runs(base)
    assert any(r.config.scheduler == "beta" for r in runs)
    assert any(r.config.sampler == "er_sde" for r in runs)
    assert any(r.config.steps == 16 for r in runs)
    # no full factorial explosion
    assert len(runs) <= 12


def test_scale_grid():
    base = RunConfig(cache="h3", quant="int8", sol_attn=False)
    runs = build_scale_runs(base)
    assert len(runs) == 25
    mps = {r.config.mp for r in runs}
    durs = {r.config.duration_s for r in runs}
    assert mps == {0.4, 0.5, 0.6, 0.7, 0.8}
    assert durs == {4.0, 5.0, 6.0, 8.0, 10.0}
    # base speed knobs preserved
    assert all(r.config.cache == "h3" for r in runs)
