"""The seam between the API and the browser.

The front end's types are generated from the OpenAPI schema, and the front end's URLs are
declared in one table. Both are checked here, because the failure they prevent — a renamed
field or a moved route reaching the browser as `undefined` — is invisible to the Python
tests and to `tsc` alike.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB = REPO_ROOT / "web"
SCHEMA_TS = WEB / "src" / "api" / "schema.ts"
ROUTES_TS = WEB / "src" / "api" / "routes.ts"
LIMITS_TS = WEB / "src" / "lib" / "limits.ts"
EVENTS_TSX = WEB / "src" / "api" / "events.tsx"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import gen_types  # noqa: E402


def test_the_generated_types_match_the_current_schema():
    """Fails when a model changes without `python scripts/gen_types.py` being re-run."""
    assert SCHEMA_TS.is_file(), f"{SCHEMA_TS} is missing — run python scripts/gen_types.py"
    expected = gen_types.generate()
    actual = SCHEMA_TS.read_text(encoding="utf-8")

    # Prettier reflows the generated source, so compare on content rather than formatting.
    assert _names(actual) == _names(expected), "the generated types are stale"
    assert _paths(actual) == _paths(expected), "the exported path list is stale"
    assert _fields(actual) == _fields(expected), "a field changed shape"


def test_the_event_stream_speaks_the_dialect_the_browser_is_listening_in():
    """Which SSE frames reach the client is decided by a field neither suite could see.

    A frame with an `event:` field is dispatched to a listener of that name; only a frame
    without one reaches `onmessage`. The client sets `onmessage` and nothing else, so naming
    the frames silently unplugged the whole live layer — with the socket open, no errors, and
    both suites green, because the Python test read the body as text and the browser fake
    called `onmessage` by hand.

    So the rule is checked across the seam, where the mismatch actually lives.
    """
    from h3lab.engine.events import Event

    client = EVENTS_TSX.read_text(encoding="utf-8")
    frame = Event(seq=1, kind="run.created").to_sse()
    named = [line for line in frame.splitlines() if line.startswith("event:")]

    if "addEventListener(" in client:
        assert named, "the client subscribes by name but the server sends unnamed frames"
    else:
        assert not named, (
            f"the server names its frames ({named[0]!r}) but the client only sets onmessage, "
            "which a named frame never reaches"
        )
    assert "onmessage" in client or "addEventListener(" in client


def test_every_url_the_front_end_calls_is_a_route_the_api_answers():
    from h3lab.api.app import create_app

    served = set(create_app().openapi()["paths"])
    called = _called_paths()
    assert called, f"no route templates found in {ROUTES_TS}"
    unknown = sorted(path for path in called if path not in served)
    assert not unknown, f"the front end calls routes the API does not serve: {unknown}"


def test_the_front_end_covers_every_route_worth_calling():
    """A route with no caller is either dead or a page that was never wired up."""
    from h3lab.api.app import create_app

    served = set(create_app().openapi()["paths"])
    called = _called_paths()
    # `/api/legacy-import` is a CLI concern; the docs routes are FastAPI's own.
    exempt = {"/api/legacy-import", "/api/events/recent"}
    missing = sorted(served - called - exempt)
    assert not missing, f"no front-end caller for: {missing}"


def _names(text: str) -> set[str]:
    return set(re.findall(r"export (?:interface|type) (\w+)", text))


def _paths(text: str) -> list[str]:
    block = re.search(r"API_PATHS = \[(.*?)\] as const", text, re.S)
    return sorted(re.findall(r'"([^"]+)"', block.group(1))) if block else []


def _fields(text: str) -> dict[str, set[str]]:
    """Every declared property per interface, normalised so formatting cannot matter."""
    out: dict[str, set[str]] = {}
    for match in re.finditer(r"export interface (\w+) \{(.*?)\n\}", text, re.S):
        name, body = match.group(1), match.group(2)
        props = set()
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("/*", "*", "//")):
                continue
            head = stripped.split(":", 1)
            if len(head) == 2:
                props.add(head[0].strip())
        out[name] = props
    return out


def _called_paths() -> set[str]:
    """Read the route table the client builds every URL from.

    Templates are written as `` `/api/runs/${id}` ``; each interpolation becomes `{x}` so the
    result can be compared against OpenAPI's own path templates.
    """
    if not ROUTES_TS.is_file():
        pytest.fail(f"{ROUTES_TS} is missing")
    text = ROUTES_TS.read_text(encoding="utf-8")
    found: set[str] = set()
    for raw in re.findall(r"[`\"'](/api/[^`\"'\n]*)[`\"']", text):
        path = re.sub(r"\$\{[^}]*\}", "{x}", raw).split("?")[0].rstrip("/")
        found.add(path or "/api")
    served = _served_templates()
    return {_align(path, served) for path in found}


def _served_templates() -> set[str]:
    from h3lab.api.app import create_app

    return set(create_app().openapi()["paths"])


def _align(path: str, served: set[str]) -> str:
    """Map `/api/runs/{x}` onto the served template that shares its shape."""
    if path in served:
        return path
    parts = path.split("/")
    for candidate in served:
        pieces = candidate.split("/")
        if len(pieces) != len(parts):
            continue
        if all(
            mine == theirs or (mine == "{x}" and theirs.startswith("{"))
            for mine, theirs in zip(parts, pieces)
        ):
            return candidate
    return path


def test_every_range_the_form_offers_is_one_the_api_accepts():
    """A control may offer a narrower range than the API, never a wider one.

    The megapixel slider started at 0.05 while the schema's floor was higher, so the form
    could hand over a value that came back as a 422 the user had no way to act on. Narrower
    is fine and often kinder — nobody benchmarks a 60 second clip — so only the direction
    that produces an unusable error is checked.
    """
    from h3lab.api.app import create_app

    fields = create_app().openapi()["components"]["schemas"]["GenerationConfig"]["properties"]
    limits = _limits()
    assert limits, f"no ranges found in {LIMITS_TS}"

    for field, offered in limits.items():
        assert field in fields, f"the form limits {field}, which the config does not have"
        spec = fields[field]
        low, high = spec.get("minimum"), spec.get("maximum")
        if low is not None:
            assert offered["min"] >= low, f"{field} slider starts below the accepted {low}"
        if high is not None:
            assert offered["max"] <= high, f"{field} slider ends above the accepted {high}"


def _limits() -> dict[str, dict[str, float]]:
    if not LIMITS_TS.is_file():
        pytest.fail(f"{LIMITS_TS} is missing")
    text = LIMITS_TS.read_text(encoding="utf-8")
    found: dict[str, dict[str, float]] = {}
    for name, body in re.findall(r"(\w+): \{([^}]*)\}", text):
        numbers = {key: float(value) for key, value in re.findall(r"(\w+): ([\d.]+)", body)}
        if {"min", "max"} <= set(numbers):
            found[name] = numbers
    return found


def test_the_generator_reports_staleness_rather_than_silently_passing(tmp_path, monkeypatch):
    monkeypatch.setattr(gen_types, "TARGET", tmp_path / "absent.ts")
    assert gen_types.main(["--check"]) == 1

    (tmp_path / "written.ts").write_text(gen_types.generate(), encoding="utf-8")
    monkeypatch.setattr(gen_types, "TARGET", tmp_path / "written.ts")
    assert gen_types.main(["--check"]) == 0


def test_the_schema_the_types_come_from_is_valid_openapi():
    from h3lab.api.app import create_app

    schema = create_app().openapi()
    assert schema["openapi"].startswith("3.")
    assert schema["info"]["title"]
    # Round-trips as JSON, which is what the generator and the docs page both consume.
    assert json.loads(json.dumps(schema)) == schema
