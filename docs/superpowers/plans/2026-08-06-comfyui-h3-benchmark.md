# MiniMax H3 ComfyUI Benchmark Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python benchmark runner that drives local ComfyUI through speed/quality/scale matrices (warmup-then-timed, no VRAM clean, progressive results) plus a live web UI that shows times and videos as each cell finishes.

**Architecture:** Stdlib-first Python package: mutate the MiniMax H3 UI workflow into API prompts per cell, submit to ComfyUI `:8188`, persist atomic `results/benchmark.json` + videos after every timed run, and serve `ui/` with a tiny HTTP API that the SPA polls every 1–2s.

**Tech Stack:** Python 3.10+, stdlib only (`urllib`, `http.server`, `json`, `pathlib`, `threading`, `argparse`), vanilla HTML/CSS/JS UI, pytest for unit tests. Workflow source: `minimax-h3_test.i2v.v2.workflow.json`. Spec: `docs/superpowers/specs/2026-08-06-comfyui-h3-benchmark-design.md`.

---

## File structure

| Path | Responsibility |
|------|----------------|
| `bench/__init__.py` | Package marker |
| `bench/constants.py` | Node IDs, baseline seed/prompt, paths, mode constants |
| `bench/models.py` | Dataclasses / typed dicts for Run, Suite, Config |
| `bench/store.py` | Atomic read/write of `benchmark.json`, video path helpers |
| `bench/workflow.py` | UI workflow → API prompt; apply config mutations |
| `bench/comfy.py` | ComfyUI HTTP client: queue, wait, download outputs |
| `bench/matrix.py` | Build Phase 1/2/3 run lists |
| `bench/runner.py` | Orchestrate phases, warmup+timed, update store, pick base_config |
| `bench/server.py` | Threaded HTTP server: static UI + `/api/results` + videos |
| `benchmark_runner.py` | CLI entrypoint |
| `ui/index.html` | SPA shell |
| `ui/styles.css` | Layout / heatmap styles |
| `ui/app.js` | Poll API, render tables/gallery |
| `tests/test_workflow.py` | Mutation unit tests |
| `tests/test_matrix.py` | Matrix size/content tests |
| `tests/test_store.py` | Atomic store tests |
| `results/` | Created at runtime (gitignored) |
| `requirements-dev.txt` | `pytest` only |
| `.gitignore` | `results/`, `__pycache__/`, etc. |

---

### Task 1: Project skeleton, constants, models

**Files:**
- Create: `.gitignore`
- Create: `requirements-dev.txt`
- Create: `bench/__init__.py`
- Create: `bench/constants.py`
- Create: `bench/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Create `.gitignore` and dev requirements**

```gitignore
__pycache__/
*.py[cod]
.pytest_cache/
.venv/
venv/
results/
*.log
.DS_Store
```

```text
pytest>=8.0
```

- [ ] **Step 2: Write `bench/constants.py`**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = ROOT / "minimax-h3_test.i2v.v2.workflow.json"
RESULTS_DIR = ROOT / "results"
BENCHMARK_JSON = RESULTS_DIR / "benchmark.json"
VIDEOS_DIR = RESULTS_DIR / "videos"
RUNS_DIR = RESULTS_DIR / "runs"
UI_DIR = ROOT / "ui"
SUITE_LOG = RESULTS_DIR / "suite.log"

DEFAULT_COMFY_URL = "http://127.0.0.1:8188"
DEFAULT_UI_PORT = 8787

# ComfyUI node mode
MODE_ACTIVE = 0
MODE_BYPASS = 4

# Node IDs from minimax-h3_test.i2v.v2.workflow.json
NODE_UNET = 1
NODE_CLIP = 2
NODE_VAE_VIDEO = 3
NODE_VAE_AUDIO = 4
NODE_I2V = 5
NODE_SCHEDULER = 6
NODE_SAMPLER = 7
NODE_GUIDER = 8
NODE_SAMPLER_ADV = 10
NODE_EASYCACHE = 15
NODE_LOAD_IMAGE = 20
NODE_SAGE = 91
NODE_SOL_ATTN = 92
NODE_RIFE = 96
NODE_CLEAN_VRAM = 97
NODE_RESOLUTION = 98
NODE_DURATION = 102
NODE_PROMPT = 107
NODE_UPSCALER = 111
NODE_SEED = 118
NODE_NOISE = 119
NODE_SPECTRUM = 122
NODE_SIGMA_SHIFT = 123
NODE_INT8 = 124
NODE_VAE_DECODE = 125
NODE_SWITCH_QUANT = 126
NODE_SWITCH_CACHE = 127
NODE_H3_CACHE = 128
NODE_VIDEO_COMBINE = 110

FIXED_SEED = 914265959575104

BASELINE_PROMPT = (
    "The scene animates from the first frame. Steam billows heavily from under "
    "the car hood. The older man exhales a tired sigh and slumps slightly. The "
    "overhead light flickers. The younger man tightens his grip on the wrench, "
    "steps forward, and angrily points it toward the engine while shouting. A "
    "sudden burst of sparks shoots up from the engine bay, casting a bright "
    "orange flash across both men's faces as the camera quickly zooms in on the "
    "younger man."
)

NVFP4_UNET = "minimax_h3_fl2va_pruned_nvfp4.safetensors"
INT8_UNET = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
```

- [ ] **Step 3: Write `bench/models.py`**

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

PhaseName = Literal["speed", "quality", "scale"]
RunStatus = Literal["queued", "warmup", "timing", "done", "failed"]
SuiteStatus = Literal["idle", "running", "completed", "aborted"]
CacheName = Literal["none", "spectrum", "easy", "h3"]
QuantName = Literal["nvfp4", "int8"]


@dataclass
class RunConfig:
    cache: CacheName = "easy"
    cache_variant: str | None = None
    quant: QuantName = "nvfp4"
    sol_attn: bool = True
    sol_variant: str | None = None
    widgets: dict[str, Any] = field(default_factory=dict)
    scheduler: str = "simple"
    sampler: str = "res_multistep"
    steps: int = 20
    mp: float = 0.5
    duration_s: float = 5.0
    seed: int = 914265959575104

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RunConfig:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Run:
    id: str
    phase: PhaseName
    status: RunStatus = "queued"
    config: RunConfig = field(default_factory=RunConfig)
    warmup_s: float | None = None
    timed_s: float | None = None
    video_path: str | None = None
    prompt_id: str | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Run:
        cfg = d.get("config") or {}
        if isinstance(cfg, dict):
            cfg = RunConfig.from_dict(cfg)
        return cls(
            id=d["id"],
            phase=d["phase"],
            status=d.get("status", "queued"),
            config=cfg,
            warmup_s=d.get("warmup_s"),
            timed_s=d.get("timed_s"),
            video_path=d.get("video_path"),
            prompt_id=d.get("prompt_id"),
            error=d.get("error"),
            started_at=d.get("started_at"),
            finished_at=d.get("finished_at"),
        )


