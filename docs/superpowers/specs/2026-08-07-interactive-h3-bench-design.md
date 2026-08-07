# Interactive H3 Benchmark (Manual Config + Dynamic Grid) — Design

**Date:** 2026-08-07  
**Status:** Approved (conversation)  
**Supersedes (product flow):** auto Phase 1/2/3 matrix in `2026-08-06-comfyui-h3-benchmark-design.md`  
**Workflow:** `minimax-h3-i2v_v3_turbo_workflow.json` (from `minimax-h3-i2v_v3_turbo_workflow (4).json`)  
**ComfyUI:** `http://127.0.0.1:8188` (local)

## Goal

Turn the benchmark tool into a **ComfyUI-like control panel** that:

1. Lets the user **tweak one config** (group-style feature toggles + sampling knobs) and click **Run**.
2. Runs the existing **warmup → clear graph cache → timed** protocol for that single config.
3. **Fills a results matrix dynamically** (growing list + smart heatmap) for later comparison.
4. Mirrors the v3 workflow’s **rgthree group bypass semantics** (GGUF vs diffusion, cache sub-pick, Turbo, RIFE, etc.) even though bypassers are not real API nodes.
5. Abstracts noisy cache / Sol-Attn widgets into **conservative / moderate / aggressive** presets.
6. Exposes **scheduler** and **sampler** as first-class controls, preferring **live lists from ComfyUI**.

## Non-goals

- Automatic full speed/quality/scale matrices (old Phase 1–3 suite).
- Multi-run queue / batch builder in v1 (one-shot Run only).
- Perceptual quality metrics (VBench, MOS).
- Multi-GPU / remote Comfy farms / auth.
- Editing workflow topology beyond config-driven mutation.
- Inventing unrun heatmap cells and auto-queueing them.

## Approach

**Config-as-source-of-truth control panel (Approach A).**

- UI edits a `RunConfig` object.
- Backend enforces mutual exclusion and expands presets into concrete node modes + widgets.
- Results accumulate as freeform runs; heatmap is inferred from history, not a predeclared product grid.

---

## §1 — Config model & mutual exclusion

### `RunConfig` fields

| Field | Values / default | Notes |
|--------|------------------|--------|
| `model_path` | `gguf` \| `safetensor` (default **`safetensor`**) | Model-GGUF vs Model-Safetensor groups |
| `quant` | `nvfp4` \| `int8` (default **`nvfp4`**) | Only when `model_path=safetensor`; ignored for GGUF (GGUF uses the workflow’s fixed GGUF filenames; not user-selectable in v1) |
| `turbo` | bool (default **`false`**) | Turbo group (TurboLoRA + turbo step source) |
| `rife` | bool (default **`false`**) | RIFE Frame Interpolation group |
| `upscaler` | bool (default **`false`**) | Upscaler group |
| `clean_vram` | bool (default **`false`**) | Clean VRAM group |
| `cache_enabled` | bool (default **`true`**) | Outer Cache group |
| `cache` | `spectrum` \| `easy` \| `h3` (default **`spectrum`**) | Exactly one when cache enabled |
| `cache_preset` | `conservative` \| `moderate` \| `aggressive` \| `custom` (default **`moderate`**) | Expands to widgets |
| `sol_attn` | bool (default **`true`**) | Use Sol-Attn group; off → Sage path via switch |
| `sol_preset` | `conservative` \| `moderate` \| `aggressive` \| `custom` (default **`moderate`**) | Only when sol on |
| `scheduler` | string (default **`beta57`**) | Matches current v3 graph |
| `sampler` | string (default **`euler`**) | Matches current v3 graph |
| `steps` | int (default **`20`**) | Default Steps when turbo off; turbo path may use graph turbo step float (e.g. 4) |
| `mp` | float (default **`0.5`**) | ResolutionSelector megapixels |
| `duration_s` | float (default **`5`**) | Duration primitive |
| `seed` | int (default **`42`**, fixed mode) | Replaces old default `914265959575104` |
| `widgets` | `dict` | Used when preset is `custom` or for advanced overrides |

### Mutual exclusion (backend enforces; UI disables illegal controls)

