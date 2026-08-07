"""Discover MiniMax H3 diffusion models from the ComfyUI models folder."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from bench.constants import (
    DIFFUSION_MODELS_DIR,
    GGUF_UNET,
    INT8_UNET,
    NVFP4_UNET,
)

ModelPath = Literal["gguf", "safetensor"]
QuantName = Literal["nvfp4", "int8"]

_MODEL_EXTS = {".safetensors", ".gguf", ".sft", ".ckpt", ".pt", ".pth"}
_NAME_RE = re.compile(r"minimax", re.I)
_H3_RE = re.compile(r"h3", re.I)


def is_minimax_h3_model(name: str) -> bool:
    """True if *name* contains both 'minimax' and 'h3' (case-insensitive)."""
    return bool(_NAME_RE.search(name) and _H3_RE.search(name))


def list_diffusion_models(directory: Path | str | None = None) -> list[str]:
    """Return sorted basenames under *directory* matching MiniMax + H3.

    Missing directory → empty list (callers fall back to defaults).
    """
    root = Path(directory) if directory is not None else DIFFUSION_MODELS_DIR
    if not root.is_dir():
        return []
    names: list[str] = []
    for p in root.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in _MODEL_EXTS:
            continue
        if not is_minimax_h3_model(p.name):
            continue
        names.append(p.name)
    return sorted(names, key=str.lower)


def infer_loader(filename: str) -> tuple[ModelPath, QuantName]:
    """Map a model filename to (model_path, quant).

    - ``*.gguf`` → GGUF loader
    - **all** ``*.safetensors`` (and other non-GGUF) → UNETLoader (``quant=nvfp4``)

    OTUNet / int8 loader path is no longer used; every diffusion safetensor is
    loaded on the same UNETLoader node as NVFP4.
    """
    n = filename.lower().replace("-", "_")
    if n.endswith(".gguf"):
        return "gguf", "nvfp4"
    return "safetensor", "nvfp4"


def default_diffusion_model(names: list[str] | None = None) -> str:
    """Pick a sensible default filename from *names* or constants fallbacks."""
    pool = list(names) if names is not None else list_diffusion_models()
    if NVFP4_UNET in pool:
        return NVFP4_UNET
    for preferred in (NVFP4_UNET, INT8_UNET, GGUF_UNET):
        if preferred in pool:
            return preferred
    # Prefer non-gguf safetensors first
    for n in pool:
        if n.lower().endswith(".safetensors") and "nvfp4" in n.lower():
            return n
    for n in pool:
        if n.lower().endswith(".safetensors"):
            return n
    if pool:
        return pool[0]
    return NVFP4_UNET


def resolve_model_filename(
    diffusion_model: str | None,
    model_path: ModelPath,
    quant: QuantName,
) -> str:
    """Concrete loader filename for apply_config."""
    if diffusion_model and diffusion_model.strip():
        return diffusion_model.strip()
    if model_path == "gguf":
        return GGUF_UNET
    # quant is ignored for filename fallback (always UNET path defaults)
    del quant
    return NVFP4_UNET