@dataclass
class PhaseState:
    status: str = "pending"
    runs: list[Run] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "runs": [r.to_dict() for r in self.runs]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PhaseState:
        runs = [Run.from_dict(x) for x in d.get("runs") or []]
        return cls(status=d.get("status", "pending"), runs=runs)


@dataclass
class Suite:
    suite_id: str
    status: SuiteStatus = "idle"
    comfy_url: str = "http://127.0.0.1:8188"
    started_at: str | None = None
    updated_at: str | None = None
    baseline: dict[str, Any] = field(default_factory=dict)
    base_config: dict[str, Any] | None = None
    current: dict[str, Any] | None = None
    phases: dict[str, PhaseState] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "status": self.status,
            "comfy_url": self.comfy_url,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "baseline": self.baseline,
            "base_config": self.base_config,
            "current": self.current,
            "phases": {k: v.to_dict() for k, v in self.phases.items()},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Suite:
        phases_raw = d.get("phases") or {}
        phases = {k: PhaseState.from_dict(v) for k, v in phases_raw.items()}
        return cls(
            suite_id=d["suite_id"],
            status=d.get("status", "idle"),
            comfy_url=d.get("comfy_url", "http://127.0.0.1:8188"),
            started_at=d.get("started_at"),
            updated_at=d.get("updated_at"),
            baseline=d.get("baseline") or {},
            base_config=d.get("base_config"),
            current=d.get("current"),
            phases=phases,
        )


def empty_suite(suite_id: str, comfy_url: str) -> Suite:
    from bench.constants import FIXED_SEED

    return Suite(
        suite_id=suite_id,
        comfy_url=comfy_url,
        baseline={
            "seed": FIXED_SEED,
            "mp": 0.5,
            "duration_s": 5,
            "scheduler": "simple",
            "sampler": "res_multistep",
            "steps": 20,
        },
        phases={
            "speed": PhaseState(),
            "quality": PhaseState(),
            "scale": PhaseState(),
        },
    )
```

- [ ] **Step 4: Write round-trip test**

```python
# tests/test_models.py
from bench.models import Run, RunConfig, empty_suite


def test_run_roundtrip():
    r = Run(
        id="speed_001",
        phase="speed",
        config=RunConfig(cache="none", quant="int8", sol_attn=False),
        timed_s=12.5,
        status="done",
    )
    back = Run.from_dict(r.to_dict())
    assert back.config.cache == "none"
    assert back.config.quant == "int8"
    assert back.timed_s == 12.5


def test_empty_suite_has_three_phases():
    s = empty_suite("t1", "http://127.0.0.1:8188")
    assert set(s.phases) == {"speed", "quality", "scale"}
    assert s.baseline["seed"] == 914265959575104
```

- [ ] **Step 5: Run tests**

```bash
pip install -r requirements-dev.txt
pytest tests/test_models.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add .gitignore requirements-dev.txt bench tests/test_models.py
git commit -m "feat: add bench package skeleton, constants, and models"
```

---

### Task 2: Atomic results store

**Files:**
- Create: `bench/store.py`
- Create: `tests/test_store.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_store.py
import json
from pathlib import Path

from bench.models import Run, RunConfig, empty_suite
from bench import store


