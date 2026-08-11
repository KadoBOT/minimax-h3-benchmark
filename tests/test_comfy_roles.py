"""Role resolution: finding the pipeline without knowing any node's id."""

from __future__ import annotations

import pytest

from h3lab.comfy import roles as R
from h3lab.comfy.workflow import load_workflow, read
from h3lab.settings import Settings

MODES = ("flf2v", "t2v", "r2v")


@pytest.fixture(scope="module")
def graphs():
    settings = Settings()
    return {mode: read(load_workflow(settings.workflow_path(mode))) for mode in MODES}


@pytest.mark.parametrize("mode", MODES)
def test_every_essential_role_is_found_in_every_template(graphs, mode):
    graph = graphs[mode]
    found = R.resolve(graph)
    assert found.missing() == []


@pytest.mark.parametrize("mode", MODES)
def test_the_roles_the_lab_switches_on_are_all_found(graphs, mode):
    graph = graphs[mode]
    found = R.resolve(graph)
    for role in (
        R.TURBO_LORA,
        R.SOL_ATTN,
        R.SAGE_ATTN,
        R.SIGMA_SHIFT,
        R.CACHE_SPECTRUM,
        R.CACHE_EASY,
        R.CACHE_H3,
        R.RIFE,
        R.FILM,
        R.UPSCALER,
        R.CLEAN_VRAM,
        R.CLEAN_TEXT_ENCODER,
        R.RESOLUTION,
        R.DURATION,
        R.BASE_FPS,
        R.NOISE,
        R.VIDEO_VAE,
        R.SAMPLER_SELECT,
    ):
        assert role in found, f"{mode} has no {role}"


@pytest.mark.parametrize("mode", MODES)
def test_no_node_plays_two_parts(graphs, mode):
    found = R.resolve(graphs[mode])
    ids = list(found.found.values())
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("mode", MODES)
def test_the_two_vae_loaders_are_told_apart(graphs, mode):
    graph = graphs[mode]
    found = R.resolve(graph)
    video = found.node(graph, R.VIDEO_VAE)
    audio = found.node(graph, R.AUDIO_VAE)
    assert video is not None and audio is not None and video.id != audio.id
    assert "video" in str(video.inputs.get("vae_name", "")).lower()
    assert "audio" in str(audio.inputs.get("vae_name", "")).lower()


@pytest.mark.parametrize("mode", MODES)
def test_the_two_vram_cleaners_are_told_apart(graphs, mode):
    graph = graphs[mode]
    found = R.resolve(graph)
    text = found.node(graph, R.CLEAN_TEXT_ENCODER)
    vram = found.node(graph, R.CLEAN_VRAM)
    assert text is not None and vram is not None and text.id != vram.id
    assert text.inputs["anything"][0] == found.id(R.CONDITIONING)
    assert vram.inputs["anything"][0] == found.id(R.SAMPLER)


def test_the_first_and_last_frame_loaders_are_told_apart(graphs):
    graph = graphs["flf2v"]
    found = R.resolve(graph)
    first = found.node(graph, R.FIRST_FRAME)
    last = found.node(graph, R.LAST_FRAME)
    assert first is not None and last is not None and first.id != last.id
    assert first.title == "MS_INPUT_FIRST_FRAME"
    assert last.title == "MS_INPUT_LAST_FRAME"


def test_a_reference_template_claims_no_keyframe_loader(graphs):
    found = R.resolve(graphs["r2v"])
    assert R.FIRST_FRAME not in found
    assert R.LAST_FRAME not in found


def test_the_output_is_the_video_node_that_is_not_bypassed(graphs):
    graph = graphs["flf2v"]
    found = R.resolve(graph)
    node = found.node(graph, R.VIDEO_OUT)
    assert node is not None and not node.disabled
    assert node.title == "MS_OUTPUT_VIDEO"


@pytest.mark.parametrize("mode", MODES)
def test_the_duration_and_fps_primitives_are_told_apart(graphs, mode):
    graph = graphs[mode]
    found = R.resolve(graph)
    assert found.node(graph, R.DURATION).inputs["value"] > 0
    assert found.node(graph, R.BASE_FPS).inputs["value"] == 24


# --- resilience ------------------------------------------------------------


def test_renumbering_every_node_changes_nothing(graphs):
    """The whole point: ids are not identity."""
    workflow = load_workflow(Settings().workflow_path("flf2v"))
    before = R.resolve(read(workflow))
    graph = read(_renumber(workflow, offset=5000))
    after = R.resolve(graph)
    assert after.missing() == []
    for role in before.found:
        node = after.node(graph, role)
        assert node is not None, role
        assert node.class_type == before_class(role, before, workflow)


def before_class(role, before, workflow):
    graph = read(workflow)
    return before.node(graph, role).class_type


def _renumber(workflow: dict, *, offset: int) -> dict:
    """Add *offset* to every node id and link endpoint, inside subgraphs too."""
    import copy

    moved = copy.deepcopy(workflow)

    def shift(level: dict) -> None:
        for node in level.get("nodes") or []:
            node["id"] = int(node["id"]) + offset
        links = level.get("links")
        if isinstance(links, list):
            for link in links:
                if isinstance(link, dict):
                    for key in ("origin_id", "target_id"):
                        if link[key] >= 0:
                            link[key] += offset
                else:
                    for index in (1, 3):
                        if link[index] >= 0:
                            link[index] += offset
        for definition in (level.get("definitions") or {}).get("subgraphs") or []:
            shift(definition)

    shift(moved)
    return moved


def test_a_title_override_beats_every_guess():
    workflow = {
        "nodes": [
            {"id": 1, "type": "VAELoader", "widgets_values": ["a.safetensors"]},
            {
                "id": 2,
                "type": "VAELoader",
                "title": "MS_ROLE:audio_vae",
                "widgets_values": ["b.safetensors"],
            },
        ],
        "links": [],
    }
    graph = read(workflow)
    found = R.resolve(graph)
    assert found.id(R.AUDIO_VAE) == "2"
    assert found.how[R.AUDIO_VAE] == "title override"


def test_an_unrecognised_workflow_reports_what_is_missing():
    graph = read({"nodes": [{"id": 1, "type": "PreviewImage"}], "links": []})
    found = R.resolve(graph)
    assert set(found.missing()) == set(R.ESSENTIAL)
    rows = {row["role"]: row for row in found.report(graph)}
    assert rows[R.SAMPLER]["node"] is None
    assert rows[R.SAMPLER]["essential"] is True


def test_two_nodes_of_one_class_are_reported_as_ambiguous():
    workflow = {
        "nodes": [
            {"id": 1, "type": "KSamplerSelect", "widgets_values": ["euler"]},
            {"id": 2, "type": "KSamplerSelect", "widgets_values": ["dpmpp_2m"]},
        ],
        "links": [],
    }
    found = R.resolve(read(workflow))
    assert found.ambiguous[R.SAMPLER_SELECT] == ("1", "2")
    assert found.id(R.SAMPLER_SELECT) == "1"
