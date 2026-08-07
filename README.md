# MiniMax H3 Benchmark

Interactive runner for the v3 turbo I2V workflow. Tweak config in the UI, click **Run**, compare results in a growing list / smart heatmap.

## Start

```bash
python benchmark_runner.py
```

Open http://127.0.0.1:8787/

Requires ComfyUI at http://127.0.0.1:8188 with MiniMax H3 models (nvfp4/int8/GGUF as needed).

## UI

- Feature toggles mirror workflow groups (GGUF vs Safetensor, Turbo, RIFE, Cache, Sol-Attn, Upscaler, Clean VRAM).
- Cache / Sol presets: conservative · moderate · aggressive.
- Scheduler/sampler lists load from Comfy when available.
- Each Run = **one** generation; results append to `results/benchmark.json` with wall time and **s/it** (seconds per sampler step, same unit as Comfy tqdm).

## Options

| Flag | Default | Purpose |
|------|---------|---------|
| `--comfy-url` | `http://127.0.0.1:8188` | ComfyUI base URL |
| `--port` | `8787` | Results UI port |
| `--ui-only` | off | Serve existing results only (no runner) |

## API

| Endpoint | Purpose |
|----------|---------|
| GET /api/results | Suite + runs |
| GET /api/options | Schedulers/samplers |
| POST /api/run | Start one config |
| POST /api/abort | Cancel |
| GET /api/health | Bench + Comfy |

## Dev

```bash
pip install -r requirements-dev.txt
pytest -v
```

## Notes

- Default seed is **42** (fixed mode).
- Suite schema v2 uses a flat `runs` list (legacy phase matrices are migrated on load).
- `bench/matrix.py` builders are **legacy** (used only by `run_all` / unit tests), not the interactive product path.

## Diffusion models

The Run panel lists basenames from `E:\AI\Models\diffusion_models` whose names contain both **MiniMax** and **H3** (case-insensitive). The loader (GGUF / NVFP4 UNET / INT OTUNet) is inferred from the filename. Add or remove files in that folder and refresh the UI — nothing is hard-coded beyond the folder path in `bench/constants.py` (`DIFFUSION_MODELS_DIR`).