def test_save_and_load_suite(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(store, "BENCHMARK_JSON", tmp_path / "benchmark.json")
    monkeypatch.setattr(store, "VIDEOS_DIR", tmp_path / "videos")
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")
    store.ensure_dirs()
    suite = empty_suite("abc", "http://127.0.0.1:8188")
    suite.phases["speed"].runs.append(
        Run(id="r1", phase="speed", status="done", timed_s=9.1, config=RunConfig())
    )
    store.save_suite(suite)
    loaded = store.load_suite()
    assert loaded.suite_id == "abc"
    assert loaded.phases["speed"].runs[0].timed_s == 9.1
    # atomic file exists and is valid JSON
    data = json.loads((tmp_path / "benchmark.json").read_text(encoding="utf-8"))
    assert data["suite_id"] == "abc"


def test_update_run_in_place(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(store, "BENCHMARK_JSON", tmp_path / "benchmark.json")
    monkeypatch.setattr(store, "VIDEOS_DIR", tmp_path / "videos")
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")
    store.ensure_dirs()
    suite = empty_suite("abc", "http://127.0.0.1:8188")
    suite.phases["speed"].runs.append(Run(id="r1", phase="speed", status="queued"))
    store.save_suite(suite)
    store.patch_run("speed", "r1", status="done", timed_s=3.3)
    loaded = store.load_suite()
    assert loaded.phases["speed"].runs[0].status == "done"
    assert loaded.phases["speed"].runs[0].timed_s == 3.3
```

- [ ] **Step 2: Run tests — expect FAIL (module missing)**

```bash
pytest tests/test_store.py -v
```

Expected: FAIL import error

- [ ] **Step 3: Implement `bench/store.py`**

```python
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bench.constants import BENCHMARK_JSON, RESULTS_DIR, RUNS_DIR, VIDEOS_DIR
from bench.models import Suite


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def save_suite(suite: Suite) -> None:
    ensure_dirs()
    suite.updated_at = _utc_now()
    atomic_write_json(BENCHMARK_JSON, suite.to_dict())


def load_suite(path: Path | None = None) -> Suite:
    p = path or BENCHMARK_JSON
    data = json.loads(p.read_text(encoding="utf-8"))
    return Suite.from_dict(data)


def try_load_suite() -> Suite | None:
    if not BENCHMARK_JSON.exists():
        return None
    return load_suite()


def patch_run(phase: str, run_id: str, **fields: Any) -> Suite:
    suite = load_suite()
    runs = suite.phases[phase].runs
    for r in runs:
        if r.id == run_id:
            for k, v in fields.items():
                if k == "config" and isinstance(v, dict):
                    from bench.models import RunConfig

                    setattr(r, k, RunConfig.from_dict(v))
                else:
                    setattr(r, k, v)
            break
    else:
        raise KeyError(f"run {run_id} not found in phase {phase}")
    save_suite(suite)
    return suite


def video_dest(run_id: str, ext: str = ".mp4") -> Path:
    ensure_dirs()
    return VIDEOS_DIR / f"{run_id}{ext}"
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/test_store.py tests/test_models.py -v
```

- [ ] **Step 5: Commit**

```bash
git add bench/store.py tests/test_store.py
git commit -m "feat: atomic benchmark.json store"
```

---

### Task 3: Workflow UI → API conversion + config mutation

**Files:**
- Create: `bench/workflow.py`
- Create: `tests/test_workflow.py`

This is the critical pure-logic module. Use the real workflow file for fixtures.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_workflow.py
from bench.constants import (
    BASELINE_PROMPT,
    MODE_BYPASS,
    NODE_CLEAN_VRAM,
    NODE_EASYCACHE,
    NODE_H3_CACHE,
    NODE_INT8,
    NODE_PROMPT,
    NODE_SOL_ATTN,
    NODE_SPECTRUM,
    NODE_UNET,
    WORKFLOW_PATH,
)
from bench.models import RunConfig
from bench.workflow import apply_config, load_ui_workflow, ui_to_api_prompt


def test_ui_to_api_has_core_nodes():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = ui_to_api_prompt(ui)
    assert str(NODE_UNET) in api or NODE_UNET in api or str(NODE_UNET) in {str(k) for k in api}
    # keys are string node ids
    assert str(NODE_PROMPT) in api
    assert api[str(NODE_PROMPT)]["class_type"] == "PrimitiveStringMultiline"


def test_no_cache_bypasses_all_three():
    ui = load_ui_workflow(WORKFLOW_PATH)
    cfg = RunConfig(cache="none", quant="nvfp4", sol_attn=True)
    api = apply_config(ui, cfg)
    # mode stored either in API meta or we track bypass via a side channel.
    # Prefer: apply_config returns (api_prompt, node_modes) OR embeds _meta.
    # Spec implementation: apply_config mutates and returns api dict;
    # bypassed nodes remain in graph with inputs but runner uses mode map.
    modes = api["_bench_modes"]
    assert modes[str(NODE_EASYCACHE)] == MODE_BYPASS
    assert modes[str(NODE_SPECTRUM)] == MODE_BYPASS
    assert modes[str(NODE_H3_CACHE)] == MODE_BYPASS
    assert modes[str(NODE_CLEAN_VRAM)] == MODE_BYPASS


def test_easy_cache_only_active():
    ui = load_ui_workflow(WORKFLOW_PATH)
    cfg = RunConfig(cache="easy")
    api = apply_config(ui, cfg)
    modes = api["_bench_modes"]
    assert modes[str(NODE_EASYCACHE)] == 0
    assert modes[str(NODE_SPECTRUM)] == MODE_BYPASS
    assert modes[str(NODE_H3_CACHE)] == MODE_BYPASS


def test_int8_vs_nvfp4_modes():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(quant="int8"))
    modes = api["_bench_modes"]
    assert modes[str(NODE_INT8)] == 0
    assert modes[str(NODE_UNET)] == MODE_BYPASS
    api2 = apply_config(ui, RunConfig(quant="nvfp4"))
    modes2 = api2["_bench_modes"]
    assert modes2[str(NODE_UNET)] == 0
    assert modes2[str(NODE_INT8)] == MODE_BYPASS


def test_sol_attn_off_bypasses():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(sol_attn=False))
    assert api["_bench_modes"][str(NODE_SOL_ATTN)] == MODE_BYPASS


def test_prompt_is_timestamp_free():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig())
    val = api[str(NODE_PROMPT)]["inputs"]["value"]
    assert val == BASELINE_PROMPT
    assert "0:00" not in val
```

**Important implementation detail:** ComfyUI `/prompt` API does **not** honor UI `mode` fields unless the frontend strips bypassed nodes or the API prompt omits them / uses passthrough. For API execution:

- **Bypass strategy:** For bypassed nodes that sit on MODEL chains, remove the node from the API graph and rewire consumers to the bypassed node’s primary input source (MODEL passthrough). Implement `apply_config` so the returned prompt graph has **only active nodes**, with links rewired.

Update tests accordingly if you choose pure rewiring (preferred for API):

```python
def test_easy_cache_only_in_graph():
    ui = load_ui_workflow(WORKFLOW_PATH)
    api = apply_config(ui, RunConfig(cache="easy"))
    assert str(NODE_EASYCACHE) in api
    assert str(NODE_SPECTRUM) not in api
    assert str(NODE_H3_CACHE) not in api
    assert str(NODE_CLEAN_VRAM) not in api
```

Use this **rewire/omit** approach in the implementation (clearer for API). Drop `_bench_modes` tests if using omit.

- [ ] **Step 2: Implement `bench/workflow.py`**

Core algorithm:

1. `load_ui_workflow(path) -> dict` — `json.loads`.
2. `ui_to_api_prompt(ui) -> dict[str, dict]`:
   - Build `links_by_id` from `ui["links"]` entries: `[link_id, from_node, from_slot, to_node, to_slot, type]`.
   - For each node, create `{ "class_type": type, "inputs": {} }`.
   - Map named inputs: for each input with a `link`, set `inputs[name] = [str(from_node), from_slot]`.
   - Map widgets: use `object_info` optional OR hardcode widget order per class_type for nodes we touch (see table below). Prefer **hardcoded widget maps** for reliability offline:

```python
WIDGET_MAP = {
    "UNETLoader": ["unet_name", "weight_dtype"],
    "OTUNetLoaderW8A8": ["unet_name", "weight_dtype", "model_type", "on_the_fly_quantization", "enable_convrot", "lora_mode"],
    "BasicScheduler": ["scheduler", "steps", "denoise"],
    "KSamplerSelect": ["sampler_name"],
    "EasyCache": ["reuse_threshold", "start_percent", "end_percent", "verbose"],
    "SpectrumApplyMiniMaxH3": [
        "enabled", "blend_weight", "degree", "ridge_lambda", "window_size",
        "flex_window", "warmup_steps", "tail_actual_steps", "max_history",
        "debug", "history_storage",
    ],
    "UC_MiniMaxH3Cache": [
        "reuse_threshold", "start_percent", "end_percent", "max_steps", "device", "verbose",
    ],
    "SolAttnPatch": [
        "tau", "start_percent", "end_percent", "min_tokens", "int8_qk",
        "sink_conditioning", "morton", "morton_curve", "verbose", "use_tma",
    ],
    "ResolutionSelector": ["aspect_ratio", "megapixels", "divisor"],  # verify names via object_info once
    "PrimitiveFloat": ["value"],
    "PrimitiveStringMultiline": ["value"],
    "easy seed": ["seed", "seed_mode", "seed_value"],  # verify widget names
    "RandomNoise": ["noise_seed", "control_after_generate"],
    "PathchSageAttentionKJ": ["sage_attention", "allow_compile"],  # verify
    "MiniMaxH3SigmaShift": ["shift", "base"],  # verify via object_info
    "MiniMaxH3ImageToVideo": ["prompt", "width", "height", "length"],  # some may be linked
    "VHS_VideoCombine": None,  # dict widgets_values in UI — handle specially
}
```

   On first implementation run against live ComfyUI:

```bash
python -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8188/object_info/ResolutionSelector')))"
```

   Align widget key names with `object_info` `input_order` / required keys.

3. `apply_config(ui, cfg: RunConfig) -> dict`:
   - Start from full API prompt.
   - Always set prompt text on NODE_PROMPT to `BASELINE_PROMPT`.
   - Always set seed fixed: NODE_SEED seed=`cfg.seed`, control fixed; NODE_NOISE same seed, control fixed.
   - Set scheduler/sampler/steps/mp/duration from `cfg`.
   - **Quant:** if nvfp4, omit NODE_INT8; rewire NODE_SWITCH_QUANT consumers... Simpler approach for Any Switch: **omit the switch and wire the chosen loader output directly** to what switch output fed (nodes that linked from 126 → use loader; nodes from 127 → use chosen cache or sigma_shift).

**Recommended simplified rewiring (avoid Any Switch complexity):**

After building the full API graph from UI:

1. Determine selected MODEL path end node:
   - Start MODEL from `NODE_UNET` or `NODE_INT8` based on quant.
   - Always apply: Sage (91) → SolAttn (92 if on else skip) → SigmaShift (123) → Cache (if not none) → consumers that were fed by switch 127 (scheduler 6, guider 8).
2. Build chain explicitly in `apply_config` for MODEL path rather than relying on switches:
   - `model_src = unet or int8`
   - `model_src → sage → [sol] → sigma → [cache] → scheduler + guider`
3. Delete unused nodes: other quant loader, other caches, clean vram, rife, upscaler, both Any Switches for model (126/127), and any nodes only used by deleted subgraphs if orphaned.
4. Keep video decode path intact (sampler → … → VHS_VideoCombine).

Implement helper:

```python
def set_link(api: dict, node_id: str, input_name: str, from_id: str, from_slot: int = 0) -> None:
    api[node_id]["inputs"][input_name] = [from_id, from_slot]
```

Widget setters:

```python
def set_widget(api: dict, node_id: str, name: str, value) -> None:
    api[str(node_id)]["inputs"][name] = value
```

Variant widgets from `cfg.widgets` e.g. `{"EasyCache.reuse_threshold": 0.35}` or nested `cfg.widgets = {"easycache": {"reuse_threshold": 0.35}}` — use nested dict in matrix builder:

```python
# cfg.widgets examples
{"reuse_threshold": 0.35, "start_percent": 0.2, "end_percent": 0.9}  # applied to active cache node
{"tau": 1.8, "start_percent": 0.1, "end_percent": 0.95}  # applied to SolAttn when sol variant
```

In `apply_config`, if `cfg.cache == "easy"` and widgets present, apply known keys onto EasyCache inputs.

- [ ] **Step 3: Verify widget names against live Comfy once**

```bash
python -c "import json,urllib.request as u
for n in ['ResolutionSelector','easy seed','RandomNoise','PrimitiveFloat','PrimitiveStringMultiline','MiniMaxH3SigmaShift','PathchSageAttentionKJ','VHS_VideoCombine']:
  try:
    d=json.load(u.urlopen(f'http://127.0.0.1:8188/object_info/{n}', timeout=5))
    print(n, list((d[n]['input'].get('required') or {})), list((d[n]['input'].get('optional') or {}))[:8])
  except Exception as e:
    print(n, e)"
```

Fix `WIDGET_MAP` / setters to match.

- [ ] **Step 4: Run unit tests**

```bash
pytest tests/test_workflow.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bench/workflow.py tests/test_workflow.py
git commit -m "feat: workflow UI-to-API conversion and config mutation"
```

---

### Task 4: Benchmark matrix builder

**Files:**
- Create: `bench/matrix.py`
- Create: `tests/test_matrix.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_matrix.py
from bench.matrix import build_quality_runs, build_scale_runs, build_speed_runs
from bench.models import RunConfig


def test_speed_core_includes_none_and_three_caches():
    runs = build_speed_runs()
    caches = {r.config.cache for r in runs if r.config.cache_variant is None and r.config.sol_variant is None}
    # core cells have no variants
    core = [r for r in runs if not r.config.cache_variant and not r.config.sol_variant]
    core_caches = {r.config.cache for r in core}
    assert core_caches == {"none", "spectrum", "easy", "h3"}
    assert len(core) == 16  # 4*2*2
    assert any(r.config.cache_variant == "easy_aggressive" for r in runs)
    assert len(runs) == 24  # 16 + 8 variants


def test_quality_one_factor():
    base = RunConfig(cache="easy", quant="nvfp4", sol_attn=True)
    runs = build_quality_runs(base)
    assert any(r.config.scheduler == "beta" for r in runs)
    assert any(r.config.sampler == "er_sde" for r in runs)
    assert any(r.config.steps == 16 for r in runs)
    # no full factorial explosion
    assert len(runs) <= 12


def test_scale_grid():
    base = RunConfig(cache="h3", quant="int8", sol_attn=False)
    runs = build_scale_runs(base)
    assert len(runs) == 25
    mps = {r.config.mp for r in runs}
    durs = {r.config.duration_s for r in runs}
    assert mps == {0.4, 0.5, 0.6, 0.7, 0.8}
    assert durs == {4.0, 5.0, 6.0, 8.0, 10.0}
    # base speed knobs preserved
    assert all(r.config.cache == "h3" for r in runs)
```

- [ ] **Step 2: Implement `bench/matrix.py`**

```python
from __future__ import annotations

from copy import deepcopy

from bench.constants import FIXED_SEED
from bench.models import Run, RunConfig

CACHES = ("none", "spectrum", "easy", "h3")
QUANTS = ("nvfp4", "int8")
SOLS = (True, False)


def _rid(phase: str, idx: int, label: str) -> str:
    safe = label.replace(" ", "_").replace("/", "-")
    return f"{phase}_{idx:03d}_{safe}"


def build_speed_runs() -> list[Run]:
    runs: list[Run] = []
    idx = 1
    for cache in CACHES:
        for quant in QUANTS:
            for sol in SOLS:
                label = f"{cache}_{quant}_sol{'on' if sol else 'off'}"
                runs.append(
                    Run(
                        id=_rid("speed", idx, label),
                        phase="speed",
                        config=RunConfig(
                            cache=cache,  # type: ignore[arg-type]
                            quant=quant,  # type: ignore[arg-type]
                            sol_attn=sol,
                            seed=FIXED_SEED,
                        ),
                    )
                )
                idx += 1

    variants = [
        ("easy_aggressive", "easy", None, {"reuse_threshold": 0.35, "start_percent": 0.2, "end_percent": 0.9}),
        ("easy_conservative", "easy", None, {"reuse_threshold": 0.1, "start_percent": 0.3, "end_percent": 0.8}),
        ("h3_aggressive", "h3", None, {"reuse_threshold": 0.1, "max_steps": 3}),
        ("h3_conservative", "h3", None, {"reuse_threshold": 0.03, "max_steps": 1}),
        ("spectrum_aggressive", "spectrum", None, {"warmup_steps": 3, "blend_weight": 0.7}),
        ("spectrum_conservative", "spectrum", None, {"warmup_steps": 8, "blend_weight": 0.3}),
        ("sol_aggressive", "easy", "sol_aggressive", {"tau": 1.8, "start_percent": 0.1, "end_percent": 0.95}),
        ("sol_conservative", "easy", "sol_conservative", {"tau": 1.0, "start_percent": 0.3, "end_percent": 0.85}),
    ]
    for name, cache, sol_var, widgets in variants:
        runs.append(
            Run(
                id=_rid("speed", idx, name),
                phase="speed",
                config=RunConfig(
                    cache=cache,  # type: ignore[arg-type]
                    cache_variant=name if sol_var is None else None,
                    quant="nvfp4",
                    sol_attn=True,
                    sol_variant=sol_var,
                    widgets=widgets,
                    seed=FIXED_SEED,
                ),
            )
        )
        idx += 1
    return runs


def build_quality_runs(base: RunConfig) -> list[Run]:
    runs: list[Run] = []
    idx = 1

    def add(label: str, **overrides):
        nonlocal idx
        cfg = deepcopy(base)
        for k, v in overrides.items():
            setattr(cfg, k, v)
        runs.append(Run(id=_rid("quality", idx, label), phase="quality", config=cfg))
        idx += 1

    for sched in ("simple", "beta"):
        add(f"sched_{sched}", scheduler=sched)
    for samp in ("euler", "er_sde", "res_multistep", "res_multistep_cfg_pp"):
        add(f"samp_{samp}", sampler=samp)
    for steps in (16, 17, 18, 19, 20):
        add(f"steps_{steps}", steps=steps)
    return runs


def build_scale_runs(base: RunConfig) -> list[Run]:
    runs: list[Run] = []
    idx = 1
    # Phase 3 keeps Phase-1 quality defaults
    for mp in (0.4, 0.5, 0.6, 0.7, 0.8):
        for dur in (4.0, 5.0, 6.0, 8.0, 10.0):
            cfg = deepcopy(base)
            cfg.mp = mp
            cfg.duration_s = dur
            cfg.scheduler = "simple"
            cfg.sampler = "res_multistep"
            cfg.steps = 20
            runs.append(
                Run(
                    id=_rid("scale", idx, f"mp{mp}_d{dur:g}"),
                    phase="scale",
                    config=cfg,
                )
            )
            idx += 1
    return runs


def pick_fastest(runs: list[Run]) -> RunConfig | None:
    done = [r for r in runs if r.status == "done" and r.timed_s is not None]
    if not done:
        return None
    best = min(done, key=lambda r: (r.timed_s, r.id))
    return deepcopy(best.config)
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_matrix.py -v
```

- [ ] **Step 4: Commit**

```bash
git add bench/matrix.py tests/test_matrix.py
git commit -m "feat: speed/quality/scale matrix builders"
```

---

### Task 5: ComfyUI client

**Files:**
- Create: `bench/comfy.py`
- Create: `tests/test_comfy_unit.py` (mock urllib; no live GPU required)

- [ ] **Step 1: Implement client with clear methods**

```python
# bench/comfy.py
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4


class ComfyError(RuntimeError):
    pass


class ComfyClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8188", timeout_s: float = 36000.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.client_id = str(uuid4())

    def _request(self, method: str, path: str, data: dict | None = None) -> Any:
        url = f"{self.base_url}{path}"
        body = None
        headers = {}
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=min(120.0, self.timeout_s)) as resp:
                raw = resp.read()
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise ComfyError(f"HTTP {e.code} {path}: {detail}") from e
        except urllib.error.URLError as e:
            raise ComfyError(f"Comfy unreachable at {self.base_url}: {e}") from e

    def system_stats(self) -> dict:
        return self._request("GET", "/system_stats")

    def queue_prompt(self, prompt: dict[str, Any]) -> str:
        payload = {"prompt": prompt, "client_id": self.client_id}
        out = self._request("POST", "/prompt", payload)
        if not out or "prompt_id" not in out:
            raise ComfyError(f"unexpected /prompt response: {out}")
        return out["prompt_id"]

    def get_history(self, prompt_id: str) -> dict | None:
        hist = self._request("GET", f"/history/{prompt_id}")
        if not hist:
            return None
        return hist.get(prompt_id)

    def wait_for_prompt(self, prompt_id: str, poll_s: float = 1.0) -> dict:
        deadline = time.time() + self.timeout_s
        while time.time() < deadline:
            item = self.get_history(prompt_id)
            if item is not None:
                status = (item.get("status") or {})
                if status.get("status_str") == "error" or status.get("completed") is False and status.get("messages"):
                    # completed false with error messages
                    msgs = status.get("messages") or []
                    raise ComfyError(f"prompt {prompt_id} error: {msgs}")
                if "outputs" in item:
                    # success path: outputs present
                    st = status.get("status_str")
                    if st == "error":
                        raise ComfyError(f"prompt {prompt_id} failed: {status}")
                    return item
            time.sleep(poll_s)
        raise ComfyError(f"timeout waiting for prompt {prompt_id}")

    def download_output_file(self, filename: str, subfolder: str, folder_type: str, dest: Path) -> Path:
        q = f"/view?filename={urllib.request.quote(filename)}&subfolder={urllib.request.quote(subfolder)}&type={urllib.request.quote(folder_type)}"
        url = f"{self.base_url}{q}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=300) as resp, open(dest, "wb") as f:
            f.write(resp.read())
        return dest

    def find_first_video(self, history_item: dict) -> tuple[str, str, str] | None:
        outputs = history_item.get("outputs") or {}
        for _node_id, node_out in outputs.items():
            for key in ("gifs", "videos", "images"):
                for item in node_out.get(key) or []:
                    fn = item.get("filename") or ""
                    if fn.lower().endswith((".mp4", ".webm", ".gif")):
                        return fn, item.get("subfolder") or "", item.get("type") or "output"
        # fallback any file-like
        for _node_id, node_out in outputs.items():
            for key, arr in node_out.items():
                if not isinstance(arr, list):
                    continue
                for item in arr:
                    if isinstance(item, dict) and item.get("filename"):
                        return item["filename"], item.get("subfolder") or "", item.get("type") or "output"
        return None

    def run_prompt(self, prompt: dict[str, Any]) -> tuple[str, float, dict]:
        """Queue prompt and wait. Returns (prompt_id, elapsed_s, history_item)."""
        t0 = time.perf_counter()
        pid = self.queue_prompt(prompt)
        item = self.wait_for_prompt(pid)
        elapsed = time.perf_counter() - t0
        return pid, elapsed, item
```

- [ ] **Step 2: Unit test with monkeypatched urlopen**

```python
# tests/test_comfy_unit.py
import io
import json
from unittest.mock import MagicMock

from bench.comfy import ComfyClient


def test_queue_prompt(monkeypatch):
    client = ComfyClient("http://example:8188")

    def fake_urlopen(req, timeout=None):
        m = MagicMock()
        m.read.return_value = json.dumps({"prompt_id": "abc"}).encode()
        m.__enter__.return_value = m
        m.__exit__.return_value = False
        return m

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert client.queue_prompt({"1": {}}) == "abc"
```

- [ ] **Step 3: Optional live smoke (manual)**

```bash
python -c "from bench.comfy import ComfyClient; print(ComfyClient().system_stats().keys())"
```

Expected: keys including device info — skip if Comfy down during unit CI.

- [ ] **Step 4: Commit**

```bash
git add bench/comfy.py tests/test_comfy_unit.py
git commit -m "feat: ComfyUI HTTP client"
```

---

### Task 6: Runner orchestration (warmup + timed + phases)

**Files:**
- Create: `bench/runner.py`
- Create: `tests/test_runner.py` (mocked ComfyClient)

- [ ] **Step 1: Implement `BenchmarkRunner`**

```python
# bench/runner.py — key behavior
"""
- build suite with matrix runs
- for each run in phase order speed → quality → scale:
  - if resume and status==done: skip
  - mark warmup, apply_config, comfy.run_prompt (discard video optional keep for debug)
  - mark timing, run again, save video, set timed_s, status done
  - on error: status failed, error message, continue
  - save_suite after every state change (progressive UI)
- after speed phase: base_config = pick_fastest; rebuild quality+scale runs from base if not yet populated
- never enable clean VRAM (workflow.apply_config omits it)
"""
```

Concrete structure:

```python
from __future__ import annotations

import traceback
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from bench import store
from bench.comfy import ComfyClient, ComfyError
from bench.constants import WORKFLOW_PATH
from bench.matrix import build_quality_runs, build_scale_runs, build_speed_runs, pick_fastest
from bench.models import Run, Suite, empty_suite
from bench.workflow import apply_config, load_ui_workflow


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BenchmarkRunner:
    def __init__(
        self,
        comfy: ComfyClient,
        workflow_path: Path = WORKFLOW_PATH,
        resume: bool = False,
        retry_failed: bool = False,
        on_update: Callable[[Suite], None] | None = None,
    ):
        self.comfy = comfy
        self.workflow_path = workflow_path
        self.resume = resume
        self.retry_failed = retry_failed
        self.on_update = on_update
        self.ui = load_ui_workflow(workflow_path)

    def _emit(self, suite: Suite) -> None:
        store.save_suite(suite)
        if self.on_update:
            self.on_update(suite)

    def init_suite(self, existing: Suite | None = None) -> Suite:
        if existing and self.resume:
            suite = existing
            suite.status = "running"
            # ensure speed runs exist
            if not suite.phases["speed"].runs:
                suite.phases["speed"].runs = build_speed_runs()
            self._emit(suite)
            return suite
        suite = empty_suite(str(uuid4())[:8], self.comfy.base_url)
        suite.status = "running"
        suite.started_at = _now()
        suite.phases["speed"].runs = build_speed_runs()
        suite.phases["speed"].status = "pending"
        suite.phases["quality"].status = "pending"
        suite.phases["scale"].status = "pending"
        self._emit(suite)
        return suite

    def _should_skip(self, run: Run) -> bool:
        if run.status == "done" and self.resume:
            return True
        if run.status == "failed" and self.resume and not self.retry_failed:
            return True
        return False

    def _execute_cell(self, suite: Suite, phase: str, run: Run) -> None:
        suite.current = {"phase": phase, "run_id": run.id, "stage": "warmup"}
        run.status = "warmup"
        run.started_at = _now()
        run.error = None
        self._emit(suite)

        prompt = apply_config(self.ui, run.config)
        try:
            pid, warm_s, _hist = self.comfy.run_prompt(prompt)
            run.warmup_s = warm_s
            run.prompt_id = pid
        except Exception as e:
            run.status = "failed"
            run.error = f"warmup: {e}\n{traceback.format_exc()}"
            run.finished_at = _now()
            suite.current = None
            self._emit(suite)
            return

        suite.current = {"phase": phase, "run_id": run.id, "stage": "timing"}
        run.status = "timing"
        self._emit(suite)

        try:
            pid, timed_s, hist = self.comfy.run_prompt(prompt)
            run.prompt_id = pid
            run.timed_s = timed_s
            vid = self.comfy.find_first_video(hist)
            if vid:
                fn, sub, typ = vid
                dest = store.video_dest(run.id, Path(fn).suffix or ".mp4")
                self.comfy.download_output_file(fn, sub, typ, dest)
                run.video_path = f"videos/{dest.name}"
            run.status = "done"
            run.finished_at = _now()
        except Exception as e:
            run.status = "failed"
            run.error = f"timed: {e}\n{traceback.format_exc()}"
            run.finished_at = _now()
        suite.current = None
        self._emit(suite)

    def run_phase(self, suite: Suite, phase: str) -> None:
        suite.phases[phase].status = "running"
        self._emit(suite)
        for run in suite.phases[phase].runs:
            if self._should_skip(run):
                continue
            self._execute_cell(suite, phase, run)
        suite.phases[phase].status = "done"
        self._emit(suite)

    def run_all(self, suite: Suite | None = None) -> Suite:
        suite = self.init_suite(suite)
        # Phase 1
        self.run_phase(suite, "speed")
        base = pick_fastest(suite.phases["speed"].runs)
        if base is None:
            suite.status = "completed"
            suite.base_config = None
            self._emit(suite)
            return suite
        suite.base_config = base.to_dict()
        self._emit(suite)

        # Phase 2 — populate if empty or not resume with existing
        if not suite.phases["quality"].runs:
            suite.phases["quality"].runs = build_quality_runs(base)
        self.run_phase(suite, "quality")

        # Phase 3
        if not suite.phases["scale"].runs:
            suite.phases["scale"].runs = build_scale_runs(base)
        self.run_phase(suite, "scale")

        suite.status = "completed"
        suite.current = None
        self._emit(suite)
        return suite
```

- [ ] **Step 2: Test with fake comfy**

```python
# tests/test_runner.py
from bench.models import RunConfig
from bench.runner import BenchmarkRunner
from bench import store


class FakeComfy:
    base_url = "http://fake"
    def __init__(self):
        self.n = 0
    def run_prompt(self, prompt):
        self.n += 1
        return f"p{self.n}", 1.5 + self.n * 0.01, {"outputs": {"110": {"gifs": [{"filename": "t.mp4", "subfolder": "", "type": "output"}]}}}
    def find_first_video(self, hist):
        return "t.mp4", "", "output"
    def download_output_file(self, fn, sub, typ, dest):
        dest.write_bytes(b"fake")
        return dest


def test_runner_speed_then_base(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(store, "BENCHMARK_JSON", tmp_path / "benchmark.json")
    monkeypatch.setattr(store, "VIDEOS_DIR", tmp_path / "videos")
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")
    # shrink matrix for test
    from bench import matrix
    monkeypatch.setattr(matrix, "build_speed_runs", lambda: [
        __import__("bench.models", fromlist=["Run"]).Run(id="s1", phase="speed", config=RunConfig(cache="none")),
        __import__("bench.models", fromlist=["Run"]).Run(id="s2", phase="speed", config=RunConfig(cache="easy")),
    ])
    monkeypatch.setattr(matrix, "build_quality_runs", lambda base: [])
    monkeypatch.setattr(matrix, "build_scale_runs", lambda base: [])
    # stub apply_config
    monkeypatch.setattr("bench.runner.apply_config", lambda ui, cfg: {"1": {}})
    monkeypatch.setattr("bench.runner.load_ui_workflow", lambda p: {})

    r = BenchmarkRunner(FakeComfy())
    # only run speed phase pieces
    suite = r.init_suite()
    r.run_phase(suite, "speed")
    assert all(x.status == "done" for x in suite.phases["speed"].runs)
    assert suite.phases["speed"].runs[0].timed_s is not None
```

Wire `pick_fastest` after speed in a small integration assertion.

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_runner.py -v
```

- [ ] **Step 4: Commit**

```bash
git add bench/runner.py tests/test_runner.py
git commit -m "feat: benchmark runner with per-cell warmup and timed runs"
```

---

### Task 7: HTTP server for progressive UI

**Files:**
- Create: `bench/server.py`
- Create: `tests/test_server.py`

- [ ] **Step 1: Implement threaded server**

```python
# bench/server.py
from __future__ import annotations

import json
import mimetypes
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from bench.constants import BENCHMARK_JSON, RESULTS_DIR, UI_DIR


class BenchHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def log_message(self, fmt, *args):
        pass  # quieter; optional write to suite.log

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/results":
            return self._send_results()
        if path.startswith("/results/"):
            return self._send_file(RESULTS_DIR / unquote(path[len("/results/"):]))
        if path.startswith("/videos/"):
            return self._send_file(RESULTS_DIR / "videos" / unquote(path[len("/videos/"):]))
        if path == "/" or path == "":
            self.path = "/index.html"
        return super().do_GET()

    def _send_results(self):
        if not BENCHMARK_JSON.exists():
            body = json.dumps({"status": "idle", "phases": {}}).encode()
        else:
            body = BENCHMARK_JSON.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path):
        path = path.resolve()
        root = RESULTS_DIR.resolve()
        if not str(path).startswith(str(root)) or not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start_server(port: int = 8787) -> ThreadingHTTPServer:
    UI_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), BenchHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd
