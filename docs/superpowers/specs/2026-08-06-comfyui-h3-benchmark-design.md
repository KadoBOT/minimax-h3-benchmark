# MiniMax H3 ComfyUI Benchmark Suite — Design

**Date:** 2026-08-06  
**Status:** Approved (conversation)  
**Workflow:** `minimax-h3_test.i2v.v2.workflow.json`  
**ComfyUI:** `http://127.0.0.1:8188` (local, already running)

## Goal

Build a **benchmark runner + progressive web UI** that:

1. Runs timed image-to-video generations against the MiniMax H3 workflow with controlled config changes.
2. Measures **wall-clock generation time** for the **same fixed seed** under different speed-relevant settings.
3. Saves each finished run’s video and metadata **immediately** so the UI shows results as soon as they exist (no wait-for-suite-end).
4. After the speed matrix, runs quality knobs and a megapixels×duration scale study on the **fastest** speed config.

## Non-goals

- Perceptual quality metrics (VBench, human MOS, etc.)
- Multi-GPU / remote Comfy farms
- Changing prompt or first-frame mid-suite
- Enabling Clean VRAM, RIFE interpolation, or RTX upscale during benchmarks

## Architecture

```
ComfyUI :8188  <--- /prompt + history/ws ---  benchmark_runner.py
                                                     |
                                                     | append result + copy video
                                                     v
                                             results/
                                               benchmark.json   (atomic rewrite)
                                               videos/<run_id>.mp4
                                               runs/<run_id>.meta.json
                                               suite.log
                                                     ^
ui/ (static SPA)  -- poll GET /api/results --  HTTP server (same process as runner)
```

### Components

| Component | Responsibility |
|-----------|----------------|
| `benchmark_runner.py` | Phase queue, workflow mutation, Comfy API client, warmup+timed protocol, result persistence, embedded UI server |
| `workflow_mutate.py` (or module) | Load UI workflow → API prompt; apply quant/cache/sol-attn/sampler/etc. |
| `results/benchmark.json` | Single source of truth for suite state; rewritten atomically after every cell |
| `ui/` | Progressive results SPA: heatmap, tables, chart, video gallery |

### Progressive results

- After each **timed** run completes (or fails), the runner updates `benchmark.json` and stores the video.
- UI polls `GET /api/results` every 1–2s (SSE optional later) and patches tables/gallery in place.
- User never needs to wait for the full suite to inspect finished cells.

## Shared run protocol

Applies to **every** benchmark cell in all phases:

| Rule | Behavior |
|------|----------|
| Seed | Fixed `914265959575104`; seed control = fixed (not randomize) on `easy seed` and `RandomNoise` |
| Content baseline | Prompt + first-frame image from the workflow as-is |
| Clean VRAM | **Always bypassed** (`easy cleanGpuUsed` mode bypass) |
| RIFE / Upscale | **Always bypassed** |
| Cache exclusivity | **Exactly one** of Spectrum, EasyCache, H3 Cache active; the other two bypassed |
| Per cell | (1) **Warmup** generation — discard timing & do not score; (2) **Timed** generation — record wall-clock from prompt accepted → outputs ready |
| Live write | On timed completion: video under `results/videos/`, row in `benchmark.json` |
| Failures | Record error, mark cell `failed`, continue queue |
| Resume | `--resume` skips `done` cells; `--retry-failed` requeues failures |

**Timing definition:** wall-clock on the client from successful `/prompt` acceptance until history shows the prompt completed with outputs (or error). Warmup duration may be logged but is not used for rankings.

## Baseline (Phase 1 fixed content settings)

Unless a phase overrides a field:

- Megapixels: `0.5` (`ResolutionSelector`)
- Aspect: `16:9 (Widescreen)`
- Duration: `5` seconds (`PrimitiveFloat` Duration → frame math)
- Scheduler: `simple`
- Sampler: `res_multistep`
- Steps: `20`
- Seed: `914265959575104`

## Phase 1 — Speed matrix (+ tuned variants)

**Purpose:** Compare generation speed across cache method, quantization, and sol-attn (plus a few widget tweaks).

### Core axes (12 cells)

| Axis | Values |
|------|--------|
| Cache | `spectrum` \| `easy` \| `h3` (only one active) |
| Quant | `nvfp4` (`UNETLoader` + model `minimax_h3_fl2va_pruned_nvfp4.safetensors`) \| `int8` (`OTUNetLoaderW8A8` + `minimax_h3_fl2va_pruned_int8_convrot.safetensors`) |
| Sol-attn | `on` (default SolAttnPatch widgets) \| `off` (bypass SolAttnPatch) |

Core: **3 × 2 × 2 = 12** cells.

### Tuned variants (~8 extra cells)

Fixed reference for variants: **`nvfp4` + sol-attn on**, unless the variant is specifically a sol-attn tweak (still nvfp4). Cache for cache-variants is the named cache only.