1. **GGUF on** → GGUF model + GGUF CLIP active; safetensor loaders bypassed; quant UI disabled.
2. **Safetensor on** → GGUF loaders bypassed; **NVFP4 XOR INT8** active.
3. **Cache off** → Spectrum, EasyCache, and H3 all bypassed.
4. **Cache on** → exactly one of Spectrum / Easy / H3 active.
5. **Sol on** → SolAttn active; Any Switch prefers Sol branch. **Sol off** → Sage path.
6. **Turbo on** → Turbo LoRA active; steps Any Switch prefers turbo step primitive. **Turbo off** → default steps from `cfg.steps`.
7. **RIFE / Upscaler / Clean VRAM** — independent group on/off.

### Presets

Presets expand to concrete widget values before node write. Each run stores **both** the preset name and the **resolved** numbers for reproducibility.

**Cache** (applied only to the selected cache type; `moderate` = workflow defaults):

| Preset | Spectrum (intent) | EasyCache (intent) | H3 (intent) |
|--------|-------------------|--------------------|-------------|
| conservative | higher warmup, lower blend | low thr, narrower window | low thr, `max_steps` 1 |
| moderate | workflow defaults | workflow defaults | workflow defaults |
| aggressive | lower warmup, higher blend | higher thr, wider window | higher thr, `max_steps` 3 |

Concrete numbers: take v3 workflow `widgets_values` as moderate; reuse prior suite’s conservative/aggressive tables where still applicable (Easy thr 0.1/0.35, H3 thr 0.03/0.1, Spectrum warmup 8/3, blend 0.3/0.7, etc.).

**Sol-Attn:**

| Preset | Intent |
|--------|--------|
| conservative | lower tau, narrower percent range |
| moderate | workflow defaults (e.g. tau 1.5, 0.2–0.9) |
| aggressive | higher tau, wider range |

### Scheduler / sampler (first-class)

| Field | Default | UI |
|--------|---------|-----|
| `scheduler` | `beta57` | dropdown |
| `sampler` | `euler` | dropdown |

**Live lists from ComfyUI (preferred):**

- `GET {comfy}/object_info/BasicScheduler` → `input.required.scheduler[0]`
- `GET {comfy}/object_info/KSamplerSelect` → `input.required.sampler_name[0]`

Bench exposes `GET /api/options` (SPA does not call `:8188` directly). Cache options in memory with short TTL + optional refresh.

**Fallback if Comfy unreachable** (user priorities):

- Schedulers: `beta`, `beta57`, `simple`
- Samplers: `euler`, `res_multistep`, `er_sde`

When live lists are available, the full Comfy combo is shown (not only the fallback three).

### Dropped from product model

- Auto Phase 1/2/3 matrices and `build_speed_runs` / `build_quality_runs` / `build_scale_runs` as the main path.
- Fixed heatmap columns only for `nvfp4 × sol`.
- Old fixed seed as default (historical results still load).

---

## §2 — UI layout & Run flow

### Layout

Single page, two columns:

- **Left (sticky): Run panel** — model path, feature group toggles, cache/sol sub-controls, sampling knobs, **Run this config**.
- **Right: Results** — tabs **List** (default) | **Heatmap** | **Gallery**.
- **Header** — suite status, current stage, fastest so far, **Abort**.
- **Detail dialog** — full config JSON, metrics, video.

### Run panel behavior

1. Defaults match §1 / v3 workflow.
2. Toggles mirror Comfy group bypasses; sub-controls grey out when parent off (cache type/preset, sol preset, quant when GGUF).
3. Exclusive pairs: GGUF ↔ Safetensor; NVFP4 ↔ INT8; cache type radio when Cache on.
4. Scheduler/sampler from `/api/options`; show “Comfy offline — limited list” on fallback.
5. **One primary action:** Run this config → POST full `RunConfig`. While a run is in progress, Run is **disabled** (no multi-run queue in v1).
6. After finish, panel **keeps settings** for nudge-and-rerun.
7. **Load from run:** click a result row → “Apply config to panel” to branch from a past cell.

### Results views

| View | Behavior |
|------|----------|
| List | Full history; status chips; timed_s / s/it; key config columns + chips; video link |
| Heatmap | Secondary; inferred axes from history only (see §4) |
| Gallery | Incremental cards; do not rewrite `<video>` on poll |

### Status & abort

- Status: `idle` \| `running` \| `completed` \| `aborted` + current `run_id` / stage (`warmup` \| `timing` \| …) + node label when available.
- Abort cancels Comfy queue and marks active run failed/aborted.
- Poll `GET /api/results` ~1.5s.

