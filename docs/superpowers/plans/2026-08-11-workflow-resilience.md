# Workflow Resilience and the Turbo LoRA Axis — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:executing-plans` to implement this
> plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking. This repository's user rule
> forbids delegating to subagents, so execution is inline.

**Goal:** Make the ComfyUI layer read the workflow instead of remembering it, so editing a template
cannot break the lab, and make the Turbo LoRA a settable, sweepable benchmark axis.

**Architecture:** Four modules with one job each — `workflow.py` (read and flatten), `schema.py`
(what the installed nodes declare), `roles.py` (what the lab names), `graph.py` (thin the live set
and write the config) — plus `editor.py` projecting the result back to a flat editor graph.

**Tech Stack:** Python 3.14, pydantic v2, FastAPI, SQLite; React 19 + TypeScript + Tailwind v4 +
Base UI on the front end; pytest and vitest; a live ComfyUI 0.31.0 (frontend 1.48.7) on
`127.0.0.1:8188` for schemas and for real generations.

## Global Constraints

- Node ids in a prompt use ComfyUI's own execution scheme: `[...instancePath, localId].join(":")`.
- No module may hold a copy of a template's structure. Ids in `nodes.py` survive only as the last
  fallback of role resolution, never as a lookup.
- `domain/` keeps knowing nothing about ComfyUI; `workflow.py` and `schema.py` know nothing about
  `GenerationConfig`; `roles.py` does no I/O.
- `editor.py` stays a projection of `apply_config`'s output. It never re-implements a wiring rule.
- Every widget the lab writes is written by name, and only if the node declares that name.
- Two new hashed config fields require migration `v3`; the arena's exhaustive partition assertion
  must pass without being widened.
- TDD: each task opens with a failing test at a public seam; the red output goes in the ledger.
- Commit after each task.

---

### Task 1: The workflow reader

**Files:**
- Create: `h3lab/comfy/workflow.py`
- Test: `tests/test_comfy_workflow.py`

**Interfaces:**
- Consumes: nothing from other tasks (takes a `widget_names: Callable[[str, dict], Sequence[str]]`
  so Task 2 can supply schemas without a cycle).
- Produces:

```python
UI_ONLY_TYPES: frozenset[str]          # Note, MarkdownNote, rgthree bypassers, Reroute

@dataclass(slots=True)
class Node:
    id: str                    # "1" or "169:1"
    class_type: str
    title: str
    mode: int                  # 0 active, 2 muted, 4 bypassed
    inputs: dict[str, Any]     # name -> [source_id, slot] | literal
    input_types: dict[str, str]
    output_types: tuple[str, ...]
    path: tuple[int, ...]      # subgraph instance chain
    local_id: int
    source: dict[str, Any]     # the template's node dict, not copied

@dataclass(slots=True)
class Graph:
    nodes: dict[str, Node]     # insertion order == template reading order
    def prompt(self) -> dict[str, dict[str, Any]]
    def consumers(self, node_id: str) -> list[tuple[str, str]]     # (consumer id, input name)

def read(workflow: dict[str, Any], *, widget_names=...) -> Graph
def to_api_prompt(workflow: dict[str, Any], *, widget_names=...) -> Prompt   # read(...).prompt()
```

- [x] **Step 1: Write the failing tests** in `tests/test_comfy_workflow.py`:
  `test_a_subgraph_instance_flattens_to_execution_ids` (hand-built: one instance `9` holding node
  `1`, expect id `"9:1"`), `test_a_promoted_widget_reaches_the_inner_node`,
  `test_a_boundary_link_resolves_to_the_outer_source`, `test_object_shaped_links_are_read`,
  `test_the_real_templates_expose_their_pipeline` (all three: ≥ 45 nodes, a `UNETLoader`, a
  `MiniMaxH3*ToVideo`, a `VHS_VideoCombine`), `test_bypassed_nodes_are_read_with_their_mode`
  (`MiniMaxH3TurboLoRA` has `mode == 4`).
- [x] **Step 2: Run and watch them fail** — `python -m pytest tests/test_comfy_workflow.py -q`,
  expected `ModuleNotFoundError: No module named 'h3lab.comfy.workflow'`.
- [x] **Step 3: Implement.** Read `nodes`, both link shapes, `definitions.subgraphs`. Algorithm:

