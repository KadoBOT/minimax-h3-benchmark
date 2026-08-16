"""Projecting a patched prompt back into the editor's notation.

The property that matters is the round trip: whatever `apply_config` decided must survive
being written as nodes and links and read back. Anything else the projection gets right is
presentation.

Nothing here names a node id. The templates fold their pipeline into a subgraph, so the ids a
prompt uses (`169:23`) are not ids an editor file can hold; the export says which number it
gave each one and these tests follow that map rather than assuming any number.
"""

from __future__ import annotations

import pytest

from h3lab.comfy import roles as R
from h3lab.comfy.editor import exported_ids, prompt_of, to_editor_workflow
from h3lab.comfy.graph import apply_config, build, load_workflow
from h3lab.settings import Settings


@pytest.fixture(scope="module")
def flf2v_workflow():
    return load_workflow(Settings().workflow_path("flf2v"))


@pytest.fixture(scope="module")
def r2v_workflow():
    return load_workflow(Settings().workflow_path("r2v"))


def node_of(exported: dict, prompt_id: str | None) -> dict:
    """The exported node for a prompt id, or `StopIteration` when it is not in the file."""
    editor_id = exported_ids(exported).get(str(prompt_id), str(prompt_id))
    return next(
        node for node in exported["nodes"] if str(node["id"]) == str(editor_id)
    )


def ids_in(exported: dict) -> set[int]:
    return {int(node["id"]) for node in exported["nodes"]}


def test_the_exported_graph_reimports_as_the_prompt_it_came_from(flf2v_workflow, base_config):
    prompt = apply_config(flf2v_workflow, base_config.merged(interp="film"), output_tag="r1")
    exported = to_editor_workflow(flf2v_workflow, prompt)
    assert prompt_of(exported) == prompt


@pytest.mark.parametrize("interp", ["off", "film", "rife"])
def test_every_interpolation_choice_survives_the_round_trip(flf2v_workflow, base_config, interp):
    prompt = apply_config(flf2v_workflow, base_config.merged(interp=interp), output_tag="r1")
    exported = to_editor_workflow(flf2v_workflow, prompt)
    assert prompt_of(exported) == prompt


@pytest.mark.parametrize("mode", ["flf2v", "t2v", "r2v"])
def test_every_mode_round_trips(base_config, mode):
    workflow = load_workflow(Settings().workflow_path(mode))
    config = base_config.merged(
        mode=mode,
        turbo=True,
        upscaler=True,
        ref_images=("one.png",) if mode == "r2v" else (),
    )
    prompt = apply_config(workflow, config, output_tag="r1")
    exported = to_editor_workflow(workflow, prompt)
    assert prompt_of(exported) == prompt


def test_a_reference_run_round_trips_with_its_minted_loaders(r2v_workflow, base_config):
    """A reference slot the template left unwired gets a loader from `apply_config` itself.

    A node the template never held has no layout to copy, which is the case most likely to
    project badly — and the one an exported reference run depends on.
    """
    import copy

    trimmed = copy.deepcopy(r2v_workflow)
    for definition in (trimmed.get("definitions") or {}).get("subgraphs") or []:
        for node in definition.get("nodes") or []:
            if node.get("type") == "MiniMaxH3ReferenceToVideo":
                node["inputs"] = [
                    slot
                    for slot in node.get("inputs") or []
                    if not (
                        str(slot.get("name", "")).startswith("ref_images.ref_image_")
                        and str(slot["name"]).rsplit("_", 1)[1] != "0"
                    )
                ]
    config = base_config.merged(
        mode="r2v",
        ref_images=("ref0.png", "ref1.png"),
        ref_videos=("clip.mp4",),
    )
    prompt = apply_config(trimmed, config, output_tag="r2")
    exported = to_editor_workflow(trimmed, prompt)

    assert prompt_of(exported) == prompt
    minted = [key for key in prompt if key.startswith("h3:")]
    assert minted, "the template leaves a reference slot unwired, so the graph supplies one"
    drawn = [node_of(exported, key) for key in minted]
    for node in drawn:
        assert node["properties"]["Node name for S&R"] == node["type"]
        assert node["outputs"], "a minted loader has to declare the slots its links refer to"
    positions = [tuple(node["pos"]) for node in drawn]
    assert len(set(positions)) == len(positions), "minted nodes are not drawn on top of each other"


def test_the_export_is_the_editor_format_not_the_api_one(flf2v_workflow, base_config):
    prompt, _graph, roles = build(flf2v_workflow, base_config, output_tag="r1")
    exported = to_editor_workflow(flf2v_workflow, prompt)

    assert {"nodes", "links", "groups", "extra", "last_node_id", "last_link_id"} <= set(exported)
    assert all(len(edge) == 6 and isinstance(edge[0], int) for edge in exported["links"])
    combine = node_of(exported, roles.id(R.VIDEO_OUT))
    assert combine["widgets_values"]["filename_prefix"].endswith("r1")
    assert combine["widgets_values"]["frame_rate"] == 24
    assert "videopreview" not in combine["widgets_values"], "not this run's playback state"


def test_the_export_is_flat_and_keeps_no_subgraph_definitions(flf2v_workflow, base_config):
    """The prompt has no subgraphs in it, so neither has the file that describes the prompt."""
    assert flf2v_workflow["definitions"]["subgraphs"], "the fixture folds its pipeline into one"

    prompt = apply_config(flf2v_workflow, base_config, output_tag="r1")
    exported = to_editor_workflow(flf2v_workflow, prompt)

    assert "definitions" not in exported
    assert all(isinstance(node["id"], int) for node in exported["nodes"])
    assert len(ids_in(exported)) == len(exported["nodes"]), "ids are unique"


