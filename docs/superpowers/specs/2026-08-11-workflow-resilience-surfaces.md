# Workflow Resilience and the Turbo LoRA Axis — Skill Bind + Surface Map

**Date:** 2026-08-11
**Request:** in the user's words — "lets update the code, so it survives workflow changes. I
constantly update the workflow files, but that might break the current API (which the current
version did). So we should have a way to keep workflows updated. in this new version I also want
to be able to change the 'MiniMax-H3 Turbo LoRA'. I want to test add different loras to the
benchmark matrix."

**Scope class:** New feature (a rewrite of the ComfyUI-facing layer) with a live regression
attached: the three templates in the repository root are already the new format, and the current
code fails 102 of 506 backend tests against them. Full one-shot pipeline — brainstorm → grill →
spec → ledger → plan → implement → close — with the `diagnosing-bugs` loop used once, to name the
exact reason the new templates break before any of it is redesigned.

**Measured starting state (2026-08-11, before any change):**

- `python -m pytest -q` → `102 failed, 404 passed`.
- Representative failure: `WorkflowError: the workflow has no diffusion model loader (node 1)`.
- Cause: the new exports put the whole pipeline inside a **ComfyUI subgraph**
  (`definitions.subgraphs[0]`, 51–54 inner nodes), so `workflow["nodes"]` holds 5–23 boxes and
  none of the node ids the lab is pinned to.
