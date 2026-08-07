# Interactive H3 Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the auto Phase 1–3 matrix with a one-shot Run control panel that mirrors v3 workflow group toggles, expands cache/sol presets, fetches scheduler/sampler lists from Comfy, and accumulates a growing results list plus smart heatmap.

**Architecture:** Config-as-source-of-truth (`RunConfig`) → `apply_config` mutates the v3 UI workflow into an API prompt (omit unused branches + rewire, same pattern as today) → interactive `BenchmarkRunner.run_one` on a background thread → flat `suite.runs[]` in `benchmark.json` → SPA posts `/api/run` and polls `/api/results`.

**Tech Stack:** Python 3 stdlib HTTP server, existing `bench/*` package, ComfyUI `/prompt` + `/object_info`, static `ui/` SPA (vanilla JS/CSS).

**Spec:** `docs/superpowers/specs/2026-08-07-interactive-h3-bench-design.md`

---

## File structure

| Path | Responsibility |
|------|----------------|
| `minimax-h3-i2v_v3_turbo_workflow.json` | Canonical v3 UI workflow (vendored) |
| `bench/constants.py` | Paths, node IDs, model filenames, seed default 42, preset tables |
| `bench/models.py` | `RunConfig`, `Run`, flat `Suite.runs`, migration helpers, statuses |
| `bench/presets.py` | **New.** Expand `cache_preset` / `sol_preset` → widget dicts |
| `bench/workflow.py` | `ui_to_api_prompt`, v3-aware `apply_config` |
| `bench/options.py` | **New.** Fetch Comfy object_info lists + fallbacks |
| `bench/store.py` | Persist suite; `patch_run` on flat runs; migration on load |
| `bench/runner.py` | `run_one(cfg)`, abort → `aborted`, drop auto matrix as default |
| `bench/server.py` | `GET /api/options`, `POST /api/run`, `POST /api/abort`, `GET /api/health` |
| `bench/matrix.py` | **Deprecate** builders (keep file with note or delete after tests drop imports) |
| `benchmark_runner.py` | Default interactive serve + wire runner into server |
| `ui/index.html`, `ui/app.js`, `ui/styles.css` | Run panel + list/heatmap/gallery |
| `tests/test_*.py` | Updated/new unit tests |
| `README.md` | Interactive usage |

---

### Task 1: Vendor v3 workflow + constants

**Files:**
- Create/ensure: `minimax-h3-i2v_v3_turbo_workflow.json`
- Modify: `bench/constants.py`
- Test: `tests/test_constants_workflow.py` (new, tiny)

- [ ] **Step 1: Ensure workflow file is in repo root**

If missing, copy from:

`C:\Users\ricar\Downloads\minimax-h3-i2v_v3_turbo_workflow (4).json`

to:

`minimax-h3-i2v_v3_turbo_workflow.json`

Verify node count ~58 and groups include `Model - GGUF`, `Turbo`, `Cache`.

```powershell
python -c "import json; w=json.load(open('minimax-h3-i2v_v3_turbo_workflow.json',encoding='utf-8')); print(len(w['nodes']), [g['title'] for g in w['groups']])"
```

Expected: includes `Model - GGUF`, `Model - Safetensor`, `Cache`, `Turbo`, `Use Sol-Attn`, `RIFE Frame Interpolation`, `Upscaler`, `Clean VRAM`.

- [ ] **Step 2: Rewrite `bench/constants.py` node map**

Replace workflow path and node IDs. Keep MODE_ACTIVE/BYPASS. Full target content:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = ROOT / "minimax-h3-i2v_v3_turbo_workflow.json"
# Keep v2 path only if tests still need it during migration — prefer single path:
# WORKFLOW_PATH_V2 = ROOT / "minimax-h3_test.i2v.v2.workflow.json"
RESULTS_DIR = ROOT / "results"
BENCHMARK_JSON = RESULTS_DIR / "benchmark.json"
VIDEOS_DIR = RESULTS_DIR / "videos"
RUNS_DIR = RESULTS_DIR / "runs"
UI_DIR = ROOT / "ui"
SUITE_LOG = RESULTS_DIR / "suite.log"

DEFAULT_COMFY_URL = "http://127.0.0.1:8188"
DEFAULT_UI_PORT = 8787

MODE_ACTIVE = 0
MODE_BYPASS = 4

