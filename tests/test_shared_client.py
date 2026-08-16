from __future__ import annotations

import io
import json

import httpx
import pytest

from h3lab.shared.client import (
    SharedProtocolError,
    SharedResponseTooLarge,
    SharedServiceClient,
    SharedServiceError,
    SharedServiceUnavailable,
    SharedSubmissionUncertain,
)
from h3lab.shared.contracts import JobSubmission
from h3lab.shared.generated_contract import PROTOCOL_VERSION, WORKFLOW_ID

REVISION = f"sha256:{'a' * 64}"
JOB_ID = "11111111-1111-4111-8111-111111111111"
ASSET_ID = "22222222-2222-4222-8222-222222222222"


def generation_document(*, endpoint: str | None = None) -> dict[str, object]:
    return {
        "protocolVersion": "1.0",
        "documentId": "minimax-h3-unified:generation",
        "schemaRevision": "h3-v1",
        "workflowId": WORKFLOW_ID,
        "workflowRevision": REVISION,
        "title": "MiniMax H3",
        "availability": {
            "state": "available",
            "observedAt": "2026-08-15T08:00:00.000Z",
        },
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
                "endpoint": endpoint or f"/v1/workflows/{WORKFLOW_ID}/jobs",
                "method": "POST",
                "optional": False,
            }
        ],
    }


def public_job(state: str = "queued") -> dict[str, object]:
    return {
        "id": JOB_ID,
        "workflowId": WORKFLOW_ID,
        "workflowRevision": REVISION,
        "schemaRevision": "h3-v1",
        "state": state,
        "version": 1,
        "createdAt": "2026-08-15T08:00:00.000Z",
        "updatedAt": "2026-08-15T08:00:01.000Z",
        "provenance": {
            "manifestDigest": f"sha256:{'b' * 64}",
            "compiler": {"id": "minimax-h3", "version": "1"},
            "catalogRevision": f"sha256:{'c' * 64}",
            "inputDigest": f"sha256:{'d' * 64}",
            "resolvedSeed": 42,
        },
        "links": {
            "self": f"/v1/jobs/{JOB_ID}",
            "view": f"/v1/jobs/{JOB_ID}/view",
            "events": f"/v1/jobs/{JOB_ID}/events",
            "cancel": f"/v1/jobs/{JOB_ID}/cancel",
        },
    }


def problem(status: int = 503) -> dict[str, object]:
    return {
        "type": "https://comfyui-sdui.local/problems/comfy-unavailable",
        "title": "ComfyUI unavailable",
        "status": status,
        "detail": "ComfyUI is not reachable.",
        "code": "comfy_unavailable",
        "retryable": True,
    }


def client(handler, **options: object) -> SharedServiceClient:
    return SharedServiceClient(
        "http://shared.test",
        transport=httpx.MockTransport(handler),
        **options,
    )


def test_generation_sends_exact_negotiation_and_validates_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == f"/v1/workflows/{WORKFLOW_ID}/views/generation"
        assert request.headers["x-sdui-protocol-version"] == PROTOCOL_VERSION
        capabilities = request.headers["x-sdui-capabilities"].split(",")
        assert "component.textarea" in capabilities
        assert "component.video" in capabilities
        assert "action.submit" in capabilities
        return httpx.Response(200, json=generation_document())

    with client(handler) as shared:
        document = shared.get_generation_document()
    assert document.workflow_revision == REVISION


