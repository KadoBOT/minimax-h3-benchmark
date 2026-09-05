# De-rope Final-Pass Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans and execute every task inline. Do not delegate.

**Goal:** Make a de-rope final pass preserve timed guides and inherit every
applicable Studio sampling setting instead of replacing a high-quality primary
pass with an unrelated four-step generation.

**Architecture:** Keep guide-time knowledge in `minimax-h3-studio` by extending
`MiniMaxH3AnchorGuides` with an optional hold map. Persist the sampling lineage
in the unified workflow: the de-rope branch receives Studio's seed, scheduler,
effective steps, active sampler configuration, and guide-aware conditioning.
The benchmark remains a consumer of that workflow and tests the flattened
executable prompt.

**Tech Stack:** Python 3.12, ComfyUI v3 node schema, LiteGraph workflow JSON,
pytest, h3-bench's workflow flattener, live ComfyUI HTTP/WebSocket execution.

## Global Constraints

- De-rope remains opt-in; its disabled image path must not change.
- De-rope injection is `0.50`.
- Explicit guide frames take precedence over `time * 24`.
- A remapped guide targets the first held copy, which `H3ExactRecover` retains.
- Existing `MiniMaxH3AnchorGuides` callers without a hold map are unchanged.
- The final pass inherits seed, scheduler, effective steps, sampler selection,
  and all ER-SDE parameters.
- Benchmark step metrics continue to describe the primary configured schedule.
- Do not add dependencies.
- Do not commit unless the user explicitly asks.

---

### Task 1: Define executable acceptance gates

**Files:**
- Modify: `/home/kadobot/Projects/minimax-h3-benchmark/GATES.md`

**Interfaces:**
- Consumes: the existing G0-G13 parity ledger.
- Produces: G14-G18 checks for diagnosis, guide remapping, workflow lineage,
  regressions, and live pass-1/final comparison.

- [ ] **Step 1: Add gates before implementation**

Add gates whose checks invoke the focused stack tests, focused benchmark parity
test, both full suites, workflow-copy comparison, and the live verification
script. Evidence starts as `pending`.

- [ ] **Step 2: Lint the ledger**

Run:

```bash
node /home/kadobot/.agents/skills/unlazy/scripts/gate-lint.mjs GATES.md
```

Expected: `LINT OK`.

---

### Task 2: Remap Studio guides onto a held clock

**Files:**
- Create:
  `/home/kadobot/Projects/comfyui-minimax-h3-stack/custom_nodes/minimax-h3-studio/guide_mapping.py`
- Modify:
  `/home/kadobot/Projects/comfyui-minimax-h3-stack/custom_nodes/minimax-h3-studio/nodes.py`
- Create:
  `/home/kadobot/Projects/comfyui-minimax-h3-stack/tests/test_guide_mapping.py`

**Interfaces:**
- Produces:
  `guide_frame(frame_idx: int, target_length: int, hold_map: str = "") -> int`.
- `MiniMaxH3AnchorGuides.execute(...)` gains optional
  `hold_map: str = ""`.

- [ ] **Step 1: Write failing guide-remapping tests**

Cover:

```python
def test_without_a_hold_map_clamps_on_the_target_clock():
    assert guide_frame(99, 20) == 19


def test_hold_map_targets_the_first_copy_retained_by_exact_recover():
    hold_map = '{"world_len":4,"holds":[1,3,2,1]}'
    assert guide_frame(0, 7, hold_map) == 0
    assert guide_frame(1, 7, hold_map) == 1
    assert guide_frame(2, 7, hold_map) == 4
    assert guide_frame(3, 7, hold_map) == 6


def test_hold_map_clamps_against_world_length_before_remapping():
    assert guide_frame(99, 7, '{"world_len":4,"holds":[1,3,2,1]}') == 6


def test_malformed_hold_map_fails_with_remapping_context():
    with pytest.raises(ValueError, match="guide hold map"):
        guide_frame(1, 7, '{"holds":[1,0]}')
```

- [ ] **Step 2: Run the tests and observe the expected failure**

Run:

```bash
/home/kadobot/Projects/minimax-h3-benchmark/.venv/bin/python -m pytest tests/test_guide_mapping.py -q
```

Working directory:
`/home/kadobot/Projects/comfyui-minimax-h3-stack`.

Expected: failure because `guide_mapping.py` does not exist.

- [ ] **Step 3: Implement the pure remapper**