# --- v3 node IDs ---
NODE_UNET = 1          # NVFP4 UNETLoader
NODE_CLIP = 2
NODE_VAE_VIDEO = 3
NODE_VAE_AUDIO = 4
NODE_I2V = 5
NODE_SCHEDULER = 6
NODE_SAMPLER = 7
NODE_GUIDER = 8
NODE_SAMPLER_ADV = 10
NODE_VAE_DECODE_AUDIO = 12
NODE_EASYCACHE = 15
NODE_LOAD_IMAGE = 20
NODE_SAGE = 91
NODE_SOL_ATTN = 92
NODE_RIFE = 96
NODE_CLEAN_VRAM = 97          # Free VRAM before decode
NODE_RESOLUTION = 98
NODE_DURATION = 102
NODE_FRAME_MATH = 103
NODE_PROMPT = 107
NODE_BASE_FPS = 108
NODE_FPS_SWITCH = 109
NODE_VIDEO_COMBINE = 110
NODE_UPSCALER = 111
NODE_SEED = 118
NODE_NOISE = 119
NODE_SPECTRUM = 122
NODE_SIGMA_SHIFT = 123
NODE_INT8 = 124
NODE_VAE_DECODE = 125
NODE_H3_CACHE = 128
NODE_GGUF = 130
NODE_CLIP_GGUF = 131
NODE_CACHE_BYPASSER = 139     # UI-only Fast Bypasser — omit from API
NODE_CLIP_SWITCH = 140
NODE_MODEL_SWITCH = 142
NODE_TRANSFORMER_BYPASSER = 143  # UI-only
NODE_CLEAN_TE = 144           # Unload Text Encoder
NODE_LAST_FRAME = 145
NODE_FIT_FIRST = 146
NODE_FIT_LAST = 147
NODE_OPTIONAL_LORA = 148
NODE_TURBO_LORA = 155
NODE_TURBO_STEPS = 157        # PrimitiveFloat (e.g. 4)
NODE_STEPS_SWITCH = 158
NODE_DEFAULT_STEPS = 159      # PrimitiveFloat default steps
NODE_FLOAT_TO_INT = 161
NODE_ATTN_SWITCH = 163        # Sol vs Sage
NODE_INTERP_FPS = 95
NODE_TARGET_FPS = 95          # alias for RIFE fps primitive

FIXED_SEED = 42

NVFP4_UNET = "minimax_h3_fl2va_pruned_nvfp4.safetensors"
INT8_UNET = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
GGUF_UNET = "MiniMax-H3-FL2VA-Q4_K_M.gguf"
GGUF_CLIP = "qwen3vl-32B-MiniMax-H3-Q4_K_M.gguf"

BASELINE_PROMPT = (
    "The scene animates from the first frame. Steam billows heavily from under "
    "the car hood. The older man exhales a tired sigh and slumps slightly. The "
    "overhead light flickers. The younger man tightens his grip on the wrench, "
    "steps forward, and angrily points it toward the engine while shouting. A "
    "sudden burst of sparks shoots up from the engine bay, casting a bright "
    "orange flash across both men's faces as the camera quickly zooms in on the "
    "younger man."
)

# Fallback option lists when Comfy object_info is unavailable
FALLBACK_SCHEDULERS = ["beta", "beta57", "simple"]
FALLBACK_SAMPLERS = ["euler", "res_multistep", "er_sde"]

DEFAULT_SCHEDULER = "beta57"
DEFAULT_SAMPLER = "euler"
```

- [ ] **Step 3: Write failing smoke test**

```python
# tests/test_constants_workflow.py
from pathlib import Path
import json
from bench.constants import WORKFLOW_PATH, FIXED_SEED, NODE_GGUF, NODE_TURBO_LORA

def test_v3_workflow_exists_and_has_gguf_turbo():
    assert WORKFLOW_PATH.is_file()
    data = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    ids = {n["id"] for n in data["nodes"]}
    assert NODE_GGUF in ids
    assert NODE_TURBO_LORA in ids
    assert FIXED_SEED == 42
```

- [ ] **Step 4: Run test**

```bash
pytest tests/test_constants_workflow.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add minimax-h3-i2v_v3_turbo_workflow.json bench/constants.py tests/test_constants_workflow.py
git commit -m "chore: vendor v3 turbo workflow and node constants"
```

---

### Task 2: Extend RunConfig + Suite flat runs + migration

**Files:**
- Modify: `bench/models.py`
- Modify: `tests/test_models.py`
- Modify: `bench/store.py` (load migrates)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_models.py — replace / extend
from bench.models import Run, RunConfig, Suite, empty_suite, migrate_suite_dict

def test_runconfig_defaults_v2():
    c = RunConfig()
    assert c.model_path == "safetensor"
    assert c.quant == "nvfp4"
    assert c.seed == 42
    assert c.scheduler == "beta57"
    assert c.sampler == "euler"
    assert c.cache_enabled is True
    assert c.cache == "spectrum"
    assert c.cache_preset == "moderate"
    assert c.sol_attn is True
    assert c.sol_preset == "moderate"
    assert c.turbo is False
    assert c.rife is False
    assert c.upscaler is False
    assert c.clean_vram is False

def test_run_roundtrip_new_fields():
    r = Run(
        id="run_001",
        phase="manual",
        config=RunConfig(model_path="gguf", turbo=True, scheduler="beta"),
        status="done",
        timed_s=10.0,
    )
    back = Run.from_dict(r.to_dict())
    assert back.config.model_path == "gguf"
    assert back.config.turbo is True
    assert back.config.scheduler == "beta"

def test_empty_suite_flat_runs():
    s = empty_suite("t1", "http://127.0.0.1:8188")
    assert s.schema_version == 2
    assert s.runs == []
    assert s.baseline["seed"] == 42
    # phases may be empty dict for new suites
    assert s.phases == {} or "speed" not in s.phases or s.phases == {}

def test_migrate_v1_phases_to_runs():
    raw = {
        "suite_id": "old",
        "status": "completed",
        "comfy_url": "http://127.0.0.1:8188",
        "baseline": {"seed": 914265959575104},
        "phases": {
            "speed": {
                "status": "done",
                "runs": [
                    {
                        "id": "speed_001",
                        "phase": "speed",
                        "status": "done",
                        "config": {"cache": "none", "quant": "nvfp4", "sol_attn": True},
                        "timed_s": 100.0,
                    }
                ],
            },
            "quality": {"status": "done", "runs": []},
            "scale": {"status": "done", "runs": []},
        },
    }
    s = migrate_suite_dict(raw)
    assert s.schema_version == 2
    assert len(s.runs) == 1
    assert s.runs[0].id == "speed_001"
    assert s.runs[0].config.model_path == "safetensor"
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/test_models.py -v
```