### Removed from UI

- Phase 1 / 2 / 3 sections and auto matrices.
- Hardcoded 4-column quant×sol-only heatmap as the sole speed view.

### Kept

- Detail modal + protocol blurb.
- Progressive persistence after each timed completion.

---

## §3 — Backend, API, workflow mutation

### Workflow asset

- Canonical graph: `minimax-h3-i2v_v3_turbo_workflow.json` (repo copy of the user’s v3 turbo workflow).
- Update `WORKFLOW_PATH` and node ID constants for v3 (including GGUF 130/131, turbo 155/157, switches 140/142/158/163/109, cache chain 122→15→128, sol/sage 92/91, clean 97/144, etc.).
- UI-only types still skipped in API conversion: `Note`, `Fast Groups Bypasser (rgthree)`, `Fast Bypasser (rgthree)`.

### Key v3 groups (reference)

| Group | Role | Typical nodes |
|-------|------|----------------|
| Model - GGUF | GGUF path | 130 `GGUFLoaderKJ`, 131 `CLIPLoaderGGUF` |
| Model - Safetensor | Diffusion path | 1 NVFP4, 124 INT8, 2 CLIP, 143 transformer toggles |
| Cache | Outer cache + inner pick | 122 Spectrum, 15 Easy, 128 H3, 139 cache toggles |
| Use Sol-Attn | Sol vs Sage | 92 Sol, 91 Sage, 163 switch |
| Turbo | Turbo LoRA + steps | 155, 157, 158/159 steps switch |
| RIFE Frame Interpolation | Interp | 95, 96, 109 FPS switch |
| Upscaler | RTX SR | 111 |
| Clean VRAM | GPU clean | 97, 144 |
| Video Options | MP / duration / frames | 98, 102, 103 |

Any Switch nodes select the first connected non-bypassed input; bypassing unused branches is the selection mechanism (same as Comfy + rgthree).

### Config → graph

`apply_config(ui, RunConfig, output_tag)`:

1. Expand presets → resolved widgets.
2. Set model path / quant modes and CLIP/MODEL switch inputs via bypass.
3. Set cache group + exclusive cache node modes; apply cache widgets.
4. Set sol/sage modes and switch preference.
5. Set turbo / RIFE / upscaler / clean_vram group modes; FPS and steps switches accordingly.
6. Write scheduler, sampler, steps, seed (fixed), mp, duration.
7. Always write the fixed duration-agnostic baseline prompt to the prompt node (same policy as v1 suite; no per-run prompt editing in v1 UI).
8. Set unique video `filename_prefix` / output tag for warmup vs timed.

Warmup and timed share the same sampling graph; only output naming differs.

### Suite model

- **Flat `runs: list[Run]`** as the product source of truth (`schema_version: 2`).
- `suite.status` for interactive mode:
  - `idle` — no active job (ready for Run)
  - `running` — one cell in warmup/timing
  - `aborted` — last job was aborted (still accepts a new Run; transitions to `running` then back to `idle` on success)
  - `completed` — reserved/legacy; interactive mode normally returns to **`idle`** after each successful run (history lives in `runs[]`, not in suite completion)
- `current`: live progress snapshot while `running`, else `null`.
- No matrix builders at suite init.
- Per-run status: `queued` \| `warmup` \| `timing` \| `done` \| `failed` \| `aborted` (user Abort → run `aborted`, not a silent `failed`).

### HTTP API

| Method | Path | Role |
|--------|------|------|
| `GET` | `/api/results` | Full suite JSON |
| `GET` | `/api/options` | `{ schedulers, samplers, source: "comfy"\|"fallback", defaults, … }` |
| `POST` | `/api/run` | Body: `RunConfig` → start one cell if idle; **`409` if busy** |
| `POST` | `/api/abort` | Cooperative abort + Comfy cancel |
| `GET` | `/api/health` | `{ ok, comfy_ok, comfy_url }` for status line |

Runner executes on a **background thread**; `POST /api/run` returns quickly with `{ run_id, status }`.

### Run protocol (unchanged intent)

Per Run click:

1. **Warmup** full pipeline (discard for ranking; record `warmup_s`).
2. **Clear Comfy graph execution cache only** (not VRAM unload unless `clean_vram` is in-graph for that config).
3. **Timed** identical sampling graph → `timed_s`, `sec_per_it`.
4. Persist video + meta; atomic rewrite `benchmark.json`.

