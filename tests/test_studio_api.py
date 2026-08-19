from __future__ import annotations

import re
from typing import AsyncIterator, Iterator

import httpx
import pytest

from h3lab.api.app import create_app
from h3lab.comfy.graph import load_workflow
from h3lab.comfy.studio import StudioContractError
from h3lab.comfy.workflow import executable
from h3lab.engine.lab import Lab
from h3lab.settings import Settings
from tests.conftest import unified_workflow_path

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def lab(lab_settings: Settings, stub) -> Iterator[Lab]:
    stub.studio_manifest = lambda: {
        "contract_version": 1,
        "component_version": "1.1.0",
        "module_url": "/minimax_h3_studio/v1/component.js",
        "prepare_url": "/minimax_h3_studio/v1/prepare",
        "input_options": {"scheduler": ["simple", "beta57"]},
    }
    stub.studio_component = lambda: (
        b"export const studio = true;\n",
        "application/javascript; charset=utf-8",
    )
    stub.prepare_studio = lambda workflow, inputs: {
        "contract_version": 1,
        "workflow": workflow,
        "inputs": inputs,
        "capabilities": {"attn": []},
        "warnings": [],
    }
    made = Lab(lab_settings, client=stub, start_worker=False)
    try:
        yield made
    finally:
        made.close()


@pytest.fixture
async def client(lab: Lab) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app(lab=lab, settings=lab.settings))
    async with httpx.AsyncClient(transport=transport, base_url="http://lab") as made:
        yield made


async def test_session_rewrites_urls_and_preserves_manifest_metadata(
    client: httpx.AsyncClient,
):
    response = await client.get("/api/studio/session?mode=flf2v")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["contract_version"] == 1
    assert payload["module_url"] == "/api/studio/component.js"
    assert payload["prepare_url"] == "/api/studio/prepare"
    assert payload["input_options"] == {"scheduler": ["simple", "beta57"]}
    studios = [
        node
        for node in payload["workflow"].values()
        if node.get("class_type") == "MiniMaxH3Studio"
    ]
    assert len(studios) == 1
    assert "Fast Groups Muter (rgthree)" not in {
        node.get("class_type") for node in payload["workflow"].values()
    }
    assert isinstance(payload["bindings"], dict)


async def test_session_serves_the_live_save_without_a_contract(
    client: httpx.AsyncClient,
    lab: Lab,
):
    live = load_workflow(unified_workflow_path())

    def strip_tags(value):
        if isinstance(value, list):
            for child in value:
                strip_tags(child)
            return
        if not isinstance(value, dict):
            return
        if isinstance(value.get("title"), str):
            value["title"] = re.sub(r"\s*\[H3S:[^\]]+\]", "", value["title"]).strip()
        for child in value.values():
            strip_tags(child)

    strip_tags(live)
    lab.workflows.get = lambda _mode: live
    lab.workflows.contract = lambda _mode: pytest.fail("contract must not be loaded")
    expected, _graph = executable(
        live,
        widget_names=lab.runner.schemas().widget_names,
    )

    response = await client.get("/api/studio/session?mode=t2v")

    assert response.status_code == 200, response.text
    assert response.json()["workflow"] == expected


async def test_component_is_proxied_unchanged(client: httpx.AsyncClient):
    response = await client.get("/api/studio/component.js")
    assert response.status_code == 200
    assert response.content == b"export const studio = true;\n"
    assert response.headers["content-type"].startswith("application/javascript")
    assert response.headers["cache-control"] == "no-cache"


async def test_prepare_forwards_complete_inputs(client: httpx.AsyncClient, lab: Lab):
    calls = []

    def prepare(workflow, inputs):
        calls.append((workflow, inputs))
        return {
            "contract_version": 1,
            "workflow": {"prepared": {"class_type": "X", "inputs": {}}},
            "inputs": {**inputs, "attn": "off"},
            "capabilities": {"attn": []},
            "warnings": [],
        }

    lab.client.prepare_studio = prepare
    workflow = {"1": {"class_type": "MiniMaxH3Studio", "inputs": {}}}
    inputs = {"prompt": "test", "future_widget": {"value": 7}}
    response = await client.post(
        "/api/studio/prepare",
        json={"contract_version": 1, "workflow": workflow, "inputs": inputs},
    )
    assert response.status_code == 200, response.text
    assert calls == [(workflow, inputs)]
    assert response.json()["workflow"] == {
        "prepared": {"class_type": "X", "inputs": {}}
    }


async def test_invalid_mode_and_body_use_problem_shape(client: httpx.AsyncClient):
    mode = await client.get("/api/studio/session?mode=invalid")
    assert mode.status_code == 422
    assert mode.json()["kind"] == "invalid"
    body = await client.post("/api/studio/prepare", json=[])
    assert body.status_code == 422
    assert body.json()["kind"] == "invalid"


async def test_missing_contract_is_an_actionable_workflow_problem(
    client: httpx.AsyncClient,
    lab: Lab,
):
    def missing():
        raise StudioContractError(
            "contract_unavailable",
            "MiniMax H3 Studio contract v1 is not installed",
        )

    lab.client.studio_manifest = missing
    response = await client.get("/api/studio/session?mode=t2v")
    assert response.status_code == 422
    assert response.json()["kind"] == "workflow"
    assert "contract v1" in response.json()["detail"]