- [ ] **Step 3: Implement `bench/models.py` changes**

Key shapes:

```python
PhaseName = Literal["manual", "speed", "quality", "scale"]  # legacy phases kept for archaeology
RunStatus = Literal["queued", "warmup", "timing", "done", "failed", "aborted"]
SuiteStatus = Literal["idle", "running", "completed", "aborted"]
ModelPath = Literal["gguf", "safetensor"]
CacheName = Literal["none", "spectrum", "easy", "h3"]  # none when cache_enabled False
QuantName = Literal["nvfp4", "int8"]
PresetName = Literal["conservative", "moderate", "aggressive", "custom"]

@dataclass
class RunConfig:
    model_path: ModelPath = "safetensor"
    quant: QuantName = "nvfp4"
    turbo: bool = False
    rife: bool = False
    upscaler: bool = False
    clean_vram: bool = False
    cache_enabled: bool = True
    cache: CacheName = "spectrum"  # ignored when not cache_enabled
    cache_preset: PresetName = "moderate"
    sol_attn: bool = True
    sol_preset: PresetName = "moderate"
    widgets: dict[str, Any] = field(default_factory=dict)
    scheduler: str = "beta57"
    sampler: str = "euler"
    steps: int = 20
    mp: float = 0.5
    duration_s: float = 5.0
    seed: int = 42
    # legacy optional fields still accepted on from_dict:
    cache_variant: str | None = None
    sol_variant: str | None = None

@dataclass
class Run:
    id: str
    phase: PhaseName = "manual"
    status: RunStatus = "queued"
    config: RunConfig = field(default_factory=RunConfig)
    # ... keep existing metric fields ...

@dataclass
class Suite:
    suite_id: str
    status: SuiteStatus = "idle"
    schema_version: int = 2
    comfy_url: str = "http://127.0.0.1:8188"
    started_at: str | None = None
    updated_at: str | None = None
    baseline: dict[str, Any] = field(default_factory=dict)
    base_config: dict[str, Any] | None = None
    current: dict[str, Any] | None = None
    runs: list[Run] = field(default_factory=list)
    phases: dict[str, PhaseState] = field(default_factory=dict)  # legacy only

    def all_runs(self) -> list[Run]:
        if self.runs:
            return list(self.runs)
        out: list[Run] = []
        for ph in self.phases.values():
            out.extend(ph.runs)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "schema_version": self.schema_version,
            "status": self.status,
            "comfy_url": self.comfy_url,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "baseline": self.baseline,
            "base_config": self.base_config,
            "current": self.current,
            "runs": [r.to_dict() for r in self.runs],
            # omit empty phases or include for debug — prefer omit if empty
            **({"phases": {k: v.to_dict() for k, v in self.phases.items()}} if self.phases else {}),
        }

def migrate_suite_dict(d: dict[str, Any]) -> Suite:
    """Normalize v1 phases-only files into schema_version 2 flat runs."""
    d = dict(d)
    if d.get("schema_version") == 2 and d.get("runs") is not None:
        return Suite.from_dict(d)
    runs_raw: list = list(d.get("runs") or [])
    if not runs_raw:
        for phase_name, phase in (d.get("phases") or {}).items():
            for r in (phase or {}).get("runs") or []:
                rr = dict(r)
                rr.setdefault("phase", phase_name)
                runs_raw.append(rr)
    d["runs"] = runs_raw
    d["schema_version"] = 2
    # Do not require phases going forward
    return Suite.from_dict(d)

def empty_suite(suite_id: str, comfy_url: str) -> Suite:
    from bench.constants import FIXED_SEED, DEFAULT_SCHEDULER, DEFAULT_SAMPLER
    from bench.models import BENCHMARK_PROTOCOL  # keep existing protocol dict; update seed text if needed
    return Suite(
        suite_id=suite_id,
        schema_version=2,
        comfy_url=comfy_url,
        baseline={
            "seed": FIXED_SEED,
            "mp": 0.5,
            "duration_s": 5,
            "scheduler": DEFAULT_SCHEDULER,
            "sampler": DEFAULT_SAMPLER,
            "steps": 20,
            "protocol": BENCHMARK_PROTOCOL,
        },
        runs=[],
        phases={},
    )
```

`RunConfig.from_dict`: ignore unknown keys; if `cache == "none"` set `cache_enabled=False` and `cache="spectrum"` for storage consistency **or** keep cache=none as the disabled sentinel — **prefer:** when loading legacy `cache="none"`, set `cache_enabled=False` and leave `cache` as `none`.

Update `RunStatus` to include `"aborted"`.

- [ ] **Step 4: Update `store.load_suite` / `try_load_suite`**

```python
def load_suite(path: Path | None = None) -> Suite:
    p = path or BENCHMARK_JSON
    data = json.loads(p.read_text(encoding="utf-8"))
    from bench.models import migrate_suite_dict
    return migrate_suite_dict(data)

def patch_run(run_id: str, **fields: Any) -> Suite:
    suite = load_suite()
    for r in suite.all_runs():
        if r.id == run_id:
            for k, v in fields.items():
                if k == "config" and isinstance(v, dict):
                    from bench.models import RunConfig
                    setattr(r, k, RunConfig.from_dict(v))
                else:
                    setattr(r, k, v)
            break
    else:
        raise KeyError(f"run {run_id} not found")
    # Prefer mutating suite.runs; if only phases (shouldn't after migrate), still save
    save_suite(suite)
    return suite
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_models.py tests/test_store.py -v
```

