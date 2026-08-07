from bench.models import Run, RunConfig, Suite, empty_suite, migrate_suite_dict


def test_runconfig_defaults_v2():
    from bench.constants import DEFAULT_FIRST_FRAME

    c = RunConfig()
    assert c.model_path == "safetensor"
    assert c.quant == "nvfp4"
    assert c.seed == 42
    assert c.scheduler == "beta57"
    assert c.sampler == "euler"
    assert c.cache_enabled is True
    assert c.cache == "spectrum"
    assert c.cache_preset == "moderate"
    assert c.sol_attn is True
    assert c.sol_preset == "moderate"
    assert c.turbo is False
    assert c.rife is False
    assert c.upscaler is False
    assert c.clean_vram is False
    assert c.first_frame == DEFAULT_FIRST_FRAME


def test_run_roundtrip_new_fields():
    r = Run(
        id="run_001",
        phase="manual",
        config=RunConfig(model_path="gguf", turbo=True, scheduler="beta"),
        status="done",
        timed_s=10.0,
    )
    back = Run.from_dict(r.to_dict())
    assert back.config.model_path == "gguf"
    assert back.config.turbo is True
    assert back.config.scheduler == "beta"


def test_empty_suite_flat_runs():
    s = empty_suite("t1", "http://127.0.0.1:8188")
    assert s.schema_version == 2
    assert s.runs == []
    assert s.baseline["seed"] == 42
    assert s.phases == {} or "speed" not in s.phases
    assert "protocol" in s.baseline
    assert s.baseline["protocol"]["vram_clean"] is False


def test_migrate_v1_phases_to_runs():
    raw = {
        "suite_id": "old",
        "status": "completed",
        "comfy_url": "http://127.0.0.1:8188",
        "baseline": {"seed": 914265959575104},
        "phases": {
            "speed": {
                "status": "done",
                "runs": [
                    {
                        "id": "speed_001",
                        "phase": "speed",
                        "status": "done",
                        "config": {"cache": "none", "quant": "nvfp4", "sol_attn": True},
                        "timed_s": 100.0,
                    }
                ],
            },
            "quality": {"status": "done", "runs": []},
            "scale": {"status": "done", "runs": []},
        },
    }
    s = migrate_suite_dict(raw)
    assert s.schema_version == 2
    assert len(s.runs) == 1
    assert s.runs[0].id == "speed_001"
    assert s.runs[0].config.model_path == "safetensor"
    assert s.runs[0].config.cache_enabled is False
    assert s.runs[0].config.cache == "none"
    assert s.phases == {}
    dumped = s.to_dict()
    assert "runs" in dumped
    assert "phases" not in dumped


def test_run_roundtrip_legacy():
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


def test_runconfig_from_dict_ignores_unknown_and_defaults():
    c = RunConfig.from_dict({"quant": "int8", "unknown_key": 1})
    assert c.quant == "int8"
    assert c.model_path == "safetensor"
    assert c.seed == 42


def test_runconfig_cache_none_disables_cache_enabled():
    c = RunConfig(cache="none")
    assert c.cache_enabled is False
    c2 = RunConfig.from_dict({"cache": "none"})
    assert c2.cache_enabled is False
    assert c2.cache == "none"


def test_migrate_schema2_empty_runs_with_phases_flattens():
    raw = {
        "suite_id": "mixed",
        "schema_version": 2,
        "status": "completed",
        "comfy_url": "http://127.0.0.1:8188",
        "baseline": {},
        "runs": [],
        "phases": {
            "speed": {
                "status": "done",
                "runs": [
                    {
                        "id": "speed_001",
                        "phase": "speed",
                        "status": "done",
                        "config": {"cache": "easy"},
                        "timed_s": 11.0,
                    }
                ],
            }
        },
    }
    s = migrate_suite_dict(raw)
    assert s.schema_version == 2
    assert len(s.runs) == 1
    assert s.runs[0].id == "speed_001"
    assert s.phases == {}
    dumped = s.to_dict()
    assert "runs" in dumped
    assert len(dumped["runs"]) == 1
    assert "phases" not in dumped or dumped.get("phases") in (None, {})
