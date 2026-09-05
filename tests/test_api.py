"""The HTTP surface, exercised over a real ASGI transport.

Every test here sends an actual request through the app — routing, dependency resolution,
validation, and serialisation all run. Assertions are on response bodies, because a 200 with
the wrong shape is the failure the browser actually suffers from.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from typing import Any
from urllib.parse import quote

import httpx
import pytest

from h3lab.api.app import create_app
from h3lab.domain.config import GenerationConfig
from h3lab.engine.lab import Lab
from h3lab.settings import Settings

pytestmark = pytest.mark.anyio

API = "/api"
TEMPLATE_CATALOG = {
    "version": 1,
    "managed_keys": [
        "steps",
        "scheduler",
        "sampler_name",
        "turbo",
        "cache",
        "attn",
    ],
    "categories": [{"id": "essentials", "name": "Essentials"}],
    "templates": [
        {
            "id": "essentials/balanced",
            "name": "Balanced",
            "requirements": [],
            "values": {
                "steps": 24,
                "scheduler": "simple",
                "sampler_name": "euler",
                "turbo": False,
                "cache": True,
                "attn": "sol",
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
            },
        },
    ],
}
STUDIO_MANIFEST = {
    "template_catalog": TEMPLATE_CATALOG,
    "capabilities": {"turbo": True},
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def lab(lab_settings: Settings, stub) -> Iterator[Lab]:
    stub.studio_manifest = lambda: STUDIO_MANIFEST
    made = Lab(lab_settings, client=stub, start_worker=False)  # type: ignore[arg-type]
    try:
        yield made
    finally:
        made.close()


@pytest.fixture
async def client(lab: Lab) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(lab=lab, settings=lab.settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://lab") as made:
        yield made


@pytest.fixture
async def live_server(lab: Lab) -> AsyncIterator[str]:
    """The app on a real ephemeral port, for the cases a real socket is required."""
    import socket
    import threading

    import uvicorn

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    config = uvicorn.Config(
        create_app(lab=lab, settings=lab.settings),
        host="127.0.0.1",
        port=port,
        log_level="warning",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="test-uvicorn", daemon=True)
    thread.start()
    try:
        deadline = asyncio.get_running_loop().time() + 20.0
        while not server.started:
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError("the test server never came up")
            await asyncio.sleep(0.02)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)


@pytest.mark.anyio
async def test_startup_does_not_reconcile_after_the_worker_is_running(
    lab_settings: Settings,
):
    class RunningLab:
        settings = lab_settings
        runner = type("Running", (), {"running": True})()
        reconciliations = 0

        def reconcile(self):
            self.reconciliations += 1

        def close(self):
            pass

    lab = RunningLab()
    app = create_app(lab=lab, settings=lab_settings)  # type: ignore[arg-type]

    async with app.router.lifespan_context(app):
        pass

    assert lab.reconciliations == 0


@pytest.fixture
def config(lab_settings: Settings) -> GenerationConfig:
    return GenerationConfig(
        mode="flf2v",
        diffusion_model="minimax_h3_fl2va_pruned_int8_convrot.safetensors",
        prompt="a courier on a magnetic skateboard",
        first_frame="frame.png",
        steps=20,
        seed=42,
    )


def body(config: GenerationConfig, **overrides: Any) -> dict[str, Any]:
    return {"config": config.merged(**overrides).model_dump(mode="json")}


async def queue_run(client: httpx.AsyncClient, config: GenerationConfig, **overrides: Any) -> str:
    response = await client.post(f"{API}/runs", json=body(config, **overrides))
    assert response.status_code == 201, response.text
    return str(response.json()[0]["run"]["id"])


def finish(lab: Lab, run_id: str, *, sec_per_it: float | None = None, video: bool = False) -> None:
    """Put a run into the state the analysis surfaces read, without a GPU."""
    from h3lab.domain.run import Artifact, RunMetrics

    if sec_per_it is not None:
        lab.runs.update_metrics(
            run_id, RunMetrics(wall_s=sec_per_it * 20, sec_per_it=sec_per_it, steps=20)
        )
    if video:
        lab.runs.attach_artifact(
            run_id,
            Artifact(video_path=f"{run_id}.mp4", width=832, height=480, fps=24.0, frame_count=96),
        )
    lab.runs.mark_succeeded(run_id)


# --- status and vocabulary -------------------------------------------------


async def test_health_reports_the_worker_state(client: httpx.AsyncClient):
    response = await client.get(f"{API}/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["worker_alive"] is False  # this lab was started without a worker


async def test_status_counts_runs_by_state(client: httpx.AsyncClient, config):
    await queue_run(client, config)
    payload = (await client.get(f"{API}/status")).json()
    assert payload["counts"]["queued"] == 1
    assert payload["total_runs"] == 1
    assert payload["rated"] == 0
    assert "motion" in payload["criteria"]


async def test_meta_gives_the_ui_its_vocabulary(client: httpx.AsyncClient):
    payload = (await client.get(f"{API}/meta")).json()
    assert {axis["field"] for axis in payload["axes"]} >= {"cache", "steps", "diffusion_model"}
    assert payload["stars"] == {"min": 1, "max": 10}
    assert payload["defaults"]["steps"] == 20
    assert payload["field_labels"]["sol_attn"] == "Sol-Attn"
    assert payload["caches"] == ["none", "spectrum", "easy", "h3"]
    assert "form" not in payload


async def test_meta_states_what_each_mode_needs(client: httpx.AsyncClient):
    """The shell knows first_frame is mandatory for flf2v before it submits."""
    modes = {entry["mode"]: entry for entry in (await client.get(f"{API}/meta")).json()["modes"]}
    assert modes["flf2v"]["requires_all"] == ["first_frame"]
    assert modes["r2v"]["requires_any"] == ["ref_images", "ref_videos", "ref_audios"]
    assert modes["t2v"]["requires_all"] == [] and modes["t2v"]["requires_any"] == []


async def test_the_catalog_answers_even_with_comfy_offline(client: httpx.AsyncClient):
    """The form must still render when ComfyUI is down; it degrades, it does not fail."""
    response = await client.get(f"{API}/catalog")
    assert response.status_code == 200
    payload = response.json()
    assert payload["comfy_online"] is False
    assert payload["samplers"], "a fallback sampler list is required"


async def test_the_catalog_offers_a_turbo_lora_to_pick_from(client: httpx.AsyncClient):
    payload = (await client.get(f"{API}/catalog")).json()
    assert payload["turbo_loras"], "the picker needs at least the shipped LoRA"
    assert payload["default_turbo_lora"] in payload["turbo_loras"]
    assert payload["turbo_loras_source"] in {"comfy", "disk", "fallback"}
    assert payload["defaults"]["turbo_lora"] == payload["default_turbo_lora"]


async def test_meta_offers_the_turbo_lora_as_a_sweepable_axis(client: httpx.AsyncClient):
    payload = (await client.get(f"{API}/meta")).json()
    axes = {axis["field"]: axis for axis in payload["axes"]}
    assert axes["turbo_lora"]["label"] == "Turbo LoRA"
    assert axes["turbo_lora_strength"]["kind"] == "numeric"
    assert "turbo_lora" in payload["config_fields"]


async def test_a_run_queued_with_a_named_lora_reports_it_back(client: httpx.AsyncClient, config):
    turbo = config.merged(
        turbo=True, turbo_lora="minimax_h3_turbo_8step.safetensors", turbo_lora_strength=0.75
    )
    response = await client.post(f"{API}/runs", json=body(turbo))
    assert response.status_code == 201
    [view] = response.json()
    assert view["run"]["config"]["turbo_lora"] == "minimax_h3_turbo_8step.safetensors"
    assert view["run"]["config"]["turbo_lora_strength"] == 0.75
    # The LoRA says how many steps it was distilled for, so the label says 8st, not 20st.
    assert "8st" in view["run"]["label"]


async def test_a_counted_enqueue_shares_a_batch(client: httpx.AsyncClient, config):
    response = await client.post(f"{API}/runs", json={**body(config), "count": 3})
    assert response.status_code == 201
    views = response.json()
    batches = {item["run"]["batch_id"] for item in views}
    assert len(views) == 3
    assert len(batches) == 1 and None not in batches


async def test_neighbors_follow_the_listing_order(client: httpx.AsyncClient, config):
    first = await queue_run(client, config, seed=1)
    middle = await queue_run(client, config, seed=2)
    last = await queue_run(client, config, seed=3)
    payload = (await client.get(f"{API}/runs/{middle}/neighbors?sort=oldest")).json()
    assert payload["prev"]["run"]["id"] == first
    assert payload["next"]["run"]["id"] == last
    ends = (await client.get(f"{API}/runs/{first}/neighbors?sort=oldest")).json()
    assert ends["prev"] is None
    assert ends["next"]["run"]["id"] == middle


async def test_a_sweep_over_two_loras_queues_one_run_each(client: httpx.AsyncClient, config):
    """The point of the whole axis: two runs that differ only in which LoRA was loaded."""
    response = await client.post(
        f"{API}/sweeps",
        json={
            "base": config.merged(turbo=True).model_dump(mode="json"),
            "axes": [
                {"field": "turbo_lora", "values": ["a_4step.safetensors", "b_4step.safetensors"]}
            ],
        },
    )
    assert response.status_code == 201, response.text
    views = response.json()
    assert [view["run"]["config"]["turbo_lora"] for view in views] == [
        "a_4step.safetensors",
        "b_4step.safetensors",
    ]
    assert len({view["run"]["config_hash"] for view in views}) == 2


async def test_a_sweep_over_lora_strength_previews_before_it_queues(
    client: httpx.AsyncClient, config
):
    response = await client.post(
        f"{API}/sweeps/preview",
        json={
            "base": config.merged(turbo=True).model_dump(mode="json"),
            "axes": [{"field": "turbo_lora_strength", "values": [0.6, 0.8, 1.0]}],
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["count"] == 3
    assert [item["config"]["turbo_lora_strength"] for item in payload["items"]] == [0.6, 0.8, 1.0]
    assert len({item["config_hash"] for item in payload["items"]}) == 3


# --- queueing --------------------------------------------------------------


async def test_queueing_a_run_returns_the_created_view(client: httpx.AsyncClient, config):
    response = await client.post(f"{API}/runs", json=body(config))
    assert response.status_code == 201
    [view] = response.json()
    assert view["run"]["status"] == "queued"
    assert view["run"]["seq"] == 1
    assert view["run"]["config"]["prompt"] == config.prompt
    assert view["stars"] is None


async def test_queueing_several_replicates_at_once(client: httpx.AsyncClient, config):
    response = await client.post(f"{API}/runs", json={**body(config), "count": 3})
    views = response.json()
    assert len({view["run"]["id"] for view in views}) == 3
    assert len({view["run"]["config_hash"] for view in views}) == 1


async def test_a_bad_config_is_refused_with_the_field_named(client: httpx.AsyncClient, config):
    response = await client.post(
        f"{API}/runs", json={"config": {**config.model_dump(mode="json"), "steps": 0}}
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["kind"] == "invalid"
    assert any("steps" in key for key in payload["fields"])


async def test_an_unknown_config_field_is_refused(client: httpx.AsyncClient, config):
    response = await client.post(
        f"{API}/runs", json={"config": {**config.model_dump(mode="json"), "nonsense": 1}}
    )
    assert response.status_code == 422
    assert "nonsense" in json.dumps(response.json())


async def test_a_dry_run_reports_a_buildable_graph_without_queueing(
    client: httpx.AsyncClient, config
):
    response = await client.post(
        f"{API}/runs/dry-run", json={"config": config.model_dump(mode="json")}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["problems"] == []
    assert payload["graph"]["missing_links"] == []
    assert (await client.get(f"{API}/runs")).json()["total"] == 0


async def test_a_dry_run_names_a_missing_input_file(client: httpx.AsyncClient, config):
    response = await client.post(
        f"{API}/runs/dry-run",
        json={"config": config.merged(first_frame="absent.png").model_dump(mode="json")},
    )
    payload = response.json()
    assert payload["ok"] is False
    assert any("absent.png" in problem for problem in payload["problems"])


async def test_rerunning_keeps_the_origin_in_the_notes(client: httpx.AsyncClient, config):
    run_id = await queue_run(client, config)
    response = await client.post(f"{API}/runs/{run_id}/rerun", json={"overrides": {"steps": 30}})
    assert response.status_code == 201
    view = response.json()
    assert view["run"]["config"]["steps"] == 30
    assert "variant of" in view["run"]["notes"]


async def test_a_run_can_be_downloaded_as_a_loadable_workflow(
    client: httpx.AsyncClient, config
):
    """Not the API prompt. A file ComfyUI opens as the graph a person laid out."""
    run_id = await queue_run(client, config)
    response = await client.get(f"{API}/runs/{run_id}/workflow")

    assert response.status_code == 200
    assert f"{run_id}" in response.headers["content-disposition"]
    assert response.headers["content-disposition"].startswith("attachment")

    payload = response.json()
    assert payload["nodes"] and payload["links"] is not None
    assert payload["extra"]["h3lab"]["run_id"] == run_id
    assert "class_type" not in json.dumps(payload), "an API prompt is what this replaces"


async def test_the_exported_workflow_reflects_the_run_not_the_template(
    client: httpx.AsyncClient, config, stub
):
    run_id = await queue_run(client, config, interp="film", steps=33)
    payload = (await client.get(f"{API}/runs/{run_id}/workflow")).json()

    assert stub.prepare_calls[-1][1]["interpolation"] == "film"
    assert widget_of(payload, "MiniMaxH3Studio", "interpolation") == "film"
    assert widget_of(payload, "MiniMaxH3Studio", "steps") == 33


def widget_of(workflow: dict[str, Any], class_type: str, name: str) -> Any:
    """One widget value out of an exported workflow, read the way ComfyUI reads it."""
    from h3lab.comfy.workflow import static_widget_names

    node = next(item for item in workflow["nodes"] if item["type"] == class_type)
    values = node["widgets_values"]
    if isinstance(values, dict):
        return values[name]
    order = list(static_widget_names(class_type, node) or ())
    return values[order.index(name)]


async def test_exporting_a_run_that_is_not_there(client: httpx.AsyncClient):
    response = await client.get(f"{API}/runs/NOPE/workflow")
    assert response.status_code == 404
    assert response.json()["kind"] == "not_found"


async def test_asking_for_a_run_that_is_not_there(client: httpx.AsyncClient):
    response = await client.get(f"{API}/runs/NOPE")
    assert response.status_code == 404
    assert response.json() == {
        "error": "no such run",
        "detail": "run NOPE does not exist",
        "kind": "not_found",
        "fields": {"run": "NOPE"},
    }


# --- listing and filtering -------------------------------------------------


async def test_runs_are_listed_newest_first_with_a_total(client: httpx.AsyncClient, config):
    first = await queue_run(client, config, seed=1)
    second = await queue_run(client, config, seed=2)
    payload = (await client.get(f"{API}/runs")).json()
    assert payload["total"] == 2
    assert [item["run"]["id"] for item in payload["items"]] == [second, first]


async def test_listing_can_filter_by_status_and_paginate(client: httpx.AsyncClient, config):
    for seed in range(5):
        await queue_run(client, config, seed=seed)
    payload = (await client.get(f"{API}/runs", params={"status": "queued", "limit": 2})).json()
    assert payload["total"] == 5
    assert len(payload["items"]) == 2
    assert payload["limit"] == 2

    second_page = (
        await client.get(f"{API}/runs", params={"status": "queued", "limit": 2, "offset": 4})
    ).json()
    assert len(second_page["items"]) == 1


async def test_listing_rejects_an_unknown_status(client: httpx.AsyncClient):
    response = await client.get(f"{API}/runs", params={"status": "elsewhere"})
    assert response.status_code == 422
    assert response.json()["kind"] == "invalid"


async def test_a_free_text_search_matches_the_prompt(client: httpx.AsyncClient, config):
    await queue_run(client, config, prompt="a courier on a skateboard")
    await queue_run(client, config, prompt="a lighthouse in fog")
    payload = (await client.get(f"{API}/runs", params={"query": "lighthouse"})).json()
    assert payload["total"] == 1
    assert "lighthouse" in payload["items"][0]["run"]["config"]["prompt"]


async def test_flags_and_tags_survive_a_patch(client: httpx.AsyncClient, config):
    run_id = await queue_run(client, config)
    response = await client.patch(
        f"{API}/runs/{run_id}",
        json={"favourite": True, "notes": "keep this one", "tags": ["hero", "int8"]},
    )
    assert response.status_code == 200
    view = response.json()
    assert view["run"]["favourite"] is True
    assert view["run"]["notes"] == "keep this one"
    assert sorted(view["run"]["tags"]) == ["hero", "int8"]
    assert (await client.get(f"{API}/tags")).json() == ["hero", "int8"]

    only_favourites = (await client.get(f"{API}/runs", params={"favourite": True})).json()
    assert [item["run"]["id"] for item in only_favourites["items"]] == [run_id]


async def test_archiving_hides_a_run_from_the_default_list(client: httpx.AsyncClient, config):
    run_id = await queue_run(client, config)
    await client.patch(f"{API}/runs/{run_id}", json={"archived": True})
    assert (await client.get(f"{API}/runs")).json()["total"] == 0
    shown = await client.get(f"{API}/runs", params={"archived": True})
    assert shown.json()["total"] == 1


async def test_deleting_a_run_removes_it(client: httpx.AsyncClient, config):
    run_id = await queue_run(client, config)
    response = await client.delete(f"{API}/runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert (await client.get(f"{API}/runs/{run_id}")).status_code == 404


# --- the queue -------------------------------------------------------------


async def test_the_queue_lists_pending_work_oldest_first(client: httpx.AsyncClient, config):
    first = await queue_run(client, config, seed=1)
    await queue_run(client, config, seed=2)
    payload = (await client.get(f"{API}/queue")).json()
    assert payload["total"] == 2
    assert payload["queued"][0]["run"]["id"] == first
    assert payload["active"] is None
    assert payload["paused"] is False


async def test_pausing_and_resuming_is_reported_back(client: httpx.AsyncClient):
    assert (await client.post(f"{API}/queue/pause")).json()["ok"] is True
    assert (await client.get(f"{API}/queue")).json()["paused"] is True
    await client.post(f"{API}/queue/resume")
    assert (await client.get(f"{API}/queue")).json()["paused"] is False


async def test_clearing_the_queue_cancels_everything_waiting(client: httpx.AsyncClient, config):
    await queue_run(client, config, seed=1)
    await queue_run(client, config, seed=2)
    response = await client.post(f"{API}/queue/clear")
    assert response.json()["count"] == 2
    assert (await client.get(f"{API}/queue")).json()["total"] == 0
    cancelled = await client.get(f"{API}/runs", params={"status": "cancelled"})
    assert cancelled.json()["total"] == 2


async def test_cancelling_a_finished_run_says_so_rather_than_failing(
    client: httpx.AsyncClient, config, lab
):
    run_id = await queue_run(client, config)
    finish(lab, run_id)
    response = await client.post(f"{API}/runs/{run_id}/cancel")
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "already finished" in response.json()["detail"]


async def test_the_frame_comfy_is_drawing_is_served_while_the_run_renders(
    client: httpx.AsyncClient, config, lab, stub
):
    """A preview is a picture of the run in flight, so it lives with the worker, not on disk."""
    stub.preview_image = b"\xff\xd8live-frame"
    stub.block.clear()  # hold the run open, the way a GPU would
    run_id = await queue_run(client, config)
    waiting = await queue_run(client, config, seed=99)

    lab.runner.start()
    try:
        for _ in range(250):
            response = await client.get(f"{API}/runs/{run_id}/preview")
            if response.status_code == 200:
                break
            await asyncio.sleep(0.02)

        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "image/jpeg"
        assert response.headers["cache-control"] == "no-store"
        assert response.content == b"\xff\xd8live-frame"

        # A run that is only queued has nothing to show, and says so plainly.
        assert (await client.get(f"{API}/runs/{waiting}/preview")).status_code == 404
    finally:
        stub.block.set()
        lab.runner.stop()


async def test_a_run_that_is_not_rendering_has_no_preview(client: httpx.AsyncClient, config):
    run_id = await queue_run(client, config)
    response = await client.get(f"{API}/runs/{run_id}/preview")
    assert response.status_code == 404
    assert "no preview" in response.json()["detail"]


# --- sweeps ----------------------------------------------------------------


async def test_a_sweep_preview_counts_the_matrix_before_running_it(
    client: httpx.AsyncClient, config
):
    response = await client.post(
        f"{API}/sweeps/preview",
        json={
            "base": config.model_dump(mode="json"),
            "axes": [
                {"field": "cache", "values": ["none", "spectrum", "h3"]},
                {"field": "steps", "values": [20, 30]},
            ],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 6
    assert payload["combinations"] == 6
    assert payload["new_count"] == 6
    assert payload["duplicate_count"] == 0
    assert {item["config"]["cache"] for item in payload["items"]} == {"none", "spectrum", "h3"}


async def test_a_template_sweep_previews_current_and_concrete_template_values(
    client: httpx.AsyncClient,
    config,
):
    response = await client.post(
        f"{API}/sweeps/preview",
        json={
            "base": config.model_dump(mode="json"),
            "axes": [
                {
                    "field": "template",
                    "values": ["__current__", "essentials/balanced"],
                }
            ],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["count"] == 2
    current, balanced = [item["config"] for item in payload["items"]]
    assert current["steps"] == config.steps
    assert balanced["steps"] == 24
    assert balanced["scheduler"] == "simple"
    assert balanced["sampler"] == "euler"
    for field in ("prompt", "mode", "duration_s", "aspect_ratio", "seed"):
        assert balanced[field] == current[field]
    assert json.loads(current["widgets"]["h3s_ui"])["template_id"] == "__current__"
    assert (
        json.loads(balanced["widgets"]["h3s_ui"])["template_id"]
        == "essentials/balanced"
    )


async def test_running_a_template_sweep_queues_each_selected_arm(
    client: httpx.AsyncClient,
    config,
):
    response = await client.post(
        f"{API}/sweeps",
        json={
            "base": config.model_dump(mode="json"),
            "axes": [
                {
                    "field": "template",
                    "values": ["__current__", "essentials/balanced"],
                }
            ],
        },
    )

    assert response.status_code == 201, response.text
    queued = response.json()
    assert [view["run"]["config"]["steps"] for view in queued] == [20, 24]
    assert [
        json.loads(view["run"]["config"]["widgets"]["h3s_ui"])["template_id"]
        for view in queued
    ] == ["__current__", "essentials/balanced"]


async def test_current_template_sweep_queues_a_normalized_spectrum_er_sde_config(
    client: httpx.AsyncClient,
    config,
):
    base = config.model_dump(mode="json")
    base.update(
        {
            "cache": "spectrum",
            "cache_enabled": True,
            "widgets": {
                **base["widgets"],
                "er_sde": True,
                "er_sde_solver": "ER-SDE",
                "er_sde_eta": 1.0,
                "er_sde_s_noise": 1.0,
            },
        }
    )
    response = await client.post(
        f"{API}/sweeps",
        json={
            "base": base,
            "axes": [{"field": "template", "values": ["__current__"]}],
            "skip_duplicates": False,
        },
    )

    assert response.status_code == 201, response.text
    queued = response.json()[0]["run"]["config"]
    assert queued["cache"] == "none"
    assert queued["cache_enabled"] is False


@pytest.mark.parametrize(
    ("axes", "message"),
    [
        (
            [
                {"field": "template", "values": ["essentials/balanced"]},
                {"field": "steps", "values": [12, 20]},
            ],
            "steps",
        ),
        (
            [{"field": "template", "values": ["missing/template"]}],
            "missing/template",
        ),
        (
            [{"field": "template", "values": ["essentials/turbo"]}],
            "Turbo LoRA",
        ),
    ],
)
async def test_an_invalid_template_sweep_fails_before_queueing(
    client: httpx.AsyncClient,
    config,
    axes,
    message,
):
    response = await client.post(
        f"{API}/sweeps/preview",
        json={"base": config.model_dump(mode="json"), "axes": axes},
    )

    assert response.status_code == 422
    assert message in response.text


async def test_a_sweep_preview_marks_what_has_already_been_run(client: httpx.AsyncClient, config):
    await queue_run(client, config, cache="none")
    payload = (
        await client.post(
            f"{API}/sweeps/preview",
            json={
                "base": config.model_dump(mode="json"),
                "axes": [{"field": "cache", "values": ["none", "spectrum"]}],
            },
        )
    ).json()
    assert payload["count"] == 2
    assert payload["duplicate_count"] == 1
    assert payload["new_count"] == 1
    already = next(item for item in payload["items"] if item["already_ran"])
    assert already["config"]["cache"] == "none"
    assert already["existing_run_id"]


async def test_running_a_sweep_queues_the_whole_matrix(client: httpx.AsyncClient, config):
    response = await client.post(
        f"{API}/sweeps",
        json={
            "base": config.model_dump(mode="json"),
            "axes": [{"field": "cache", "values": ["none", "spectrum", "easy"]}],
        },
    )
    assert response.status_code == 201
    queued = response.json()
    assert len(queued) == 3
    assert {view["run"]["config"]["cache"] for view in queued} == {"none", "spectrum", "easy"}


async def test_a_sweep_skips_configs_already_run(client: httpx.AsyncClient, config):
    await queue_run(client, config, cache="none")
    response = await client.post(
        f"{API}/sweeps",
        json={
            "base": config.model_dump(mode="json"),
            "axes": [{"field": "cache", "values": ["none", "spectrum"]}],
        },
    )
    assert [view["run"]["config"]["cache"] for view in response.json()] == ["spectrum"]


async def test_a_sweep_on_an_unknown_field_is_refused(client: httpx.AsyncClient, config):
    response = await client.post(
        f"{API}/sweeps/preview",
        json={
            "base": config.model_dump(mode="json"),
            "axes": [{"field": "vibes", "values": [1, 2]}],
        },
    )
    assert response.status_code == 422
    assert "vibes" in json.dumps(response.json())


# --- judging ---------------------------------------------------------------


async def test_rating_a_run_shows_up_on_its_view(client: httpx.AsyncClient, config):
    run_id = await queue_run(client, config)
    response = await client.put(
        f"{API}/runs/{run_id}/rating",
        json={"stars": 8, "criteria": {"motion": 4, "adherence": 5}},
    )
    assert response.status_code == 200
    view = response.json()
    assert view["stars"] == 8
    assert view["criteria"] == {"motion": 4, "adherence": 5}
    assert (await client.get(f"{API}/runs/{run_id}")).json()["stars"] == 8


async def test_rating_twice_replaces_rather_than_duplicates(client: httpx.AsyncClient, config):
    run_id = await queue_run(client, config)
    await client.put(f"{API}/runs/{run_id}/rating", json={"stars": 3})
    await client.put(f"{API}/runs/{run_id}/rating", json={"stars": 9})
    assert (await client.get(f"{API}/runs/{run_id}")).json()["stars"] == 9
    assert (await client.get(f"{API}/status")).json()["rated"] == 1


async def test_stars_outside_the_scale_are_refused(client: httpx.AsyncClient, config):
    run_id = await queue_run(client, config)
    response = await client.put(f"{API}/runs/{run_id}/rating", json={"stars": 11})
    assert response.status_code == 422
    assert response.json()["kind"] == "invalid"


async def test_an_unknown_criterion_is_dropped_rather_than_stored(
    client: httpx.AsyncClient, config
):
    run_id = await queue_run(client, config)
    response = await client.put(
        f"{API}/runs/{run_id}/rating", json={"stars": 6, "criteria": {"vibes": 5, "motion": 3}}
    )
    assert response.json()["criteria"] == {"motion": 3}


async def test_removing_a_rating_clears_it(client: httpx.AsyncClient, config):
    run_id = await queue_run(client, config)
    await client.put(f"{API}/runs/{run_id}/rating", json={"stars": 7})
    response = await client.delete(f"{API}/runs/{run_id}/rating")
    assert response.json()["stars"] is None


async def test_a_vote_moves_the_elo_ratings_apart(client: httpx.AsyncClient, config):
    winner = await queue_run(client, config, seed=1)
    loser = await queue_run(client, config, seed=2)
    response = await client.post(
        f"{API}/votes", json={"run_a": winner, "run_b": loser, "winner": winner}
    )
    assert response.status_code == 201
    table = (await client.get(f"{API}/elo")).json()
    assert table[winner]["rating"] > table[loser]["rating"]
    assert table[winner]["games"] == 1


async def test_a_draw_is_recordable(client: httpx.AsyncClient, config):
    first = await queue_run(client, config, seed=1)
    second = await queue_run(client, config, seed=2)
    response = await client.post(
        f"{API}/votes", json={"run_a": first, "run_b": second, "winner": None}
    )
    assert response.status_code == 201
    assert response.json()["winner"] is None
    table = (await client.get(f"{API}/elo")).json()
    assert table[first]["rating"] == table[second]["rating"]


async def test_voting_for_a_run_that_is_not_in_the_pair_is_refused(
    client: httpx.AsyncClient, config
):
    first = await queue_run(client, config, seed=1)
    second = await queue_run(client, config, seed=2)
    response = await client.post(
        f"{API}/votes", json={"run_a": first, "run_b": second, "winner": "SOMEONE_ELSE"}
    )
    assert response.status_code in (400, 422)


# --- the arena -------------------------------------------------------------


async def arena_pair(
    client: httpx.AsyncClient, lab, config, **overrides: Any
) -> tuple[str, str]:
    """Two finished, watchable runs in the same pool, differing as ``overrides`` says."""
    first = await queue_run(client, config)
    second = await queue_run(client, config, **overrides)
    for run_id in (first, second):
        finish(lab, run_id, sec_per_it=10.0, video=True)
    return first, second


async def test_the_arena_offers_a_matchup_of_two_watchable_runs(
    client: httpx.AsyncClient, config, lab
):
    first, second = await arena_pair(client, lab, config, sampler="dpmpp_2m")
    response = await client.get(f"{API}/arena/next")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert {payload["a"]["run"]["id"], payload["b"]["run"]["id"]} == {first, second}
    assert payload["matchup"]["axis"] == "sampler"
    assert payload["matchup"]["seed_matched"] is True
    assert payload["matchup"]["held"]["Megapixels"] == "0.5 MP"
    assert payload["a"]["run"]["artifact"]["video_path"]


async def test_the_arena_never_offers_runs_from_different_pools(
    client: httpx.AsyncClient, config, lab
):
    """A 1 MP clip beside a 0.5 MP one asks about resolution, whatever the question said."""
    await arena_pair(client, lab, config, mp=1.0)
    response = await client.get(f"{API}/arena/next")
    assert response.status_code == 404
    body = response.json()
    assert body["kind"] == "not_found"
    assert "same" in body["detail"].lower()


async def test_a_run_the_voter_skipped_is_not_offered_again(
    client: httpx.AsyncClient, config, lab
):
    first, _second = await arena_pair(client, lab, config, sampler="dpmpp_2m")
    response = await client.get(f"{API}/arena/next", params={"exclude": first})
    assert response.status_code == 404


async def test_a_run_without_a_video_is_not_offered(client: httpx.AsyncClient, config, lab):
    first = await queue_run(client, config)
    second = await queue_run(client, config, sampler="dpmpp_2m")
    finish(lab, first, sec_per_it=10.0, video=True)
    finish(lab, second, sec_per_it=10.0, video=False)
    assert (await client.get(f"{API}/arena/next")).status_code == 404


async def test_the_standings_rank_the_setting_the_votes_chose(
    client: httpx.AsyncClient, config, lab
):
    first, second = await arena_pair(client, lab, config, sampler="dpmpp_2m")
    for _ in range(4):
        posted = await client.post(
            f"{API}/votes", json={"run_a": first, "run_b": second, "winner": second}
        )
        assert posted.status_code == 201

    payload = (await client.get(f"{API}/arena/standings")).json()
    assert payload["votes_counted"] == 4
    sampler = next(axis for axis in payload["axes"] if axis["axis"] == "sampler")
    assert sampler["standings"][0]["key"] == "dpmpp_2m"
    assert sampler["standings"][0]["rating"] > sampler["standings"][1]["rating"]
    assert sampler["standings"][0]["seed_matched"] == 4
    assert sampler["standings"][0]["mean_sec_per_it"] == 10.0
    assert sampler["verdict"]["kind"] == "winner"
    assert "dpmpp_2m" in sampler["verdict"]["reason"]
    assert payload["loadouts"][0]["games"] == 4


async def test_a_vote_across_pools_is_reported_rather_than_ranked(
    client: httpx.AsyncClient, config, lab
):
    first, second = await arena_pair(client, lab, config, mp=1.0)
    await client.post(f"{API}/votes", json={"run_a": first, "run_b": second, "winner": first})
    payload = (await client.get(f"{API}/arena/standings")).json()
    assert payload["votes_counted"] == 0
    assert payload["votes_ignored"] == 1
    assert payload["axes"] == []
    assert list(payload["ignored_reasons"]) == ["the two runs were not comparable"]


async def test_the_duel_that_ignored_fairness_is_gone(client: httpx.AsyncClient):
    assert (await client.get(f"{API}/pairs/next")).status_code == 404


# --- analysis --------------------------------------------------------------


async def test_the_leaderboard_ranks_by_the_blended_score(client: httpx.AsyncClient, config, lab):
    slow_good = await queue_run(client, config, seed=1)
    fast_bad = await queue_run(client, config, seed=2)
    finish(lab, slow_good, sec_per_it=20.0)
    finish(lab, fast_bad, sec_per_it=5.0)
    await client.put(f"{API}/runs/{slow_good}/rating", json={"stars": 9})
    await client.put(f"{API}/runs/{fast_bad}/rating", json={"stars": 2})

    quality_first = (
        await client.get(f"{API}/leaderboard", params={"quality": 1.0, "speed": 0.0})
    ).json()
    assert quality_first["entries"][0]["view"]["run"]["id"] == slow_good
    assert quality_first["entries"][0]["rank"] == 1

    speed_first = (
        await client.get(f"{API}/leaderboard", params={"quality": 0.0, "speed": 1.0})
    ).json()
    assert speed_first["entries"][0]["view"]["run"]["id"] == fast_bad


async def test_the_leaderboard_says_how_many_runs_are_unrated(
    client: httpx.AsyncClient, config, lab
):
    run_id = await queue_run(client, config)
    finish(lab, run_id, sec_per_it=9.0)
    payload = (await client.get(f"{API}/leaderboard")).json()
    assert payload["considered"] == 1
    assert payload["unrated"] == 1
    assert payload["entries"][0]["unrated"] is True


async def test_comparing_runs_names_what_differs_and_what_is_shared(
    client: httpx.AsyncClient, config
):
    first = await queue_run(client, config, cache="none", steps=20)
    second = await queue_run(client, config, cache="spectrum", steps=20)
    response = await client.get(f"{API}/compare", params=[("ids", first), ("ids", second)])
    assert response.status_code == 200
    payload = response.json()
    assert [item["run"]["id"] for item in payload["runs"]] == [first, second]
    # cache_enabled is derived from cache, so it must not be reported as a second difference.
    assert {diff["field"] for diff in payload["differences"]} == {"cache"}
    assert payload["differences"][0]["values"] == ["none", "spectrum"]
    assert payload["shared"]["Steps"] == "20"


async def test_comparing_needs_at_least_two_runs(client: httpx.AsyncClient, config):
    run_id = await queue_run(client, config)
    response = await client.get(f"{API}/compare", params={"ids": run_id})
    assert response.status_code == 422


async def test_the_available_axes_reflect_what_has_actually_varied(
    client: httpx.AsyncClient, config, lab
):
    for cache in ("none", "spectrum"):
        finish(lab, await queue_run(client, config, cache=cache), sec_per_it=10.0)
    fields = {axis["field"] for axis in (await client.get(f"{API}/insights/axes")).json()}
    assert "cache" in fields
    assert "steps" not in fields


async def test_an_insight_reports_cells_and_a_verdict(client: httpx.AsyncClient, config, lab):
    # Two seeds per side, so the paired comparison has matched groups to work from.
    plan = (("none", 1, 4, 10.0), ("none", 2, 5, 10.0), ("spectrum", 1, 8, 5.0), ("spectrum", 2, 9, 5.0))
    for cache, seed, stars, rate in plan:
        run_id = await queue_run(client, config, cache=cache, seed=seed)
        finish(lab, run_id, sec_per_it=rate)
        await client.put(f"{API}/runs/{run_id}/rating", json={"stars": stars})

    payload = (await client.get(f"{API}/insights/cache")).json()
    assert payload["axis"] == "cache"
    assert payload["label"] == "Cache"
    cells = {cell["value"]: cell for cell in payload["marginal"]}
    assert cells["spectrum"]["mean_stars"] == 8.5
    assert cells["none"]["mean_stars"] == 4.5
    assert cells["spectrum"]["n"] == 2
    assert "confounded" in payload["marginal_caveat"]
    assert payload["quality_verdict"]["kind"] == "winner"
    assert payload["quality_verdict"]["value"] == "spectrum"
    assert payload["quality_verdict"]["runner_up"] == "none"
    assert payload["speed_verdict"]["value"] == "spectrum"


async def test_an_insight_says_a_paired_comparison_held_the_seed_constant(
    client: httpx.AsyncClient, config, lab
):
    """A controlled comparison is worth more than a confounded one, so it must say which."""
    for cache, seed, stars in (("none", 1, 4), ("none", 2, 5), ("spectrum", 1, 8), ("spectrum", 2, 9)):
        run_id = await queue_run(client, config, cache=cache, seed=seed)
        finish(lab, run_id, sec_per_it=10.0)
        await client.put(f"{API}/runs/{run_id}/rating", json={"stars": stars})

    [comparison] = (await client.get(f"{API}/insights/cache")).json()["paired"]
    assert comparison["matched_on"] == "seed"
    assert comparison["controlled"] is True
    assert comparison["pair_groups"] == 2
    # The delta is a minus b, so spectrum leading none by four stars reads as -4.
    assert (comparison["value_a"], comparison["value_b"]) == ("none", "spectrum")
    assert comparison["stars"]["mean"] == -4.0
    assert comparison["stars"]["better_b"] == 2
    assert comparison["stars"]["conclusive"] is True


async def test_an_unknown_axis_is_a_clean_404(client: httpx.AsyncClient):
    response = await client.get(f"{API}/insights/vibes")
    assert response.status_code == 404
    assert response.json()["fields"]["axis"] == "vibes"


async def test_recipes_group_replicates_of_one_experiment(client: httpx.AsyncClient, config, lab):
    for seed, stars in ((1, 6), (2, 8)):
        run_id = await queue_run(client, config, seed=seed)
        finish(lab, run_id, sec_per_it=10.0)
        await client.put(f"{API}/runs/{run_id}/rating", json={"stars": stars})
    # A genuinely different recipe, so it must not join the replicate group.
    finish(lab, await queue_run(client, config, steps=30), sec_per_it=8.0)

    groups = (await client.get(f"{API}/recipes")).json()
    assert len(groups) == 2
    by_size = {group["n"]: group for group in groups}
    assert by_size[2]["mean_stars"] == 7.0
    assert by_size[2]["n_rated"] == 2
    assert len(by_size[2]["run_ids"]) == 2
    assert by_size[1]["mean_stars"] is None


# --- library ---------------------------------------------------------------


async def test_a_preset_can_be_saved_from_a_run_and_listed(client: httpx.AsyncClient, config):
    run_id = await queue_run(client, config)
    response = await client.post(f"{API}/presets", json={"name": "hero", "run_id": run_id})
    assert response.status_code == 201
    assert response.json()["name"] == "hero"
    listed = (await client.get(f"{API}/presets")).json()
    assert [preset["name"] for preset in listed] == ["hero"]
    assert listed[0]["config"]["prompt"] == config.prompt


async def test_saving_two_presets_under_one_name_is_a_conflict(client: httpx.AsyncClient, config):
    payload = {"name": "hero", "config": config.model_dump(mode="json")}
    assert (await client.post(f"{API}/presets", json=payload)).status_code == 201
    clash = await client.post(f"{API}/presets", json=payload)
    assert clash.status_code == 409
    assert clash.json()["kind"] == "conflict"


async def test_a_preset_can_be_replaced_on_purpose(client: httpx.AsyncClient, config):
    await client.post(f"{API}/presets", json={"name": "hero", "config": config.model_dump(mode="json")})
    response = await client.post(
        f"{API}/presets",
        json={
            "name": "hero",
            "config": config.merged(steps=40).model_dump(mode="json"),
            "replace": True,
        },
    )
    assert response.status_code == 201
    listed = (await client.get(f"{API}/presets")).json()
    assert len(listed) == 1
    assert listed[0]["config"]["steps"] == 40


async def test_deleting_a_preset_that_is_not_there(client: httpx.AsyncClient):
    response = await client.delete(f"{API}/presets/nope")
    assert response.status_code == 404
    assert response.json()["kind"] == "not_found"


async def test_a_preset_needs_either_a_run_or_a_config(client: httpx.AsyncClient):
    response = await client.post(f"{API}/presets", json={"name": "empty"})
    assert response.status_code == 400
    assert "needs either" in response.json()["error"]


async def test_pinning_a_baseline_marks_it_on_the_run_view(client: httpx.AsyncClient, config):
    run_id = await queue_run(client, config)
    response = await client.put(f"{API}/baseline", json={"run_id": run_id})
    assert response.json() == {"baseline_run_id": run_id}
    assert (await client.get(f"{API}/runs/{run_id}")).json()["is_baseline"] is True

    await client.put(f"{API}/baseline", json={"run_id": None})
    assert (await client.get(f"{API}/runs/{run_id}")).json()["is_baseline"] is False


async def test_pinning_a_baseline_that_does_not_exist(client: httpx.AsyncClient):
    response = await client.put(f"{API}/baseline", json={"run_id": "GHOST"})
    assert response.status_code == 404


# --- media -----------------------------------------------------------------


async def test_a_generated_video_is_served_with_its_bytes(
    client: httpx.AsyncClient, lab_settings: Settings
):
    (lab_settings.videos_dir / "clip.mp4").write_bytes(b"\x00\x01video")
    response = await client.get(f"{API}/media/videos/clip.mp4")
    assert response.status_code == 200
    assert response.content == b"\x00\x01video"
    assert response.headers["content-type"] == "video/mp4"


async def test_a_missing_video_is_a_clean_404(client: httpx.AsyncClient):
    response = await client.get(f"{API}/media/videos/absent.mp4")
    assert response.status_code == 404
    assert response.json()["kind"] == "not_found"


@pytest.mark.parametrize(
    "escape",
    [
        r"..%5C..%5Ch3lab.db",  # a backslash stays inside one path segment on Windows
        r"%2e%2e%5C%2e%2e%5C%2e%2e%5Csettings.py",
        r"..%5Cposters%5Cnot-mine.png",
    ],
)
async def test_a_media_name_that_leaves_its_folder_is_refused(
    client: httpx.AsyncClient, escape: str
):
    response = await client.get(f"{API}/media/videos/{escape}")
    assert response.status_code in {400, 404}
    assert b"SQLite" not in response.content


async def test_an_encoded_slash_never_serves_a_file_either(client: httpx.AsyncClient):
    """An encoded separator is rewritten before routing, so it simply matches nothing."""
    response = await client.get(f"{API}/media/videos/..%2f..%2fh3lab.db")
    assert response.status_code != 200
    assert b"SQLite" not in response.content


async def test_an_input_image_is_served_so_the_form_can_show_it(
    client: httpx.AsyncClient, lab_settings: Settings
):
    """Picking a frame from a list of 138 filenames is guesswork without seeing it."""
    lab_settings.comfy_input_dir.mkdir(parents=True, exist_ok=True)
    (lab_settings.comfy_input_dir / "frame.png").write_bytes(b"\x89PNGnot-really")
    response = await client.get(f"{API}/media/inputs/frame.png")
    assert response.status_code == 200
    assert response.content == b"\x89PNGnot-really"
    assert response.headers["content-type"] == "image/png"


async def test_an_input_image_is_not_cached_forever(
    client: httpx.AsyncClient, lab_settings: Settings
):
    """Unlike an artifact, an input name can be overwritten by the next upload.

    Artifact filenames carry a run id, so the same URL always means the same bytes and can be
    cached immutably. Inputs are whatever the user last dropped in the folder under that
    name, so caching one forever would show a stale frame after a re-upload.
    """
    lab_settings.comfy_input_dir.mkdir(parents=True, exist_ok=True)
    (lab_settings.comfy_input_dir / "ref.png").write_bytes(b"first")
    response = await client.get(f"{API}/media/inputs/ref.png")
    assert "immutable" not in response.headers.get("cache-control", "")


async def test_an_input_name_that_leaves_the_folder_is_refused(client: httpx.AsyncClient):
    response = await client.get(f"{API}/media/inputs/..%5C..%5Ch3lab.db")
    assert response.status_code in {400, 404}
    assert b"SQLite" not in response.content


async def test_an_input_name_with_an_ellipsis_survives_the_round_trip(
    client: httpx.AsyncClient, lab_settings: Settings
):
    """The baseline frame's real filename contains U+2026, which must not be mangled."""
    name = "Cyberpunk_courier_riding_magneti…_2K_202608070843.jpeg"
    lab_settings.comfy_input_dir.mkdir(parents=True, exist_ok=True)
    (lab_settings.comfy_input_dir / name).write_bytes(b"jpegish")
    response = await client.get(f"{API}/media/inputs/{quote(name)}")
    assert response.status_code == 200
    assert response.content == b"jpegish"