def test_create_job_sends_consumer_idempotency_and_pinned_submission():
    submission = JobSubmission(
        workflowRevision=REVISION,
        schemaRevision="h3-v1",
        input={"prompt": "A lighthouse", "seed": 42},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == f"/v1/workflows/{WORKFLOW_ID}/jobs"
        assert request.headers["x-consumer-id"] == "h3-test"
        assert request.headers["idempotency-key"] == "run-01"
        assert json.loads(request.content) == submission.model_dump(by_alias=True)
        return httpx.Response(
            201,
            json=public_job(),
            headers={"Idempotency-Replayed": "false", "Location": f"/v1/jobs/{JOB_ID}"},
        )

    with client(handler) as shared:
        result = shared.create_job(submission, idempotency_key="run-01")
    assert result.replayed is False
    assert result.job.provenance and result.job.provenance.resolved_seed == 42


def test_typed_problem_and_malformed_or_oversized_json_are_rejected():
    def refused(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json=problem())

    with client(refused) as shared, pytest.raises(SharedServiceError) as raised:
        shared.get_job(JOB_ID)
    assert raised.value.problem.code == "comfy_unavailable"
    assert raised.value.problem.retryable is True

    with (
        client(lambda _request: httpx.Response(200, content=b"{not-json")) as shared,
        pytest.raises(SharedProtocolError),
    ):
        shared.get_job(JOB_ID)

    with (
        client(
            lambda _request: httpx.Response(
                200,
                content=b"{}" * 100,
                headers={"Content-Length": "200"},
            ),
            max_json_bytes=64,
        ) as shared,
        pytest.raises(SharedResponseTooLarge),
    ):
        shared.get_job(JOB_ID)


def test_redirects_and_unsafe_returned_paths_never_escape_the_service():
    with (
        client(
            lambda _request: httpx.Response(
                302, headers={"Location": "https://attacker.invalid"}
            )
        ) as shared,
        pytest.raises(SharedProtocolError),
    ):
        shared.get_job(JOB_ID)

    with (
        client(
            lambda _request: httpx.Response(
                200,
                json=generation_document(endpoint="//attacker.invalid/jobs"),
            )
        ) as shared,
        pytest.raises(SharedProtocolError),
    ):
        shared.get_generation_document()

    with (
        client(lambda _request: httpx.Response(200, content=b"x")) as shared,
        pytest.raises(ValueError),
    ):
        shared.read_content("//attacker.invalid/video")

    wrong_identity = public_job()
    wrong_identity["links"] = {
        **wrong_identity["links"],
        "self": "/api/runs/not-the-upstream-job/shared",
    }
    with (
        client(lambda _request: httpx.Response(200, json=wrong_identity)) as shared,
        pytest.raises(SharedProtocolError, match="identity"),
    ):
        shared.get_job(JOB_ID)


def test_transport_failures_distinguish_safe_reads_from_uncertain_submission():
    def disconnected(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    with client(disconnected) as shared:
        with pytest.raises(SharedServiceUnavailable):
            shared.get_generation_document()
        with pytest.raises(SharedSubmissionUncertain):
            shared.create_job(
                JobSubmission(
                    workflowRevision=REVISION,
                    schemaRevision="h3-v1",
                    input={"prompt": "x"},
                ),
                idempotency_key="run-02",
            )


def test_upload_and_bounded_content_preserve_opaque_media_metadata():
    image = b"\x89PNG\r\n\x1a\nfixture"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            assert request.url.path == "/v1/assets"
            assert b'filename="frame.png"' in request.content
            assert image in request.content
            return httpx.Response(
                201,
                json={
                    "id": ASSET_ID,
                    "kind": "asset",
                    "mediaKind": "image",
                    "mime": "image/png",
                    "size": len(image),
                    "digest": f"sha256:{'e' * 64}",
                    "filename": "frame.png",
                    "contentUrl": f"/v1/assets/{ASSET_ID}/content",
                },
            )
        assert request.headers["range"] == "bytes=0-7"
        return httpx.Response(
            206,
            content=image[:8],
            headers={
                "Content-Type": "image/png",
                "Content-Range": f"bytes 0-7/{len(image)}",
            },
        )

    with client(handler, max_media_bytes=32) as shared:
        metadata = shared.upload_asset(
            io.BytesIO(image), filename="frame.png", mime="image/png"
        )
        content = shared.read_content(metadata.content_url, range_header="bytes=0-7")
    assert metadata.id == ASSET_ID
    assert content.status_code == 206
    assert content.body == image[:8]

    with (
        client(
            lambda _request: httpx.Response(200, content=b"x" * 33),
            max_media_bytes=32,
        ) as shared,
        pytest.raises(SharedResponseTooLarge),
    ):
        shared.read_content(f"/v1/assets/{ASSET_ID}/content")


def test_sse_parser_replays_from_cursor_and_validates_event_payloads():
    event = {
        "jobId": JOB_ID,
        "sequence": 7,
        "type": "progress",
        "at": "2026-08-15T08:00:02.000Z",
        "data": {"value": 1, "maximum": 4},
    }
    body = (
        f": heartbeat\n\nid: 7\nevent: progress\ndata: {json.dumps(event)}\n\n"
    ).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v1/jobs/{JOB_ID}/events"
        assert request.headers["last-event-id"] == "6"
        return httpx.Response(
            200, content=body, headers={"Content-Type": "text/event-stream"}
        )

    with client(handler) as shared:
        events = list(shared.iter_events(JOB_ID, after_sequence=6))
    assert len(events) == 1
    assert events[0].sequence == 7
    assert events[0].type == "progress"
