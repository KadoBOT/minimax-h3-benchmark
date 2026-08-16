"""Pin and verify the shared ComfyUI SDUI OpenAPI contract.

The browser and Python bridge compile against a checked-in snapshot. Runtime never reaches
into the shared backend's source tree, while this explicit command makes contract upgrades
reviewable and byte-deterministic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET = REPO_ROOT / "contracts" / "comfyui-sdui.openapi.json"
GENERATED = REPO_ROOT / "h3lab" / "shared" / "generated_contract.py"

REQUIRED_PATHS = (
    "/v1/artifacts/{mediaId}/content",
    "/v1/assets",
    "/v1/assets/{mediaId}/content",
    "/v1/jobs/{jobId}",
    "/v1/jobs/{jobId}/cancel",
    "/v1/jobs/{jobId}/events",
    "/v1/jobs/{jobId}/preview",
    "/v1/jobs/{jobId}/retry-collection",
    "/v1/jobs/{jobId}/view",
    "/v1/workflows",
    "/v1/workflows/{workflowId}/jobs",
    "/v1/workflows/{workflowId}/views/generation",
)
REQUIRED_SCHEMAS = (
    "GenerationDocument",
    "JobDocument",
    "JobSubmission",
    "Problem",
    "PublicJob",
    "PublicJobEvent",
    "PublicJobProvenance",
    "PublicMediaMetadata",
)


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read OpenAPI contract at {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TypeError("OpenAPI contract must be a JSON object")
    return value


def _validate(document: dict[str, Any]) -> None:
    if document.get("openapi") != "3.1.0":
        raise ValueError("shared contract must use OpenAPI 3.1.0")
    info = document.get("info")
    if not isinstance(info, dict) or info.get("title") != "ComfyUI SDUI Backend API":
        raise ValueError("shared contract has an unexpected API identity")
    paths = document.get("paths")
    if not isinstance(paths, dict):
        raise TypeError("shared contract has no path map")
    missing_paths = [path for path in REQUIRED_PATHS if path not in paths]
    schemas = (document.get("components") or {}).get("schemas") or {}
    if not isinstance(schemas, dict):
        raise TypeError("shared contract has no schema map")
    missing_schemas = [name for name in REQUIRED_SCHEMAS if name not in schemas]
    if missing_paths or missing_schemas:
        parts = []
        if missing_paths:
            parts.append(f"paths: {', '.join(missing_paths)}")
        if missing_schemas:
            parts.append(f"schemas: {', '.join(missing_schemas)}")
        raise ValueError("shared contract is missing required " + "; ".join(parts))


def _canonical(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _kind_constants(node: object) -> Iterable[str]:
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            kind = properties.get("kind")
            if isinstance(kind, dict):
                if isinstance(kind.get("const"), str):
                    yield kind["const"]
                enum = kind.get("enum")
                if (
                    isinstance(enum, list)
                    and len(enum) == 1
                    and isinstance(enum[0], str)
                ):
                    yield enum[0]
        for value in node.values():
            yield from _kind_constants(value)
    elif isinstance(node, list):
        for value in node:
            yield from _kind_constants(value)


def _generated(document: dict[str, Any], canonical: str) -> str:
    schemas = document["components"]["schemas"]
    generation_kinds = sorted(
        set(_kind_constants(schemas["GenerationDocument"])) - {"generation"}
    )
    job_kinds = sorted(set(_kind_constants(schemas["JobDocument"])) - {"job"})
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    version = str(document["info"].get("version") or "")

    def tuple_text(values: Iterable[str]) -> str:
        return (
            "(\n"
            + "".join(
                f"    {json.dumps(value, ensure_ascii=False)},\n" for value in values
            )
            + ")"
        )

    return (
        '"""Generated metadata for the pinned shared-service contract. Do not edit."""\n\n'
        f'OPENAPI_SHA256 = (\n    "sha256:{digest}"\n)\n'
        f"OPENAPI_VERSION = {json.dumps(version)}\n"
        'PROTOCOL_VERSION = "1.0"\n'
        'WORKFLOW_ID = "minimax-h3-unified"\n'
        f"REQUIRED_PATHS = {tuple_text(REQUIRED_PATHS)}\n"
        f"REQUIRED_SCHEMAS = {tuple_text(REQUIRED_SCHEMAS)}\n"
        f"GENERATION_KINDS = {tuple_text(generation_kinds)}\n"
        f"JOB_KINDS = {tuple_text(job_kinds)}\n"
    )


def _matches(path: Path, expected: str) -> bool:
    try:
        return path.read_text(encoding="utf-8") == expected
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=TARGET)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    try:
        document = _load(args.source)
        _validate(document)
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))

    canonical = _canonical(document)
    generated = _generated(document, canonical)
    if args.check:
        stale = []
        if not _matches(TARGET, canonical):
            stale.append(str(TARGET))
        if not _matches(GENERATED, generated):
            stale.append(str(GENERATED))
        if stale:
            print("stale shared contract output: " + ", ".join(stale), file=sys.stderr)
            return 1
        print("shared contract snapshot and metadata are current")
        return 0

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    GENERATED.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(canonical, encoding="utf-8")
    GENERATED.write_text(generated, encoding="utf-8")
    print(f"wrote {TARGET}")
    print(f"wrote {GENERATED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