Fix any store tests that assume `phases.speed`.

- [ ] **Step 6: Commit**

```bash
git add bench/models.py bench/store.py tests/test_models.py tests/test_store.py
git commit -m "feat: flat suite.runs schema and RunConfig v2 fields"
```

---

### Task 3: Preset expansion

**Files:**
- Create: `bench/presets.py`
- Create: `tests/test_presets.py`

- [ ] **Step 1: Failing tests**

```python
from bench.presets import expand_presets
from bench.models import RunConfig

def test_moderate_matches_empty_widgets_merge():
    cfg = RunConfig(cache="easy", cache_preset="moderate", sol_attn=True, sol_preset="moderate")
    w = expand_presets(cfg)
    assert "reuse_threshold" in w or w == {} or "tau" in w
    # moderate must return concrete numbers for the active cache + sol
    assert w.get("reuse_threshold") == 0.2  # EasyCache workflow default from v3

def test_aggressive_easy_and_sol():
    cfg = RunConfig(cache="easy", cache_preset="aggressive", sol_attn=True, sol_preset="aggressive")
    w = expand_presets(cfg)
    assert w["reuse_threshold"] == 0.35
    assert w["tau"] == 1.8

def test_custom_uses_cfg_widgets_only():
    cfg = RunConfig(
        cache="h3",
        cache_preset="custom",
        sol_attn=True,
        sol_preset="custom",
        widgets={"reuse_threshold": 0.07, "tau": 1.2},
    )
    w = expand_presets(cfg)
    assert w["reuse_threshold"] == 0.07
    assert w["tau"] == 1.2

def test_cache_disabled_skips_cache_keys():
    cfg = RunConfig(cache_enabled=False, cache_preset="aggressive", sol_attn=False)
    w = expand_presets(cfg)
    assert "warmup_steps" not in w
    assert "tau" not in w
```

- [ ] **Step 2: Implement `bench/presets.py`**

```python
from __future__ import annotations
from typing import Any
from bench.models import RunConfig

# Values: moderate = v3 workflow widgets; cons/aggr from prior design tables
EASY = {
    "conservative": {"reuse_threshold": 0.1, "start_percent": 0.3, "end_percent": 0.8},
    "moderate": {"reuse_threshold": 0.2, "start_percent": 0.15, "end_percent": 0.95},
    "aggressive": {"reuse_threshold": 0.35, "start_percent": 0.2, "end_percent": 0.9},
}
H3 = {
    "conservative": {"reuse_threshold": 0.03, "start_percent": 0.15, "end_percent": 0.9, "max_steps": 1},
    "moderate": {"reuse_threshold": 0.05, "start_percent": 0.15, "end_percent": 0.9, "max_steps": 2},
    "aggressive": {"reuse_threshold": 0.1, "start_percent": 0.15, "end_percent": 0.9, "max_steps": 3},
}
SPECTRUM = {
    "conservative": {"warmup_steps": 8, "blend_weight": 0.3, "enabled": True},
    "moderate": {"warmup_steps": 5, "blend_weight": 0.5, "enabled": True},
    "aggressive": {"warmup_steps": 3, "blend_weight": 0.7, "enabled": True},
}
SOL = {
    "conservative": {"tau": 1.0, "start_percent": 0.3, "end_percent": 0.85},
    "moderate": {"tau": 1.5, "start_percent": 0.2, "end_percent": 0.9},
    "aggressive": {"tau": 1.8, "start_percent": 0.1, "end_percent": 0.95},
}

def expand_presets(cfg: RunConfig) -> dict[str, Any]:
    """Return flat widget overrides for active cache + sol (if enabled)."""
    out: dict[str, Any] = {}
    if cfg.cache_enabled and cfg.cache != "none":
        if cfg.cache_preset == "custom":
            out.update({k: v for k, v in (cfg.widgets or {}).items() if k in _CACHE_KEYS})
        else:
            table = {"easy": EASY, "h3": H3, "spectrum": SPECTRUM}[cfg.cache]
            out.update(table[cfg.cache_preset])
    if cfg.sol_attn:
        if cfg.sol_preset == "custom":
            out.update({k: v for k, v in (cfg.widgets or {}).items() if k in _SOL_KEYS})
        else:
            out.update(SOL[cfg.sol_preset])
    return out

_CACHE_KEYS = {
    "reuse_threshold", "start_percent", "end_percent", "max_steps",
    "warmup_steps", "blend_weight", "enabled", "degree", "verbose",
}
_SOL_KEYS = {"tau", "start_percent", "end_percent", "min_tokens", "int8_qk", "verbose"}
```

- [ ] **Step 3: pytest pass + commit**

```bash
pytest tests/test_presets.py -v
git add bench/presets.py tests/test_presets.py
git commit -m "feat: cache and sol-attn preset expansion"
```

---

### Task 4: v3 `apply_config` (core mutation)

**Files:**
- Modify: `bench/workflow.py`
- Rewrite: `tests/test_workflow.py`