| Variant id | Changes (relative to node defaults / workflow values) |
|------------|--------------------------------------------------------|
| `easy_aggressive` | EasyCache: reuse_threshold `0.35`, start `0.2`, end `0.9` |
| `easy_conservative` | EasyCache: thr `0.1`, start `0.3`, end `0.8` |
| `h3_aggressive` | H3: thr `0.1`, max_steps `3` |
| `h3_conservative` | H3: thr `0.03`, max_steps `1` |
| `spectrum_aggressive` | Spectrum: warmup_steps `3`, blend_weight `0.7` |
| `spectrum_conservative` | Spectrum: warmup_steps `8`, blend_weight `0.3` |
| `sol_aggressive` | SolAttn: tau `1.8`, start `0.1`, end `0.95` (cache = EasyCache defaults; sol on) |
| `sol_conservative` | SolAttn: tau `1.0`, start `0.3`, end `0.85` (cache = EasyCache defaults; sol on) |

**Total Phase 1 ≈ 20 cells** × (warmup + timed) ≈ 40 Comfy executions.

### Phase 1 outcome

- `base_config` = config of the **fastest successful timed** Phase 1 cell (lowest `timed_s`).
- Ties: prefer lower failure risk / core cell over variant if equal; else first by run order.
- UI highlights winner; Phases 2–3 use `base_config` for all speed-related knobs (cache, quant, sol-attn, and any tuned widgets from that winning cell).

## Phase 2 — Quality settings (not in speed heatmap)

**Purpose:** See how scheduler / sampler / steps affect time (and produce videos) on `base_config`.

Still fixed: 0.5 MP, 5s duration, seed, and all of `base_config` speed knobs.

**One-factor-at-a-time** from defaults (`simple`, `res_multistep`, 20):

1. **Schedulers:** `simple`, `beta` (sampler/steps held default)
2. **Samplers:** `euler`, `er_sde`, `res_multistep`, `res_multistep_cfg_pp` (scheduler/steps held default)
3. **Steps:** `16`, `17`, `18`, `19`, `20` (scheduler/sampler held default)

≈ **11 cells** (duplicate default triple may be skipped if already measured).

Phase 2 results live in a **separate table**, not the Phase 1 heatmap.

## Phase 3 — Megapixels × duration

**Purpose:** Measure time vs resolution and length only.

- Speed knobs: `base_config` from Phase 1
- Quality knobs: **Phase 1 defaults** (`simple` / `res_multistep` / 20) — Phase 2 does not change the Phase 3 base unless we later add a flag; **spec: keep Phase-1 quality settings for Phase 3**
- **MP:** `0.4`, `0.5`, `0.6`, `0.7`, `0.8`
- **Duration (s):** `4`, `5`, `6`, `8`, `10`
- Grid: **5 × 5 = 25** cells

Expect multi-tens of minutes at 0.8 MP × 10s. No short artificial timeout; UI shows elapsed while `timing`.

## Workflow mutation

### Source graph

UI workflow `minimax-h3_test.i2v.v2.workflow.json` (38 nodes). Relevant nodes:

| Node id | Type | Role |
|---------|------|------|
| 1 | UNETLoader | nvfp4 model |
| 124 | OTUNetLoaderW8A8 | int8 fast model |
| 126 | Any Switch | quant pick (first live MODEL) |
| 91 | PathchSageAttentionKJ | sage attn patch |
| 92 | SolAttnPatch | sol-attn |
| 123 | MiniMaxH3SigmaShift | sigma shift |
| 15 | EasyCache | easy cache |
| 122 | SpectrumApplyMiniMaxH3 | spectrum cache |
| 128 | UC_MiniMaxH3Cache | h3 cache |
| 127 | Any Switch | cache pick |
| 6 | BasicScheduler | scheduler + steps |
| 7 | KSamplerSelect | sampler |
| 98 | ResolutionSelector | aspect + megapixels |
| 102 | PrimitiveFloat | duration seconds |
| 118 / 119 | easy seed / RandomNoise | seed |
| 97 | easy cleanGpuUsed | VRAM clean — always bypass |
| 96 / 111 | RIFE / RTX SR | post — always bypass |

ComfyUI node `mode`: `0` = active, `4` = bypass.

### Mutation steps per cell

1. Load UI JSON → convert to API prompt (node id → `{class_type, inputs}`).
2. Set quant path: activate one loader, bypass the other.
3. Set sol-attn: active or bypass node 92.
4. Set cache: activate exactly one of 15/122/128; bypass the other two; apply widget overrides for variants.
5. Force bypass: 97, 96, 111 (and related helpers if needed).
6. Write seed, scheduler, sampler, steps, MP, duration as required by the cell.
7. Submit, wait, collect outputs.

