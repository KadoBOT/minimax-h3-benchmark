"""Generate the front end's mirror of the API types from the live OpenAPI schema.

Run `python scripts/gen_types.py` after changing any model the API returns.
`tests/test_contract.py` regenerates and byte-compares, so drift fails the suite rather
than surfacing as a runtime `undefined` in the browser.

Written here rather than delegated to `openapi-typescript` because that package peers on
TypeScript 5 while this project is on 6, and because a schema this small does not justify
the dependency.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET = REPO_ROOT / "web" / "src" / "api" / "schema.ts"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

HEADER = """/* eslint-disable */
/**
 * Generated from the API's OpenAPI schema by `python scripts/gen_types.py`.
 * Do not edit by hand — `tests/test_contract.py` regenerates this file and fails on drift.
 */
"""

PRIMITIVES = {
    "string": "string",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
    "null": "null",
}


def schema_json() -> dict[str, Any]:
    from h3lab.api.app import create_app

    return create_app().openapi()


def ts_name(name: str) -> str:
    """Component names are already the model names; only FastAPI's generated bodies need work.

    `Body_upload_api_uploads_post` becomes `BodyUploadApiUploadsPost`, while `GenerationConfig`
    is passed through untouched — title-casing it would flatten it to `Generationconfig`.
    """
    if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", name) and "_" not in name:
        return name
    parts = re.split(r"[^0-9a-zA-Z]+", name)
    cleaned = "".join(part[:1].upper() + part[1:] for part in parts if part)
    return cleaned or "Unknown"


def render(node: Any, names: dict[str, str], depth: int = 0) -> str:
    if node is True or node == {}:
        return "unknown"
    if node is False:
        return "never"
    if not isinstance(node, dict):
        return "unknown"

    if "$ref" in node:
        ref = node["$ref"].rsplit("/", 1)[-1]
        return names.get(ref, ts_name(ref))

    if "const" in node:
        return json.dumps(node["const"])

    if "enum" in node:
        return " | ".join(json.dumps(value) for value in node["enum"]) or "never"

    for key in ("anyOf", "oneOf"):
        if key in node:
            parts = [render(part, names, depth) for part in node[key]]
            unique = list(dict.fromkeys(parts))
            return " | ".join(unique) if unique else "unknown"

    if "allOf" in node:
        parts = [render(part, names, depth) for part in node["allOf"]]
        unique = list(dict.fromkeys(parts))
        return " & ".join(unique) if unique else "unknown"

    kind = node.get("type")

    if kind == "array":
        if node.get("prefixItems"):
            inner = ", ".join(render(item, names, depth) for item in node["prefixItems"])
            return f"[{inner}]"
        return f"{wrap(render(node.get('items', {}), names, depth))}[]"

    if kind == "object" or "properties" in node:
        if "properties" in node:
            return object_body(node, names, depth)
        extra = node.get("additionalProperties")
        inner = render(extra, names, depth) if isinstance(extra, dict) else "unknown"
        return f"Record<string, {inner}>"

    if isinstance(kind, list):
        return " | ".join(PRIMITIVES.get(item, "unknown") for item in kind)

    return PRIMITIVES.get(kind, "unknown")


def wrap(rendered: str) -> str:
    """Parenthesise unions and intersections so `X | Y` arrays stay `(X | Y)[]`."""
    bare = re.sub(r"\[[^\]]*\]", "", rendered)
    return f"({rendered})" if ("|" in bare or "&" in bare) else rendered


def object_body(node: dict[str, Any], names: dict[str, str], depth: int) -> str:
    required = set(node.get("required", ()))
    pad = "  " * (depth + 1)
    lines = []
    for prop, spec in node.get("properties", {}).items():
        mark = "" if prop in required else "?"
        lines.append(f"{pad}{quote(prop)}{mark}: {render(spec, names, depth + 1)};")
    if not lines:
        return "Record<string, never>"
    close = "  " * depth
    return "{\n" + "\n".join(lines) + f"\n{close}}}"


def quote(prop: str) -> str:
    return prop if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", prop) else json.dumps(prop)


def doc_for(name: str, node: dict[str, Any]) -> str:
    text = (node.get("description") or "").strip()
    if not text:
        return ""
    first = text.split("\n\n", 1)[0].replace("\n", " ").strip()
    return f"/** {first} */\n" if first else ""


def generate() -> str:
    schema = schema_json()
    components: dict[str, Any] = schema.get("components", {}).get("schemas", {})
    names = {raw: ts_name(raw) for raw in components}

    blocks: list[str] = []
    for raw in sorted(components):
        node = components[raw]
        name = names[raw]
        body = render(node, names, 0)
        doc = doc_for(name, node)
        if body.startswith("{"):
            blocks.append(f"{doc}export interface {name} {body}")
        else:
            blocks.append(f"{doc}export type {name} = {body};")

    paths = sorted(schema.get("paths", {}))
    route_list = "\n".join(f"  {json.dumps(path)}," for path in paths)
    blocks.append(
        "/** Every path the API answers, so the client's URLs can be checked against it. */\n"
        f"export const API_PATHS = [\n{route_list}\n] as const;"
    )

    return HEADER + "\n" + "\n\n".join(blocks) + "\n"


def main(argv: list[str]) -> int:
    text = generate()
    if "--check" in argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.is_file() else ""
        if current != text:
            print(f"{TARGET} is stale — run `python scripts/gen_types.py`", file=sys.stderr)
            return 1
        print(f"{TARGET} matches the schema")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(text, encoding="utf-8")
    print(f"wrote {TARGET} ({len(text.splitlines())} lines)")
    prettier = REPO_ROOT / "web" / "node_modules" / ".bin" / "prettier.cmd"
    if prettier.is_file():
        subprocess.run([str(prettier), "--write", str(TARGET)], check=False, capture_output=True)
        print("formatted with prettier")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