Strategy (keep proven omit+rewire pattern; do not ship Fast Bypasser nodes):

**MODEL chain (conceptual):**

```
loader(GGUF|INT8|NVFP4)
  → [TurboLoRA if turbo]
  → [optional Lora omit always for bench unless needed — omit 148 if bypassed]
  → attention: Sol XOR Sage (link one, omit other)
  → SigmaShift
  → [Spectrum?] → [Easy?] → [H3?]   # only selected cache node kept
  → Scheduler model + Guider model
```

**CLIP:** link I2V `clip` from GGUF CLIP or safetensor CLIP; omit the other and omit CLIP switch.

**Steps:** set scheduler `steps` from `cfg.steps`. If `turbo`, also set turbo float if kept; force `steps` to int(turbo steps) when turbo True (read 4 from constant `TURBO_STEPS_DEFAULT = 4` or cfg override). Spec: turbo uses turbo step source — simplest: `steps_eff = 4 if cfg.turbo else cfg.steps` written to BasicScheduler.

**Post path:**
- If not clean_vram: omit 97/144; samples → VAEDecode → (upscale?) → (rife?) → VideoCombine
- If clean_vram: keep 97 in path if graph requires it — if hard, omit always in v1 except mode flag stored for display only. **Prefer real omit when false; when true, insert clean node only if wiring is simple.** Minimum: when `clean_vram=False` omit both clean nodes; when `True`, keep node 97 between sampler and decode if that was original intent.

Inspect v3: sampler → audio decode and clean; video decode separate. Mirror existing rewire: `10 → 125 → 110` when rife/upscaler off. When upscaler on: `125 → 111 → 110`. When rife on: insert 96 before combine and set FPS switch to interp fps.

- [ ] **Step 1: Write failing tests** (use v3 WORKFLOW_PATH)

```python
from bench.constants import *
from bench.models import RunConfig
from bench.workflow import apply_config, load_ui_workflow, ui_to_api_prompt

def test_ui_skips_rgthree_bypassers():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = ui_to_api_prompt(ui)
    types = {n["class_type"] for n in api.values()}
    assert "Fast Groups Bypasser (rgthree)" not in types
    assert "Fast Bypasser (rgthree)" not in types

def test_gguf_omits_safetensor_loaders():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(model_path="gguf"))
    assert str(NODE_GGUF) in api
    assert str(NODE_UNET) not in api
    assert str(NODE_INT8) not in api
    assert str(NODE_CLIP_GGUF) in api
    assert api[str(NODE_I2V)]["inputs"]["clip"][0] == str(NODE_CLIP_GGUF)

def test_safetensor_int8_vs_nvfp4():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(model_path="safetensor", quant="int8"))
    assert str(NODE_INT8) in api and str(NODE_UNET) not in api
    api2 = apply_config(ui, RunConfig(model_path="safetensor", quant="nvfp4"))
    assert str(NODE_UNET) in api2 and str(NODE_INT8) not in api2

def test_single_cache_spectrum():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(cache_enabled=True, cache="spectrum"))
    assert str(NODE_SPECTRUM) in api
    assert str(NODE_EASYCACHE) not in api
    assert str(NODE_H3_CACHE) not in api

def test_cache_off_omits_all():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(cache_enabled=False))
    assert str(NODE_SPECTRUM) not in api
    assert str(NODE_EASYCACHE) not in api
    assert str(NODE_H3_CACHE) not in api

def test_sol_off_uses_sage_only():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(sol_attn=False))
    assert str(NODE_SOL_ATTN) not in api
    assert str(NODE_SAGE) in api

def test_turbo_includes_turbo_lora_and_steps():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(turbo=True, steps=20))
    assert str(NODE_TURBO_LORA) in api
    assert api[str(NODE_SCHEDULER)]["inputs"]["steps"] == 4

def test_rife_upscaler_optional():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(rife=False, upscaler=False))
    assert str(NODE_RIFE) not in api
    assert str(NODE_UPSCALER) not in api
    api2 = apply_config(ui, RunConfig(rife=True, upscaler=True))
    assert str(NODE_RIFE) in api2
    assert str(NODE_UPSCALER) in api2

def test_scheduler_sampler_seed():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(scheduler="simple", sampler="euler", seed=42, steps=18))
    assert api[str(NODE_SCHEDULER)]["inputs"]["scheduler"] == "simple"
    assert api[str(NODE_SCHEDULER)]["inputs"]["steps"] == 18
    assert api[str(NODE_SAMPLER)]["inputs"]["sampler_name"] == "euler"
    assert api[str(NODE_SEED)]["inputs"]["seed"] == 42
```

- [ ] **Step 2: Implement `apply_config` for v3**

Implementation outline inside `apply_config`:

1. `api = ui_to_api_prompt(ui)`
2. Expand presets: `from bench.presets import expand_presets` then `widgets = {**expand_presets(cfg), **(cfg.widgets or {})}` when presets not custom — for custom, expand_presets already reads widgets.
3. Set prompt, seed, scheduler, sampler, mp, duration, filename_prefix.
4. Choose loader; omit other loaders + unused CLIP; set I2V clip link; set model chain start.
5. Turbo: if on, keep TURBO_LORA, link model through it, steps=4; else omit TURBO_LORA and TURBO_STEPS/STEPS_SWITCH if unused, steps=cfg.steps.
6. Omit OPTIONAL_LORA if always bypassed in bench (link past it).
7. Sol vs Sage exclusive.
8. Sigma shift + exclusive cache.
9. Link scheduler+guider model from end of chain.
10. Omit model/clip/attn/steps switches (140,142,158,163,109 if rewired).
11. Post: rewire video path based on flags.
12. Apply widgets to cache + sol nodes.
13. Prune dangling refs (existing loop).