- Three more independent breakages found while reading, each of which would have broken the lab
  on its own: the reference loaders moved from ids 200–240 to 20/400–422 while ids 200–205 became
  a colour-grade chain (so the lab's r2v pruning would delete the grade and orphan the muxer);
  four node classes changed their widget lists under the lab's static table
  (`MiniMaxH3TurboLoRA.strength_model` → `strength` + `low_vram`, `SolAttnPatch` gained `int8_pv`
  *in the middle*, `SpectrumApplyMiniMaxH3` gained four, `RTXVideoSuperResolution` became a
  dynamic combo); and thirteen classes in the templates have no entry in that table at all, so
  their widget values are dropped on the way to the API prompt.

---

## Relevant skills (bound)

Scanned the installed skill list against the full request and both sub-goals ("survive workflow
changes", "change and sweep the Turbo LoRA").

| Skill | Why it is bound |
| --- | --- |
| `superpowers:brainstorming` | Pipeline step 1. Three genuinely different answers exist to "survive workflow changes" (re-pin the constants, let ComfyUI's frontend compile the graph, or read the graph instead of assuming it) and the choice decides the whole shape |
| `grilling` (self-mode) | Pipeline step 2. The bypass-semantics branch, the export-shape branch, the id-scheme branch and the LoRA-scope branch all have to be settled before code |
| `superpowers:writing-plans` | Pipeline step 5 — bite-sized TDD plan on disk |
| `roadmap-discipline` → `task-start-roadmap-check` | Ran first. The workspace holds four ledgers (`2026-08-07-h3lab`, `2026-08-08-arena`, `2026-08-08-workflow-export`, and the two older design docs); every one reads `Status: Complete`, so no execution lock blocks this work |
| `roadmap-discipline` → `phase-ledger-maintenance` | The ledger is the completion contract for an eight-phase change |
| `roadmap-discipline` → `roadmap-verification` | No completion claim without fresh evidence |
| `diagnosing-bugs` | "which broke the current API (which the current version did)" is a reported defect. Phase 1 of that skill — build the tightest loop that goes red — is why this map opens with a measured failure count and a named cause rather than a theory |
| `tdd` | Every unit here has a public seam: a workflow reader, a schema lookup, a role resolver, a graph transform, a migration, a route |
| `domain-modeling` | `CONTEXT.md` is this repo's ubiquitous-language artifact. Two new terms have to land there and then be used in code, in the database, on the wire and in the UI with no synonym: **role** (what the lab names in a graph, instead of a node id) and **Turbo LoRA** (the weights file the turbo setting applies) |
| `codebase-design` | The load-bearing decision is where the knowledge of "what this graph means" lives. Today it is spread across `nodes.py` constants, `graph.py` wiring and `editor.py`. The design splits it into a reader, a schema, a role resolver and a patcher, each testable alone |
| `frontend-design` | The Lab form's Turbo toggle becomes a toggle plus a LoRA picker and a strength field; the sweep builder gains a LoRA axis whose values are real filenames from ComfyUI |
| `playwright` | The UI surface is verified by driving the built bundle (`scripts/smoke.py`), and the exported graph is verified by dropping it on ComfyUI's own canvas (`web/scripts/comfy-drop.mjs`) |
| `superpowers:verification-before-completion` | Gate before claiming done |
| `superpowers:finishing-a-development-branch` | Step 8 substitute — `finalize-completed-work` is not installed here |
| `context7-mcp` / `docs-researcher` | **Not bound.** ComfyUI 0.31.0 is running on this machine and its source is on disk. `/object_info` and `execution.py` are a stronger authority than any documentation snapshot, and the frontend's own id scheme was read out of the shipped bundle rather than guessed |
| `shadcn` | **Not bound.** The LoRA picker is built from the `select` and `number-field` primitives already vendored in `web/src/components/ui/` |

Not bound (checked, off-topic): the marketing and growth packs (`ads`, `seo-*`, `emails`,
`social`, `pricing`, `cro`, `launch`, …), cloudflare / workers / durable-objects, hyperframes and
the video-authoring skills (this is a benchmarking harness for video, not a video editor),
atlassian, huggingface, caveman / ponytail.

---

## Surfaces (every surface this work will change)

| Surface | What changes |
| --- | --- |
| **Library / core** | New `h3lab/comfy/workflow.py` — reads an editor workflow in either shape (flat, or nested subgraph definitions with object-shaped links) and flattens it to ComfyUI's own execution ids (`169:1`), keeping slot types, bypass state, titles and layout provenance. New `h3lab/comfy/schema.py` — widget names and order per node class from the live `/object_info`, with dynamic-combo expansion, an in-memory cache, a static fallback, and a prompt validator. New `h3lab/comfy/roles.py` — the ~24 roles the lab names, each resolved by title tag, class, or graph edge, with a report. `h3lab/comfy/graph.py` rewritten: `apply_config` now prunes a live set with ComfyUI's own type-matched bypass rule instead of rewiring an assumed chain. `h3lab/comfy/editor.py` projects the pruned graph back as a flat positioned editor workflow. `h3lab/comfy/nodes.py` keeps only the legacy id fallbacks and the static widget table |
| **Domain** | `h3lab/domain/config.py` gains `turbo_lora: str` and `turbo_lora_strength: float`, both hashed, with `resolve_turbo_lora()` mirroring `resolve_model_filename()`. `h3lab/domain/arena.py` classifies both as contested; `h3lab/domain/insights.py` gains the axis; labels and diffs follow |
| **Data layer** | Migration `v3`. Two new hashed fields change the canonical form, so every stored `config_hash` and `recipe_hash` would silently stop matching new runs. The migration rewrites each stored config through the model and recomputes both digests, for `runs` and `presets`, exactly as `v2` did for `interp` |
| **HTTP / API** | `GET /api/catalog` grows `loras`, `turbo_loras`, `loras_source` and a `turbo_lora` default; `GET /api/meta` grows the new field labels and axis; `GET /api/status`/`check` report role resolution. `scripts/gen_types.py` re-run so `web/src/api/schema.ts` matches |
| **CLI** | `h3lab check` reports, per template, which node each role resolved to and by what rule, every unresolved role, and every problem ComfyUI's own `/object_info` says the built prompt has — the difference between "ComfyUI rejected the graph three minutes into a model load" and a one-second answer |
| **UI / frontend** | The Lab form's Turbo toggle gains a LoRA picker and a strength field, greyed out when turbo is off; the sweep builder offers `turbo_lora` as an axis populated from the catalog; the run page and compare table show the LoRA |
| **Infra / config** | `WorkflowCache` reloads a template whose file changed on disk, and says so on the event bus, so editing a workflow no longer needs a restart. The three templates in the repository root are the user's new subgraph exports and are treated as fixtures, not edited by this work |
| **Docs / content** | `CONTEXT.md` gains **Role**, **Turbo LoRA** and a corrected **Workflow** entry; `README.md` gains a "Surviving workflow changes" section and the LoRA setting; spec, ledger, plan, this map |

Not changed: the scoring and leaderboard maths, the event bus wire format, the arena's selection
algorithm (one new contested field), the storage schema (migration rewrites values, not columns).

---

## Verification method per surface

| Surface | Method | Bar |
| --- | --- | --- |
| **Library / core** | `pytest tests/test_comfy_workflow.py tests/test_comfy_schema.py tests/test_comfy_roles.py tests/test_comfy_graph.py tests/test_comfy_editor.py` — load the shipped modules as a fresh consumer and assert real return values against the **real templates in the repository**: every role resolves, no link dangles, the colour-grade chain survives an flf2v run, the reference loaders are found by the conditioning slot they feed rather than by id, and the exported graph re-reads as the prompt it came from | Round-trip and no-dangling-link properties, not shape checks. Every test that used to name a node id now names a role or a class |
| **Domain** | `pytest tests/test_domain_config.py tests/test_domain_arena.py tests/test_domain_insights.py` — the arena's exhaustive partition assertion is the guard that a new hashed field cannot be forgotten | Real values asserted; the partition check must pass without being widened |
| **Data layer** | A test that writes a pre-v3 row into a real temp SQLite file, opens the store (running migrations), and asserts the stored config now carries the LoRA fields with both digests equal to what the model computes today | Assert stored data after the real migration path |
| **HTTP / API** | `pytest tests/test_api.py tests/test_contract.py` over `httpx.ASGITransport` against the real app, asserting status **and** body content, plus one real `GET` over a socket against a live `python -m h3lab serve` | Status and body, over a real socket at least once |
| **CLI** | `python -m h3lab check --json` run for real against the live ComfyUI, asserting exit code and the reported role table | Real process invocation, output content asserted |
| **UI / frontend** | Vitest + Testing Library driving the real components (picking a LoRA changes the queued config; the strength field greys out with turbo off; the sweep axis offers the catalog's files), then Chromium against the built bundle via `python scripts/smoke.py` | Assert real DOM output. If Playwright cannot run here, the launcher error is recorded verbatim and the DOM tests stand as the substitute |
| **Infra / config** | A test that edits a template file on disk between two `WorkflowCache.get()` calls and asserts the second call sees the edit; plus **real generations on the live ComfyUI** for the templates themselves | A green suite has never proved a graph runs. Real generations are the only evidence that counts for the templates |
| **Docs / content** | `CONTEXT.md` terms grepped back to shipping identifiers; `pytest tests/test_contract.py` for the route/type seam | Shipped artifact asserted |

### Domain-skill verify bars (stricter, must also be met)

- **`diagnosing-bugs` bar:** the loop is `python -m pytest -q` against the templates on disk. It
  was observed red (102 failed) before the design, and the same command must be green after. The
  named cause — subgraph nesting plus id renumbering plus widget drift — must each have a test
  that fails on the old code for the old reason.
- **`domain-modeling` bar:** `CONTEXT.md` defines **role** and **Turbo LoRA**; the same words are
  the config field, the JSON field, the axis label and the control's label. No synonym anywhere.
- **`codebase-design` bar:** the four new modules have one job each and no cycles —
  `workflow.py` knows nothing about `GenerationConfig`, `schema.py` knows nothing about roles,
  `roles.py` does no I/O, and `editor.py` remains a projection of `apply_config`'s output rather
  than a second implementation of its rules. Deleting `editor.py` must remove the ability to
  export a graph, not change what a run does.
- **`frontend-design` bar:** the LoRA picker reads as part of the Turbo setting, not as a
  separate feature; it lists only files the running ComfyUI actually offers; and it says what an
  empty choice means, because "which LoRA am I actually running" is the question a benchmark user
  has when comparing two rows.
- **`tdd` bar:** every unit opens with a failing test at a public seam, and the red output is
  quoted in the ledger.

---

## Verification results

Filled in at ledger close, from commands actually run. Nothing is recorded here before it has
been measured. Full detail in `2026-08-11-workflow-resilience-phases.md`.

| Surface | Evidence | Result |
| --- | --- | --- |
| **Library / core** | `pytest tests/test_comfy_workflow.py tests/test_comfy_schema.py tests/test_comfy_roles.py tests/test_comfy_graph.py tests/test_comfy_editor.py tests/test_comfy_progress.py` against the real templates on disk; `python -m pytest -q` overall | **Pass** — 618 passed, 0 failed (from `102 failed, 404 passed`). Round trips assert `prompt_of(export) == prompt`; a template renumbered by +5000 in `test_the_same_workflow_renumbered_produces_the_same_prompt` yields the same graph; no test names a node id |
| **Domain** | `pytest tests/test_domain_config.py tests/test_domain_arena.py tests/test_domain_insights.py` | **Pass** — 99 passed. The arena's exhaustive partition assertion passes unwidened with both new fields classified as contested |
| **Data layer** | `pytest tests/test_storage.py` — two tests write a pre-v3 row into a real temp SQLite file, open the store so migrations run, and assert the stored config and both digests | **Pass** — 41 passed. A pre-v3 turbo row comes back naming `minimax_h3_turbo_4step_comfyui_pruned.safetensors` with digests equal to what the model computes today; a non-turbo row still claims no LoRA |
| **HTTP / API** | `pytest tests/test_api.py tests/test_contract.py`, then real sockets against `python -m h3lab serve --port 8791/8792/8793`: `GET /api/catalog`, `GET /api/meta`, `POST /api/runs`, `GET /api/runs/{id}`, `POST /api/sweeps/preview`, `POST /api/sweeps` | **Pass** — suites green; over the socket: catalog 200 with 4 turbo LoRAs `source=comfy` and the 4-step default, meta 200 with `Turbo LoRA` / `Turbo strength` labels and a categorical + numeric axis, `POST /api/runs` 201 labelled `turbo/4step_ema_ckpt850@0.75`, sweep preview 200 with two distinct hashes, `POST /api/sweeps` 201 queueing 0.6 and 1.0 |
| **CLI** | `python -m h3lab check --roles` and `python -m h3lab check --roles --json` as real processes against the running ComfyUI | **Pass** — exit 0, 13/13 checks, 2937 node classes read, `roles t2v/flf2v/r2v` rows all ok; the JSON carries a 37-row table per mode naming node, class, and rule (`169:5 MiniMaxH3ReferenceToVideo (title)`), with no guessed and no missing essential role |
| **UI / frontend** | `npm test` (real DOM), `npm run typecheck`, `npm run build`, then Chromium against the built bundle via `python scripts/smoke.py` | **Pass** — 120 tests in 11 files, typecheck clean, build clean, smoke walked every page with a clean console. The new `turbo-lora` browser step drives the whole feature against the real API: two LoRAs offered under readable names, picking the 8-step one moves the schedule, the inert steps field reads 8, the keyboard moves strength to 0.95, and the swept matrix comes back naming two LoRAs at that strength. It caught a real defect a green jsdom suite had missed — the steps field kept showing the count the run would ignore (`.smoke/shots/turbo-lora.png`) |
| **Infra / config** | `pytest tests/test_engine.py -k template` (edit a file between two `get()` calls), then `python scripts/verify_workflow.py` — 7 real generations on the live ComfyUI | **Pass** — three reload tests green; live: t2v/flf2v/r2v each produced a 56-frame 416×256 clip, a template renumbered on disk between two runs ran with **0 of 20 node ids shared** (`169:1` → `5169:5001`), two turbo LoRAs each ran and named their own file with different config hashes, and the installed nodes objected to nothing in any of the three templates |
| **Docs / content** | `CONTEXT.md` and `README.md` edited; `rg -l turbo_lora h3lab web/src`; `pytest tests/test_contract.py`; `node web/scripts/comfy-drop.mjs` on an exported flf2v workflow | **Pass** — `role`, `execution id`, `node schema`, `Turbo LoRA` and `template reload` defined in `CONTEXT.md` and used as the identifiers in 15 shipping files with no synonym; contract 7 passed; ComfyUI's own frontend opened the export as 33 positioned nodes in 18 columns with all 9 groups and 29 template titles |

## Completion criterion

- [x] Relevance pass ran against the full request and the installed skill list
- [x] Every clear-match installed skill is bound with a reason
- [x] Every surface the task will change is named
- [x] Each surface has a matching verification method
- [x] Domain-skill verify bars recorded
- [x] This file exists on disk and is linked from the phase ledger
- [x] Every named surface has fresh evidence recorded above
- [x] Every bound skill was loaded and followed, not merely listed

### Domain-skill bars, met

- **`diagnosing-bugs`:** the loop was `python -m pytest -q`, observed red at `102 failed, 404
  passed` before the design and green at `618 passed` after. Each named cause has a test that
  fails on the old code for its own reason: subgraph nesting
  (`test_a_subgraph_instance_flattens_to_comfys_execution_ids`), renumbering
  (`test_the_same_workflow_renumbered_produces_the_same_prompt`,
  `test_renumbering_every_node_changes_nothing`), widget drift
  (`test_the_turbo_lora_node_is_read_with_the_widgets_the_installed_node_has`).
- **`domain-modeling`:** `CONTEXT.md` defines **role**, **execution id**, **node schema**,
  **Turbo LoRA** and **template reload**; `turbo_lora` / `turbo_lora_strength` are the config
  field, the JSON field, the axis and the control label, with `lora_stem`/`loraStem` the single
  display shortener on both sides.
- **`codebase-design`:** `workflow.py` imports no config and no roles; `schema.py` imports
  `workflow` and `nodes` only; `roles.py` does no I/O; `editor.py` projects `build()`'s output and
  nothing depends on it to run a graph — the runner would still submit without it.
- **`frontend-design`:** the picker and strength are nested inside the Turbo block, listed from
  the running ComfyUI's own combo, and the step field shows the schedule the chosen LoRA implies —
  and hands the typed count back when turbo goes off — rather than going quietly inert over a
  number the run will ignore.
- **`tdd`:** every unit in phases 1–7 opened red; the red output per phase is quoted in the ledger.
- **`playwright`:** both browser paths ran here — `scripts/smoke.py` (Chromium over the built
  bundle, now including a `turbo-lora` step that drives the picker, the schedule, the strength and
  the sweep) and `web/scripts/comfy-drop.mjs` (a real drag-and-drop onto ComfyUI's canvas). No
  environment limit to record. The smoke fixture seeds two LoRA files and a turbo pair that
  differs in nothing else, so the browser has a real choice to make rather than a list of one.
