# MiniMax H3 model catalog correction

## Problem

h3bench can retain `minimax_h3_fl2va_pruned_nvfp4.safetensors` even when that
file is not installed. The live catalog currently reports the seven real
`minimax-h3/` models correctly, but an earlier offline load can create and
persist the phantom value.

Two behaviors combine to cause this:

1. the disk fallback scans only the top level of `models/diffusion_models`, so
   it misses files in `models/diffusion_models/minimax-h3` and substitutes
   hard-coded fallback names; and
2. the browser's persisted draft overrides later catalog defaults without
   checking that the selected model is still installed.

## Catalog ownership

For a local ComfyUI installation, the authoritative model set is every
supported model file directly under:

```text
models/diffusion_models/minimax-h3
```

Catalog values retain the ComfyUI combo prefix, for example:

```text
minimax-h3/MiniMax_H3_FL2VA_pruned_int8_convrot.safetensors
```

The directory name establishes the model family, so files in it do not also
need `minimax` and `h3` in their filename. Files elsewhere under
`diffusion_models` are not offered.

If the local folder does not exist or is empty, h3bench may use the running
ComfyUI server's loadable values, restricted to the `minimax-h3/` folder. This
preserves remote-ComfyUI support.

If neither source has a model, the catalog returns an empty list and empty
default. It never invents a checkpoint filename.

## Default and persisted draft

The selected default is the existing preferred file when it is installed,
otherwise an installed NVFP4 safetensors file, otherwise the first installed
safetensors file, otherwise the first installed model.

After the catalog loads, a persisted `diffusion_model` is normalized:

- an exact installed combo value is retained;
- a unique case-insensitive basename match is rewritten to its installed combo
  value;
- a missing or ambiguous value is replaced by the catalog default.

All other persisted draft fields remain unchanged. The corrected draft is
written back through the existing local-storage effect.

## Benchmark axis

The existing `diffusion_model` sweep axis consumes
`Catalog.diffusion_models`. It therefore offers exactly the same installed
MiniMax H3 files as the ordinary Weights picker. It remains compatible with
the Template axis because templates do not manage model selection.

## Failure behavior

With no model available, the ordinary run and sweep actions are blocked with a
missing `Weights` message. A blank model must not fall through to the historical
`DEFAULT_UNET` during a new run.

Stored historical runs retain their recorded filename. At execution,
`match_installed` may still map an old basename to a unique installed combo
value, but a genuinely missing explicit model fails clearly rather than
silently selecting another quantization.

## Verification

Tests must prove:

1. disk discovery returns only files from the `minimax-h3` folder with combo
   prefixes;
2. a local folder wins over unrelated or stale live entries;
3. remote live entries are used only when the local folder is unavailable;
4. an empty installation returns no fabricated NVFP4 or GGUF values;
5. stale local-storage values normalize to the current catalog default;
6. basename values normalize to their unique installed combo value;
7. the Weights picker and diffusion-model sweep axis expose the same list; and
8. the live h3bench instance reports and selects all seven currently installed
   models.
