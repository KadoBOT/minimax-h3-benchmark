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
from bench.server import start_server


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="H3 ComfyUI benchmark suite")
    p.add_argument("--comfy-url", default=DEFAULT_COMFY_URL)
    p.add_argument("--port", type=int, default=DEFAULT_UI_PORT)
    p.add_argument("--ui-only", action="store_true")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--retry-failed", action="store_true")
    args = p.parse_args(argv)

    store.ensure_dirs()
    httpd = start_server(args.port)
    print(f"Results UI: http://127.0.0.1:{args.port}/")

    if args.ui_only:
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
        print(f"ERROR: {e}", file=sys.stderr)
        httpd.shutdown()
        return 1

    existing = store.try_load_suite() if args.resume else None
    runner = BenchmarkRunner(
        client,
        resume=args.resume,
        retry_failed=args.retry_failed,
    )
    try:
        runner.run_all(existing)
    except KeyboardInterrupt:
        print("Aborting… interrupting ComfyUI and clearing queue.")
        runner.request_abort()
        suite = store.try_load_suite()
        if suite:
            suite.status = "aborted"
            suite.current = None
            store.save_suite(suite)
        print("Aborted.")
    finally:
        # Always ensure Comfy is not left running our jobs after exit path.
        try:
            client.cancel_all()
        except Exception:
            pass
        print(f"UI still at http://127.0.0.1:{args.port}/ (Ctrl+C to exit)")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            try:
                client.cancel_all()
            except Exception:
                pass
            pass
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
