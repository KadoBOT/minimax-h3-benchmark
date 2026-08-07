#!/usr/bin/env python3
"""MiniMax H3 ComfyUI benchmark runner + progressive results UI."""
from __future__ import annotations

import argparse
import sys
import time

from bench import store
from bench.comfy import ComfyClient, ComfyError
from bench.constants import DEFAULT_COMFY_URL, DEFAULT_UI_PORT
from bench.runner import BenchmarkRunner
from bench.server import attach_runner, start_server


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="H3 ComfyUI interactive benchmark")
    p.add_argument("--comfy-url", default=DEFAULT_COMFY_URL)
    p.add_argument("--port", type=int, default=DEFAULT_UI_PORT)
    p.add_argument(
        "--ui-only",
        action="store_true",
        help="Serve results UI only (no Comfy attach / no runner)",
    )
    args = p.parse_args(argv)

    store.ensure_dirs()

    if args.ui_only:
        httpd = start_server(args.port)
        print(f"Results UI: http://127.0.0.1:{args.port}/")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            httpd.shutdown()
            return 0

    client = ComfyClient(args.comfy_url)
    try:
        client.system_stats()
    except ComfyError as e:
        print(f"WARNING: ComfyUI not reachable at {args.comfy_url}: {e}", file=sys.stderr)
        print("UI will start; health/options will report fallbacks until Comfy is up.")

    existing = store.try_load_suite()
    runner = BenchmarkRunner(client, resume=False)
    suite = existing or runner.ensure_suite()
    if not suite.runs:
        suite.status = "idle"
    store.save_suite(suite)

    attach_runner(runner, suite)
    httpd = start_server(args.port)
    print(f"Interactive UI: http://127.0.0.1:{args.port}/")
    print("Tweak config in the UI and click Run. Ctrl+C to exit.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("Shutting down…")
        runner.request_abort()
        try:
            client.cancel_all()
        except Exception:
            pass
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