```python
def _read_graph(nodes, links, *, path, defs, boundary_inputs, out) -> dict[int, tuple[str, int]]:
    # links: {link_id: (origin_id, origin_slot, target_id, target_slot, type)}
    # boundary_inputs: {slot_index: value_or_link} supplied by the caller for inputNode links
    # returns {output_slot: (flat_id, slot)} for links into the subgraph's outputNode
```

  For each node: if `type` is a subgraph definition id, build that definition's `boundary_inputs`
  from the instance's own resolved inputs (link → resolved source; widget-promoted → the positional
  `widgets_values` entry) and recurse with `path + (local_id,)`; record the returned output map so
  consumers of the instance's slots re-point at the inner producer. Otherwise emit a `Node`, folding
  `widgets_values` in with `widget_names(class_type, node)` (dict-shaped values by key, minus
  `videopreview`), links winning over widget values.
- [x] **Step 4: Run the tests** — all green.
- [x] **Step 5: Commit** — `feat(comfy): read subgraph workflows into flat execution ids`.

---

### Task 2: Node schemas from the installed nodes

**Files:**
- Create: `h3lab/comfy/schema.py`
- Modify: `h3lab/comfy/nodes.py` (keep `WIDGET_ORDER` as the offline fallback, drop nothing yet)
- Test: `tests/test_comfy_schema.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class NodeSchema:
    class_type: str
    widgets: tuple[str, ...]
    required: tuple[str, ...]
    optional: tuple[str, ...]
    types: dict[str, str]
    output_node: bool

class Schemas:
    def __init__(self, client: ComfyClient | None = None, *, object_info: dict | None = None)
    def get(self, class_type: str) -> NodeSchema | None
    def widget_names(self, class_type: str, node: dict[str, Any] | None = None) -> tuple[str, ...]
    def problems(self, prompt: Prompt) -> list[str]
    @property
    def source(self) -> str            # "comfy" | "offline"

def static_schemas() -> Schemas        # no I/O; the fallback table only
```

- [x] **Step 1: Write the failing tests.** `test_a_dynamic_combo_expands_for_the_selected_option`
  (feed an `/object_info` payload shaped like the live `RTXVideoSuperResolution`, assert
  `widget_names(...) == ("resize_type", "scale", "quality")` for the value `"scale by multiplier"`),
  `test_link_only_inputs_are_not_widgets`, `test_an_unknown_class_falls_back_to_the_nodes_own_inputs`,
  `test_offline_falls_back_to_the_static_table`, `test_problems_names_a_missing_required_input`,
  `test_problems_names_an_unknown_class`.
- [x] **Step 2: Run and watch them fail** (`ModuleNotFoundError`).
- [x] **Step 3: Implement.** One `GET /object_info` for the whole catalogue, cached on the instance.
  Widget rule: walk `input_order.required + input_order.optional`; skip inputs whose spec type is a
  bare link type (an upper-case string that is not `INT/FLOAT/STRING/BOOLEAN/COMBO` and is not a
  list); after a `COMFY_DYNAMICCOMBO_V3` input, append the nested `required` inputs of the option
  whose `key` equals the node's current value for that input.
- [x] **Step 4: Run the tests** — green.
- [x] **Step 5: Commit** — `feat(comfy): take widget order from the installed nodes`.

---

### Task 3: Roles

**Files:**
- Create: `h3lab/comfy/roles.py`
- Test: `tests/test_comfy_roles.py`

**Interfaces:**

```python
class Role(str, Enum):
    DIFFUSION_LOADER, GGUF_LOADER, CLIP, GGUF_CLIP, VIDEO_VAE, AUDIO_VAE, CONDITIONING,
    RESOLUTION, DURATION, SCHEDULER, SAMPLER_SELECT, GUIDER, SAMPLER, NOISE, SIGMA_SHIFT,
    TURBO_LORA, SOL_ATTN, CACHE_SPECTRUM, CACHE_EASY, CACHE_H3, DECODE, DECODE_AUDIO,
    RIFE, FILM, FILM_LOADER, UPSCALER, VIDEO_OUT, SAVE_IMAGE, SAVE_AUDIO,
    CLEAN_VRAM, CLEAN_TEXT_ENCODER

@dataclass(frozen=True, slots=True)
class Resolved:
    role: Role
    node_id: str
    rule: str                  # "title" | "class" | "edge" | "legacy id"

class Roles:
    def id(self, role: Role) -> str | None
    def ids(self, role: Role) -> tuple[str, ...]
    def role_of(self, node_id: str) -> Role | None
    def missing(self) -> tuple[Role, ...]
    def report(self) -> list[dict[str, str]]

def resolve(graph: Graph) -> Roles
CACHE_ROLES: dict[str, Role]    # "spectrum"/"easy"/"h3" -> Role
```