async def test_an_upload_lands_where_comfyui_will_find_it(
    client: httpx.AsyncClient, lab_settings: Settings
):
    response = await client.post(
        f"{API}/uploads", files={"file": ("ref.png", b"\x89PNG payload", "image/png")}
    )
    assert response.status_code == 201
    assert response.json() == {"name": "ref.png", "bytes": 12, "kind": "image"}
    assert (lab_settings.comfy_input_dir / "ref.png").read_bytes() == b"\x89PNG payload"


async def test_an_upload_reports_the_kind_of_field_it_can_fill(client: httpx.AsyncClient):
    """The front end offers an upload for the field being edited, so the kind has to come back."""
    for name, kind in (("clip.mp4", "video"), ("bed.wav", "audio"), ("ref.webp", "image")):
        response = await client.post(f"{API}/uploads", files={"file": (name, b"bytes")})
        assert response.status_code == 201
        assert response.json()["kind"] == kind


async def test_an_upload_of_the_wrong_kind_is_refused(client: httpx.AsyncClient):
    response = await client.post(
        f"{API}/uploads", files={"file": ("evil.exe", b"MZ", "application/octet-stream")}
    )
    assert response.status_code == 415
    assert ".exe is not accepted" in response.json()["error"]


async def test_an_upload_cannot_choose_its_own_directory(
    client: httpx.AsyncClient, lab_settings: Settings
):
    response = await client.post(
        f"{API}/uploads", files={"file": ("../../escaped.png", b"data", "image/png")}
    )
    assert response.status_code == 201
    assert response.json()["name"] == "escaped.png"
    assert (lab_settings.comfy_input_dir / "escaped.png").is_file()