Add WIDGET_MAP entries for new class types:

```python
"GGUFLoaderKJ": ["unet_name", "weight_dtype", ...],  # match widgets_values order from file
"CLIPLoaderGGUF": ["clip_name", "type"],
"MiniMaxH3TurboLoRA": ["lora_name", "strength_model"],
"LoraLoaderModelOnly": ["lora_name", "strength_model"],
"ImageScale": ["upscale_method", "width", "height", "crop"],
"CM_FloatToInt": ["a"],  # if needed
```

Inspect actual `widgets_values` lengths in the v3 JSON when filling WIDGET_MAP.

- [ ] **Step 3: pytest workflow tests**

```bash
pytest tests/test_workflow.py -v
```

- [ ] **Step 4: Commit**

```bash
git add bench/workflow.py tests/test_workflow.py
git commit -m "feat: apply_config for v3 GGUF/turbo/cache groups"
```

---

### Task 5: Options fetch + runner `run_one`

**Files:**
- Create: `bench/options.py`
- Modify: `bench/comfy.py` (optional thin `get_json` helper if missing)
- Modify: `bench/runner.py`
- Create: `tests/test_options.py`
- Modify: `tests/test_runner.py`

- [ ] **Step 1: `bench/options.py`**

```python
from __future__ import annotations
import json
import time
import urllib.request
from typing import Any
from bench.constants import (
    DEFAULT_SAMPLER, DEFAULT_SCHEDULER,
    FALLBACK_SAMPLERS, FALLBACK_SCHEDULERS,
)

_cache: dict[str, Any] = {"t": 0.0, "data": None}
_TTL = 60.0

def fetch_comfy_options(comfy_url: str, timeout: float = 3.0) -> dict[str, Any]:
    now = time.time()
    if _cache["data"] and now - _cache["t"] < _TTL:
        return _cache["data"]
    base = comfy_url.rstrip("/")
    try:
        sched = _combo(f"{base}/object_info/BasicScheduler", "scheduler", timeout)
        samp = _combo(f"{base}/object_info/KSamplerSelect", "sampler_name", timeout)
        if not sched or not samp:
            raise RuntimeError("empty combo")
        data = {
            "schedulers": sched,
            "samplers": samp,
            "source": "comfy",
            "defaults": {
                "scheduler": DEFAULT_SCHEDULER,
                "sampler": DEFAULT_SAMPLER,
                "seed": 42,
                "steps": 20,
                "mp": 0.5,
                "duration_s": 5,
            },
        }
    except Exception:
        data = {
            "schedulers": list(FALLBACK_SCHEDULERS),
            "samplers": list(FALLBACK_SAMPLERS),
            "source": "fallback",
            "defaults": {
                "scheduler": DEFAULT_SCHEDULER,
                "sampler": DEFAULT_SAMPLER,
                "seed": 42,
                "steps": 20,
                "mp": 0.5,
                "duration_s": 5,
            },
        }
    _cache["t"] = now
    _cache["data"] = data
    return data

def _combo(url: str, field: str, timeout: float) -> list[str]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        info = json.loads(resp.read().decode())
    # object_info/{Node} returns { "BasicScheduler": { "input": { "required": { "scheduler": [[...], {...}] }}}}
    node = next(iter(info.values()))
    raw = node["input"]["required"][field][0]
    return list(raw)
```

- [ ] **Step 2: Runner interactive API**

Replace `run_all` default usage with:

```python
def ensure_suite(self, existing: Suite | None = None) -> Suite:
    if existing:
        return existing
    s = empty_suite(str(uuid4())[:8], self.comfy.base_url)
    s.status = "idle"
    self._emit(s)
    return s

def run_one(self, suite: Suite, cfg: RunConfig, *, run_id: str | None = None) -> Run:
    """Append one run and execute warmup+timed. Caller ensures not already running."""
    from bench.presets import expand_presets
    resolved = expand_presets(cfg)
    # store resolved widgets on config copy for reproducibility
    cfg = deepcopy(cfg)
    if cfg.cache_preset != "custom" or cfg.sol_preset != "custom":
        cfg.widgets = {**(cfg.widgets or {}), **resolved}

    rid = run_id or self._next_run_id(suite, cfg)
    run = Run(id=rid, phase="manual", status="queued", config=cfg)
    suite.runs.append(run)
    suite.status = "running"
    self._emit(suite)
    try:
        self._execute_cell(suite, "manual", run)
        if run.status == "done":
            suite.status = "idle"
        elif run.status == "aborted":
            suite.status = "aborted"
        else:
            suite.status = "idle"
    except KeyboardInterrupt:
        run.status = "aborted"
        run.error = run.error or "aborted"
        run.finished_at = _now()
        suite.status = "aborted"
        suite.current = None
        self._emit(suite)
        raise
    suite.current = None
    self._emit(suite)
    return run

def _next_run_id(self, suite: Suite, cfg: RunConfig) -> str:
    n = len(suite.all_runs()) + 1
    path = "gguf" if cfg.model_path == "gguf" else cfg.quant
    cache = "none" if not cfg.cache_enabled else cfg.cache
    sol = "solon" if cfg.sol_attn else "soloff"
    return f"run_{n:03d}_{path}_{cache}_{sol}"
```

