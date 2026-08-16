from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient

from h3lab.api.app import create_app
from h3lab.engine.lab import Lab
from h3lab.shared.client import SharedServiceClient
from h3lab.shared.generated_contract import WORKFLOW_ID

REVISION = f"sha256:{'a' * 64}"
ASSET_ID = "22222222-2222-4222-8222-222222222222"


def generation_document(*, state: str = "available") -> dict[str, object]:
    availability: dict[str, object] = {
        "state": state,
        "observedAt": "2026-08-15T08:00:00.000Z",
    }
    if state != "available":
        availability["reason"] = {
            "code": "comfy_unreachable",
            "detail": "ComfyUI is not reachable.",
            "retryable": True,
        }
    return {
        "protocolVersion": "1.0",
        "documentId": "minimax-h3-unified:generation",
        "schemaRevision": "h3-v1",
        "workflowId": WORKFLOW_ID,
        "workflowRevision": REVISION,
        "title": "MiniMax H3",
        "availability": availability,
        "capabilities": {
            "required": ["component.textarea", "action.submit"],
            "optional": [],
        },
        "components": [
            {
                "id": "prompt",
                "kind": "textarea",
                "binding": "prompt",
                "label": "Prompt",
                "required": True,
                "optional": False,
                "defaultValue": "",
            }
        ],
        "actions": [
            {
                "id": "generate",
                "kind": "submit",
                "label": "Generate",
                "endpoint": f"/v1/workflows/{WORKFLOW_ID}/jobs",
                "method": "POST",
                "optional": False,
            }
        ],
    }


def make_client(settings, stub, handler) -> tuple[TestClient, SharedServiceClient, Lab]:
    shared = SharedServiceClient(
        "http://shared.internal",
        transport=httpx.MockTransport(handler),
    )
    lab = Lab(settings, client=stub, start_worker=False)
    app = create_app(lab=lab, settings=settings, shared_client=shared)
    return TestClient(app), shared, lab


def test_generation_proxy_rewrites_submit_and_preserves_disabled_state(settings, stub):
    state = "disabled"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v1/workflows/{WORKFLOW_ID}/views/generation"
        return httpx.Response(200, json=generation_document(state=state))

    browser, shared, lab = make_client(settings, stub, handler)
    try:
        with browser:
            response = browser.get("/api/shared/generation")
        assert response.status_code == 200
        body = response.json()
        assert body["availability"]["state"] == "disabled"
        assert body["actions"][0]["endpoint"] == "/api/runs"
        assert "shared.internal" not in response.text
    finally:
        shared.close()
        lab.close()


def test_generation_proxy_translates_typed_upstream_problem(settings, stub):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={
                "type": "https://comfyui-sdui.local/problems/comfy-unavailable",
                "title": "ComfyUI unavailable",
                "status": 503,
                "detail": "ComfyUI is not reachable.",
                "code": "comfy_unavailable",
                "retryable": True,
            },
        )

    browser, shared, lab = make_client(settings, stub, handler)
    try:
        with browser:
            response = browser.get("/api/shared/generation")
        assert response.status_code == 503
        assert response.json() == {
            "error": "ComfyUI unavailable",
            "detail": "ComfyUI is not reachable.",
            "kind": "shared_unavailable",
            "fields": {},
            "code": "comfy_unavailable",
            "retryable": True,
            "errors": [],
        }
        assert "shared.internal" not in response.text
    finally:
        shared.close()
        lab.close()


def test_asset_upload_and_content_are_streamed_through_safe_same_origin_routes(
    settings, stub
):
    payload = b"\x89PNG\r\n\x1a\nopaque-image"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            assert request.url.path == "/v1/assets"
            assert payload in request.read()
            return httpx.Response(
                201,
                json={
                    "id": ASSET_ID,
                    "kind": "asset",
                    "mediaKind": "image",
                    "mime": "image/png",
                    "size": len(payload),
                    "digest": f"sha256:{'b' * 64}",
                    "filename": "frame.png",
                    "contentUrl": f"/v1/assets/{ASSET_ID}/content",
                },
            )
        assert request.url.path == f"/v1/assets/{ASSET_ID}/content"
        assert request.headers["range"] == "bytes=0-7"
        return httpx.Response(
            206,
            content=payload[:8],
            headers={
                "Content-Type": "image/png",
                "Content-Range": f"bytes 0-7/{len(payload)}",
                "Accept-Ranges": "bytes",
                "ETag": '"asset-v1"',
                "Set-Cookie": "must-not-leak=1",
            },
        )

    browser, shared, lab = make_client(settings, stub, handler)
    try:
        with browser:
            upload = browser.post(
                "/api/shared/assets",
                files={"file": ("frame.png", payload, "image/png")},
            )
            assert upload.status_code == 201
            metadata = upload.json()
            assert metadata["id"] == ASSET_ID
            assert metadata["contentUrl"] == f"/api/shared/assets/{ASSET_ID}/content"
            assert "shared.internal" not in json.dumps(metadata)

            content = browser.get(
                f"/api/shared/assets/{ASSET_ID}/content",
                headers={"Range": "bytes=0-7"},
            )
        assert content.status_code == 206
        assert content.content == payload[:8]
        assert content.headers["content-range"] == f"bytes 0-7/{len(payload)}"
        assert content.headers["accept-ranges"] == "bytes"
        assert "set-cookie" not in content.headers
    finally:
        shared.close()
        lab.close()