# --- events ----------------------------------------------------------------


async def test_recent_events_replay_what_a_late_client_missed(client: httpx.AsyncClient, config):
    run_id = await queue_run(client, config)
    all_events = (await client.get(f"{API}/events/recent")).json()
    kinds = [event["kind"] for event in all_events]
    assert "run.created" in kinds and "queue.changed" in kinds

    created = next(event for event in all_events if event["kind"] == "run.created")
    assert created["run_id"] == run_id
    assert created["data"]["run_seq"] == 1
    assert created["seq"] == 1  # the stream position is its own counter

    after_first = (await client.get(f"{API}/events/recent", params={"after": 1})).json()
    assert [event["seq"] for event in after_first] == [
        event["seq"] for event in all_events if event["seq"] > 1
    ]


async def test_the_event_stream_replays_and_then_streams(live_server: str, lab: Lab):
    """A real SSE read over a real socket: replay first, then a live publish.

    This one cannot use the in-process transport: httpx's ASGI transport runs the app to
    completion before handing back a response, and an event stream never completes. So the
    app is served by uvicorn on a real port for this test.
    """
    lab.events.publish("lab.message", text="already happened")

    events: list[dict[str, Any]] = []
    async with (
        httpx.AsyncClient(base_url=live_server, timeout=20.0) as reader,
        reader.stream("GET", f"{API}/events", params={"after": 0}) as response,
    ):
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        async def publish_soon() -> None:
            await asyncio.sleep(0.1)
            lab.enqueue(GenerationConfig(mode="t2v", prompt="stream me"))

        publisher = asyncio.ensure_future(publish_soon())
        try:
            async with asyncio.timeout(20):
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        events.append(json.loads(line[len("data:") :]))
                        if any(item["kind"] == "run.created" for item in events):
                            break
        finally:
            publisher.cancel()

    assert events[0]["kind"] == "lab.message"
    assert events[0]["data"]["text"] == "already happened"
    created = next(item for item in events if item["kind"] == "run.created")
    assert created["run_id"]
    # The stream position must keep climbing; it is what ?after= resumes from.
    assert created["seq"] > events[0]["seq"]