Parse the optional map once per call, require positive integer holds, require
`world_len == len(holds)` and `sum(holds) == target_length`, clamp the original
frame to `[0, world_len - 1]`, and return `sum(holds[:frame_idx])`. Without a
map, retain the existing target-length clamp.

- [ ] **Step 4: Extend guide anchoring**

Add an optional force-input string socket at the end of
`MiniMaxH3AnchorGuides`:

```python
io.String.Input("hold_map", default="", optional=True, force_input=True)
```

Pass each explicit or time-derived original frame through `guide_frame` before
calling `MiniMaxH3AddGuide`. Preserve the current precedence of `frame` over
`time`.

- [ ] **Step 5: Run the focused stack tests**

Run:

```bash
/home/kadobot/Projects/minimax-h3-benchmark/.venv/bin/python -m pytest tests/test_guide_mapping.py tests/test_studio_ui.py -q
```

Expected: all pass.

---

### Task 3: Persist complete de-rope sampling lineage

**Files:**
- Modify:
  `/home/kadobot/Projects/comfyui-minimax-h3-stack/tests/test_workflow.py`
- Modify:
  `/home/kadobot/Projects/comfyui-minimax-h3-stack/workflows/minimax_h3_unified_guided_dual.json`

**Interfaces:**
- Consumes: Engine inputs `steps`, `noise_seed`, `scheduler`, `sampler_name`,
  `positive_refs_only`, `guides`, `length`, `er_sde`, and its four ER-SDE
  parameter inputs.
- Produces: one guide-aware conditioning path and one Studio-driven sampler
  selector for Engine's de-rope sampler.

- [ ] **Step 1: Write failing structural workflow tests**

Resolve every input through the Engine level's links and assert:

- `H3InjectSchedule.scheduler` comes from Engine `scheduler`.
- `H3InjectSchedule.total_steps` comes from Engine `steps`.
- `H3InjectSchedule.inject == 0.50`.
- de-rope `RandomNoise.noise_seed` comes from Engine `noise_seed`.
- a `MiniMaxH3AnchorGuides` node consumes Engine `positive_refs_only`, Engine
  `guides`, `VAEEncode`'s smeared latent, `H3TimeSmear`'s length and hold map,
  and both VAEs.
- de-rope `BasicGuider.conditioning` consumes that anchor node.
- a `ComfySwitchNode` selects Engine's ordinary sampler or a parameterized
  `SamplerER_SDE`, and de-rope `SamplerCustomAdvanced.sampler` consumes it.
- all four `SamplerER_SDE` inputs and the switch flag come from the matching
  Engine inputs.

- [ ] **Step 2: Run the structural tests and observe failure**

Run:

```bash
/home/kadobot/Projects/minimax-h3-benchmark/.venv/bin/python -m pytest tests/test_workflow.py -q
```

Expected: the new final-pass parity test fails on the fixed beta/6/0.70
schedule, references-only guider, and generic sampler.

- [ ] **Step 3: Patch the Engine graph**

Use existing nodes in the Sampler and Latent Upscaler subgraphs as JSON shape
references:

- add `MiniMaxH3AnchorGuides` after smeared `VAEEncode`;
- link its optional `hold_map` to `H3TimeSmear.hold_map_used`;
- route its conditioning output into de-rope `BasicGuider`;
- link schedule, total steps, and seed to Engine inputs;
- set injection to `0.50`;
- replace the generic `KSamplerSelect("er_sde")` path with an ordinary
  `KSamplerSelect`, parameterized `SamplerER_SDE`, and `ComfySwitchNode` driven
  by Engine inputs.

Keep node ids, link ids, slot declarations, `widgets_values`, and
`widgets_values_named` internally consistent.

- [ ] **Step 4: Run the structural tests**

Run the Task 3 Step 2 command.

Expected: all pass.

---

### Task 4: Prove flattened h3-bench execution parity

**Files:**
- Modify:
  `/home/kadobot/Projects/minimax-h3-benchmark/tests/test_execution_parity.py`
- Modify:
  `/home/kadobot/Projects/minimax-h3-benchmark/minimax_h3_unified_guided_dual.json`
- Update installed copy:
  `/home/kadobot/ComfyUI/user/default/workflows/minimax_h3_unified_guided_dual.json`

**Interfaces:**
- Consumes: the canonical stack workflow from Task 3.
- Produces: semantically identical active workflow copies and executable-prompt
  assertions.

- [ ] **Step 1: Add a failing executable-prompt test**

Prepare a de-rope config with non-default values:

