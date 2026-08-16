from __future__ import annotations

import hashlib
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from h3lab.api.app import create_app
from h3lab.domain.run import Artifact
from h3lab.domain.sweeps import SweepAxis, SweepSpec
from h3lab.engine.lab import Lab
from h3lab.engine.shared_runner import SharedEventGap
from h3lab.shared.client import SharedServiceClient
from h3lab.shared.contracts import GenerationDocument, JobSubmission
from h3lab.shared.generated_contract import WORKFLOW_ID

REVISION = f"sha256:{'a' * 64}"
JOB_ID = "11111111-1111-4111-8111-111111111111"
ARTIFACT_ID = "22222222-2222-4222-8222-222222222222"
VIDEO_BYTES = b"\x00\x00\x00\x18ftypmp42managed-video"


def generation_document() -> GenerationDocument:
    return GenerationDocument.model_validate(
        {
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
                "required": ["component.seed", "action.submit"],
                "optional": [],
            },
            "components": [
                {
                    "id": "seed",
                    "kind": "seed",
                    "binding": "seed",
                    "label": "Seed",
                    "required": True,
                    "optional": False,
                    "allowRandom": True,
                    "minimum": 0,
                    "maximum": 1125899906842624,
                    "defaultValue": None,
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
    )


def h3_input(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "mode": "text_to_video",
        "prompt": "A lighthouse in rain",
        "seed": 42,
        "duration": 5,
        "aspectRatio": "16:9 (Widescreen)",
        "megapixels": 1,
        "steps": 20,
        "turboLora": "none",
        "filenamePrefix": "h3-test-video",
        "cache": "easy",
        "attention": "sage_sol",
        "interpolation": "none",
        "upscaler": "none",
        "cleanVram": True,
        "postGrade": True,
        "faceRefine": False,
        "firstFrame": [],
        "lastFrame": [],
        "referenceImages": [],
        "referenceVideos": [],
        "referenceVideoAudio": [],
        "referenceAudio": [],
    }
    value.update(overrides)
    return value


def submission(**overrides: object) -> JobSubmission:
    return JobSubmission(
        workflowRevision=REVISION,
        schemaRevision="h3-v1",
        input=h3_input(**overrides),
    )


def public_job(job_id: str = JOB_ID, state: str = "queued") -> dict[str, object]:
    links: dict[str, str] = {
        "self": f"/v1/jobs/{job_id}",
        "view": f"/v1/jobs/{job_id}/view",
        "events": f"/v1/jobs/{job_id}/events",
    }
    if state in {"accepted", "queued", "running", "cancelling"}:
        links["cancel"] = f"/v1/jobs/{job_id}/cancel"
    if state == "running":
        links["preview"] = f"/v1/jobs/{job_id}/preview"
    if state == "collection_failed":
        links["retryCollection"] = f"/v1/jobs/{job_id}/retry-collection"
    job: dict[str, object] = {
        "id": job_id,
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
        "links": links,
    }
    if state == "succeeded":
        job["artifact"] = {
            "id": ARTIFACT_ID,
            "mime": "video/mp4",
            "size": len(VIDEO_BYTES),
            "filename": "render.mp4",
            "contentUrl": f"/v1/artifacts/{ARTIFACT_ID}/content",
        }
    return job


def job_document(job_id: str = JOB_ID) -> dict[str, object]:
    return {
        "kind": "job",
        "protocolVersion": "1.0",
        "documentId": f"minimax-h3-unified:job:{job_id}",
        "schemaRevision": "h3-v1",
        "workflowId": WORKFLOW_ID,
        "workflowRevision": REVISION,
        "jobId": job_id,
        "title": "MiniMax H3 job",
        "availability": {
            "state": "available",
            "observedAt": "2026-08-15T08:00:00.000Z",
        },
        "capabilities": {
            "required": ["component.status"],
            "optional": [
                "component.preview",
                "component.video",
                "component.download",
                "action.cancel",
            ],
        },
        "components": [
            {
                "id": "status",
                "kind": "status",
                "optional": False,
                "state": "running",
                "label": "Running",
            },
            {
                "id": "preview",
                "kind": "preview",
                "optional": True,
                "src": f"/v1/jobs/{job_id}/preview",
                "mime": "image/png",
                "sequence": 9,
            },
            {
                "id": "video",
                "kind": "video",
                "optional": True,
                "src": f"/v1/artifacts/{ARTIFACT_ID}/content",
                "mime": "video/mp4",
            },
            {
                "id": "download",
                "kind": "download",
                "optional": True,
                "href": f"/v1/artifacts/{ARTIFACT_ID}/content",
                "filename": "render.mp4",
                "label": "Download",
            },
        ],
        "actions": [
            {
                "id": "cancel",
                "kind": "cancel",
                "label": "Cancel",
                "endpoint": f"/v1/jobs/{job_id}/cancel",
                "method": "POST",
                "optional": True,
            }
        ],
    }


class FakeShared:
    def __init__(self) -> None:
        self.create_calls: list[tuple[str, dict[str, object]]] = []
        self.create_attempts = 0
        self.job_for_key: dict[str, str] = {}
        self.get_attempts = 0
        self.disconnect_once = False
        self.problem: tuple[int, dict[str, object]] | None = None
        self.jobs: dict[str, dict[str, object]] = {}
        self.event_batches: list[list[dict[str, object]]] = []
        self.event_after: list[str | None] = []
        self.event_disconnect_once = False
        self.cancel_calls: list[str] = []
        self.retry_calls: list[str] = []
        self.preview = b"\x89PNG\r\n\x1a\npreview"
        self.video_bytes = VIDEO_BYTES
        self.video_mime = "video/mp4"
        self.video_etag: str | None = (
            f'"sha256:{hashlib.sha256(self.video_bytes).hexdigest()}"'
        )
        self.video_length: int | None = len(self.video_bytes)
        self.content_requests: list[tuple[str, str | None]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/views/generation"):
            return httpx.Response(
                200,
                json=generation_document().model_dump(mode="json", by_alias=True),
            )
        if request.method == "POST" and request.url.path.endswith("/jobs"):
            self.create_attempts += 1
            key = request.headers["idempotency-key"]
            body = json.loads(request.content)
            self.create_calls.append((key, body))
            if self.disconnect_once:
                self.disconnect_once = False
                raise httpx.ReadError("response lost after submission")
            if self.problem is not None:
                status, problem = self.problem
                return httpx.Response(status, json=problem)
            job_id = self.job_for_key.get(key)
            if job_id is None:
                ordinal = len(self.job_for_key)
                job_id = (
                    JOB_ID
                    if ordinal == 0
                    else f"10000000-0000-4000-8000-{ordinal:012d}"
                )
                self.job_for_key[key] = job_id
            job = public_job(job_id)
            self.jobs[job_id] = job
            return httpx.Response(
                201,
                json=job,
                headers={
                    "Idempotency-Replayed": (
                        "true" if self.create_attempts > 1 else "false"
                    ),
                    "Location": f"/v1/jobs/{job_id}",
                },
            )
        if (
            request.method == "GET"
            and request.url.path == f"/v1/artifacts/{ARTIFACT_ID}/content"
        ):
            range_header = request.headers.get("range")
            self.content_requests.append((request.url.path, range_header))
            headers = {"Content-Type": self.video_mime}
            if self.video_etag is not None:
                headers["ETag"] = self.video_etag
            if self.video_length is not None:
                headers["Content-Length"] = str(self.video_length)
            if range_header == "bytes=0-3":
                headers["Content-Length"] = "4"
                headers["Content-Range"] = f"bytes 0-3/{len(self.video_bytes)}"
                headers["Accept-Ranges"] = "bytes"
                return httpx.Response(
                    206,
                    content=self.video_bytes[:4],
                    headers=headers,
                )
            return httpx.Response(200, content=self.video_bytes, headers=headers)
        parts = request.url.path.strip("/").split("/")
        routed_job_id = (
            parts[2] if len(parts) >= 3 and parts[:2] == ["v1", "jobs"] else None
        )
        if request.method == "GET" and routed_job_id is not None and len(parts) == 3:
            self.get_attempts += 1
            return httpx.Response(
                200,
                json=self.jobs.get(routed_job_id, public_job(routed_job_id)),
            )
        if (
            request.method == "GET"
            and routed_job_id is not None
            and parts[3:] == ["view"]
        ):
            return httpx.Response(200, json=job_document(routed_job_id))
        if (
            request.method == "GET"
            and routed_job_id is not None
            and parts[3:] == ["events"]
        ):
            self.event_after.append(request.headers.get("last-event-id"))
            if self.event_disconnect_once:
                self.event_disconnect_once = False
                raise httpx.ReadError("event stream disconnected")
            batch = self.event_batches.pop(0) if self.event_batches else []
            frames = []
            for event in batch:
                frames.append(
                    f"id: {event['sequence']}\nevent: {event['type']}\n"
                    f"data: {json.dumps(event)}\n\n"
                )
            return httpx.Response(
                200,
                content="".join(frames),
                headers={"Content-Type": "text/event-stream"},
            )
        if (
            request.method == "GET"
            and routed_job_id is not None
            and parts[3:] == ["preview"]
        ):
            return httpx.Response(
                200,
                content=self.preview,
                headers={"Content-Type": "image/png"},
            )
        if (
            request.method == "POST"
            and routed_job_id is not None
            and parts[3:] == ["cancel"]
        ):
            self.cancel_calls.append(routed_job_id)
            job = public_job(routed_job_id, state="cancelling")
            self.jobs[routed_job_id] = job
            return httpx.Response(200, json=job)
        if (
            request.method == "POST"
            and routed_job_id is not None
            and parts[3:] == ["retry-collection"]
        ):
            self.retry_calls.append(routed_job_id)
            job = public_job(routed_job_id, state="collecting")
            self.jobs[routed_job_id] = job
            return httpx.Response(200, json=job)
        raise AssertionError(
            f"unexpected shared request {request.method} {request.url.path}"
        )

    def client(self) -> SharedServiceClient:
        return SharedServiceClient(
            "http://shared.internal",
            transport=httpx.MockTransport(self.handler),
        )


def shared_event(
    event_sequence: int,
    type_: str,
    at: str,
    **data: object,
) -> dict[str, object]:
    return {
        "jobId": JOB_ID,
        "sequence": event_sequence,
        "type": type_,
        "at": at,
        "data": data,
    }


def test_production_lab_submits_immediately_with_local_run_id_as_upstream_key(settings):
    fake = FakeShared()
    shared = fake.client()
    lab = Lab(settings, shared_client=shared, start_worker=False)
    try:
        made = lab.enqueue_shared(
            generation_document(),
            submission(),
            request_key="browser-request-1",
        )
        assert len(made) == 1
        run = made[0].run
        assert run.shared_job_id == JOB_ID
        assert run.shared_submission == submission()
        assert run.shared_provenance and run.shared_provenance.resolved_seed == 42
        assert fake.create_calls == [
            (
                run.id,
                submission().model_dump(mode="json", by_alias=True),
            )
        ]
        assert lab.legacy_execution_enabled is False
    finally:
        lab.close()
        shared.close()


def test_same_browser_key_replays_one_local_and_shared_job_but_conflicts_on_new_input(
    settings,
):
    fake = FakeShared()
    shared = fake.client()
    lab = Lab(settings, shared_client=shared, start_worker=False)
    try:
        first = lab.enqueue_shared(
            generation_document(), submission(), request_key="same-browser-key"
        )[0]
        replayed = lab.enqueue_shared(
            generation_document(), submission(), request_key="same-browser-key"
        )[0]
        assert replayed.run.id == first.run.id
        assert fake.create_attempts == 1

        with pytest.raises(ValueError, match="different submission"):
            lab.enqueue_shared(
                generation_document(),
                submission(prompt="A different prompt"),
                request_key="same-browser-key",
            )
        assert fake.create_attempts == 1
    finally:
        lab.close()
        shared.close()


def test_definitive_upstream_refusal_removes_the_phantom_local_run(settings):
    fake = FakeShared()
    fake.problem = (
        422,
        {
            "type": "https://comfyui-sdui.local/problems/job-input-invalid",
            "title": "Invalid input",
            "status": 422,
            "detail": "Prompt rejected.",
            "code": "job_input_invalid",
            "retryable": False,
        },
    )
    shared = fake.client()
    lab = Lab(settings, shared_client=shared, start_worker=False)
    try:
        with pytest.raises(Exception, match="Prompt rejected"):
            lab.enqueue_shared(generation_document(), submission(), request_key="bad")
        assert lab.runs.all() == []
    finally:
        lab.close()
        shared.close()


def test_ambiguous_create_survives_restart_and_reuses_exactly_the_same_key(settings):
    fake = FakeShared()
    fake.disconnect_once = True
    first_client = fake.client()
    first = Lab(settings, shared_client=first_client, start_worker=False)
    try:
        with pytest.raises(Exception, match="uncertain"):
            first.enqueue_shared(
                generation_document(),
                submission(),
                request_key="restartable",
            )
        pending = first.runs.all()[0]
        assert pending.shared_job_id is None
        local_id = pending.id
        assert fake.create_calls[0][0] == local_id
    finally:
        first.close()
        first_client.close()

    second_client = fake.client()
    second = Lab(settings, shared_client=second_client, start_worker=False)
    try:
        assert second.reconcile() >= 1
        recovered = second.runs.require(local_id)
        assert recovered.shared_job_id == JOB_ID
        assert [key for key, _body in fake.create_calls] == [local_id, local_id]
    finally:
        second.close()
        second_client.close()


def test_http_create_requires_idempotency_and_uses_shared_body(settings):
    fake = FakeShared()
    shared = fake.client()
    lab = Lab(settings, shared_client=shared, start_worker=False)
    app = create_app(lab=lab, settings=settings, shared_client=shared)
    body = {
        "workflowRevision": REVISION,
        "schemaRevision": "h3-v1",
        "input": h3_input(),
    }
    try:
        with TestClient(app) as browser:
            missing = browser.post("/api/runs", json=body)
            assert missing.status_code == 422
            created = browser.post(
                "/api/runs",
                json=body,
                headers={"Idempotency-Key": "browser-http-1"},
            )
        assert created.status_code == 201
        assert created.json()[0]["run"]["shared_job_id"] == JOB_ID
        assert fake.create_attempts == 1
    finally:
        lab.close()
        shared.close()


@pytest.mark.parametrize(
    ("shared_state", "local_state"),
    [
        ("accepted", "queued"),
        ("queued", "queued"),
        ("running", "running"),
        ("cancelling", "running"),
        ("collecting", "running"),
        ("succeeded", "succeeded"),
        ("failed", "failed"),
        ("cancelled", "cancelled"),
        ("interrupted", "interrupted"),
        ("collection_failed", "collection_failed"),
    ],
)
def test_restart_reconciles_every_linked_shared_state_once(
    settings, shared_state, local_state
):
    fake = FakeShared()
    first_client = fake.client()
    first = Lab(settings, shared_client=first_client, start_worker=False)
    try:
        run_id = first.enqueue_shared(
            generation_document(),
            submission(),
            request_key=f"state-{shared_state}",
        )[0].run.id
    finally:
        first.close()
        first_client.close()

    fake.jobs[JOB_ID] = public_job(state=shared_state)
    second_client = fake.client()
    second = Lab(settings, shared_client=second_client, start_worker=False)
    try:
        assert second.reconcile() == 1
        assert second.runs.require(run_id).status == local_state
        reads = fake.get_attempts
        if local_state not in {"queued", "running"}:
            assert second.reconcile() == 0
            assert fake.get_attempts == reads
    finally:
        second.close()
        second_client.close()


def test_disabled_document_refuses_before_creating_a_local_or_shared_job(settings):
    fake = FakeShared()
    shared = fake.client()
    lab = Lab(settings, shared_client=shared, start_worker=False)
    disabled_payload = generation_document().model_dump(mode="json", by_alias=True)
    disabled_payload["availability"] = {
        "state": "disabled",
        "observedAt": "2026-08-15T08:00:00.000Z",
        "reason": {
            "code": "comfy_unreachable",
            "detail": "ComfyUI is offline",
            "retryable": True,
        },
    }
    disabled = GenerationDocument.model_validate(disabled_payload)
    try:
        with pytest.raises(ValueError, match="not currently available"):
            lab.enqueue_shared(disabled, submission(), request_key="disabled")
        assert lab.runs.all() == []
        assert fake.create_attempts == 0
    finally:
        lab.close()
        shared.close()


def test_sse_observation_persists_cursor_translates_feedback_and_derives_metrics(
    settings,
):
    fake = FakeShared()
    shared = fake.client()
    lab = Lab(settings, shared_client=shared, start_worker=False)
    try:
        run_id = lab.enqueue_shared(
            generation_document(),
            submission(),
            request_key="observed",
        )[0].run.id
        fake.jobs[JOB_ID] = public_job(state="running")
        fake.event_batches.append(
            [
                shared_event(1, "running", "2026-08-15T08:00:01Z", state="running"),
                shared_event(2, "status", "2026-08-15T08:00:01.500Z", queueRemaining=2),
                shared_event(
                    3, "executing", "2026-08-15T08:00:01.750Z", nodeId="sampler"
                ),
                shared_event(
                    4,
                    "progress",
                    "2026-08-15T08:00:02Z",
                    value=1,
                    maximum=20,
                    nodeId="sampler",
                ),
                shared_event(
                    5,
                    "progress",
                    "2026-08-15T08:00:04Z",
                    value=2,
                    maximum=20,
                    nodeId="sampler",
                ),
                shared_event(
                    6,
                    "log",
                    "2026-08-15T08:00:04.250Z",
                    level="info",
                    message="2/20 [00:04<00:36, 2.00s/it]",
                ),
                shared_event(
                    7,
                    "preview",
                    "2026-08-15T08:00:04.500Z",
                    mime="image/png",
                    available=True,
                    sequence=9,
                    url=f"/v1/jobs/{JOB_ID}/preview",
                    nodeId="sampler",
                ),
            ]
        )

        assert lab.runner.observe_once(run_id) == 7
        frame = lab.preview(run_id)
        assert frame is not None
        assert frame.data == fake.preview
        assert frame.content_type == "image/png"
        assert frame.seq == 9

        fake.jobs[JOB_ID] = public_job(state="succeeded")
        fake.event_batches.append(
            [
                shared_event(
                    8,
                    "succeeded",
                    "2026-08-15T08:00:07Z",
                    state="succeeded",
                )
            ]
        )
        assert lab.runner.observe_once(run_id) == 1
        run = lab.runs.require(run_id)
        assert run.shared_event_cursor == 8
        assert run.status == "succeeded"
        assert run.metrics.wall_s == 6.0
        assert run.metrics.sec_per_it == 2.0
        assert run.metrics.steps == 20

        history = lab.events.history()
        assert any(event.kind == "run.progress" for event in history)
        assert any(
            event.kind == "run.log" and "2.00s/it" in event.data["message"]
            for event in history
        )
        preview_event = next(event for event in history if event.kind == "run.preview")
        assert preview_event.data == {"sequence": 9, "available": True}
        assert "shared.internal" not in json.dumps(
            [event.model_dump(mode="json") for event in history]
        )

        assert lab.preview(run_id) is None, "terminal feedback drops transient previews"
    finally:
        lab.close()
        shared.close()


def test_sse_duplicate_is_ignored_and_gap_reconnects_from_durable_cursor(settings):
    fake = FakeShared()
    shared = fake.client()
    lab = Lab(settings, shared_client=shared, start_worker=False)
    try:
        run_id = lab.enqueue_shared(
            generation_document(),
            submission(),
            request_key="cursor",
        )[0].run.id
        first = shared_event(1, "accepted", "2026-08-15T08:00:00Z", state="accepted")
        fake.event_batches.append(
            [
                first,
                first,
                shared_event(3, "running", "2026-08-15T08:00:02Z", state="running"),
            ]
        )
        with pytest.raises(SharedEventGap, match="jumped from 1 to 3"):
            lab.runner.observe_once(run_id)
        assert lab.runs.require(run_id).shared_event_cursor == 1

        fake.jobs[JOB_ID] = public_job(state="running")
        fake.event_batches.append(
            [
                shared_event(2, "queued", "2026-08-15T08:00:01Z", state="queued"),
                shared_event(3, "running", "2026-08-15T08:00:02Z", state="running"),
            ]
        )
        assert lab.runner.observe_once(run_id) == 2
        assert lab.runs.require(run_id).shared_event_cursor == 3
        assert lab.runs.require(run_id).status == "running"
        assert fake.event_after == [None, "1"]
    finally:
        lab.close()
        shared.close()


def test_sse_disconnect_recovery_reuses_the_last_durable_cursor(settings):
    fake = FakeShared()
    shared = fake.client()
    lab = Lab(settings, shared_client=shared, start_worker=False)
    try:
        run_id = lab.enqueue_shared(
            generation_document(),
            submission(),
            request_key="disconnect",
        )[0].run.id
        fake.event_disconnect_once = True
        with pytest.raises(Exception, match="disconnected"):
            lab.runner.observe_once(run_id)
        assert lab.runs.require(run_id).shared_event_cursor is None

        fake.jobs[JOB_ID] = public_job(state="running")
        fake.event_batches.append(
            [shared_event(1, "running", "2026-08-15T08:00:01Z", state="running")]
        )
        assert lab.runner.observe_once(run_id) == 1
        assert lab.runs.require(run_id).shared_event_cursor == 1
        assert fake.event_after == [None, None]
    finally:
        lab.close()
        shared.close()


def test_cancel_and_collection_retry_target_only_the_linked_shared_job(settings):
    fake = FakeShared()
    shared = fake.client()
    lab = Lab(settings, shared_client=shared, start_worker=False)
    try:
        run_id = lab.enqueue_shared(
            generation_document(),
            submission(),
            request_key="actions",
        )[0].run.id
        assert lab.cancel(run_id) is True
        assert fake.cancel_calls == [JOB_ID]
        assert lab.runs.require(run_id).status == "running"

        fake.jobs[JOB_ID] = public_job(state="collection_failed")
        lab.runs.sync_shared_status(run_id, "collection_failed", error="copy failed")
        assert lab.retry_collection(run_id) is True
        assert fake.retry_calls == [JOB_ID]
        assert lab.runs.require(run_id).status == "running"
    finally:
        lab.close()
        shared.close()


def test_count_and_rerun_keep_exact_shared_inputs_with_distinct_stable_keys(settings):
    fake = FakeShared()
    shared = fake.client()
    lab = Lab(settings, shared_client=shared, start_worker=False)
    try:
        repeated = lab.enqueue_shared(
            generation_document(),
            submission(),
            request_key="counted",
            count=3,
        )
        assert len({view.run.id for view in repeated}) == 3
        assert len({view.run.shared_job_id for view in repeated}) == 3
        assert all(view.run.shared_submission == submission() for view in repeated)
        assert [key for key, _body in fake.create_calls] == [
            view.run.id for view in repeated
        ]

        rerun = lab.rerun(
            repeated[0].run.id,
            overrides={"prompt": "A new exact prompt"},
            request_key="rerun-key",
        )
        assert rerun.run.id not in {view.run.id for view in repeated}
        assert rerun.run.shared_submission is not None
        assert rerun.run.shared_submission.input["prompt"] == "A new exact prompt"
        assert (
            repeated[0].run.shared_submission.input["prompt"] == "A lighthouse in rain"
        )
        assert rerun.run.config_hash != repeated[0].run.config_hash
    finally:
        lab.close()
        shared.close()


def test_shared_sweep_projects_axes_back_to_exact_binding_maps(settings):
    fake = FakeShared()
    shared = fake.client()
    lab = Lab(settings, shared_client=shared, start_worker=False)
    try:
        base = lab.enqueue_shared(
            generation_document(),
            submission(),
            request_key="sweep-base",
        )[0].run
        made = lab.run_sweep(
            SweepSpec(
                base=base.config,
                axes=(SweepAxis(field="steps", values=(20, 24)),),
            ),
            skip_duplicates=False,
            request_key="sweep",
        )
        assert [view.run.shared_submission.input["steps"] for view in made] == [20, 24]
        assert [view.run.config.steps for view in made] == [20, 24]
        assert len({view.run.config_hash for view in made}) == 2
        assert all(
            body == view.run.shared_submission.model_dump(mode="json", by_alias=True)
            for (_key, body), view in zip(fake.create_calls[-2:], made, strict=True)
        )
    finally:
        lab.close()
        shared.close()


def test_succeeded_video_is_verified_imported_derived_and_range_playable(
    settings, monkeypatch
):
    fake = FakeShared()
    shared = fake.client()
    lab = Lab(settings, shared_client=shared, start_worker=False)
    derived: list[bytes] = []

    def build(run_id, video, build_settings):
        payload = video.read_bytes()
        derived.append(payload)
        (build_settings.posters_dir / f"{run_id}.jpg").write_bytes(b"poster")
        (build_settings.strips_dir / f"{run_id}.jpg").write_bytes(b"strip")
        return Artifact(
            video_path=video.name,
            poster_path=f"{run_id}.jpg",
            strip_path=f"{run_id}.jpg",
            width=1280,
            height=720,
            fps=24.0,
            frame_count=120,
            size_bytes=len(payload),
        )

    monkeypatch.setattr("h3lab.engine.shared_runner.artifacts.build", build)
    try:
        run_id = lab.enqueue_shared(
            generation_document(),
            submission(),
            request_key="artifact",
        )[0].run.id
        fake.jobs[JOB_ID] = public_job(state="succeeded")
        assert lab.reconcile() == 1

        run = lab.runs.require(run_id)
        assert run.status == "succeeded"
        assert run.artifact.video_path == f"{run_id}.mp4"
        assert run.artifact.poster_path == f"{run_id}.jpg"
        assert run.artifact.strip_path == f"{run_id}.jpg"
        assert (
            settings.videos_dir / run.artifact.video_path
        ).read_bytes() == VIDEO_BYTES
        assert derived == [VIDEO_BYTES]
        assert list(settings.videos_dir.glob(f".{run_id}.*.part")) == []

        app = create_app(lab=lab, settings=settings, shared_client=shared)
        with TestClient(app) as browser:
            ranged = browser.get(
                f"/api/media/videos/{run.artifact.video_path}",
                headers={"Range": "bytes=0-7"},
            )
            assert ranged.status_code == 206
            assert ranged.content == VIDEO_BYTES[:8]
            assert ranged.headers["accept-ranges"] == "bytes"
    finally:
        lab.close()
        shared.close()


def test_job_bff_rewrites_every_link_and_streams_preview_events_and_video(settings):
    fake = FakeShared()
    shared = fake.client()
    lab = Lab(settings, shared_client=shared, start_worker=False)
    try:
        run_id = lab.enqueue_shared(
            generation_document(),
            submission(),
            request_key="job-bff",
        )[0].run.id
        running = public_job(state="running")
        running["artifact"] = public_job(state="succeeded")["artifact"]
        fake.jobs[JOB_ID] = running
        fake.event_batches.append(
            [
                shared_event(
                    1,
                    "preview",
                    "2026-08-15T08:00:01Z",
                    mime="image/png",
                    available=True,
                    sequence=9,
                    url=f"/v1/jobs/{JOB_ID}/preview",
                )
            ]
        )
        app = create_app(lab=lab, settings=settings, shared_client=shared)
        with TestClient(app) as browser:
            job = browser.get(f"/api/runs/{run_id}/shared")
            assert job.status_code == 200
            encoded_job = json.dumps(job.json())
            assert "/v1/" not in encoded_job
            assert job.json()["links"]["view"] == f"/api/runs/{run_id}/shared-view"
            assert job.json()["artifact"]["contentUrl"] == (
                f"/api/runs/{run_id}/shared-video"
            )

            view = browser.get(f"/api/runs/{run_id}/shared-view")
            assert view.status_code == 200
            encoded_view = json.dumps(view.json())
            assert "/v1/" not in encoded_view
            assert f"/api/runs/{run_id}/shared-preview" in encoded_view
            assert f"/api/runs/{run_id}/shared-video" in encoded_view
            assert f"/api/runs/{run_id}/cancel" in encoded_view

            events = browser.get(f"/api/runs/{run_id}/shared-events")
            assert events.status_code == 200
            assert f"/api/runs/{run_id}/shared-preview" in events.text
            assert "/v1/jobs/" not in events.text

            preview = browser.get(f"/api/runs/{run_id}/shared-preview")
            assert preview.status_code == 200
            assert preview.content == fake.preview
            assert preview.headers["content-type"] == "image/png"

            video = browser.get(
                f"/api/runs/{run_id}/shared-video",
                headers={"Range": "bytes=0-3"},
            )
            assert video.status_code == 206
            assert video.content == VIDEO_BYTES[:4]
            assert video.headers["content-range"] == f"bytes 0-3/{len(VIDEO_BYTES)}"
        assert fake.content_requests[-1] == (
            f"/v1/artifacts/{ARTIFACT_ID}/content",
            "bytes=0-3",
        )
    finally:
        lab.close()
        shared.close()


@pytest.mark.parametrize(
    ("field", "value", "error_fragment"),
    [
        ("video_mime", "video/webm", "Content-Type"),
        ("video_length", len(VIDEO_BYTES) - 1, "Content-Length"),
        ("video_etag", '"sha256:' + "0" * 64 + '"', "digest"),
        ("video_etag", None, "SHA-256 ETag"),
    ],
)
def test_invalid_managed_video_never_replaces_existing_output(
    settings, field, value, error_fragment
):
    fake = FakeShared()
    shared = fake.client()
    lab = Lab(settings, shared_client=shared, start_worker=False)
    try:
        run_id = lab.enqueue_shared(
            generation_document(),
            submission(),
            request_key=f"invalid-artifact-{field}-{value}",
        )[0].run.id
        destination = settings.videos_dir / f"{run_id}.mp4"
        destination.write_bytes(b"previous-valid-result")
        setattr(fake, field, value)
        fake.jobs[JOB_ID] = public_job(state="succeeded")

        assert lab.reconcile() == 1
        failed = lab.runs.require(run_id)
        assert failed.status == "collection_failed"
        assert failed.shared_failure_kind == "local_artifact_import_failed"
        assert error_fragment in (failed.error or "")
        assert destination.read_bytes() == b"previous-valid-result"
        assert list(settings.videos_dir.glob(f".{run_id}.*.part")) == []
    finally:
        lab.close()
        shared.close()


def test_local_collection_retry_redownloads_without_rerendering(settings):
    fake = FakeShared()
    fake.video_etag = '"sha256:' + "0" * 64 + '"'
    shared = fake.client()
    lab = Lab(settings, shared_client=shared, start_worker=False)
    try:
        run_id = lab.enqueue_shared(
            generation_document(),
            submission(),
            request_key="local-retry",
        )[0].run.id
        fake.jobs[JOB_ID] = public_job(state="succeeded")
        lab.reconcile()
        assert lab.runs.require(run_id).status == "collection_failed"

        fake.video_etag = f'"sha256:{hashlib.sha256(VIDEO_BYTES).hexdigest()}"'
        assert lab.retry_collection(run_id) is True
        retried = lab.runs.require(run_id)
        assert retried.status == "succeeded"
        assert retried.shared_failure_kind is None
        assert (
            settings.videos_dir / retried.artifact.video_path
        ).read_bytes() == VIDEO_BYTES
        assert fake.retry_calls == []
        assert fake.create_attempts == 1
    finally:
        lab.close()
        shared.close()


def test_observation_concurrency_is_bounded_across_many_linked_jobs(settings):
    fake = FakeShared()
    shared = fake.client()
    lab = Lab(settings, shared_client=shared, start_worker=False)
    try:
        first = lab.enqueue_shared(
            generation_document(),
            submission(),
            request_key="bounded-0",
        )[0].run
        for index in range(1, 7):
            local = lab.runs.create(
                first.config,
                run_id=f"bounded-local-{index}",
                shared_submission=submission(prompt=f"Prompt {index}"),
            )
            job_id = f"00000000-0000-4000-8000-{index:012d}"
            fake.jobs[job_id] = public_job(job_id)
            lab.runs.set_shared_job(local.id, job_id, None)

        lab.runner.start()
        deadline = time.monotonic() + 2
        while lab.runner.observer_count < 4 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert lab.runner.observer_count == 4
    finally:
        lab.close()
        shared.close()


def test_shared_production_composition_never_constructs_legacy_comfy_client(
    settings, monkeypatch
):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("legacy ComfyClient must not be constructed")

    monkeypatch.setattr("h3lab.engine.lab.ComfyClient", forbidden)
    fake = FakeShared()
    shared = fake.client()
    lab = Lab(settings, shared_client=shared, start_worker=False)
    try:
        lab.enqueue_shared(
            generation_document(), submission(), request_key="composition"
        )
        assert fake.create_attempts == 1
    finally:
        lab.close()
        shared.close()
