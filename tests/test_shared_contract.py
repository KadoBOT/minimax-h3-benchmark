from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from h3lab.shared.contracts import (
    GenerationDocument,
    Problem,
    PublicJob,
    PublicJobProvenance,
)
from h3lab.shared.generated_contract import (
    OPENAPI_SHA256,
    REQUIRED_PATHS,
    REQUIRED_SCHEMAS,
)
from scripts.sync_shared_contract import GENERATED, TARGET, main


def generation_document(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "protocolVersion": "1.0",
        "documentId": "minimax-h3-unified:generation",
        "schemaRevision": "h3-v1",
        "workflowId": "minimax-h3-unified",
        "workflowRevision": f"sha256:{'a' * 64}",
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
                "maxLength": 1000,
            }
        ],
        "actions": [
            {
                "id": "generate",
                "kind": "submit",
                "label": "Generate",
                "endpoint": "/v1/workflows/minimax-h3-unified/jobs",
                "method": "POST",
                "optional": False,
            }
        ],
    }
    value.update(overrides)
    return value


def test_pinned_contract_and_generated_metadata_are_byte_current():
    assert main(["--check"]) == 0
    canonical = TARGET.read_text(encoding="utf-8")
    assert OPENAPI_SHA256 == f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"
    document = json.loads(canonical)
    assert set(REQUIRED_PATHS) <= set(document["paths"])
    assert set(REQUIRED_SCHEMAS) <= set(document["components"]["schemas"])
    assert GENERATED.is_file()
    assert "/v1/workflows" in REQUIRED_PATHS


def test_generation_contract_is_strict_and_rejects_unsafe_action_paths():
    parsed = GenerationDocument.model_validate(generation_document())
    assert parsed.workflow_id == "minimax-h3-unified"
    assert parsed.actions[0].endpoint == "/v1/workflows/minimax-h3-unified/jobs"

    unsafe = generation_document()
    unsafe["actions"] = [
        {
            "id": "generate",
            "kind": "submit",
            "label": "Generate",
            "endpoint": "//attacker.invalid/jobs",
            "method": "POST",
            "optional": False,
        }
    ]
    with pytest.raises(ValidationError):
        GenerationDocument.model_validate(unsafe)

    extra = generation_document(localPath="/tmp/private")
    with pytest.raises(ValidationError):
        GenerationDocument.model_validate(extra)


def test_public_job_exposes_only_safe_provenance():
    provenance = PublicJobProvenance.model_validate(
        {
            "manifestDigest": f"sha256:{'b' * 64}",
            "compiler": {"id": "h3", "version": "1"},
            "catalogRevision": f"sha256:{'c' * 64}",
            "inputDigest": f"sha256:{'d' * 64}",
            "resolvedSeed": 42,
        }
    )
    assert provenance.resolved_seed == 42
    with pytest.raises(ValidationError):
        PublicJobProvenance.model_validate(
            {
                **provenance.model_dump(by_alias=True),
                "clientId": "11111111-1111-4111-8111-111111111111",
            }
        )

    job = PublicJob.model_validate(
        {
            "id": "11111111-1111-4111-8111-111111111111",
            "workflowId": "minimax-h3-unified",
            "workflowRevision": f"sha256:{'a' * 64}",
            "schemaRevision": "h3-v1",
            "state": "queued",
            "version": 1,
            "createdAt": "2026-08-15T08:00:00.000Z",
            "updatedAt": "2026-08-15T08:00:01.000Z",
            "provenance": provenance.model_dump(by_alias=True),
            "links": {
                "self": "/v1/jobs/11111111-1111-4111-8111-111111111111",
                "view": "/v1/jobs/11111111-1111-4111-8111-111111111111/view",
                "events": "/v1/jobs/11111111-1111-4111-8111-111111111111/events",
                "cancel": "/v1/jobs/11111111-1111-4111-8111-111111111111/cancel",
            },
        }
    )
    assert job.provenance == provenance


def test_problem_contract_preserves_typed_field_errors():
    parsed = Problem.model_validate(
        {
            "type": "https://comfyui-sdui.local/problems/job-input-invalid",
            "title": "Invalid input",
            "status": 422,
            "detail": "The prompt is too long.",
            "instance": "/v1/workflows/minimax-h3-unified/jobs",
            "code": "job_input_invalid",
            "retryable": False,
            "errors": [
                {
                    "field": "input.prompt",
                    "code": "too_big",
                    "detail": "Maximum length is 1000.",
                }
            ],
        }
    )
    assert parsed.errors and parsed.errors[0].field == "input.prompt"


def test_contract_snapshot_does_not_contain_machine_paths():
    text = Path(TARGET).read_text(encoding="utf-8")
    assert "/home/kadobot" not in text
    assert "/run/media" not in text
