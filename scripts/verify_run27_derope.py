#!/usr/bin/env python3
"""Audit run 27 and compare its repaired primary and de-rope outputs."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from h3lab.comfy.client import OUTPUT_KEYS, VIDEO_SUFFIXES, ComfyClient
from h3lab.comfy.graph import load_workflow
from h3lab.comfy.schema import Schemas
from h3lab.comfy.studio import prepare_prompt
from h3lab.engine.artifacts import make_filmstrip, probe
from h3lab.settings import Settings
from h3lab.storage import open_store
from h3lab.storage.runs import RunRepository

ROOT = Path(__file__).resolve().parents[1]
STACK_WORKFLOW = (
    ROOT.parent
    / "comfyui-minimax-h3-stack"
    / "workflows"
    / "minimax_h3_unified_guided_dual.json"
)
BENCH_WORKFLOW = ROOT / "minimax_h3_unified_guided_dual.json"
INSTALLED_WORKFLOW = (
    Path("/home/kadobot/ComfyUI/user/default/workflows")
    / "minimax_h3_unified_guided_dual.json"
)
REGRESSION_RECORD = Path(__file__).with_name("run27_derope_regression.json")
VERIFY_DIR = ROOT / "results" / "verification" / "run27"


def run_by_seq(runs: RunRepository, seq: int):
    run = next((item for item in runs.all() if item.seq == seq), None)
    if run is None:
        raise RuntimeError(f"run {seq} is unavailable")
    return run


def history_prompt(history: dict) -> dict:
    payload = history.get("prompt")
    if not isinstance(payload, list) or len(payload) < 3 or not isinstance(payload[2], dict):
        raise RuntimeError("ComfyUI history has no executable prompt")
    return payload[2]


def one_node(prompt: dict, class_type: str) -> tuple[str, dict]:
    found = [
        (str(node_id), node)
        for node_id, node in prompt.items()
        if node.get("class_type") == class_type
    ]
    if len(found) != 1:
        raise RuntimeError(f"expected one {class_type}, found {len(found)}")
    return found[0]


def secondary_sampler(prompt: dict) -> tuple[str, dict, str, dict]:
    schedule_id, schedule = one_node(prompt, "H3InjectSchedule")
    found = [
        (str(node_id), node)
        for node_id, node in prompt.items()
        if node.get("class_type") == "SamplerCustomAdvanced"
        and node.get("inputs", {}).get("sigmas") == [schedule_id, 0]
    ]
    if len(found) != 1:
        raise RuntimeError(f"expected one de-rope sampler, found {len(found)}")
    sampler_id, sampler = found[0]
    return sampler_id, sampler, schedule_id, schedule


def ancestors(prompt: dict, start_id: str) -> set[str]:
    found: set[str] = set()
    pending = [str(start_id)]
    while pending:
        node_id = pending.pop()
        if node_id in found:
            continue
        found.add(node_id)
        node = prompt.get(node_id) or {}
        for value in (node.get("inputs") or {}).values():
            if isinstance(value, list) and len(value) == 2:
                pending.append(str(value[0]))
    return found


def audit_run27(settings: Settings, runs: RunRepository) -> None:
    run = run_by_seq(runs, 27)
    if not run.prompt_id:
        raise RuntimeError("run 27 has no ComfyUI prompt id")
    with ComfyClient(settings.comfy_url) as client:
        history = client.history(run.prompt_id)
    if history is None:
        history = json.loads(REGRESSION_RECORD.read_text(encoding="utf-8"))
        if history.get("source_prompt_id") != run.prompt_id:
            raise RuntimeError("run 27's persisted regression record has the wrong prompt id")
    prompt = history_prompt(history)
    studio_id, studio = one_node(prompt, "MiniMaxH3Studio")
    _sampler_id, sampler, _schedule_id, schedule = secondary_sampler(prompt)

    total_steps = schedule["inputs"].get("total_steps")
    inject = schedule["inputs"].get("inject")
    if studio["inputs"].get("steps") != 28 or total_steps != 6 or inject != 0.7:
        raise RuntimeError("run 27 no longer reproduces its 28 + 4 schedule")
    work_steps = max(1, round(total_steps * inject))
    if work_steps != 4:
        raise RuntimeError(f"run 27's final pass resolves to {work_steps}, not 4")

    guider = prompt[str(sampler["inputs"]["guider"][0])]
    if guider["inputs"].get("conditioning") != [studio_id, 14]:
        raise RuntimeError("run 27's final pass was not references-only as reported")

    output_id, output = one_node(prompt, "VHS_VideoCombine")
    image_source = output["inputs"].get("images")
    if not isinstance(image_source, list):
        raise TypeError("run 27's saved video has no linked image source")
    lineage = ancestors(prompt, str(image_source[0]))
    if not any(prompt[node_id].get("class_type") == "H3ExactRecover" for node_id in lineage):
        raise RuntimeError(f"run 27 output {output_id} did not select exact recovery")

    run25 = run_by_seq(runs, 25)
    first = settings.videos_dir / run25.artifact.video_path
    second = settings.videos_dir / run.artifact.video_path
    artifact_digest = hashlib.sha256(second.read_bytes()).digest()
    if hashlib.sha256(first.read_bytes()).digest() != artifact_digest:
        raise RuntimeError("same-config runs 25 and 27 were not byte-identical")
    recorded_digest = history.get("artifact_sha256")
    if recorded_digest is not None and artifact_digest.hex() != recorded_digest:
        raise RuntimeError("run 27's artifact no longer matches its regression record")
    print("RUN27_REGRESSION_REPRODUCED")


def check_workflows() -> None:
    workflows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (STACK_WORKFLOW, BENCH_WORKFLOW, INSTALLED_WORKFLOW)
    ]
    if workflows[1:] != workflows[:-1]:
        raise RuntimeError("canonical, benchmark, and installed workflows differ")
    print("DEROPE_WORKFLOWS_IN_SYNC")


def output_video(history: dict, node_id: str) -> tuple[str, str, str]:
    output = (history.get("outputs") or {}).get(node_id) or {}
    for key in OUTPUT_KEYS:
        for item in output.get(key) or []:
            filename = str(item.get("filename") or "")
            if filename.lower().endswith(VIDEO_SUFFIXES):
                return (
                    filename,
                    str(item.get("subfolder") or ""),
                    str(item.get("type") or "output"),
                )
    raise RuntimeError(f"output node {node_id} produced no video")


def assert_repaired_lineage(prompt: dict, expected_guides: int) -> tuple[str, str]:
    studio_id, studio = one_node(prompt, "MiniMaxH3Studio")
    sampler_id, sampler, _schedule_id, schedule = secondary_sampler(prompt)
    if schedule["inputs"].get("scheduler") != [studio_id, 8]:
        raise RuntimeError("de-rope scheduler is not Studio-driven")
    if schedule["inputs"].get("total_steps") != [studio_id, 6]:
        raise RuntimeError("de-rope total steps are not Studio-driven")
    if schedule["inputs"].get("inject") != 0.5:
        raise RuntimeError("de-rope injection is not the fidelity setting 0.50")

    noise = prompt[str(sampler["inputs"]["noise"][0])]
    if noise["inputs"].get("noise_seed") != [studio_id, 7]:
        raise RuntimeError("de-rope noise seed is not Studio-driven")
    sampler_switch = prompt[str(sampler["inputs"]["sampler"][0])]
    if sampler_switch.get("_meta", {}).get("title") != "DEROPE_ER_SDE_GATE":
        raise RuntimeError("de-rope does not use its Studio sampler gate")
    if sampler_switch["inputs"].get("switch") != [studio_id, 27]:
        raise RuntimeError("de-rope ER-SDE selection is not Studio-driven")

    er_sde = prompt[str(sampler_switch["inputs"]["on_true"][0])]
    expected_er_sde = {
        "solver_type": [studio_id, 28],
        "max_stage": [studio_id, 29],
        "eta": [studio_id, 30],
        "s_noise": [studio_id, 31],
    }
    if er_sde.get("inputs") != expected_er_sde:
        raise RuntimeError("de-rope ER-SDE parameters are not Studio-driven")

    guider = prompt[str(sampler["inputs"]["guider"][0])]
    anchor_id = str(guider["inputs"]["conditioning"][0])
    anchor = prompt[anchor_id]
    if anchor.get("class_type") != "MiniMaxH3AnchorGuides":
        raise RuntimeError("de-rope conditioning does not re-anchor guides")
    if anchor["inputs"].get("positive") != [studio_id, 14]:
        raise RuntimeError("de-rope guide anchor does not start from reference conditioning")
    if anchor["inputs"].get("guides") != [studio_id, 15]:
        raise RuntimeError("de-rope guide list is not Studio-driven")
    if len(json.loads(studio["inputs"]["guides"])) != expected_guides:
        raise RuntimeError("de-rope prompt did not retain every run 27 guide")

    smear_id, smear = one_node(prompt, "H3TimeSmear")
    if anchor["inputs"].get("length") != [smear_id, 2]:
        raise RuntimeError("de-rope guide anchor does not use stretched length")
    if anchor["inputs"].get("hold_map") != [smear_id, 1]:
        raise RuntimeError("de-rope guide anchor does not use the hold map")
    if anchor["inputs"].get("latent") != sampler["inputs"].get("latent_image"):
        raise RuntimeError("de-rope guides are not anchored to the combined AV init")
    anchor_latent = prompt[str(anchor["inputs"]["latent"][0])]
    if anchor_latent.get("class_type") != "H3V2VInit":
        raise RuntimeError("de-rope guide anchor did not receive a MiniMax AV latent")
    image_source = smear["inputs"].get("images")
    if not isinstance(image_source, list):
        raise TypeError("H3TimeSmear has no primary image source")
    return sampler_id, str(image_source[0])


def compare_live(settings: Settings, runs: RunRepository) -> None:
    run = run_by_seq(runs, 27)
    workflow = load_workflow(settings.workflow_path(run.config.mode))
    with ComfyClient(
        settings.comfy_url,
        run_timeout_s=settings.comfy_timeout_s,
    ) as client:
        schemas = Schemas.from_client(client)
        prepared = prepare_prompt(
            client,
            workflow,
            run.config,
            schemas=schemas,
            output_tag="run27-derope-verify",
        )
        prompt = prepared.prompt
        _sampler_id, primary_images_id = assert_repaired_lineage(
            prompt,
            expected_guides=7,
        )
        final_id, final_output = one_node(prompt, "VHS_VideoCombine")
        final_output["inputs"]["filename_prefix"] = "h3lab/run27-derope-verify-final"

        primary_id = "run27-derope-verify-primary"
        primary_output = copy.deepcopy(final_output)
        primary_output["inputs"]["images"] = [primary_images_id, 0]
        primary_output["inputs"]["filename_prefix"] = "h3lab/run27-derope-verify-primary"
        primary_output.setdefault("_meta", {})["title"] = "Run 27 primary verification"
        prompt[primary_id] = primary_output

        if not client.clear_execution_cache():
            raise RuntimeError("could not clear ComfyUI's execution cache")
        outcome = client.execute(prompt)
        outputs = {
            "primary": output_video(outcome.history, primary_id),
            "derope": output_video(outcome.history, final_id),
        }
        VERIFY_DIR.mkdir(parents=True, exist_ok=True)
        for name, (filename, subfolder, folder_type) in outputs.items():
            destination = VERIFY_DIR / f"{name}.mp4"
            client.download(filename, subfolder, folder_type, destination)
            details = probe(destination, ffprobe=settings.ffprobe)
            if (
                details.width,
                details.height,
                details.fps,
                details.frame_count,
            ) != (960, 544, 24.0, 124):
                raise RuntimeError(f"{name} output has unexpected shape: {details}")
            strip = make_filmstrip(
                destination,
                VERIFY_DIR / f"{name}-strip.jpg",
                ffmpeg=settings.ffmpeg,
                ffprobe=settings.ffprobe,
            )
            if strip is None:
                raise RuntimeError(f"could not render the {name} verification strip")

        print(
            json.dumps(
                {
                    "prompt_id": outcome.prompt_id,
                    "wall_s": round(outcome.wall_s, 3),
                    "configured_primary_steps": run.config.steps,
                    "partial_steps": round(run.config.effective_steps * 0.5),
                    "primary": str(VERIFY_DIR / "primary.mp4"),
                    "derope": str(VERIFY_DIR / "derope.mp4"),
                },
                sort_keys=True,
            )
        )
    print("RUN27_DEROPE_PARITY_OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--check-workflows", action="store_true")
    args = parser.parse_args()

    settings = Settings.from_env()
    runs = RunRepository(open_store(settings.db_path))
    if args.audit_only:
        audit_run27(settings, runs)
    elif args.check_workflows:
        check_workflows()
    else:
        check_workflows()
        compare_live(settings, runs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
