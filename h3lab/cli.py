"""Command line entry point.

`serve` is the normal path. `check` exists because the two failures that used to waste the
most time — ComfyUI not running, and a workflow template that cannot be patched — are both
answerable in under a second without queueing anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import suppress
from pathlib import Path
from typing import Sequence, TextIO

from h3lab.settings import Settings

EXIT_OK = 0
EXIT_PROBLEM = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="h3lab",
        description="Benchmark, judge, and compare MiniMax H3 video generations.",
    )
    parser.add_argument("--comfy-url", help="ComfyUI base URL")
    parser.add_argument("--data-dir", type=Path, help="where runs, videos, and the database live")
    parser.add_argument("--models-dir", type=Path, help="diffusion model folder to scan")
    parser.add_argument("--comfy-input-dir", type=Path, help="ComfyUI input folder")
    parser.add_argument("--workflow-dir", type=Path, help="folder holding the workflow templates")
    parser.add_argument("--web-dist", type=Path, help="built front end to serve")

    # Bare `h3lab` serves, so serve's own flags need defaults on the top-level parser too.
    # The subparser action owns `command` and defaults it to None, which `main` reads as serve.
    parser.set_defaults(host=None, port=None, reload=False, no_worker=False, open=False, json=False)

    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="run the web app (default)")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--reload", action="store_true", help="restart on source changes")
    serve.add_argument("--no-worker", action="store_true", help="serve without executing runs")
    serve.add_argument("--open", action="store_true", help="open a browser once listening")

    check = sub.add_parser("check", help="report what is wrong without queueing anything")
    check.add_argument("--json", action="store_true", help="machine-readable output")

    sub.add_parser("import-legacy", help="pull runs out of the previous lab's database")
    sub.add_parser("routes", help="list every route the API answers")
    sub.add_parser("openapi", help="print the OpenAPI schema the front end's types mirror")
    return parser


def settings_from(args: argparse.Namespace) -> Settings:
    return Settings.from_env(
        comfy_url=getattr(args, "comfy_url", None),
        host=getattr(args, "host", None),
        port=getattr(args, "port", None),
        data_dir=getattr(args, "data_dir", None),
        models_dir=getattr(args, "models_dir", None),
        comfy_input_dir=getattr(args, "comfy_input_dir", None),
        workflow_dir=getattr(args, "workflow_dir", None),
        web_dist=getattr(args, "web_dist", None),
    )


class Report:
    """What `check` found: one row per subsystem."""

    def __init__(self) -> None:
        self.checks: list[dict[str, object]] = []

    def record(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append({"check": name, "ok": ok, "detail": detail})

    @property
    def ok(self) -> bool:
        return all(bool(item["ok"]) for item in self.checks)


def _checks(settings: Settings) -> Report:
    """Each check answers one question a user would otherwise answer by trial and error."""
    from h3lab.comfy.client import ComfyClient, ComfyError
    from h3lab.comfy.graph import load_workflow
    from h3lab.comfy.schema import Schemas
    from h3lab.comfy.studio import find_studio_node
    from h3lab.comfy.workflow import executable
    from h3lab.domain.config import GEN_MODES
    from h3lab.engine import artifacts

    report = Report()
    record = report.record

    record("data directory", True, str(settings.data_dir))
    settings.ensure_dirs()

    # ComfyUI comes first because its answer changes the workflow checks: with the live node
    # schemas in hand, a widget a node pack renamed is reported here instead of at run time.
    client = ComfyClient(settings.comfy_url, connect_timeout_s=1.5, request_timeout_s=5.0)
    schemas = Schemas()
    try:
        stats = client.system_stats()
        devices = stats.get("devices") or []
        name = devices[0].get("name", "unknown") if devices else "unknown"
        record("comfyui", True, f"{settings.comfy_url} — {name}")
        schemas = Schemas.from_client(client)
        record(
            "node schemas",
            bool(schemas),
            f"{len(schemas)} node classes installed" if schemas else "ComfyUI answered nothing",
        )
    except ComfyError as exc:
        record("comfyui", False, f"{settings.comfy_url} — {exc}")

    for mode in GEN_MODES:
        path = settings.workflow_path(mode)
        if not path.is_file():
            record(f"workflow {mode}", False, f"missing at {path}")
            record(f"studio {mode}", False, f"missing at {path}")
            continue
        try:
            template = load_workflow(path)
            prompt, _graph = executable(
                template,
                widget_names=schemas.widget_names,
            )
            studio_id, _studio = find_studio_node(prompt)
            record(
                f"workflow {mode}",
                True,
                f"{len(prompt)} nodes",
            )
            record(f"studio {mode}", True, f"node {studio_id}")
        except Exception as exc:  # noqa: BLE001 - a broken template is the answer, not a crash
            record(f"workflow {mode}", False, f"{type(exc).__name__}: {exc}")
            record(f"studio {mode}", False, f"{type(exc).__name__}: {exc}")

    client.close()

    models_dir = settings.models_dir
    if models_dir.is_dir():
        found = sum(
            1
            for path in models_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in {".safetensors", ".gguf", ".sft"}
        )
        record("models", found > 0, f"{found} file(s) under {models_dir}")
    else:
        record("models", False, f"{models_dir} is not a directory")

    for tool in ("ffmpeg", "ffprobe"):
        binary = getattr(settings, tool)
        found = artifacts.tool_available(binary)
        record(tool, found, binary if found else f"{binary} is not on PATH — previews will be skipped")

    dist = settings.web_dist / "index.html"
    record(
        "front end",
        dist.is_file(),
        str(settings.web_dist) if dist.is_file() else "not built — run `npm run build` in web/",
    )
    return report


def command_check(settings: Settings, as_json: bool, out: TextIO) -> int:
    report = _checks(settings)
    results = report.checks
    if as_json:
        json.dump({"ok": report.ok, "checks": results}, out, indent=2)
        out.write("\n")
    else:
        width = max(len(str(item["check"])) for item in results)
        for item in results:
            mark = "ok  " if item["ok"] else "FAIL"
            out.write(f"{mark}  {str(item['check']).ljust(width)}  {item['detail']}\n")
        failed = [item for item in results if not item["ok"]]
        out.write(
            f"\n{len(results) - len(failed)}/{len(results)} checks passed\n"
            if failed
            else f"\nall {len(results)} checks passed\n"
        )
    # ffmpeg and the front end are optional; the lab runs without them.
    fatal = {"comfyui"} | {
        item["check"]
        for item in results
        if str(item["check"]).startswith(("workflow", "studio"))
    }
    return EXIT_PROBLEM if any(not i["ok"] and i["check"] in fatal for i in results) else EXIT_OK


def command_routes(settings: Settings, out: TextIO) -> int:
    from h3lab.api.app import create_app, routes_of

    app = create_app(settings=settings)
    for method, path in sorted(routes_of(app), key=lambda pair: (pair[1], pair[0])):
        if method in ("HEAD", "OPTIONS"):
            continue
        out.write(f"{method:<7} {path}\n")
    return EXIT_OK


def command_openapi(settings: Settings, out: TextIO) -> int:
    """Print the OpenAPI schema, so the front end's types can be generated from it."""
    from h3lab.api.app import create_app

    app = create_app(settings=settings)
    json.dump(app.openapi(), out, indent=2, sort_keys=True)
    out.write("\n")
    return EXIT_OK