### CLI

- Default: start UI server and **wait for POSTs** (interactive bench), not auto-start a matrix.
- Resume still loads existing `benchmark.json` for display and continuation of history.

### Tests (required themes)

- Preset expansion unit tests.
- Mutual exclusion / API prompt shape (GGUF vs safetensor, single cache, sol switch).
- `POST /api/run` → 409 when busy; options fallback when Comfy mocked down.
- Workflow convert skips rgthree bypassers.
- Migration flatten of v1 `phases.*` into `runs`.

---

## §4 — Smart heatmap, storage, migration

### Growing list

Primary view of history. Every attempt is one `Run` with full config, metrics, status, video path.

### Smart heatmap (secondary)

**When:** ≥2 done runs with non-null `timed_s`.

**Axis inference** — among done runs, find fields that take ≥2 distinct values, using priority:

1. `cache` (use `none` if `cache_enabled=false`)
2. model key: `gguf` \| `nvfp4` \| `int8` (from `model_path` + `quant`)
3. `sol_attn`
4. `turbo`
5. `scheduler`
6. `sampler`
7. `steps`
8. `cache_preset` / `sol_preset`
9. `mp`, `duration_s`, `rife`, `upscaler`, …

Pick up to **two** highest-priority varying fields as row/column axes.  
If only one varies → 1D table.  
If none vary → message: change a knob and run again.

**Cells:** key = axis value tuple. Multiple runs with same key → keep **best (lowest) `timed_s`** (tooltip may show n). Empty = never run. Highlight global fastest among displayed cells.

**Do not** invent unrun combinations or auto-queue them.

### Storage

```
results/
  benchmark.json
  videos/<run_id>.mp4
  runs/<run_id>.meta.json
  suite.log
```

### `benchmark.json` v2 (conceptual)

```json
{
  "suite_id": "...",
  "schema_version": 2,
  "status": "idle",
  "comfy_url": "http://127.0.0.1:8188",
  "baseline": { "seed": 42, "protocol": { } },
  "current": null,
  "runs": []
}
```

### Migration

| Case | Behavior |
|------|----------|
| v1 `phases.speed/quality/scale` | Flatten all runs into `runs[]`; keep original `phase` on each run; set `schema_version: 2` |
| Missing new fields | Defaults: `model_path=safetensor`, feature flags false, presets `moderate` when applicable |
| UI mid-upgrade | Index both `runs` and `phases.*.runs` |
| Existing videos | Paths unchanged |

### Gallery / errors

- Same incremental gallery DOM rules as current UI.
- Duplicate config re-runs allowed (new id); heatmap prefers fastest for that key.
- Failed runs listed, excluded from heatmap best-cell selection.
- Abort → run status `aborted` + suite returns to accepting Run.

---

## Architecture

```
Browser UI  --GET /api/results-->  Bench HTTP server
            --GET /api/options-->       |
            --POST /api/run------------>|
            --POST /api/abort---------->|
                                        v
                                 BenchmarkRunner (thread)
                                        |
                    apply_config(v3 UI workflow) + ComfyClient
                                        |
                                        v
                                 ComfyUI :8188
                                        |
                                        v
                                 results/benchmark.json + videos/
```

## Success criteria

1. User can toggle GGUF vs safetensor, quant, Turbo, RIFE, Cache (+ type), Sol-Attn, Upscaler, Clean VRAM from the UI without opening Comfy.
2. Cache and Sol presets change underlying widgets without exposing every float by default.
3. Scheduler/sampler dropdowns prefer live Comfy lists; fallback works offline.
4. One Run click produces one warmup+timed cell and appends to history immediately.
5. List always shows all runs; heatmap appears when axes vary; no auto matrix.
6. Old `benchmark.json` still loads (flattened).
7. Tests cover exclusivity, presets, API busy/options, and migration.

## Implementation order (hint for plan)

1. Vendor v3 workflow + constants/node map.
2. Extend `RunConfig` + preset expansion + `apply_config` for v3 groups.
3. Suite flat `runs` + migration + store.
4. HTTP: options, run, abort; runner interactive mode.
5. UI Run panel + list/heatmap/gallery rework.
6. Tests + README update.
```
