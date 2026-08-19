from __future__ import annotations

from pathlib import Path

from h3lab.settings import (
    DEFAULT_COMFY_WORKFLOW_DIR,
    DEFAULT_COMFY_URL,
    DEFAULT_PORT,
    Settings,
    UNIFIED_WORKFLOW_NAME,
)


def test_defaults_preserve_the_previous_behaviour():
    made = Settings()
    assert made.comfy_url == DEFAULT_COMFY_URL
    assert made.port == DEFAULT_PORT
    assert made.data_dir.name == "results"
    assert made.db_path.name == "h3lab.db"


def test_environment_overrides_defaults():
    made = Settings.from_env({"H3LAB_COMFY_URL": "http://box:9000", "H3LAB_PORT": "9999"})
    assert made.comfy_url == "http://box:9000"
    assert made.port == 9999


def test_explicit_override_beats_the_environment():
    made = Settings.from_env({"H3LAB_PORT": "9999"}, port=4321)
    assert made.port == 4321


def test_none_overrides_are_ignored_so_unset_cli_flags_do_not_clobber():
    made = Settings.from_env({"H3LAB_PORT": "9999"}, port=None, comfy_url=None)
    assert made.port == 9999
    assert made.comfy_url == DEFAULT_COMFY_URL


def test_malformed_numeric_environment_value_does_not_crash_startup():
    made = Settings.from_env({"H3LAB_PORT": "not-a-number"})
    assert made.port == DEFAULT_PORT


def test_paths_from_environment_are_expanded_to_path_objects(tmp_path: Path):
    made = Settings.from_env({"H3LAB_DATA_DIR": str(tmp_path / "lab")})
    assert made.data_dir == tmp_path / "lab"
    assert made.videos_dir == tmp_path / "lab" / "videos"


def test_ensure_dirs_creates_every_media_directory(tmp_path: Path):
    made = Settings(data_dir=tmp_path / "lab")
    made.ensure_dirs()
    for directory in made.media_dirs:
        assert directory.is_dir()


def test_settings_without_env_use_the_live_comfyui_workflow_directory():
    made = Settings()
    assert made.workflow_dir == DEFAULT_COMFY_WORKFLOW_DIR
    assert made.workflow_path("t2v") == DEFAULT_COMFY_WORKFLOW_DIR / UNIFIED_WORKFLOW_NAME
    assert made.workflow_path("flf2v") == made.workflow_path("r2v")


def test_configured_directory_has_no_fixture_or_legacy_fallback(tmp_path: Path):
    exact = tmp_path / "minimax_h3_t2v_workflow.json"
    exact.write_text("{}", encoding="utf-8")
    made = Settings(workflow_dir=tmp_path)

    for mode in ("t2v", "flf2v", "r2v"):
        assert made.workflow_path(mode) == tmp_path / UNIFIED_WORKFLOW_NAME


def test_with_overrides_returns_a_new_frozen_settings(tmp_path: Path):
    made = Settings()
    other = made.with_overrides(port=1234, comfy_url=None)
    assert other.port == 1234
    assert made.port == DEFAULT_PORT
    assert other.comfy_url == made.comfy_url