def command_import_legacy(settings: Settings, out: TextIO) -> int:
    from h3lab.engine.lab import Lab

    lab = Lab(settings, start_worker=False)
    try:
        report = lab.import_legacy()
    finally:
        lab.close()
    out.write(
        f"imported {report.runs_imported} run(s), {report.ratings_imported} rating(s),"
        f" {report.videos_copied} video(s) from {settings.legacy_db_path}\n"
        f"{report.already_present} already present, {len(report.skipped)} skipped\n"
        f"built previews for {report.previews_built} run(s)\n"
    )
    for note in report.skipped:
        out.write(f"  skipped {note}\n")
    return EXIT_OK


def browsable_url(settings: Settings) -> str:
    """The address to actually open.

    `0.0.0.0` means "bind every interface", not a host you can reach — a browser given it
    either refuses or guesses. Anything else is what the user asked to bind, so it is left
    exactly as they wrote it.
    """
    host = "127.0.0.1" if settings.host in {"0.0.0.0", "::"} else settings.host
    return f"http://{host}:{settings.port}"


def command_serve(settings: Settings, args: argparse.Namespace, out: TextIO) -> int:
    import uvicorn

    out.write(f"H3 Lab on {browsable_url(settings)}  (ComfyUI: {settings.comfy_url})\n")
    if not (settings.web_dist / "index.html").is_file():
        out.write("  the front end is not built yet — run `npm install && npm run build` in web/\n")
    out.flush()

    if args.open:
        import threading
        import webbrowser

        url = f"{browsable_url(settings)}/"
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    if args.reload:
        # Reload needs an import string, so settings travel through the environment.
        import os

        os.environ.setdefault("H3LAB_COMFY_URL", settings.comfy_url)
        os.environ.setdefault("H3LAB_DATA_DIR", str(settings.data_dir))
        uvicorn.run(
            "h3lab.api.factory:app",
            host=settings.host,
            port=settings.port,
            reload=True,
            factory=False,
            timeout_graceful_shutdown=1.0,
        )
        return EXIT_OK

    from h3lab.api.app import create_app
    from h3lab.engine.lab import Lab

    lab = Lab(settings, start_worker=not args.no_worker)
    app = create_app(lab=lab, settings=settings)
    try:
        uvicorn.run(
            app,
            host=settings.host,
            port=settings.port,
            log_level="info",
            timeout_graceful_shutdown=1.0,
        )
    finally:
        lab.close()
    return EXIT_OK


def main(argv: Sequence[str] | None = None, out: TextIO | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    stream = out or sys.stdout
    # The messages here use em dashes and arrows. A legacy Windows code page cannot encode
    # those, and a report must not die on its own punctuation.
    if out is None:
        with suppress(AttributeError, OSError, ValueError):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    settings = settings_from(args)

    handlers = {
        "check": lambda: command_check(settings, as_json=args.json, out=stream),
        "routes": lambda: command_routes(settings, stream),
        "openapi": lambda: command_openapi(settings, stream),
        "import-legacy": lambda: command_import_legacy(settings, stream),
        "serve": lambda: command_serve(settings, args, stream),
    }
    handler = handlers.get(args.command or "serve")
    if handler is None:
        parser.print_help(stream)
        return EXIT_USAGE
    return handler()


if __name__ == "__main__":
    raise SystemExit(main())
