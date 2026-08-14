"""Three real generations over the real API, one per interpolation choice.

Not a test: it needs a GPU, a running ComfyUI, and a few minutes of both. It exists because
nothing in the suite can answer the two questions this feature actually turns on — whether ComfyUI
accepts the FILM branch, and whether the frame rate that reaches the file is the one the graph
claimed. Both are properties of the muxed output, so the check reads the output.

    python scripts/verify_interp.py

Prints a line per run and exits non-zero on the first disagreement.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from h3lab.api.app import create_app
from h3lab.settings import Settings

# What each choice must produce. Off is the sampler's own rate; FILM doubles the frames it is
# given; RIFE resamples to a rate it is told.
EXPECTED_FPS = {"off": 24, "film": 48, "rife": 60}

# Small enough to run three of on a laptop, large enough that the samplers' own minimums do not
# bite: megapixels below 0.1 are rejected by the resolution node.
CONFIG = {
    "mode": "t2v",
    "prompt": "a paper boat turning in a puddle, overcast",
    "steps": 4,
    "mp": 0.1,
    "duration_s": 2,
    "seed": 11,
}


def ffprobe(path: Path, entries: str) -> str:
    return subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", entries,
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def measured_fps(path: Path) -> float:
    raw = ffprobe(path, "stream=avg_frame_rate")
    num, _, den = raw.partition("/")
    return int(num) / int(den or 1)


def comfy_png(settings: Settings, run_id: str) -> dict | None:
    """The graph inside the still VHS saved beside the video, straight from ComfyUI.

    The lab's own poster is an ffmpeg thumbnail and carries nothing; the file that matters is the
    one ComfyUI wrote, which is what a person drags onto the canvas.
    """
    from PIL import Image

    query = urllib.parse.urlencode(
        {"filename": f"{run_id}_00001.png", "subfolder": "h3lab", "type": "output"}
    )
    with urllib.request.urlopen(f"{settings.comfy_url}/view?{query}", timeout=30) as response:
        blob = response.read()
    scratch = Path(tempfile.gettempdir()) / f"h3lab-verify-{run_id}.png"
    scratch.write_bytes(blob)
    with Image.open(scratch) as image:
        raw = image.info.get("workflow")
    return json.loads(raw) if raw else None


def main() -> int:
    scratch = Path(tempfile.mkdtemp(prefix="h3lab-live-"))
    settings = replace(Settings.from_env(), data_dir=scratch)
    app = create_app(settings=settings)
    failures: list[str] = []

    with TestClient(app) as client:
        queued = []
        for interp in EXPECTED_FPS:
            response = client.post("/api/runs", json={"config": {**CONFIG, "interp": interp}})
            response.raise_for_status()
            run_id = response.json()[0]["run"]["id"]
            queued.append((interp, run_id))
            print(f"queued {interp:<5} {run_id}")

        for interp, run_id in queued:
            deadline = time.monotonic() + 900
            view: dict = {}
            status = "unknown"
            while time.monotonic() < deadline:
                view = client.get(f"/api/runs/{run_id}").json()
                status = view["run"]["status"]
                if status in {"succeeded", "failed", "cancelled"}:
                    break
                time.sleep(3)

            if status != "succeeded":
                failures.append(f"{interp}: {status} — {view.get('run', {}).get('error')}")
                print(f"FAIL  {interp:<5} {status}: {view.get('run', {}).get('error')}")
                continue

            artifact = view["run"]["artifact"]
            video = settings.videos_dir / artifact["video_path"]
            fps = measured_fps(video)
            expected = EXPECTED_FPS[interp]
            ok = abs(fps - expected) < 0.5
            failures.extend(
                [] if ok else [f"{interp}: {fps:g} fps in the file, expected {expected}"]
            )
            print(
                f"{'ok  ' if ok else 'FAIL'}  {interp:<5} {fps:g} fps (expected {expected}), "
                f"{artifact['frame_count']} frames, {artifact['width']}x{artifact['height']}, "
                f"{artifact['size_bytes']} bytes"
            )

            # Editor format has `nodes`; an API prompt is a bare mapping of node ids.
            graph = comfy_png(settings, run_id)
            editor = isinstance(graph, dict) and "nodes" in graph
            if not editor:
                failures.append(f"{interp}: the saved PNG carries no editor graph")
            stamp = (graph or {}).get("extra", {}).get("h3lab", {}).get("run_id")
            print(
                f"      {interp:<5} png: {'editor' if editor else 'NOT editor'} graph, "
                f"{len((graph or {}).get('nodes') or [])} nodes, run_id {stamp}"
            )

            exported = client.get(f"/api/runs/{run_id}/workflow").json()
            names = sorted(
                node["type"]
                for node in exported["nodes"]
                if "Interpolat" in str(node.get("type")) or "RIFE" in str(node.get("type"))
            )
            print(f"      {interp:<5} export: {len(exported['nodes'])} nodes, interpolators {names}")

    print()
    for line in failures:
        print(f"FAILED: {line}")
    if not failures:
        print(f"all {len(EXPECTED_FPS)} generations agree with the graph they were built from")
    print(f"artifacts under {scratch}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
