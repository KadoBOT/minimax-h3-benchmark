from __future__ import annotations

from pathlib import Path

from h3lab.settings import (
    DEFAULT_COMFY_URL,
    DEFAULT_PORT,
    Settings,
    classify_h3_workflow,
    resolve_workflow_path,
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


def test_unified_graph_is_the_exact_name_for_every_mode(tmp_path: Path):
    unified = tmp_path / "minimax_h3_unified.json"
    t2v = tmp_path / "minimax_h3_t2v_workflow.json"
    graded = tmp_path / "minimax_h3_r2v_graded.v5.json"
    unified.write_text('{"nodes":[{"type":"MiniMaxH3ImageToVideo"}]}', encoding="utf-8")
    t2v.write_text('{"nodes":[{"type":"MiniMaxH3TextToVideo"}]}', encoding="utf-8")
    graded.write_text('{"nodes":[{"type":"MiniMaxH3ReferenceToVideo"}]}', encoding="utf-8")
    for mode in ("t2v", "flf2v", "r2v"):
        assert resolve_workflow_path(tmp_path, mode) == unified


def test_exact_lab_names_win_over_a_newer_classified_file(tmp_path: Path):
    exact = tmp_path / "minimax_h3_flf2v_workflow.json"
    graded = tmp_path / "minimax_h3_flf2v_graded.v4.json"
    exact.write_text('{"nodes":[{"type":"MiniMaxH3ImageToVideo"}]}', encoding="utf-8")
    graded.write_text('{"nodes":[{"type":"MiniMaxH3ImageToVideo"}]}', encoding="utf-8")
    graded.touch()
    assert resolve_workflow_path(tmp_path, "flf2v") == exact


def test_classifies_a_graded_export_by_filename_and_picks_the_newest(tmp_path: Path):
    older = tmp_path / "minimax_h3_flf2v_graded.json"
    newer = tmp_path / "minimax_h3_flf2v_graded.v4.json"
    older.write_text("{}", encoding="utf-8")
    newer.write_text("{}", encoding="utf-8")
    import os

    os.utime(older, (1_000_000_000, 1_000_000_000))
    os.utime(newer, (2_000_000_000, 2_000_000_000))
    assert resolve_workflow_path(tmp_path, "flf2v") == newer


def test_backups_are_not_templates(tmp_path: Path):
    backup = tmp_path / "_minimax_h3_t2v_workflow.json"
    backup.write_text('{"nodes":[{"type":"MiniMaxH3TextToVideo"}]}', encoding="utf-8")
    assert classify_h3_workflow(backup) is None


def test_settings_without_env_still_use_the_repo_fixtures():
    made = Settings()
    assert made.workflow_dir.name != "workflows" or made.workflow_path("t2v").is_file()
    assert made.workflow_path("t2v").name == "minimax_h3_t2v_workflow.json"


def test_with_overrides_returns_a_new_frozen_settings(tmp_path: Path):
    made = Settings()
    other = made.with_overrides(port=1234, comfy_url=None)
    assert other.port == 1234
    assert made.port == DEFAULT_PORT
    assert other.comfy_url == made.comfy_url
