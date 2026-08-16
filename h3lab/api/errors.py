"""One failure shape for the whole API.

The old lab answered failures three different ways: a plain string, a validation array, and
an HTML stack trace. The browser could not render one path, so it rendered none of them well.
Every refusal here becomes a `Problem`: a short `error` to show, a `detail` to expand, and a
`kind` the UI can branch on (offline ComfyUI is a banner, a bad field is inline).
"""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from h3lab.api.schemas import Problem, ProblemFieldError, ProblemKind
from h3lab.comfy.client import ComfyError, ComfyUnreachable
from h3lab.comfy.graph import WorkflowError
from h3lab.engine.shared_runner import SharedRequestConflict
from h3lab.settings import Settings
from h3lab.shared.client import (
    SharedProtocolError,
    SharedServiceError,
    SharedServiceUnavailable,
    SharedSubmissionUncertain,
)
from h3lab.storage.library import PresetNameTaken
from h3lab.storage.runs import RunNotFound


# Declared on every router so the schema — and the front end's generated types — carry the
# failure shape, rather than the handlers below returning an undocumented body.
PROBLEM_RESPONSES: dict[int | str, dict[str, object]] = {
    status: {"model": Problem, "description": description}
    for status, description in {
        400: "the request cannot be carried out as asked",
        404: "no such run, preset, or file",
        409: "the name or state conflicts with something that already exists",
        422: "a field is missing or out of range",
        502: "ComfyUI refused the request",
        503: "ComfyUI is not reachable",
    }.items()
}


def problem(
    status: int,
    kind: ProblemKind,
    error: str,
    detail: str = "",
    code: str | None = None,
    retryable: bool | None = None,
    errors: list[ProblemFieldError] | None = None,
    field_map: Mapping[str, str] | None = None,
    **fields: str,
) -> JSONResponse:
    body = Problem(
        error=error,
        detail=detail or error,
        kind=kind,
        fields={**(field_map or {}), **fields},
        code=code,
        retryable=retryable,
        errors=errors,
    )
    return JSONResponse(status_code=status, content=body.model_dump(exclude_none=True))


def _field_path(location: object) -> str:
    if not isinstance(location, (list, tuple)):
        return ""
    parts = [str(part) for part in location if part not in ("body", "__root__")]
    return ".".join(parts)


def _from_validation(exc: ValidationError | RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    first = errors[0] if errors else {}
    where = _field_path(first.get("loc"))
    fields = {_field_path(item.get("loc")) or "?": str(item.get("msg", "")) for item in errors}
    return problem(
        422,
        "invalid",
        first.get("msg", "the request is not valid"),
        f"{where or 'request'}: {first.get('msg', 'invalid')}",
        field_map=fields,
    )


def install(app: FastAPI, settings: Settings) -> None:
    @app.exception_handler(RunNotFound)
    async def _run_missing(_request: Request, exc: RunNotFound) -> JSONResponse:
        run_id = str(exc.args[0]) if exc.args else "?"
        return problem(404, "not_found", "no such run", f"run {run_id} does not exist", run=run_id)

    @app.exception_handler(PresetNameTaken)
    async def _preset_taken(_request: Request, exc: PresetNameTaken) -> JSONResponse:
        return problem(
            409,
            "conflict",
            "that preset name is taken",
            f"{exc}. Save under another name, or replace the existing one.",
        )

    @app.exception_handler(WorkflowError)
    async def _workflow_broken(_request: Request, exc: WorkflowError) -> JSONResponse:
        return problem(422, "workflow", "the workflow cannot run this config", str(exc))

    @app.exception_handler(ComfyUnreachable)
    async def _comfy_down(_request: Request, exc: ComfyUnreachable) -> JSONResponse:
        return problem(
            503,
            "comfy_unreachable",
            "ComfyUI is not reachable",
            f"{exc}. Start ComfyUI, then retry.",
            url=settings.comfy_url,
        )

    @app.exception_handler(ComfyError)
    async def _comfy_failed(_request: Request, exc: ComfyError) -> JSONResponse:
        return problem(502, "invalid", "ComfyUI refused the request", str(exc))

    @app.exception_handler(SharedServiceUnavailable)
    async def _shared_down(_request: Request, exc: SharedServiceUnavailable) -> JSONResponse:
        return problem(
            503,
            "shared_unavailable",
            "The shared generation service is not reachable",
            str(exc),
            code="shared_service_unavailable",
            retryable=True,
        )

    @app.exception_handler(SharedSubmissionUncertain)
    async def _shared_uncertain(_request: Request, exc: SharedSubmissionUncertain) -> JSONResponse:
        return problem(
            503,
            "shared_uncertain",
            "The shared submission outcome is uncertain",
            str(exc),
            code="shared_submission_uncertain",
            retryable=True,
        )

    @app.exception_handler(SharedServiceError)
    async def _shared_refused(_request: Request, exc: SharedServiceError) -> JSONResponse:
        upstream = exc.problem
        field_errors = [
            ProblemFieldError(field=item.field, code=item.code, detail=item.detail)
            for item in upstream.errors or []
        ]
        return problem(
            upstream.status,
            (
                "shared_unavailable"
                if upstream.status == 503 and upstream.retryable
                else "conflict"
                if upstream.status == 409
                else "invalid"
            ),
            upstream.title,
            upstream.detail or upstream.title,
            code=upstream.code,
            retryable=upstream.retryable,
            errors=field_errors,
            **{item.field: item.detail for item in field_errors},
        )

    @app.exception_handler(SharedProtocolError)
    async def _shared_protocol(_request: Request, exc: SharedProtocolError) -> JSONResponse:
        return problem(
            502,
            "shared_protocol",
            "The shared service returned an incompatible response",
            str(exc),
            code="shared_protocol_error",
            retryable=False,
        )

    @app.exception_handler(RequestValidationError)
    async def _bad_request(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return _from_validation(exc)

    @app.exception_handler(ValidationError)
    async def _bad_model(_request: Request, exc: ValidationError) -> JSONResponse:
        return _from_validation(exc)

    @app.exception_handler(FileNotFoundError)
    async def _file_missing(_request: Request, exc: FileNotFoundError) -> JSONResponse:
        return problem(404, "not_found", "that file is not on disk", str(exc))

    @app.exception_handler(SharedRequestConflict)
    async def _shared_conflict(_request: Request, exc: SharedRequestConflict) -> JSONResponse:
        return problem(409, "conflict", "Idempotency key conflict", str(exc))

    @app.exception_handler(ValueError)
    async def _bad_value(_request: Request, exc: ValueError) -> JSONResponse:
        return problem(400, "invalid", str(exc) or "the request is not valid")


__all__ = ["PROBLEM_RESPONSES", "install", "problem"]