- [x] **Step 1: Write the failing tests.** `test_every_role_resolves_on_the_real_templates`
  (parametrised over the three; assert `missing()` holds only the roles a mode legitimately lacks),
  `test_the_two_vae_loaders_are_told_apart_by_the_slot_they_feed`,
  `test_a_title_tag_wins_over_the_class_rule`, `test_a_renumbered_node_still_resolves`
  (rewrite a template's ids in memory, assert the same roles resolve),
  `test_the_report_names_the_rule_that_matched`.
- [x] **Step 2: Run and watch them fail.**
- [x] **Step 3: Implement** the four strategies in order, recording the rule that matched.
- [x] **Step 4: Run the tests** — green.
- [x] **Step 5: Commit** — `feat(comfy): resolve node roles instead of hard-coding ids`.

---

### Task 4: Patch by thinning the live set

**Files:**
- Modify: `h3lab/comfy/graph.py` (rewrite), `h3lab/comfy/nodes.py` (reduce to fallbacks)
- Test: `tests/test_comfy_graph.py` (rewrite the id-pinned assertions)

**Interfaces:**

```python
def apply_config(workflow, config, *, output_tag="run", schemas=None) -> Prompt
def bypass(graph: Graph, node_id: str) -> None          # type-matched pass-through removal
def resolve_value(graph: Graph, node_id: str, input_name: str, default=None) -> Any
class WorkflowError(RuntimeError)
```

- [x] **Step 1: Write the failing tests.** Key new ones:
  `test_a_node_the_lab_does_not_know_survives_in_place` (the colour-grade chain is in an flf2v
  prompt and sits between the decode and the muxer), `test_removing_a_node_heals_the_chain_by_type`,
  `test_the_reference_loaders_are_found_by_the_slot_they_feed`,
  `test_a_gguf_model_without_a_gguf_loader_is_a_clear_error`,
  `test_the_frame_rate_is_read_from_the_template`, plus every existing behavioural test rewritten
  to assert by role/class.
- [x] **Step 2: Run and watch them fail** — currently 102 failures across the suite; this task's
  file is the loop.
- [x] **Step 3: Implement** the six steps from the spec's *Patching* section.
- [x] **Step 4: Run** `python -m pytest tests/test_comfy_graph.py -q` — green.
- [x] **Step 5: Commit** — `feat(comfy): patch by thinning the template's own graph`.

---

### Task 5: Flat editor projection

**Files:**
- Modify: `h3lab/comfy/editor.py`
- Test: `tests/test_comfy_editor.py`

- [x] **Step 1: Write the failing tests.** `test_the_export_reimports_as_the_prompt_it_came_from`
  (equality up to id bijection, via a `same_graph(a, b)` helper in the test file),
  `test_the_export_keeps_positions_titles_and_groups`,
  `test_subgraph_nodes_are_translated_clear_of_the_parent`,
  `test_a_node_the_run_does_not_use_is_absent`, `test_provenance_travels_in_the_extra_block`,
  `test_the_template_is_not_modified_by_being_projected`.
- [x] **Step 2: Run and watch them fail.**
- [x] **Step 3: Implement.** Walk `graph.nodes` in reading order, keep those in the prompt (plus
  notes), renumber to ints, translate by `path`, re-mint links from the prompt, copy groups
  (translated for subgraph groups), write widget values through the schema.
- [x] **Step 4: Run the tests** — green.
- [x] **Step 5: Commit** — `feat(comfy): export a run as a flat positioned editor graph`.

---

### Task 6: The Turbo LoRA becomes a setting

**Files:**
- Modify: `h3lab/domain/config.py`, `h3lab/domain/arena.py`, `h3lab/domain/insights.py`,
  `h3lab/storage/migrations.py`, `h3lab/comfy/catalog.py`, `h3lab/comfy/graph.py`,
  `h3lab/engine/runner.py` (preflight), `h3lab/engine/lab.py` (`_COMPARABLE_FIELDS`)
- Test: `tests/test_domain_config.py`, `tests/test_domain_arena.py`, `tests/test_storage.py`,
  `tests/test_comfy_graph.py`, `tests/test_engine.py`

**Interfaces:**

```python
DEFAULT_TURBO_LORA = "minimax_h3_turbo_4step_comfyui_pruned.safetensors"
def resolve_turbo_lora(name: str) -> str
def lora_stem(name: str) -> str
# GenerationConfig: turbo_lora: str = "", turbo_lora_strength: float = 1.0  (ge=-10, le=10)
# Catalog: loras, turbo_loras, loras_source, defaults["turbo_lora"]
```

- [x] **Step 1: Write the failing tests.** `test_the_turbo_lora_is_part_of_the_config_hash`,
  `test_the_arena_ranks_the_turbo_lora` (partition assertion + `contested_differences`),
  `test_a_pre_v3_row_gains_the_lora_fields_and_fresh_digests`,
  `test_the_lora_file_and_strength_reach_the_turbo_node` (by whichever strength name the node
  declares), `test_turbo_off_leaves_the_lora_node_out`,
  `test_preflight_rejects_a_lora_comfy_does_not_offer`.
- [x] **Step 2: Run and watch them fail.**
- [x] **Step 3: Implement,** migration v3 modelled on v2.
- [x] **Step 4: Run** the five test files — green.
- [x] **Step 5: Commit** — `feat: make the turbo LoRA a settable, sweepable axis`.

---

### Task 7: API, generated types, and the front end

**Files:**
- Modify: `h3lab/api/routes/lab.py`, `h3lab/comfy/catalog.py`, `web/src/api/schema.ts` (generated),
  `web/src/pages/lab/config-form.tsx`, `web/src/pages/lab/sweep-builder.tsx`,
  `web/src/lib/config.ts`, `web/src/test/harness.tsx`
- Test: `tests/test_api.py`, `tests/test_contract.py`, `web/src/pages/lab/lab.test.tsx`,
  `web/src/lib/config.test.ts`

- [x] **Step 1: Write the failing tests.** `test_the_catalog_offers_the_h3_turbo_loras`,
  a vitest `it("picks a turbo LoRA and queues it")` and
  `it("greys out the LoRA controls when turbo is off")`, and a sweep-builder test that the axis
  offers the catalog's LoRAs.
- [x] **Step 2: Run and watch them fail.**
- [x] **Step 3: Implement,** then `python scripts/gen_types.py`.
- [x] **Step 4: Run** `pytest tests/test_api.py tests/test_contract.py -q`, `npm test`,
  `npm run typecheck` — green.
- [x] **Step 5: Commit** — `feat(web): pick and sweep the turbo LoRA`.

---

### Task 8: Resilience surfaces

**Files:**
- Modify: `h3lab/engine/runner.py`, `h3lab/comfy/progress.py`, `h3lab/comfy/client.py`,
  `h3lab/cli.py`
- Test: `tests/test_engine.py`, `tests/test_comfy_progress.py`, `tests/test_cli.py`

- [x] **Step 1: Write the failing tests.** `test_a_template_edited_on_disk_is_reloaded`,
  `test_progress_labels_come_from_the_node_class`,
  `test_check_reports_the_role_each_node_plays`,
  `test_check_reports_what_object_info_says_is_wrong`.
- [x] **Step 2: Run and watch them fail.**
- [x] **Step 3: Implement:** mtime/size reload with a `lab.message` event; `ProgressTracker(labels=,
  preferred=)` built from the prompt's classes; `sampler_cached` keyed by the resolved sampler id;
  `check` printing the role table and `Schemas.problems`.
- [x] **Step 4: Run** the three test files — green.
- [x] **Step 5: Commit** — `feat: reload edited templates and report what the lab found`.

---

### Task 9: Verification and documentation

**Files:**
- Modify: `README.md`, `CONTEXT.md`, `docs/superpowers/specs/2026-08-11-workflow-resilience-*.md`
- Create: `scripts/verify_workflow.py` (a real generation per template plus a LoRA A/B)

- [x] **Step 1:** `python -m pytest -q` — expect 0 failures.
- [x] **Step 2:** `python scripts/verify_workflow.py` — a real 4-step generation per template
  through the real engine, then two runs differing only in `turbo_lora`; assert both succeed, that
  the submitted prompts name different LoRA files, and that the colour-grade chain is in both.
- [x] **Step 3:** `npm test`, `npm run typecheck`, `npm run build`, `python scripts/smoke.py`,
  `node web/scripts/comfy-drop.mjs` on an exported workflow.
- [x] **Step 4:** `CONTEXT.md` gains **Role** and **Turbo LoRA**; `README.md` gains *Surviving
  workflow changes* and the LoRA setting.
- [x] **Step 5:** Fill the surface map's results table, close the ledger, commit.

## Self-review

- **Spec coverage:** reader (T1), schemas (T2), roles (T3), patching (T4), export (T5), LoRA
  domain/storage/catalog (T6), API + UI (T7), reload/check/progress (T8), verification and docs
  (T9). Every numbered success criterion in the spec maps to a task: 1 → T4/T9, 2 → T9, 3 → T4,
  4 → T3, 5 → T8, 6 → T5/T9, 7 → T6/T7.
- **Placeholder scan:** none — every task names its files, its interfaces and its tests.
- **Type consistency:** `Graph`/`Node` (T1) are consumed by T3, T4 and T5 under those names;
  `Schemas.widget_names` is the callback T1 takes; `Roles.id/ids` is what T4 calls;
  `resolve_turbo_lora` is used by T4's widget write and T6's config.