def test_the_export_keeps_the_layout_the_template_drew(flf2v_workflow, base_config):
    from h3lab.comfy.workflow import source_nodes

    prompt = apply_config(flf2v_workflow, base_config.merged(interp="rife"), output_tag="r1")
    exported = to_editor_workflow(flf2v_workflow, prompt)

    template = source_nodes(flf2v_workflow)
    editor_ids = exported_ids(exported)
    drawn = {editor_ids.get(flat, flat): node for flat, node in template.items()}
    for node in exported["nodes"]:
        original = drawn.get(node["id"]) or drawn.get(str(node["id"]))
        if original is None:
            continue  # minted; it never had a position
        assert node["pos"] == original["pos"]
        assert node["size"] == original["size"]

    inner = flf2v_workflow["definitions"]["subgraphs"][0]["groups"]
    titles = [group["title"] for group in exported["groups"]]
    assert titles == [group["title"] for group in flf2v_workflow["groups"]] + [
        group["title"] for group in inner
    ], "the boxes drawn inside the subgraph come up with its nodes"


def test_a_bypassed_node_the_run_uses_is_exported_as_running(flf2v_workflow, base_config):
    """The interpolators ship bypassed so the template's own default run is uninterpolated.

    An export that kept `mode: 4` would draw the right graph and produce a different video
    when its reader pressed Run.
    """
    from h3lab.comfy.workflow import read

    graph = read(flf2v_workflow)
    rife = R.resolve(graph).node(graph, R.RIFE)
    assert rife is not None and rife.mode == 4, "only meaningful while RIFE ships bypassed"

    prompt, _graph, roles = build(flf2v_workflow, base_config.merged(interp="rife"), output_tag="r")
    exported = to_editor_workflow(flf2v_workflow, prompt)

    assert node_of(exported, roles.id(R.RIFE))["mode"] == 0


def test_a_node_the_run_does_not_use_is_absent_from_the_export(flf2v_workflow, base_config):
    prompt, _graph, roles = build(flf2v_workflow, base_config, output_tag="r1")
    exported = to_editor_workflow(flf2v_workflow, prompt)

    assert roles.id(R.RIFE) not in prompt, "only meaningful with interpolation off"
    for role in (R.RIFE, R.FILM, R.FILM_LOADER, R.UPSCALER):
        with pytest.raises(StopIteration):
            node_of(exported, roles.id(role))


def test_notes_are_kept_and_dead_switches_are_not(flf2v_workflow, base_config):
    """A note is the template's own commentary; a bypasser drives nodes that are gone."""
    prompt = apply_config(flf2v_workflow, base_config, output_tag="r1")
    exported = to_editor_workflow(flf2v_workflow, prompt)
    types = [node["type"] for node in exported["nodes"]]

    assert "Note" in types
    assert not [name for name in types if "rgthree" in name]


def test_no_link_points_at_a_node_the_export_does_not_have(flf2v_workflow, base_config):
    prompt = apply_config(flf2v_workflow, base_config.merged(interp="rife"), output_tag="r1")
    exported = to_editor_workflow(flf2v_workflow, prompt)
    alive = ids_in(exported)

    for edge in exported["links"]:
        assert edge[1] in alive and edge[3] in alive

    linked = {edge[0] for edge in exported["links"]}
    for node in exported["nodes"]:
        for slot in node.get("inputs") or []:
            assert slot.get("link") is None or slot["link"] in linked
        for slot in node.get("outputs") or []:
            assert set(slot.get("links") or []) <= linked


def test_a_reused_output_keeps_one_link_per_consumer(flf2v_workflow, base_config):
    """The decoder's images feed the interpolator and the video node in the same graph."""
    prompt, _graph, roles = build(flf2v_workflow, base_config.merged(interp="film"), output_tag="r")
    exported = to_editor_workflow(flf2v_workflow, prompt)
    decode = node_of(exported, roles.id(R.VAE_DECODE))
    film = node_of(exported, roles.id(R.FILM))

    edges = [edge for edge in exported["links"] if edge[1] == decode["id"]]
    assert film["id"] in {edge[3] for edge in edges}
    assert len(decode["outputs"][0]["links"]) == len(edges)


def test_provenance_travels_in_the_extra_block(flf2v_workflow, base_config):
    prompt = apply_config(flf2v_workflow, base_config, output_tag="r1")
    exported = to_editor_workflow(flf2v_workflow, prompt, provenance={"run_id": "r1", "seq": 4})

    assert exported["extra"]["h3lab"]["run_id"] == "r1"
    assert exported["extra"]["h3lab"]["seq"] == 4
    assert set(flf2v_workflow["extra"]) <= set(exported["extra"]), "the template's own extra"


def test_the_id_map_names_every_node_that_could_not_keep_its_number(flf2v_workflow, base_config):
    prompt = apply_config(flf2v_workflow, base_config, output_tag="r1")
    exported = to_editor_workflow(flf2v_workflow, prompt)
    mapped = exported_ids(exported)

    composite = [key for key in prompt if not key.isdigit()]
    assert composite, "the fixture's pipeline lives in a subgraph"
    assert set(composite) <= set(mapped)
    assert len(set(mapped.values())) == len(mapped), "no two nodes were given the same number"


def test_the_template_is_not_modified_by_being_projected(flf2v_workflow, base_config):
    before = load_workflow(Settings().workflow_path("flf2v"))
    to_editor_workflow(
        flf2v_workflow, apply_config(flf2v_workflow, base_config, output_tag="r1")
    )
    assert flf2v_workflow == before