async def test_the_api_answers_over_a_real_socket(live_server: str, config, lab: Lab):
    """One end-to-end pass over TCP, so nothing here depends on the in-process shortcut."""
    async with httpx.AsyncClient(base_url=live_server, timeout=20.0) as real:
        assert (await real.get(f"{API}/health")).json()["ok"] is True

        created = await real.post(f"{API}/runs", json=body(config))
        assert created.status_code == 201
        run_id = created.json()[0]["run"]["id"]

        rated = await real.put(f"{API}/runs/{run_id}/rating", json={"stars": 7})
        assert rated.json()["stars"] == 7

        listed = await real.get(f"{API}/runs", params={"min_stars": 7})
        assert [item["run"]["id"] for item in listed.json()["items"]] == [run_id]


async def test_arena_endpoints_support_min_stars_filtering(client: httpx.AsyncClient, config, lab: Lab):
    r1 = await queue_run(client, config, cache="easy")
    r2 = await queue_run(client, config, cache="h3")
    finish(lab, r1, sec_per_it=8.0, video=True)
    finish(lab, r2, sec_per_it=6.0, video=True)

    # Initially, neither is rated, so min_stars=7 returns 404 not found
    res = await client.get(f"{API}/arena/next", params={"min_stars": 7})
    assert res.status_code == 404

    # With min_stars=0 (all runs), it finds the pair
    res_all = await client.get(f"{API}/arena/next", params={"min_stars": 0})
    assert res_all.status_code == 200

    # Rate both above 7
    await client.put(f"{API}/runs/{r1}/rating", json={"stars": 8})
    await client.put(f"{API}/runs/{r2}/rating", json={"stars": 9})

    # Now min_stars=7 finds the pair
    res_filtered = await client.get(f"{API}/arena/next", params={"min_stars": 7})
    assert res_filtered.status_code == 200