Update abort paths in `_execute_cell` to set `status="aborted"` when KeyboardInterrupt.

Keep `run_all` only if tests need it — mark deprecated or delete and update tests to use `run_one`.

- [ ] **Step 3: Tests for options fallback and run_one with mock comfy**

Reuse existing runner test patterns with monkeypatched `ComfyClient`.

- [ ] **Step 4: Commit**

```bash
git add bench/options.py bench/runner.py tests/test_options.py tests/test_runner.py
git commit -m "feat: comfy options fetch and runner.run_one"
```

---

### Task 6: HTTP control plane + interactive CLI

**Files:**
- Modify: `bench/server.py`
- Modify: `benchmark_runner.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Server app state**

Introduce a small process-global controller:

```python
# bench/server.py
class BenchApp:
    def __init__(self):
        self.lock = threading.Lock()
        self.runner: BenchmarkRunner | None = None
        self.suite: Suite | None = None
        self.worker: threading.Thread | None = None
        self.comfy_url: str = DEFAULT_COMFY_URL

APP = BenchApp()

def attach_runner(runner: BenchmarkRunner, suite: Suite) -> None:
    APP.runner = runner
    APP.suite = suite
    APP.comfy_url = runner.comfy.base_url
```

- [ ] **Step 2: Handlers**

`do_GET`:
- `/api/results` — `suite.to_dict()` or load from disk; include `runs` (always).
- `/api/options` — `fetch_comfy_options(APP.comfy_url)`
- `/api/health` — try `runner.comfy.system_stats()` or urllib; `{ok:true, comfy_ok:bool, comfy_url}`

`do_POST`:
- `/api/run` — parse JSON body as RunConfig; if worker alive → 409 `{"error":"busy"}`; else spawn thread `runner.run_one(suite, cfg)`; return 202 `{"run_id", "status":"warmup"}`.
- `/api/abort` — `runner.request_abort()`; return 200.

```python
def do_POST(self):
    parsed = urlparse(self.path)
    length = int(self.headers.get("Content-Length") or 0)
    raw = self.rfile.read(length) if length else b"{}"
    if parsed.path == "/api/run":
        return self._handle_run(raw)
    if parsed.path == "/api/abort":
        return self._handle_abort()
    self.send_error(404)

def _handle_run(self, raw: bytes):
    if APP.runner is None or APP.suite is None:
        return self._json(503, {"error": "runner not attached"})
    with APP.lock:
        if APP.worker and APP.worker.is_alive():
            return self._json(409, {"error": "busy"})
        body = json.loads(raw.decode() or "{}")
        cfg = RunConfig.from_dict(body)
        def job():
            try:
                APP.runner.run_one(APP.suite, cfg)
            except KeyboardInterrupt:
                pass
            except Exception:
                traceback.print_exc()
        t = threading.Thread(target=job, daemon=True)
        APP.worker = t
        t.start()
    return self._json(202, {"status": "started"})
```

CORS not required (same origin).

- [ ] **Step 3: `benchmark_runner.py` default interactive**

```python
def main(...):
    ...
    store.ensure_dirs()
    client = ComfyClient(args.comfy_url)
    # system_stats soft-fail for ui-only
    existing = store.try_load_suite()
    runner = BenchmarkRunner(client, resume=False)
    suite = existing or runner.ensure_suite()
    suite.status = suite.status if suite.runs else "idle"
    store.save_suite(suite)
    from bench.server import attach_runner, start_server
    attach_runner(runner, suite)
    httpd = start_server(args.port)
    print(f"Interactive UI: http://127.0.0.1:{args.port}/")
    print("Tweak config in the UI and click Run. Ctrl+C to exit.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        runner.request_abort()
        httpd.shutdown()
    return 0
```

Remove auto `run_all` from default path. Optional flag `--legacy-matrix` only if cheap; **YAGNI: delete default matrix invocation**.

- [ ] **Step 4: Tests**

- `POST /api/run` with fake runner that no-ops.
- Second POST → 409.
- `GET /api/options` with monkeypatched fetch returning fallback.
- Results include `runs` key.

- [ ] **Step 5: Commit**

```bash
git add bench/server.py benchmark_runner.py tests/test_server.py
git commit -m "feat: POST /api/run control plane and interactive CLI"
```

---

### Task 7: UI Run panel + results (list, heatmap, gallery)

**Files:**
- Rewrite: `ui/index.html`
- Rewrite: `ui/app.js`
- Modify: `ui/styles.css`

- [ ] **Step 1: HTML structure**

```html
<header class="top">...</header>
<div class="layout">
  <aside class="panel" id="run-panel">
    <h2>Run config</h2>
    <!-- model path radios, quant, feature toggles, cache, sol, sampling -->
    <button id="btn-run" type="button">Run this config</button>
    <button id="btn-abort" type="button" class="danger">Abort</button>
  </aside>
  <main>
    <div class="tabs">
      <button data-tab="list" class="active">List</button>
      <button data-tab="heatmap">Heatmap</button>
      <button data-tab="gallery">Gallery</button>
    </div>
    <section id="tab-list"></section>
    <section id="tab-heatmap" hidden></section>
    <section id="tab-gallery" hidden></section>
  </main>
</div>
<dialog id="detail">...</dialog>
```

- [ ] **Step 2: JS state + options load**

```javascript
const state = {
  config: {
    model_path: "safetensor",
    quant: "nvfp4",
    turbo: false,
    rife: false,
    upscaler: false,
    clean_vram: false,
    cache_enabled: true,
    cache: "spectrum",
    cache_preset: "moderate",
    sol_attn: true,
    sol_preset: "moderate",
    scheduler: "beta57",
    sampler: "euler",
    steps: 20,
    mp: 0.5,
    duration_s: 5,
    seed: 42,
  },
  options: null,
  busy: false,
};

async function loadOptions() {
  const r = await fetch("/api/options", { cache: "no-store" });
  state.options = await r.json();
  fillSelect("scheduler", state.options.schedulers, state.config.scheduler);
  fillSelect("sampler", state.options.samplers, state.config.sampler);
  // show banner if source === "fallback"
}
```

Wire form controls ↔ `state.config`. Disable quant when `model_path==="gguf"`. Disable cache radios when `!cache_enabled`. Disable sol preset when `!sol_attn`.

- [ ] **Step 3: Run / Abort**

```javascript
async function runConfig() {
  const r = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(state.config),
  });
  if (r.status === 409) { alert("Busy — wait for current run"); return; }
  if (!r.ok) { alert(await r.text()); return; }
  state.busy = true;
  syncButtons();
}

