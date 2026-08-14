"""Turning a downloaded video into something a list of runs can display.

A grid of autoplaying videos is unusable, so every finished run gets a poster frame and a
filmstrip. Both are optional: when ffmpeg is missing the run still counts, it just shows a
placeholder. That is deliberate — a benchmark result must never be lost to a thumbnail.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from h3lab.domain.run import Artifact
from h3lab.settings import Settings

POSTER_WIDTH = 640
STRIP_TILES = 6
STRIP_TILE_WIDTH = 240
PROBE_TIMEOUT_S = 30.0
RENDER_TIMEOUT_S = 120.0


@dataclass(frozen=True, slots=True)
class Probe:
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    frame_count: int | None = None
    duration_s: float | None = None


def _run(command: list[str], timeout: float) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None


def tool_available(name: str) -> bool:
    return shutil.which(name) is not None


def _parse_rate(value: str | None) -> float | None:
    """ffprobe reports frame rates as fractions like ``24000/1001``."""
    if not value:
        return None
    text = value.strip()
    try:
        if "/" in text:
            numerator, denominator = text.split("/", 1)
            denom = float(denominator)
            return float(numerator) / denom if denom else None
        return float(text)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def probe(video: Path, *, ffprobe: str = "ffprobe") -> Probe:
    result = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,avg_frame_rate,nb_frames,duration",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(video),
        ],
        PROBE_TIMEOUT_S,
    )
    if result is None or result.returncode != 0:
        return Probe()
    try:
        payload = json.loads(result.stdout.decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError:
        return Probe()

    streams = payload.get("streams") or []
    stream = streams[0] if streams else {}
    fps = _parse_rate(stream.get("avg_frame_rate"))
    duration = _parse_rate(stream.get("duration")) or _parse_rate(
        (payload.get("format") or {}).get("duration")
    )
    frames = stream.get("nb_frames")
    try:
        frame_count = int(frames) if frames not in (None, "N/A") else None
    except (TypeError, ValueError):
        frame_count = None
    if frame_count is None and fps and duration:
        frame_count = max(1, round(fps * duration))

    return Probe(
        width=stream.get("width") if isinstance(stream.get("width"), int) else None,
        height=stream.get("height") if isinstance(stream.get("height"), int) else None,
        fps=round(fps, 3) if fps else None,
        frame_count=frame_count,
        duration_s=round(duration, 3) if duration else None,
    )


def make_poster(
    video: Path, destination: Path, *, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe"
) -> Path | None:
    """A single frame from a third of the way in — past any fade-up, before the payoff."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    seek = 0.0
    details = probe(video, ffprobe=ffprobe)
    if details.duration_s:
        seek = max(0.0, details.duration_s / 3.0)
    result = _run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-ss",
            f"{seek:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            f"scale={POSTER_WIDTH}:-2:flags=bicubic",
            "-q:v",
            "3",
            str(destination),
        ],
        RENDER_TIMEOUT_S,
    )
    if result is None or result.returncode != 0 or not destination.is_file():
        return None
    return destination


def make_filmstrip(
    video: Path,
    destination: Path,
    *,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    tiles: int = STRIP_TILES,
) -> Path | None:
    """Evenly spaced frames in one row, so motion is judgeable without pressing play."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    details = probe(video, ffprobe=ffprobe)
    frames = details.frame_count or 0
    # Picking every Nth frame keeps the tiles evenly spread whatever the clip length is.
    every = max(1, frames // tiles) if frames else 12
    result = _run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-vf",
            (
                f"select='not(mod(n\\,{every}))',"
                f"scale={STRIP_TILE_WIDTH}:-2:flags=bicubic,"
                f"tile={tiles}x1"
            ),
            "-frames:v",
            "1",
            "-q:v",
            "4",
            str(destination),
        ],
        RENDER_TIMEOUT_S,
    )
    if result is None or result.returncode != 0 or not destination.is_file():
        return None
    return destination


def build(run_id: str, video: Path, settings: Settings) -> Artifact:
    """Describe a downloaded video, rendering previews when the tools allow it."""
    settings.ensure_dirs()
    details = probe(video, ffprobe=settings.ffprobe)

    poster = make_poster(
        video,
        settings.posters_dir / f"{run_id}.jpg",
        ffmpeg=settings.ffmpeg,
        ffprobe=settings.ffprobe,
    )
    strip = make_filmstrip(
        video,
        settings.strips_dir / f"{run_id}.jpg",
        ffmpeg=settings.ffmpeg,
        ffprobe=settings.ffprobe,
    )

    try:
        size = video.stat().st_size
    except OSError:
        size = None

    return Artifact(
        video_path=video.name,
        poster_path=poster.name if poster else None,
        strip_path=strip.name if strip else None,
        width=details.width,
        height=details.height,
        fps=details.fps,
        frame_count=details.frame_count,
        size_bytes=size,
    )
