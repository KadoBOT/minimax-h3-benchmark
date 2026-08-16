"""Bounded HTTP/SSE boundary to an already-running shared SDUI service."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import IO, Self
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

from h3lab.shared.contracts import (
    ApiPath,
    GenerationDocument,
    JobDocument,
    JobSubmission,
    OpaqueId,
    Problem,
    PublicJob,
    PublicJobEvent,
    PublicMediaMetadata,
)
from h3lab.shared.generated_contract import PROTOCOL_VERSION, WORKFLOW_ID

CONSUMER_ID = "h3-test"
SUPPORTED_CAPABILITIES = tuple(
    sorted(
        {
            "action.cancel",
            "action.delete",
            "action.retry_collection",
            "action.submit",
            "component.asset",
            "component.download",
            "component.log",
            "component.number",
            "component.preview",
            "component.progress",
            "component.seed",
            "component.select",
            "component.status",
            "component.text",
            "component.textarea",
            "component.toggle",
            "component.video",
        }
    )
)

_PATH = TypeAdapter(ApiPath)
_OPAQUE_ID = TypeAdapter(OpaqueId)
_RANGE = re.compile(r"^bytes=(?:\d*-\d*|\d+-)(?:,\s*(?:\d*-\d*|\d+-))*$")


class SharedClientError(RuntimeError):
    """Base class for a failure at the shared-service boundary."""


class SharedServiceUnavailable(SharedClientError):
    """A read or safely retryable request could not reach the service."""


class SharedSubmissionUncertain(SharedClientError):
    """A create request may have reached the service and must reuse its key."""


class SharedProtocolError(SharedClientError):
    """The service returned a malformed or contract-incompatible response."""


class SharedResponseTooLarge(SharedProtocolError):
    """A response exceeded the configured in-memory boundary."""


class SharedServiceError(SharedClientError):
    def __init__(self, problem: Problem) -> None:
        super().__init__(problem.detail or problem.title)
        self.problem = problem


@dataclass(frozen=True, slots=True)
class CreateJobResult:
    job: PublicJob
    replayed: bool


@dataclass(frozen=True, slots=True)
class SharedContent:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


class SharedContentStream:
    def __init__(self, response: httpx.Response, maximum_bytes: int) -> None:
        self._response = response
        self._maximum_bytes = maximum_bytes
        self.status_code = response.status_code
        self.headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower()
            in {
                "accept-ranges",
                "cache-control",
                "content-disposition",
                "content-length",
                "content-range",
                "content-type",
                "etag",
                "last-modified",
            }
        }

    def iter_bytes(self) -> Iterator[bytes]:
        size = 0
        for chunk in self._response.iter_bytes():
            size += len(chunk)
            if size > self._maximum_bytes:
                raise SharedResponseTooLarge(
                    f"shared media response exceeds {self._maximum_bytes} bytes"
                )
            yield chunk

    def close(self) -> None:
        self._response.close()


class SharedServiceClient:
    def __init__(
        self,
        base_url: str,
        *,
        request_timeout_s: float = 60.0,
        connect_timeout_s: float = 3.0,
        max_json_bytes: int = 4 * 1024 * 1024,
        max_media_bytes: int = 4 * 1024 * 1024 * 1024,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        _validate_base_url(base_url)
        if max_json_bytes < 1 or max_media_bytes < 1:
            raise ValueError("response limits must be positive")
        self.base_url = base_url.rstrip("/")
        self.max_json_bytes = max_json_bytes
        self.max_media_bytes = max_media_bytes
        self._headers = {
            "X-SDUI-Protocol-Version": PROTOCOL_VERSION,
            "X-SDUI-Capabilities": ",".join(SUPPORTED_CAPABILITIES),
        }
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(request_timeout_s, connect=connect_timeout_s),
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close()

    def get_generation_document(
        self, workflow_id: str = WORKFLOW_ID
    ) -> GenerationDocument:
        _validate_workflow_id(workflow_id)
        return self._json_model(
            "GET",
            f"/v1/workflows/{workflow_id}/views/generation",
            GenerationDocument,
        )

    def create_job(
        self,
        submission: JobSubmission,
        *,
        idempotency_key: str,
        workflow_id: str = WORKFLOW_ID,
    ) -> CreateJobResult:
        _validate_workflow_id(workflow_id)
        if (
            not idempotency_key
            or len(idempotency_key) > 200
            or _has_control(idempotency_key)
        ):
            raise ValueError(
                "idempotency key must be 1-200 characters without controls"
            )
        response, body = self._request(
            "POST",
            f"/v1/workflows/{workflow_id}/jobs",
            headers={
                "X-Consumer-ID": CONSUMER_ID,
                "Idempotency-Key": idempotency_key,
                "Content-Type": "application/json",
            },
            content=json.dumps(
                submission.model_dump(mode="json", by_alias=True),
                separators=(",", ":"),
            ).encode(),
            uncertain_on_transport=True,
        )
        job = self._validate_model(body, PublicJob)
        replayed = response.headers.get("idempotency-replayed", "").lower()
        if replayed not in {"true", "false"}:
            raise SharedProtocolError(
                "create response has no valid Idempotency-Replayed header"
            )
        location = response.headers.get("location")
        if location is not None:
            _PATH.validate_python(location)
            if location != job.links.self:
                raise SharedProtocolError(
                    "create response Location does not match the job"
                )
        return CreateJobResult(job=job, replayed=replayed == "true")

    def get_job(self, job_id: str) -> PublicJob:
        job_id = _validate_opaque_id(job_id)
        return self._json_model("GET", f"/v1/jobs/{job_id}", PublicJob)

    def get_job_document(self, job_id: str) -> JobDocument:
        job_id = _validate_opaque_id(job_id)
        return self._json_model("GET", f"/v1/jobs/{job_id}/view", JobDocument)

    def cancel_job(self, job_id: str) -> PublicJob:
        job_id = _validate_opaque_id(job_id)
        return self._json_model("POST", f"/v1/jobs/{job_id}/cancel", PublicJob)

    def retry_collection(self, job_id: str) -> PublicJob:
        job_id = _validate_opaque_id(job_id)
        return self._json_model(
            "POST", f"/v1/jobs/{job_id}/retry-collection", PublicJob
        )

    def upload_asset(
        self,
        stream: IO[bytes],
        *,
        filename: str,
        mime: str,
    ) -> PublicMediaMetadata:
        if (
            not filename
            or len(filename) > 240
            or "/" in filename
            or "\\" in filename
            or _has_control(filename)
        ):
            raise ValueError("upload filename must be a safe leaf name")
        if not re.fullmatch(r"(?:image|video|audio)/[A-Za-z0-9.+-]+", mime):
            raise ValueError("upload MIME must be a supported media type")
        try:
            with self._http.stream(
                "POST",
                "/v1/assets",
                headers=self._headers,
                files={"file": (filename, stream, mime)},
            ) as response:
                body = self._consume_response(response, self.max_json_bytes)
        except httpx.HTTPError as exc:
            raise SharedSubmissionUncertain(
                f"asset upload outcome is uncertain: {exc}"
            ) from exc
        return self._validate_model(body, PublicMediaMetadata)

    def read_content(
        self,
        path: str,
        *,
        range_header: str | None = None,
        if_none_match: str | None = None,
        maximum_bytes: int | None = None,
    ) -> SharedContent:
        stream = self.open_content(
            path,
            range_header=range_header,
            if_none_match=if_none_match,
            maximum_bytes=maximum_bytes,
        )
        try:
            return SharedContent(
                stream.status_code,
                stream.headers,
                b"".join(stream.iter_bytes()),
            )
        finally:
            stream.close()

    def open_content(
        self,
        path: str,
        *,
        range_header: str | None = None,
        if_none_match: str | None = None,
        maximum_bytes: int | None = None,
    ) -> SharedContentStream:
        safe_path = _PATH.validate_python(path)
        headers: dict[str, str] = {}
        if range_header is not None:
            if not _RANGE.fullmatch(range_header):
                raise ValueError("Range must use a bounded bytes syntax")
            headers["Range"] = range_header
        if if_none_match is not None:
            if len(if_none_match) > 512 or _has_control(if_none_match):
                raise ValueError("If-None-Match is invalid")
            headers["If-None-Match"] = if_none_match
        limit = (
            self.max_media_bytes
            if maximum_bytes is None
            else min(maximum_bytes, self.max_media_bytes)
        )
        try:
            request = self._http.build_request(
                "GET",
                safe_path,
                headers={**self._headers, **headers},
            )
            response = self._http.send(request, stream=True)
        except httpx.HTTPError as exc:
            raise SharedServiceUnavailable(f"cannot read shared media: {exc}") from exc
        try:
            self._ensure_success(response)
            length = response.headers.get("content-length")
            if length is not None and int(length) > limit:
                raise SharedResponseTooLarge(
                    f"shared media response exceeds {limit} bytes"
                )
            return SharedContentStream(response, limit)
        except (ValueError, SharedClientError):
            response.close()
            raise

    def iter_events(
        self,
        job_id: str,
        *,
        after_sequence: int | None = None,
    ) -> Iterator[PublicJobEvent]:
        job_id = _validate_opaque_id(job_id)
        if after_sequence is not None and after_sequence < 0:
            raise ValueError("event sequence cannot be negative")
        headers = dict(self._headers)
        if after_sequence is not None:
            headers["Last-Event-ID"] = str(after_sequence)
        try:
            with self._http.stream(
                "GET",
                f"/v1/jobs/{job_id}/events",
                headers=headers,
            ) as response:
                self._ensure_success(response)
                content_type = response.headers.get("content-type", "")
                if not content_type.lower().startswith("text/event-stream"):
                    raise SharedProtocolError("event response is not text/event-stream")
                yield from self._decode_sse(response)
        except httpx.HTTPError as exc:
            raise SharedServiceUnavailable(
                f"shared event stream disconnected: {exc}"
            ) from exc

    def _json_model[Model: BaseModel](
        self,
        method: str,
        path: str,
        model: type[Model],
    ) -> Model:
        _response, body = self._request(method, path)
        return self._validate_model(body, model)

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        content: bytes | None = None,
        uncertain_on_transport: bool = False,
    ) -> tuple[httpx.Response, bytes]:
        safe_path = _PATH.validate_python(path)
        try:
            with self._http.stream(
                method,
                safe_path,
                headers={**self._headers, **dict(headers or {})},
                content=content,
            ) as response:
                body = self._consume_response(response, self.max_json_bytes)
                return response, body
        except httpx.HTTPError as exc:
            if uncertain_on_transport:
                raise SharedSubmissionUncertain(
                    f"shared submission outcome is uncertain at {self.base_url}: {exc}"
                ) from exc
            raise SharedServiceUnavailable(
                f"cannot reach shared service at {self.base_url}: {exc}"
            ) from exc

    def _consume_response(self, response: httpx.Response, limit: int) -> bytes:
        self._ensure_success(response)
        return self._read_limited(response, limit)

    def _read_limited(self, response: httpx.Response, limit: int) -> bytes:
        length = response.headers.get("content-length")
        if length is not None:
            try:
                if int(length) > limit:
                    raise SharedResponseTooLarge(
                        f"shared response exceeds {limit} bytes"
                    )
            except ValueError as exc:
                raise SharedProtocolError(
                    "shared response has an invalid Content-Length"
                ) from exc
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > limit:
                raise SharedResponseTooLarge(f"shared response exceeds {limit} bytes")
            chunks.append(chunk)
        return b"".join(chunks)

    def _ensure_success(self, response: httpx.Response) -> None:
        if 200 <= response.status_code < 300 or response.status_code == 304:
            return
        if 300 <= response.status_code < 400:
            raise SharedProtocolError("shared service redirects are not accepted")
        raw = self._read_limited(response, self.max_json_bytes)
        try:
            problem = Problem.model_validate_json(raw)
        except (ValidationError, ValueError) as exc:
            raise SharedProtocolError(
                f"shared service returned HTTP {response.status_code} without a valid problem"
            ) from exc
        if problem.status != response.status_code:
            raise SharedProtocolError(
                "shared problem status does not match HTTP status"
            )
        raise SharedServiceError(problem)

    def _validate_model[Model: BaseModel](
        self, body: bytes, model: type[Model]
    ) -> Model:
        try:
            parsed = model.model_validate_json(body)
        except (ValidationError, ValueError) as exc:
            raise SharedProtocolError(
                f"invalid shared {model.__name__} response"
            ) from exc
        if isinstance(parsed, PublicJob):
            _validate_upstream_job_paths(parsed)
        return parsed

    def _decode_sse(self, response: httpx.Response) -> Iterator[PublicJobEvent]:
        fields: dict[str, list[str]] = {}
        for line in response.iter_lines():
            if len(line) > 64 * 1024:
                raise SharedResponseTooLarge("shared SSE line is too large")
            if line == "":
                if fields:
                    yield self._event_from_fields(fields)
                    fields = {}
                continue
            if line.startswith(":"):
                continue
            name, separator, value = line.partition(":")
            if not separator:
                value = ""
            elif value.startswith(" "):
                value = value[1:]
            if name in {"id", "event", "data"}:
                fields.setdefault(name, []).append(value)
        if fields:
            yield self._event_from_fields(fields)

    def _event_from_fields(self, fields: dict[str, list[str]]) -> PublicJobEvent:
        data = "\n".join(fields.get("data", []))
        if not data or len(data.encode()) > self.max_json_bytes:
            raise SharedProtocolError("shared SSE event has invalid data")
        event = self._validate_model(data.encode(), PublicJobEvent)
        event_ids = fields.get("id", [])
        event_types = fields.get("event", [])
        if len(event_ids) != 1 or event_ids[0] != str(event.sequence):
            raise SharedProtocolError("shared SSE id does not match event sequence")
        if len(event_types) != 1 or event_types[0] != event.type:
            raise SharedProtocolError("shared SSE name does not match event type")
        return event


def _validate_base_url(value: str) -> None:
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/"}
    ):
        raise ValueError(
            "shared service URL must be an HTTP origin without credentials or path"
        )


def _validate_workflow_id(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9._-]{0,127}", value):
        raise ValueError("workflow id is invalid")
    return value


def _validate_opaque_id(value: str) -> str:
    return _OPAQUE_ID.validate_python(value)


def _has_control(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _validate_upstream_job_paths(job: PublicJob) -> None:
    base = f"/v1/jobs/{job.id}"
    required = {
        job.links.self: base,
        job.links.view: f"{base}/view",
        job.links.events: f"{base}/events",
    }
    if any(actual != expected for actual, expected in required.items()):
        raise SharedProtocolError("shared job links do not match its identity")
    optional = {
        job.links.preview: f"{base}/preview",
        job.links.cancel: f"{base}/cancel",
        job.links.retry_collection: f"{base}/retry-collection",
    }
    if any(
        actual is not None and actual != expected
        for actual, expected in optional.items()
    ):
        raise SharedProtocolError("shared job action link does not match its identity")
    if job.artifact is not None and job.artifact.content_url != (
        f"/v1/artifacts/{job.artifact.id}/content"
    ):
        raise SharedProtocolError("shared artifact link does not match its identity")