```

- [ ] **Step 2: Test `/api/results`**

```python
# tests/test_server.py
import json
import urllib.request

from bench import store
from bench.models import empty_suite
from bench.server import start_server


def test_api_results(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(store, "BENCHMARK_JSON", tmp_path / "benchmark.json")
    monkeypatch.setattr("bench.server.BENCHMARK_JSON", tmp_path / "benchmark.json")
    monkeypatch.setattr("bench.server.RESULTS_DIR", tmp_path)
    store.ensure_dirs()
    s = empty_suite("x", "http://127.0.0.1:8188")
    store.save_suite(s)
    httpd = start_server(9876)
    try:
        data = json.load(urllib.request.urlopen("http://127.0.0.1:9876/api/results"))
        assert data["suite_id"] == "x"
    finally:
        httpd.shutdown()
```

- [ ] **Step 3: Commit**

```bash
git add bench/server.py tests/test_server.py
git commit -m "feat: progressive results HTTP server"
```

---

### Task 8: Web UI (heatmap, tables, gallery, live poll)

**Files:**
- Create: `ui/index.html`
- Create: `ui/styles.css`
- Create: `ui/app.js`

- [ ] **Step 1: HTML shell**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>H3 Benchmark</title>
  <link rel="stylesheet" href="/styles.css" />
</head>
<body>
  <header class="top">
    <div>
      <h1>MiniMax H3 Benchmark</h1>
      <p id="status-line" class="muted">Loading…</p>
    </div>
    <div id="fastest" class="stat"></div>
  </header>
  <main>
    <section>
      <h2>Phase 1 — Speed</h2>
      <div id="speed-heatmap" class="table-wrap"></div>
    </section>
    <section>
      <h2>Phase 2 — Quality</h2>
      <div id="quality-table" class="table-wrap"></div>
    </section>
    <section>
      <h2>Phase 3 — MP × Duration</h2>
      <div id="scale-table" class="table-wrap"></div>
    </section>
    <section>
      <h2>Gallery</h2>
      <div id="gallery" class="gallery"></div>
    </section>
  </main>
  <dialog id="detail">
    <form method="dialog"><button class="close">Close</button></form>
    <div id="detail-body"></div>
  </dialog>
  <script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: CSS — dark technical bench aesthetic**

Dense monospace data tables, amber highlight for best cell, status chips (`queued`/`warmup`/`timing`/`done`/`failed`). Avoid generic purple AI gradient. Background `#0e1116`, text `#e7ecf3`, accent `#f0a202`.

- [ ] **Step 3: `app.js` poll + render**

```javascript
const POLL_MS = 1500;

async function fetchResults() {
  const r = await fetch("/api/results", { cache: "no-store" });
  if (!r.ok) throw new Error("api failed");
  return r.json();
}

function fmtSec(s) {
  if (s == null) return "—";
  return `${Number(s).toFixed(1)}s`;
}

function renderStatus(data) {
  const el = document.getElementById("status-line");
  const cur = data.current;
  const curText = cur ? `${cur.phase} / ${cur.run_id} / ${cur.stage}` : "idle";
  el.textContent = `suite=${data.status || "?"} · ${curText} · updated ${data.updated_at || ""}`;
  const best = findFastest(data.phases?.speed?.runs || []);
  document.getElementById("fastest").textContent = best
    ? `Fastest: ${fmtSec(best.timed_s)} (${best.id})`
    : "";
}

function findFastest(runs) {
  return runs.filter(r => r.status === "done" && r.timed_s != null)
    .sort((a, b) => a.timed_s - b.timed_s)[0];
}

function renderSpeedHeatmap(runs) {
  // pivot core-like rows by cache(+variant) and columns quant|sol
  // show timed_s or status
}

function renderQuality(runs) { /* table */ }
function renderScale(runs) { /* table mp x duration */ }
function renderGallery(allRuns) {
  const done = allRuns.filter(r => r.video_path).sort((a, b) => (b.finished_at || "").localeCompare(a.finished_at || ""));
  const g = document.getElementById("gallery");
  g.innerHTML = done.map(r => `
    <article class="card">
      <video src="/${r.video_path}" controls preload="metadata"></video>
      <div class="meta"><strong>${r.id}</strong><br>${fmtSec(r.timed_s)} · ${r.config?.cache} · ${r.config?.quant}</div>
    </article>`).join("");
}

async function tick() {
  try {
    const data = await fetchResults();
    renderStatus(data);
    const speed = data.phases?.speed?.runs || [];
    const quality = data.phases?.quality?.runs || [];
    const scale = data.phases?.scale?.runs || [];
    renderSpeedHeatmap(speed);
    renderQuality(quality);
    renderScale(scale);
    renderGallery([...speed, ...quality, ...scale]);
  } catch (e) {
    document.getElementById("status-line").textContent = `Waiting for results… (${e.message})`;
  }
}

tick();
setInterval(tick, POLL_MS);
```

Flesh out heatmap: columns `nvfp4|sol_on`, `nvfp4|sol_off`, `int8|sol_on`, `int8|sol_off`; rows for each cache and variant label. Click cell opens `<dialog>` with full config JSON + video.

- [ ] **Step 4: Manual check**

Create a dummy `results/benchmark.json` with one `done` run and `ui-only` serve; open browser.

- [ ] **Step 5: Commit**

```bash
git add ui
git commit -m "feat: progressive benchmark results UI"
```

---

### Task 9: CLI entrypoint

**Files:**
- Create: `benchmark_runner.py`
- Create: `README.md` (short usage only)

- [ ] **Step 1: Implement CLI**

```python
#!/usr/bin/env python3
"""MiniMax H3 ComfyUI benchmark runner + progressive results UI."""
from __future__ import annotations

import argparse
import sys
import time

from bench.comfy import ComfyClient, ComfyError
from bench.constants import DEFAULT_COMFY_URL, DEFAULT_UI_PORT
from bench.runner import BenchmarkRunner
from bench.server import start_server
from bench import store


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="H3 ComfyUI benchmark suite")
    p.add_argument("--comfy-url", default=DEFAULT_COMFY_URL)
    p.add_argument("--port", type=int, default=DEFAULT_UI_PORT)
    p.add_argument("--ui-only", action="store_true")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--retry-failed", action="store_true")
    args = p.parse_args(argv)

    store.ensure_dirs()
    httpd = start_server(args.port)
    print(f"Results UI: http://127.0.0.1:{args.port}/")

    if args.ui_only:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            httpd.shutdown()
            return 0

    client = ComfyClient(args.comfy_url)
    try:
        client.system_stats()
    except ComfyError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        httpd.shutdown()
        return 1

    existing = store.try_load_suite() if args.resume else None
    runner = BenchmarkRunner(
        client,
        resume=args.resume,
        retry_failed=args.retry_failed,
    )
    try:
        runner.run_all(existing)
    except KeyboardInterrupt:
        suite = store.try_load_suite()
        if suite:
            suite.status = "aborted"
            store.save_suite(suite)
        print("Aborted.")
    finally:
        print(f"Suite finished. UI still at http://127.0.0.1:{args.port}/ (Ctrl+C to exit)")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: README usage**

```markdown
# MiniMax H3 Benchmark

## Run suite + live UI

```bash
python benchmark_runner.py
```

Open http://127.0.0.1:8787/

## UI only / resume

```bash
python benchmark_runner.py --ui-only
python benchmark_runner.py --resume
```

Requires ComfyUI at http://127.0.0.1:8188 with the MiniMax H3 workflow models installed.
```

- [ ] **Step 3: Commit**

```bash
git add benchmark_runner.py README.md
git commit -m "feat: CLI entrypoint for benchmark suite"
```

---

### Task 10: End-to-end dry validation against live ComfyUI

**Files:**
- Possibly fix `bench/workflow.py` widget names after live probe

- [ ] **Step 1: Probe object_info and fix any widget key mismatches**

Run the object_info script from Task 3; update setters.

- [ ] **Step 2: Single-cell smoke (optional env flag)**

Add temporary one-off:

```bash
python -c "
from bench.comfy import ComfyClient
from bench.workflow import load_ui_workflow, apply_config
from bench.models import RunConfig
from bench.constants import WORKFLOW_PATH
ui=load_ui_workflow(WORKFLOW_PATH)
api=apply_config(ui, RunConfig(cache='none', quant='nvfp4', sol_attn=True, steps=16, duration_s=4, mp=0.4))
c=ComfyClient()
print('nodes', len(api))
# Uncomment to actually run (long):
# print(c.run_prompt(api)[1])
"
```

Validate `/prompt` accepts graph (if validation error, fix graph until queue accepts). **Do not** require full suite in this task — only that Comfy accepts one mutated prompt.

- [ ] **Step 3: Run full unit suite**

```bash
pytest -v
```

Expected: all PASS

- [ ] **Step 4: Commit fixes**

```bash
git add -A
git commit -m "fix: align workflow mutation with live ComfyUI node schemas"
```

- [ ] **Step 5: Start the real suite when ready**

```bash
python benchmark_runner.py
```

Open UI; confirm first cell moves warmup → timing → done with video and heatmap update without waiting for suite end.

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Progressive results UI | 7, 8, 9 |
| Comfy local API | 5, 9 |
| Fixed seed, no VRAM clean, no RIFE/upscale | 3, 6 |
| Discard first gen per cell | 6 |
| Cache none/spectrum/easy/h3 exclusive | 3, 4 |
| nvfp4 vs int8, sol on/off | 3, 4 |
| Tuned variants | 4 |
| base_config = fastest Phase 1 | 4 (`pick_fastest`), 6 |
| Phase 2 one-factor quality | 4, 6 |
| Phase 3 MP×duration grid | 4, 6 |
| Timestamp-free prompt | 1 (constant), 3 |
| Resume / retry-failed / ui-only | 6, 9 |
| Atomic benchmark.json | 2 |

## Placeholder / consistency notes

- Widget input names must match live `object_info` — Task 3 + Task 10 explicitly fix them.
- API graph uses **omit + rewire** for bypass (not UI `mode` flags alone).
- Video URL in UI is `/{video_path}` with `video_path` like `videos/foo.mp4` served by Task 7.
- Phase 3 resets scheduler/sampler/steps to Phase-1 defaults per spec.
