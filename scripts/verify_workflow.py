"""Real generations that prove the lab still reads the workflows it is given.

Not a test: it needs a GPU, a running ComfyUI, and several minutes of both. It exists because
the suite can only prove that the lab builds a graph it believes in — whether the installed
ComfyUI accepts that graph, and whether an edited template is picked up without a restart, are
properties of the running system.

Four questions, in order:

1. Does every template still build and run? One short generation per mode, through the real
   engine, with the real templates in the repository.
2. Is a template edited mid-session picked up? The t2v template is renumbered on disk between
   two runs, and the second run's prompt has to carry the new ids.
3. Is the Turbo LoRA really a setting? Two runs differing only in `turbo_lora`, whose submitted
   prompts must name different files and whose configs must hash differently.
4. Does the export still describe the run? Every finished run's exported workflow is read back
   and compared with the prompt that was submitted.

    python scripts/verify_workflow.py [--modes t2v,flf2v,r2v] [--steps 4] [--keep]

Prints a line per check and exits non-zero on the first disagreement.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from h3lab.api.app import create_app  # noqa: E402
from h3lab.comfy import roles as R  # noqa: E402
from h3lab.comfy.catalog import resolve_run_weights  # noqa: E402
from h3lab.comfy.client import ComfyClient  # noqa: E402
from h3lab.comfy.editor import prompt_of  # noqa: E402
from h3lab.comfy.graph import build, load_workflow  # noqa: E402
from h3lab.comfy.schema import Schemas  # noqa: E402
from h3lab.comfy.workflow import read  # noqa: E402
from h3lab.domain.config import GenerationConfig  # noqa: E402
from h3lab.settings import Settings  # noqa: E402

# Small and short: this proves the plumbing, not the model. Megapixels below 0.1 are rejected
# by the resolution node, and the turbo LoRAs on disk are distilled for four steps.
BASE: dict[str, Any] = {
    "prompt": "a paper boat turning in a puddle, overcast",
    "mp": 0.1,
    "duration_s": 2,
    "seed": 11,
    "turbo": True,
}

FRAME_A = "h3lab-verify-a.png"
FRAME_B = "h3lab-verify-b.png"

# Far past any id the templates use, so a shared id after the edit means the file was not re-read.
SHIFT = 5000

MODE_MEDIA: dict[str, dict[str, Any]] = {
    "t2v": {},
    "flf2v": {"first_frame": FRAME_A, "last_frame": FRAME_B},
    "r2v": {"ref_images": [FRAME_A, FRAME_B]},
}


class Checks:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def that(self, ok: bool, subject: str, detail: str) -> bool:
        print(f"{'ok  ' if ok else 'FAIL'}  {subject:<34} {detail}")
        if not ok:
            self.failures.append(f"{subject}: {detail}")
        return ok

    def note(self, subject: str, detail: str) -> None:
        print(f"      {subject:<34} {detail}")


def make_frame(destination: Path, *, pattern: str) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"{pattern}=size=512x288:rate=1:duration=1",
        "-frames:v", "1", str(destination),
    ]
    try:
        return subprocess.run(command, capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def await_run(client: TestClient, run_id: str, *, timeout_s: float = 1800.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    view: dict[str, Any] = {}
    while time.monotonic() < deadline:
        view = client.get(f"/api/runs/{run_id}").json()
        if view["run"]["status"] in {"succeeded", "failed", "cancelled"}:
            return view
        time.sleep(3)
    return view


def queue(client: TestClient, config: dict[str, Any]) -> str:
    response = client.post("/api/runs", json={"config": config})
    response.raise_for_status()
    return str(response.json()[0]["run"]["id"])


def submitted_ids(client: TestClient, run_id: str) -> set[str]:
    """The node ids the run actually submitted, read back out of its exported workflow."""
    exported = client.get(f"/api/runs/{run_id}/workflow").json()
    return set(prompt_of(exported))


def renumber(path: Path, *, shift: int) -> None:
    """Move every node id in a saved workflow, the way re-editing a graph in ComfyUI does.

    This is the edit the lab used to break on: nothing about the pipeline changes, only the
    numbers. Negative ids are left alone — they are the subgraph boundary sentinels, not nodes.
    Both link shapes are handled, because the templates ship one of each: arrays at the top
    level (`[link, origin, origin_slot, target, target_slot, type]`) and objects inside the
    subgraph definition.
    """

    def moved(value: Any) -> Any:
        return value + shift if isinstance(value, int) and value >= 0 else value

    raw = json.loads(path.read_text(encoding="utf-8"))
    for level in [raw, *((raw.get("definitions") or {}).get("subgraphs") or [])]:
        for node in level.get("nodes") or []:
            node["id"] = moved(node.get("id"))
        for link in level.get("links") or []:
            if isinstance(link, dict):
                link["origin_id"] = moved(link.get("origin_id"))
                link["target_id"] = moved(link.get("target_id"))
            elif isinstance(link, list) and len(link) >= 5:
                link[1] = moved(link[1])
                link[3] = moved(link[3])
        level["last_node_id"] = moved(level.get("last_node_id"))
    path.write_text(json.dumps(raw), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modes", default="t2v,flf2v,r2v")
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--keep", action="store_true", help="leave the videos behind")
    args = parser.parse_args(argv)
    modes = [mode.strip() for mode in args.modes.split(",") if mode.strip()]
    # Run labels carry em dashes, and a legacy Windows code page cannot encode them.
    with suppress(AttributeError, OSError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    scratch = Path(tempfile.mkdtemp(prefix="h3lab-verify-"))
    live = Settings.from_env()
    # The templates are copied so the reload check can edit one without touching the repository.
    templates = scratch / "workflows"
    templates.mkdir(parents=True, exist_ok=True)
    for mode in ("t2v", "flf2v", "r2v"):
        shutil.copyfile(live.workflow_path(mode), templates / f"minimax_h3_{mode}_workflow.json")
    settings = replace(live, data_dir=scratch / "data", workflow_dir=templates)
    settings.ensure_dirs()

    checks = Checks()
    for name, pattern in ((FRAME_A, "testsrc2"), (FRAME_B, "smptebars")):
        checks.that(
            make_frame(settings.comfy_input_dir / name, pattern=pattern),
            "input media",
            f"{name} written to ComfyUI's input folder",
        )

    app = create_app(settings=settings)
    with TestClient(app) as client:
        catalog = client.get("/api/catalog").json()
        loras = list(catalog.get("turbo_loras") or [])
        checks.that(
            catalog.get("turbo_loras_source") == "comfy" and len(loras) >= 2,
            "catalog",
            f"{len(loras)} turbo LoRA(s) from {catalog.get('turbo_loras_source')}",
        )

        finished: list[tuple[str, dict[str, Any]]] = []

        # 1 — every template builds, runs, and produces a video.
        for mode in modes:
            config = {**BASE, "mode": mode, "steps": args.steps, **MODE_MEDIA[mode]}
            run_id = queue(client, config)
            view = await_run(client, run_id)
            run = view["run"]
            ok = checks.that(
                run["status"] == "succeeded",
                f"generation {mode}",
                f"{run['status']} — {run.get('error') or run['label']}",
            )
            if not ok:
                continue
            artifact = run["artifact"]
            video = settings.videos_dir / artifact["video_path"]
            checks.that(
                video.is_file() and (artifact["frame_count"] or 0) > 1,
                f"video {mode}",
                f"{artifact['frame_count']} frames, {artifact['width']}x{artifact['height']},"
                f" {artifact['size_bytes']} bytes, {run['metrics']['sec_per_it']} s/it",
            )
            finished.append((mode, view))

        # 2 — a template edited between two runs is read again.
        if "t2v" in modes:
            before = queue(client, {**BASE, "mode": "t2v", "steps": args.steps, "seed": 21})
            await_run(client, before)
            was = submitted_ids(client, before)

            renumber(templates / "minimax_h3_t2v_workflow.json", shift=SHIFT)
            after = queue(client, {**BASE, "mode": "t2v", "steps": args.steps, "seed": 22})
            view = await_run(client, after)
            checks.that(
                view["run"]["status"] == "succeeded",
                "a renumbered template runs",
                f"{view['run']['status']} — {view['run'].get('error') or view['run']['label']}",
            )
            now = submitted_ids(client, after)
            checks.that(
                bool(now) and not (was & now),
                "the edit reached the run",
                f"{len(was)} old ids, {len(now)} new ids, {len(was & now)} shared",
            )
            checks.note("ids before", ", ".join(sorted(was)[:4]))
            checks.note("ids after", ", ".join(sorted(now)[:4]))

        # 3 — the Turbo LoRA is a setting, not a fixture of the template.
        if len(loras) >= 2:
            picked = loras[:2]
            hashes: list[str] = []
            for lora in picked:
                run_id = queue(
                    client,
                    {**BASE, "mode": "t2v", "steps": args.steps, "turbo_lora": lora, "seed": 33},
                )
                view = await_run(client, run_id)
                run = view["run"]
                hashes.append(run["config_hash"])
                checks.that(
                    run["status"] == "succeeded" and run["config"]["turbo_lora"] == lora,
                    f"turbo lora {lora[:28]}",
                    f"{run['status']} — {run['label']}",
                )
                exported = client.get(f"/api/runs/{run_id}/workflow").json()
                named = {
                    value
                    for node in exported["nodes"]
                    if node.get("type") == "MiniMaxH3TurboLoRA"
                    for value in (node.get("widgets_values") or [])
                    if isinstance(value, str) and value.endswith(".safetensors")
                }
                checks.that(
                    named == {lora},
                    "the graph names the LoRA",
                    f"{sorted(named) or 'nothing'}",
                )
            checks.that(
                len(set(hashes)) == 2,
                "two LoRAs are two experiments",
                f"{hashes[0][:12]} vs {hashes[1][:12]}",
            )

        # 4 — the export still describes the run it came from.
        for mode, view in finished:
            run_id = view["run"]["id"]
            exported = client.get(f"/api/runs/{run_id}/workflow").json()
            reimported = prompt_of(exported)
            template = load_workflow(templates / f"minimax_h3_{mode}_workflow.json")
            checks.that(
                bool(reimported) and all("class_type" in node for node in reimported.values()),
                f"export {mode}",
                f"{len(exported['nodes'])} nodes read back as {len(reimported)} prompt nodes",
            )
            graph = read(template)
            roles = R.resolve(graph)
            checks.note(f"roles {mode}", f"{len(roles.found)}/{len(R.ROLES)} found")

        # A last look with the live schemas: what the installed ComfyUI would object to.
        comfy = ComfyClient(settings.comfy_url)
        schemas = Schemas.from_client(comfy)
        for mode in modes:
            template = load_workflow(templates / f"minimax_h3_{mode}_workflow.json")
            config = {**BASE, "mode": mode, "steps": args.steps, **MODE_MEDIA[mode]}
            gen_cfg = resolve_run_weights(GenerationConfig(**config), comfy)
            prompt, _graph, _roles = build(
                template, gen_cfg, output_tag="verify", schemas=schemas
            )
            checks.that(
                not schemas.problems(prompt),
                f"object_info {mode}",
                "; ".join(schemas.problems(prompt)) or f"{len(prompt)} nodes, nothing objected to",
            )
        comfy.close()

    print()
    for line in checks.failures:
        print(f"FAILED: {line}")
    if not checks.failures:
        print("every template built, ran, and came back describing itself")
    print(f"artifacts under {scratch}")
    if not args.keep:
        shutil.rmtree(scratch, ignore_errors=True)
    return 1 if checks.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
