"""Serving generated media and accepting input media.

Videos and posters live outside the web root, so every name is resolved and then confined to
its own folder before anything is opened. A name that escapes is refused, not served.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict

from h3lab.api.deps import LabDep, SettingsDep
from h3lab.api.errors import problem
from h3lab.settings import REPO_ROOT

router = APIRouter(tags=["media"])


class Upload(BaseModel):
    """Where the file landed. `name` is what a config field should be set to."""

    model_config = ConfigDict(frozen=True)

    name: str
    bytes: int
    kind: str


UPLOAD_KINDS: dict[str, str] = {
    **{suffix: "image" for suffix in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")},
    **{suffix: "video" for suffix in (".mp4", ".webm", ".mkv", ".mov")},
    **{suffix: "audio" for suffix in (".wav", ".mp3", ".flac", ".ogg", ".m4a")},
}
UPLOAD_SUFFIXES: frozenset[str] = frozenset(UPLOAD_KINDS)
MAX_UPLOAD_BYTES = 512 * 1024 * 1024
# Artifact names embed the run id, so a name never points at different bytes later.
CACHE_FOREVER = "public, max-age=31536000, immutable"
# An input name is only ever "whatever is in the folder under that name", and the next upload
# can replace it, so this one is revalidated instead of trusted.
CACHE_BRIEFLY = "public, max-age=30"


def serve(directory: Path, name: str, *, cache: str = CACHE_FOREVER) -> Response:
    root = directory.resolve()
    candidate = (root / name).resolve()
    if candidate == root or root not in candidate.parents:
        return problem(400, "invalid", "that path is not allowed", name)
    if not candidate.is_file():
        return problem(404, "not_found", f"{name} is not here", str(candidate))
    media_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    return FileResponse(candidate, media_type=media_type, headers={"Cache-Control": cache})


@router.get("/media/videos/{name:path}", response_class=FileResponse)
def video(settings: SettingsDep, name: str) -> Response:
    return serve(settings.videos_dir, name)


@router.get("/media/posters/{name:path}", response_class=FileResponse)
def poster(settings: SettingsDep, name: str) -> Response:
    return serve(settings.posters_dir, name)


@router.get("/media/strips/{name:path}", response_class=FileResponse)
def strip(settings: SettingsDep, name: str) -> Response:
    return serve(settings.strips_dir, name)


@router.get("/media/inputs/{name:path}", response_class=FileResponse)
def input_media(settings: SettingsDep, name: str) -> Response:
    """A file already in ComfyUI's input folder, so the form can show what was picked."""
    target = settings.comfy_input_dir / name
    if not target.is_file():
        fallback = REPO_ROOT / "inputs" / name
        if fallback.is_file():
            return serve(REPO_ROOT / "inputs", name, cache=CACHE_BRIEFLY)
    return serve(settings.comfy_input_dir, name, cache=CACHE_BRIEFLY)


@router.post("/uploads", status_code=201, response_model=Upload)
async def upload(
    lab: LabDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
) -> Any:
    """Put a reference image, video, or audio file where ComfyUI will find it."""
    name = Path(file.filename or "upload").name
    suffix = Path(name).suffix.lower()
    if suffix not in UPLOAD_SUFFIXES:
        return problem(
            415,
            "invalid",
            f"{suffix or 'that file type'} is not accepted",
            "Upload an image, a video, or an audio file.",
        )
    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        return problem(
            413,
            "invalid",
            "that file is too large",
            f"{len(payload) / 1e6:.0f} MB exceeds the {MAX_UPLOAD_BYTES / 1e6:.0f} MB limit",
        )

    destination = settings.comfy_input_dir / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    lab.catalog_cache.invalidate()
    return Upload(name=name, bytes=len(payload), kind=UPLOAD_KINDS[suffix])
