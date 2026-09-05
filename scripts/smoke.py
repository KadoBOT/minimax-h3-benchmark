"""Drive the built front end in a real browser against a real server.

Unit tests render components against a fake API. This does neither: it seeds a throwaway
database with runs that have real videos, serves `web/dist` from the real app on a real
socket, and hands the URL to Chromium. What it proves is the part no jsdom test can — that
the built bundle boots, the router resolves, the API answers the fetches the pages make,
and nothing lands in the console.

    python scripts/smoke.py [--headed] [--keep]
"""

from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from h3lab.api.app import create_app  # noqa: E402
from h3lab.domain.config import GenerationConfig  # noqa: E402
from h3lab.domain.run import RunMetrics  # noqa: E402
from h3lab.engine import artifacts  # noqa: E402
from h3lab.engine.lab import Lab  # noqa: E402
from h3lab.settings import DEFAULT_COMFY_URL, Settings  # noqa: E402

SMOKE_DIR = REPO_ROOT / ".smoke"
PROMPT_A = "a courier on a magnetic skateboard, neon alley, heavy rain"
PROMPT_B = "a lighthouse keeper walking a cliff path at dawn"

# (cache, sol_attn, steps, sampler, seed, wall_s, sec_per_it, stars)
PLAN: tuple[tuple[str, bool, int, str, int, float, float, int], ...] = (
    ("spectrum", True, 20, "euler", 42, 172.0, 8.4, 8),
    ("spectrum", True, 20, "euler", 77, 168.0, 8.2, 7),
    ("none", True, 20, "euler", 42, 244.0, 12.1, 9),
    ("none", True, 20, "euler", 77, 249.0, 12.4, 8),
    ("easy", True, 20, "euler", 42, 151.0, 7.3, 5),
    ("easy", True, 20, "euler", 77, 149.0, 7.1, 4),
    ("h3", True, 20, "euler", 42, 138.0, 6.6, 6),
    ("spectrum", False, 20, "euler", 42, 205.0, 10.1, 8),
    ("spectrum", False, 20, "euler", 77, 210.0, 10.4, 7),
    ("spectrum", True, 30, "euler", 42, 256.0, 8.4, 9),
    ("spectrum", True, 12, "euler", 42, 104.0, 8.5, 4),
    ("spectrum", True, 20, "dpmpp_2m", 42, 176.0, 8.6, 6),
    ("spectrum", True, 20, "dpmpp_2m", 77, 174.0, 8.5, 7),
    ("h3", True, 20, "euler", 77, 141.0, 6.8, 5),
)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def synth_clip(destination: Path, *, pattern: str, seconds: float = 2.0) -> bool:
    """A real, tiny, decodable clip, so posters and filmstrips are real images."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"{pattern}=size=320x180:rate=12:duration={seconds}",
        "-pix_fmt", "yuv420p", str(destination),
    ]
    try:
        return subprocess.run(command, capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


SMOKE_FRAME = "smoke-frame.png"

# Two distilled LoRAs with different schedules in their names, so the picker has a real choice
# and the step count the form quotes has to follow the pick rather than a constant.
SMOKE_LORAS = (
    "minimax_h3_turbo_4step_comfyui_pruned.safetensors",
    "minimax_h3_fl2v_lightx2v_turbo_8step_v0.1_comfy.safetensors",
)


def seed_loras(settings: Settings) -> list[str]:
    """Files in the LoRA folder, so the catalog's disk path answers with more than one name.

    ComfyUI is not running here, so the list cannot come from the turbo node. Writing real
    files exercises the fallback the browser will actually be served.
    """
    folder = settings.lora_models_dir
    folder.mkdir(parents=True, exist_ok=True)
    for name in SMOKE_LORAS:
        (folder / name).write_bytes(b"")
    return list(SMOKE_LORAS)


def seed_input_media(settings: Settings) -> bool:
    """One real image in ComfyUI's input folder, so a frame mode has something to pre-fill.

    Deliberately not the baseline frame: the fallback path is the one every machine but this
    one takes, and it is the path that has to keep working.
    """
    destination = settings.comfy_input_dir / SMOKE_FRAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=1:duration=1",
        "-frames:v", "1", str(destination),
    ]
    try:
        return subprocess.run(command, capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def seed(lab: Lab, settings: Settings) -> int:
    """Runs the pages can actually render: varied axes, matched seeds, real media."""
    seed_input_media(settings)
    seed_loras(settings)
    sources: list[Path] = []
    for index, pattern in enumerate(("testsrc2", "smptebars")):
        clip = settings.data_dir / f"_source{index}.mp4"
        if synth_clip(clip, pattern=pattern):
            sources.append(clip)

    made = []
    for index, (cache, sol, steps, sampler, seed_value, wall, rate, stars) in enumerate(PLAN):
        config = GenerationConfig(
            mode="t2v",
            diffusion_model="minimax_h3_fl2va_pruned_int8_convrot.safetensors",
            prompt=PROMPT_A if index % 3 else PROMPT_B,
            cache=cache,
            sol_attn=sol,
            steps=steps,
            sampler=sampler,
            seed=seed_value,
        )
        run = lab.runs.create(config)
        lab.runs.update_metrics(
            run.id,
            RunMetrics(wall_s=wall, sec_per_it=rate, steps=steps, cache_cleared=True),
        )
        if sources:
            video = settings.videos_dir / f"{run.id}.mp4"
            shutil.copyfile(sources[index % len(sources)], video)
            lab.runs.attach_artifact(run.id, artifacts.build(run.id, video, settings))
        lab.runs.mark_succeeded(run.id)
        # Criteria run 1-5 while stars run 1-10, so halve and keep it in range.
        graded = min(5, max(1, round(stars / 2)))
        lab.rate(
            run.id,
            stars,
            {"motion": graded, "detail": graded, "consistency": max(1, graded - 1)},
        )
        if index % 4 == 0:
            lab.patch(run.id, favourite=True)
        lab.runs.set_tags(run.id, ["keeper"] if stars >= 8 else ["baseline"])
        made.append(run.id)

    # One interpolated run, so the pages have an `interp` other than off to render and the
    # workflow download has a graph with an interpolator in it. Deliberately alone in its pool:
    # interpolation is a held setting, and a second one would offer the arena a matchup whose
    # sides differ in nothing the standings can rank.
    interpolated = lab.runs.create(
        GenerationConfig(mode="t2v", prompt=PROMPT_A, seed=4242, interp="film")
    )
    lab.runs.update_metrics(
        interpolated.id, RunMetrics(wall_s=196.0, sec_per_it=9.1, steps=20, cache_cleared=True)
    )
    if sources:
        video = settings.videos_dir / f"{interpolated.id}.mp4"
        shutil.copyfile(sources[0], video)
        lab.runs.attach_artifact(
            interpolated.id, artifacts.build(interpolated.id, video, settings)
        )
    lab.runs.mark_succeeded(interpolated.id)
    lab.rate(interpolated.id, 7, {"motion": 4, "detail": 3, "consistency": 3})

    # A turbo pair that differs in nothing but which LoRA sampled it — the matchup the axis
    # exists for. Each samples at the schedule its own filename declares, so the pages have to
    # show two different step counts for two runs whose `steps` field is identical.
    for index, (lora, stars) in enumerate(zip(SMOKE_LORAS, (8, 6))):
        run = lab.runs.create(
            GenerationConfig(
                mode="t2v", prompt=PROMPT_A, seed=808, turbo=True, turbo_lora=lora
            )
        )
        lab.runs.update_metrics(
            run.id,
            RunMetrics(
                wall_s=34.0 + index * 21.0,
                sec_per_it=8.4 + index * 0.2,
                steps=run.config.effective_steps,
                cache_cleared=True,
            ),
        )
        if sources:
            video = settings.videos_dir / f"{run.id}.mp4"
            shutil.copyfile(sources[index % len(sources)], video)
            lab.runs.attach_artifact(run.id, artifacts.build(run.id, video, settings))
        lab.runs.mark_succeeded(run.id)
        lab.rate(run.id, stars, {"motion": 4, "detail": 3, "consistency": 3})

    # One failure and one queued run, so those states are on screen too.
    stuck = lab.runs.create(GenerationConfig(mode="t2v", prompt=PROMPT_B, seed=999))
    lab.runs.mark_failed(stuck.id, "ComfyUI returned no video for prompt 4c1f")
    lab.enqueue(GenerationConfig(mode="t2v", prompt=PROMPT_A, seed=1234))

    for left, right in zip(made, made[1:]):
        lab.vote(left, right, left if made.index(left) % 2 == 0 else right)
    lab.set_baseline(made[0])
    for source in sources:
        source.unlink(missing_ok=True)
    return len(made) + 5


def serve(lab: Lab, settings: Settings, port: int) -> "object":
    import uvicorn

    config = uvicorn.Config(
        create_app(lab=lab, settings=settings),
        host="127.0.0.1",
        port=port,
        log_level="warning",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, name="smoke-uvicorn", daemon=True).start()
    deadline = time.monotonic() + 30.0
    while not server.started:
        if time.monotonic() > deadline:
            raise TimeoutError("the smoke server never came up")
        time.sleep(0.02)
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headed", action="store_true", help="watch it happen")
    parser.add_argument("--keep", action="store_true", help="leave the seeded data behind")
    parser.add_argument(
        "--comfy-url",
        default=DEFAULT_COMFY_URL,
        help="ComfyUI instance providing the read-only Studio v1 contract",
    )
    args = parser.parse_args(argv)

    dist = REPO_ROOT / "web" / "dist" / "index.html"
    if not dist.is_file():
        print("build the front end first: cd web && npm run build", file=sys.stderr)
        return 2

    if SMOKE_DIR.exists():
        shutil.rmtree(SMOKE_DIR, ignore_errors=True)
    settings = Settings(
        data_dir=SMOKE_DIR / "data",
        comfy_input_dir=SMOKE_DIR / "input",
        # Its own folder, not the install's: this seeds files, and the real LoRA folder is
        # not somewhere a smoke test gets to write.
        loras_dir=SMOKE_DIR / "loras",
        comfy_url=args.comfy_url,
        web_dist=REPO_ROOT / "web" / "dist",
    )
    settings.ensure_dirs()
    settings.comfy_input_dir.mkdir(parents=True, exist_ok=True)

    lab = Lab(settings=settings, start_worker=False)
    try:
        count = seed(lab, settings)
        port = free_port()
        server = serve(lab, settings, port)
        url = f"http://127.0.0.1:{port}"
        print(f"seeded {count} runs, serving {url}")

        # The driver lives under web/ so `playwright` resolves from web/node_modules.
        driver = [
            "node",
            str(REPO_ROOT / "web" / "scripts" / "smoke.mjs"),
            url,
            *(["--headed"] if args.headed else []),
        ]
        result = subprocess.run(driver, cwd=REPO_ROOT / "web")
        server.should_exit = True
        return result.returncode
    finally:
        lab.close()
        if not args.keep:
            shutil.rmtree(SMOKE_DIR, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
