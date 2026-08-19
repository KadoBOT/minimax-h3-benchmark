from __future__ import annotations

import json

import httpx
import pytest

from h3lab.comfy.client import ComfyClient, ComfyError
from h3lab.comfy.studio import (
    STUDIO_CONTRACT_VERSION,
    StudioContractError,
    find_studio_node,
)


def client_for(handler) -> ComfyClient:
    client = ComfyClient("http://comfy.test")
    client._http.close()
    client._http = httpx.Client(
        base_url="http://comfy.test",
        transport=httpx.MockTransport(handler),
    )
    return client


def response(status: int, payload=None, *, content=b"", content_type="application/json"):
    if payload is not None:
        content = json.dumps(payload).encode()
    return httpx.Response(status, content=content, headers={"content-type": content_type})


def test_manifest_get_preserves_additive_fields():
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/minimax_h3_studio/v1/manifest"
        return response(200, {
            "contract_version": 1,
            "component_version": "1.1.0",
            "module_url": "/minimax_h3_studio/v1/component.js",
            "prepare_url": "/minimax_h3_studio/v1/prepare",
            "input_options": {"scheduler": ["simple"]},
        })

    with client_for(handler) as client:
        manifest = client.studio_manifest()
    assert manifest["input_options"] == {"scheduler": ["simple"]}


def test_component_returns_exact_bytes_and_content_type():
    source = b"export const answer = 42;\n"

    def handler(request):
        assert request.url.path == "/minimax_h3_studio/v1/component.js"
        return response(
            200,
            content=source,
            content_type="application/javascript; charset=utf-8",
        )

    with client_for(handler) as client:
        body, content_type = client.studio_component()
    assert body == source
    assert content_type == "application/javascript; charset=utf-8"


def test_prepare_posts_exact_envelope_and_validates_response():
    workflow = {"1": {"class_type": "MiniMaxH3Studio", "inputs": {}}}
    inputs = {"attn": "off"}

    def handler(request):
        assert request.url.path == "/minimax_h3_studio/v1/prepare"
        assert json.loads(request.content) == {
            "contract_version": STUDIO_CONTRACT_VERSION,
            "workflow": workflow,
            "inputs": inputs,
        }
        return response(200, {
            "contract_version": 1,
            "workflow": workflow,
            "inputs": inputs,
            "capabilities": {"attn": []},
            "warnings": [],
        })

    with client_for(handler) as client:
        prepared = client.prepare_studio(workflow, inputs)
    assert prepared["workflow"] == workflow
    assert prepared["inputs"] == inputs


def test_prepare_preserves_structured_contract_error():
    def handler(_request):
        return response(422, {
            "error": {
                "code": "ambiguous_role",
                "message": "cache role is ambiguous",
                "details": {"node_ids": ["1", "2"]},
            }
        })

    with client_for(handler) as client:
        with pytest.raises(StudioContractError) as caught:
            client.prepare_studio({}, {})
    assert caught.value.code == "ambiguous_role"
    assert caught.value.details == {"node_ids": ["1", "2"]}


@pytest.mark.parametrize("method", ["studio_manifest", "prepare_studio"])
def test_missing_contract_route_is_definitive(method):
    with client_for(lambda _request: response(404, {"error": "missing"})) as client:
        args = ({}, {}) if method == "prepare_studio" else ()
        with pytest.raises(StudioContractError) as caught:
            getattr(client, method)(*args)
    assert caught.value.code == "contract_unavailable"


def test_unknown_major_is_definitive():
    with client_for(lambda _request: response(200, {
        "contract_version": 2,
        "module_url": "/component.js",
        "prepare_url": "/prepare",
    })) as client:
        with pytest.raises(StudioContractError) as caught:
            client.studio_manifest()
    assert caught.value.code == "contract_unavailable"


def test_transport_failure_remains_retryable_comfy_error():
    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    with client_for(handler) as client:
        with pytest.raises(ComfyError):
            client.studio_manifest()


def test_find_studio_node_requires_exactly_one():
    workflow = {"7": {"class_type": "MiniMaxH3Studio", "inputs": {"prompt": "x"}}}
    node_id, studio = find_studio_node(workflow)
    assert node_id == "7"
    assert studio["inputs"]["prompt"] == "x"
    assert find_studio_node({}, required=False) is None
    with pytest.raises(StudioContractError, match="no MiniMaxH3Studio"):
        find_studio_node({})
    with pytest.raises(StudioContractError, match="2 MiniMaxH3Studio"):
        find_studio_node({"1": workflow["7"], "2": workflow["7"]})


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"contract_version": 1, "workflow": [], "inputs": {}},
        {"contract_version": 1, "workflow": {}, "inputs": []},
    ],
)
def test_malformed_prepare_response_is_rejected(payload):
    with client_for(lambda _request: response(200, payload)) as client:
        with pytest.raises(StudioContractError, match="prepare response"):
            client.prepare_studio({}, {})