# --- the built front end ---------------------------------------------------


async def test_an_unbuilt_front_end_says_how_to_build_it(client: httpx.AsyncClient):
    response = await client.get("/")
    assert response.status_code == 503
    assert "npm run build" in response.text


async def test_the_built_shell_is_served_for_a_client_route(
    client: httpx.AsyncClient, lab_settings: Settings
):
    lab_settings.web_dist.mkdir(parents=True, exist_ok=True)
    (lab_settings.web_dist / "index.html").write_text("<!doctype html><title>lab</title>")
    assets = lab_settings.web_dist / "assets"
    assets.mkdir(exist_ok=True)
    (assets / "app.js").write_text("export const ok = 1")

    shell = await client.get("/runs/anything")
    assert shell.status_code == 200
    assert "<title>lab</title>" in shell.text

    asset = await client.get("/assets/app.js")
    assert asset.status_code == 200
    assert "export const ok" in asset.text


async def test_an_unknown_api_path_does_not_fall_through_to_the_shell(
    client: httpx.AsyncClient, lab_settings: Settings
):
    lab_settings.web_dist.mkdir(parents=True, exist_ok=True)
    (lab_settings.web_dist / "index.html").write_text("<!doctype html><title>lab</title>")
    response = await client.get(f"{API}/nonsense")
    assert response.status_code == 404
    assert "<title>" not in response.text


async def test_the_openapi_document_describes_every_route(client: httpx.AsyncClient):
    document = (await client.get(f"{API}/openapi.json")).json()
    paths = document["paths"]
    assert f"{API}/runs" in paths
    assert f"{API}/insights/{{axis}}" in paths
    assert paths[f"{API}/runs"]["post"]["responses"]["201"]


@pytest.mark.parametrize(
    ("path", "expected"),
    [(f"{API}/runs", {"status", "limit", "offset", "sort"}), (f"{API}/leaderboard", {"quality", "speed", "limit"})],
)
async def test_query_models_arrive_as_plain_parameters(
    client: httpx.AsyncClient, path: str, expected: set[str]
):
    """FastAPI only flattens a query model when it is the sole query parameter.

    Adding a scalar beside one turns the whole model into a single required parameter that
    no browser would ever send, so the shape is asserted rather than assumed.
    """
    parameters = (await client.get(f"{API}/openapi.json")).json()["paths"][path]["get"][
        "parameters"
    ]
    names = {item["name"] for item in parameters}
    assert expected <= names
    assert all("$ref" not in json.dumps(item["schema"]) for item in parameters)
    assert not any(item["required"] for item in parameters)
