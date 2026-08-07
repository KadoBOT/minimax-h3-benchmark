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
    """Map a model filename to (model_path, quant) for the v3 loaders.

    ``quant`` here means *loader class*, not bit-width:

    - ``*.gguf`` → GGUF loader
    - convrot / mixed / w8a8 weights → OTUNetLoaderW8A8 (``quant=int8``)
    - INT4Q / nvfp4 / other packs → standard UNETLoader (``quant=nvfp4``)

    IMPORTANT: Music Suite loads ``*INT4Q*.safetensors`` via **UNETLoader**, not
    OTUNet. Routing INT4Q through OTUNet caused CUDA illegal memory access during
    model init (confirmed against a working Comfy API export).
    """
    n = filename.lower().replace("-", "_")
    if n.endswith(".gguf"):
        return "gguf", "nvfp4"
    # Pre-packed INT4Q (and similar) use the plain UNET loader.
    if "int4q" in n:
        return "safetensor", "nvfp4"
    # On-the-fly / convrot W8A8 style weights
    if any(tok in n for tok in ("convrot", "mixed", "w8a8")):
        return "safetensor", "int8"
    # Bare int8 (no nvfp4) still goes to OTUNet
    if "int8" in n and "nvfp4" not in n:
        return "safetensor", "int8"
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
    if quant == "int8":
        return INT8_UNET
    return NVFP4_UNET