document.getElementById("btn-abort").onclick = () =>
  fetch("/api/abort", { method: "POST" });
```

- [ ] **Step 4: List + Load from run**

Render `data.runs || flatten(data.phases)` sorted by id or finished_at. Row click opens detail; button "Apply to panel" copies `run.config` into `state.config` and refreshes form.

- [ ] **Step 5: Smart heatmap**

```javascript
const AXIS_PRIORITY = [
  (c) => (!c.cache_enabled || c.cache === "none" ? "none" : c.cache),
  (c) => (c.model_path === "gguf" ? "gguf" : c.quant),
  (c) => (c.sol_attn ? "sol_on" : "sol_off"),
  (c) => (c.turbo ? "turbo" : "no_turbo"),
  (c) => c.scheduler,
  (c) => c.sampler,
  (c) => String(c.steps),
  (c) => c.cache_preset,
  (c) => c.sol_preset,
];

function inferAxes(runs) {
  const done = runs.filter((r) => r.status === "done" && r.timed_s != null);
  const varying = [];
  for (const fn of AXIS_PRIORITY) {
    const vals = new Set(done.map((r) => fn(r.config || {})));
    if (vals.size >= 2) varying.push(fn);
    if (varying.length === 2) break;
  }
  return varying;
}
// Build table; on duplicate keys keep min timed_s
```

- [ ] **Step 6: Gallery**

Port existing incremental gallery logic; extend `configChips` for new fields.

- [ ] **Step 7: CSS**

Two-column `.layout`, sticky `.panel`, toggle chips, disabled controls opacity, tabs.

- [ ] **Step 8: Manual smoke (if Comfy up)**

```bash
python benchmark_runner.py --port 8787
```

Open UI, Run once with defaults, confirm list row appears.

- [ ] **Step 9: Commit**

```bash
git add ui/index.html ui/app.js ui/styles.css
git commit -m "feat: interactive Run panel and dynamic results UI"
```

---

### Task 8: Fix remaining tests, README, cleanup

**Files:**
- Modify: any broken tests (`test_matrix.py` — skip/delete matrix tests or mark deprecated)
- Modify: `README.md`
- Optionally delete or stub `bench/matrix.py` builders

- [ ] **Step 1: Full test suite green**

```bash
pytest -v
```

Fix imports of old FIXED_SEED, phases, WORKFLOW v2 assumptions.

For `tests/test_matrix.py`: replace with a short note test that matrix builders are gone, or delete file and remove from suite.

- [ ] **Step 2: README**

```markdown
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
- Each Run = warmup + timed protocol; results append to `results/benchmark.json`.

## API

| Endpoint | Purpose |
|----------|---------|
| GET /api/results | Suite + runs |
| GET /api/options | Schedulers/samplers |
| POST /api/run | Start one config |
| POST /api/abort | Cancel |
| GET /api/health | Bench + Comfy |
```

- [ ] **Step 3: Final commit**

```bash
git add README.md tests/
git commit -m "docs: interactive bench README; fix tests for v2 suite"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| v3 workflow vendor | T1 |
| RunConfig fields + exclusivity | T2, T4 |
| Presets cons/mod/aggr | T3 |
| Scheduler/sampler live + fallback | T5, T6, T7 |
| apply_config GGUF/turbo/cache/rife/… | T4 |
| Flat runs + migrate v1 | T2 |
| POST run / abort / options / health | T6 |
| One-shot Run UI + disable while busy | T7 |
| List + smart heatmap + gallery | T7 |
| Seed default 42 | T1–T2 |
| Drop auto phases | T5–T6, T8 |
| Progressive results | existing runner path + T5 |
| Abort status | T5 |

## Placeholder / consistency notes

- `phase` for new runs is always `"manual"`.
- Turbo steps forced to **4** in apply_config when `turbo=True` (matches v3 turbo float default).
- GGUF filenames fixed constants; not UI-selectable in v1.
- `cache="none"` legacy ≡ `cache_enabled=False`.
- Smart heatmap axis functions must match keys stored on `RunConfig` after T2.
```