Any Switch nodes select the first connected non-bypassed input; bypassing unused branches is the supported selection mechanism (do not rely on combining caches).

## Data model

### Directory layout

```
results/
  benchmark.json
  videos/<run_id>.mp4
  runs/<run_id>.meta.json
  suite.log
ui/
  index.html
  app.js
  styles.css
benchmark_runner.py
# supporting modules as needed
minimax-h3_test.i2v.v2.workflow.json
```

### `benchmark.json` (conceptual schema)

```json
{
  "suite_id": "string",
  "status": "idle|running|completed|aborted",
  "comfy_url": "http://127.0.0.1:8188",
  "started_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "baseline": {
    "seed": 914265959575104,
    "mp": 0.5,
    "duration_s": 5,
    "scheduler": "simple",
    "sampler": "res_multistep",
    "steps": 20
  },
  "base_config": null,
  "current": { "phase": "speed", "run_id": "...", "stage": "warmup|timing" },
  "phases": {
    "speed": { "status": "pending|running|done", "runs": [] },
    "quality": { "status": "pending|running|done", "runs": [] },
    "scale": { "status": "pending|running|done", "runs": [] }
  }
}
```

### Run object

```json
{
  "id": "speed_001_easy_nvfp4_sol_on",
  "phase": "speed|quality|scale",
  "status": "queued|warmup|timing|done|failed",
  "config": {
    "cache": "easy|spectrum|h3",
    "cache_variant": null,
    "quant": "nvfp4|int8",
    "sol_attn": true,
    "sol_variant": null,
    "widgets": {},
    "scheduler": "simple",
    "sampler": "res_multistep",
    "steps": 20,
    "mp": 0.5,
    "duration_s": 5,
    "seed": 914265959575104
  },
  "warmup_s": null,
  "timed_s": null,
  "video_path": null,
  "prompt_id": null,
  "error": null,
  "started_at": null,
  "finished_at": null
}
```

Writes are **atomic** (write temp file → rename) so the UI never reads a half-written JSON.

## UI design

**URL:** runner serves static `ui/` + API on a local port (default **8787**).

### Sections

1. **Header** — suite status, phase, current cell, stage (warmup/timing), elapsed, fastest-so-far.
2. **Phase 1 heatmap** — cache (+ variant) × quant×sol-attn; cell shows `timed_s` or pending/fail; click → detail + video.
3. **Phase 2 table** — scheduler / sampler / steps / time / video link.
4. **Phase 3** — table + simple chart (gen time vs video duration, series by MP).
5. **Gallery** — newest completed first; config chips + `<video controls>`.

### API (minimal)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/results` | Full `benchmark.json` (+ maybe slim summary headers) |
| `GET /api/videos/<path>` | Serve saved videos |
| `GET /` | SPA |

## CLI

```text
python benchmark_runner.py                  # run suite + serve UI
python benchmark_runner.py --ui-only        # serve existing results only
python benchmark_runner.py --resume         # skip done cells
python benchmark_runner.py --retry-failed   # with --resume, redo failures
python benchmark_runner.py --comfy-url URL  # default http://127.0.0.1:8188
python benchmark_runner.py --port 8787      # UI port
```

## Error handling & ops

- Comfy unreachable at start → fail fast with clear message.
- Mid-suite OOM / node error → cell `failed`, log to `suite.log`, continue.
- Phase 3 long jobs: status `timing` with `started_at` so UI can show live elapsed.
- Ctrl+C → mark suite `aborted`, flush JSON, keep finished results.

## Scale estimate

| Phase | Cells | Gens (warm+timed) |
|-------|------:|------------------:|
| Speed | ~20 | ~40 |
| Quality | ~11 | ~22 |
| Scale | 25 | 50 |
| **Total** | **~56** | **~112** |

Wall time depends heavily on GPU and Phase 3 high-MP/long-duration cells.

## Implementation notes (for planning)

- Prefer Python 3.10+ stdlib + minimal deps (`websockets` optional; urllib is enough).
- UI: vanilla HTML/CSS/JS — no build step.
- Convert UI workflow → API format carefully (rgthree Any Switch, bypass modes).
- Never enable Clean VRAM group/node.
- Discard first generation **per cell** (not once per suite).

## Decisions log (from brainstorming)

| Topic | Choice |
|-------|--------|
| Comfy access | Local API already running |
| Baseline | Workflow defaults + fixed seed |
| Variant depth | Core matrix + ~8 tuned variants |
| Warmup | Once per cell (warmup + timed) |
| Post-matrix base | Fastest Phase 1 timed cell |
| Delivery | Python runner + static UI + live poll |
| Progressive UI | Required — results appear as available |
| Phase 2 design | One-factor-at-a-time |
| Sampler name | `er_sde` (user LGTM) |
| Phase 3 quality knobs | Keep Phase 1 defaults |
| Visual companion | Declined |
