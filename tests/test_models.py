from bench.models import Run, RunConfig, empty_suite


def test_run_roundtrip():
    r = Run(
        id="speed_001",
        phase="speed",
        config=RunConfig(cache="none", quant="int8", sol_attn=False),
        timed_s=12.5,
        status="done",
    )
    back = Run.from_dict(r.to_dict())
    assert back.config.cache == "none"
    assert back.config.quant == "int8"
    assert back.timed_s == 12.5


def test_empty_suite_has_three_phases():
    s = empty_suite("t1", "http://127.0.0.1:8188")
    assert set(s.phases) == {"speed", "quality", "scale"}
    assert s.baseline["seed"] == 914265959575104