```python
config = _config(
    steps=28,
    seed=123,
    scheduler="beta57",
    sampler="euler",
    widgets={
        "derope": True,
        "guides": '[{"time":1.0,"image":"guide.png"}]',
        "er_sde": True,
        "er_sde_solver": "ODE",
        "er_sde_max_stage": 2,
        "er_sde_eta": 0.25,
        "er_sde_s_noise": 0.75,
    },
)
```

Assert the flattened final-pass schedule, noise, guide anchor, sampler switch,
and ER-SDE nodes link to the correct `MiniMaxH3Studio` output slots and contain
injection `0.50`.

- [ ] **Step 2: Run the focused test and observe failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_execution_parity.py -k derope -q
```

Expected: failure against the old workflow.

- [ ] **Step 3: Copy canonical workflow semantics**

Serialize the Task 3 canonical workflow into the benchmark and installed paths.
Do not overwrite unrelated files. Confirm all three JSON objects compare equal
after parsing.

- [ ] **Step 4: Run focused parity tests**

Run the Task 4 Step 2 command.

Expected: all de-rope parity tests pass and `missing_links(prompt) == []`.

---

### Task 5: Add a repeatable live run-27 comparison

**Files:**
- Create:
  `/home/kadobot/Projects/minimax-h3-benchmark/scripts/verify_run27_derope.py`

**Interfaces:**
- Consumes: run 27's persisted `GenerationConfig`, the current unified
  workflow, and live ComfyUI.
- Produces: one prompt with two video outputs, `run27-pass1.mp4` and
  `run27-derope.mp4`, plus `RUN27_DEROPE_PARITY_OK`.

- [ ] **Step 1: Write the verification script**

The script must:

1. load run 27 from `RunRepository`;
2. build its current prompt through `prepare_prompt`;
3. assert the final `H3InjectSchedule` inherits Studio slots 6 and 8 and uses
   injection `0.50`;
4. find the primary `VAEDecode` that feeds `H3TimeSmear`;
5. clone the final `VHS_VideoCombine`, point the clone at primary decoded
   images, and give both outputs unique verification prefixes;
6. submit once to ComfyUI so both videos share the exact primary pass;
7. download both outputs and generate filmstrips;
8. assert both contain 124 frames at 960x544 and print the success token.

- [ ] **Step 2: Syntax-check without using the GPU**

Run:

```bash
.venv/bin/python -m py_compile scripts/verify_run27_derope.py
```

Expected: exit 0.

- [ ] **Step 3: Pause h3-bench safely and restart ComfyUI**

Pause the benchmark queue, allow the currently running prompt to finish, then
restart ComfyUI so the extended node schema is loaded. Do not interrupt an
active unaffected run.

- [ ] **Step 4: Run the live comparison**

Run:

```bash
.venv/bin/python scripts/verify_run27_derope.py
```

Expected: `RUN27_DEROPE_PARITY_OK`.

- [ ] **Step 5: Inspect the paired filmstrips**

Confirm the prompt applies all seven guide entries, including the two
out-of-range entries clamped to the final frame. Confirm the five in-range shot
anchors remain recognizable in the final strip and that the final is a de-rope
refinement of the same primary scene, not an unrelated generation. Record the
paths and observations in `GATES.md`.

- [ ] **Step 6: Resume the benchmark queue**

Resume only after ComfyUI health and the live result are confirmed.

---

### Task 6: Regressions and evidence

**Files:**
- Modify: `/home/kadobot/Projects/minimax-h3-benchmark/GATES.md`

- [ ] **Step 1: Run the complete stack suite**

```bash
/home/kadobot/Projects/minimax-h3-benchmark/.venv/bin/python -m pytest tests -q
```

Working directory:
`/home/kadobot/Projects/comfyui-minimax-h3-stack`.

Expected: all pass.

- [ ] **Step 2: Run the complete h3-bench suite**

```bash
.venv/bin/python -m pytest tests -q
```

Expected: all pass.

- [ ] **Step 3: Run lint and JSON checks**

Run the repository's existing Ruff and frontend checks for touched Python/UI
surfaces, then parse all three workflow copies with Python.

Expected: exit 0 with no new diagnostics.

- [ ] **Step 4: Record gate evidence**

Replace every new `pending` evidence entry with measured command output,
test counts, prompt lineage, and live artifact paths. Re-run gate lint.

- [ ] **Step 5: Re-read the request and diff**

Confirm the four affected queued runs remain cancelled, no unrelated queued
runs were changed, no default-off route changed, and no user-owned uncommitted
work was overwritten.
