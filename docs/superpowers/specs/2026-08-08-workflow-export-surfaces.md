# Workflow Export and Frame Interpolation — Skill Bind + Surface Map

**Date:** 2026-08-08
**Request:** Three things, in the user's words:

1. "add the ability to export a run workflow, not an API but a copy of the base workflow
   merged with the run updates";
2. "make sure that the generated images (the ones that are saved alongside the video) can be
   loaded like the original workflow, not the API. I've tried dragging an image on ComfyUI
   and the nodes looked like when you drag an API file";
3. "modify the workflow so it accepts this frame interpolation:
   `E:\AI\Models\frame_interpolation\film_net_fp16.safetensors` (like RIFE? so we introduce:
   OFF, Film Net and RIFE as options?)".

**Scope class:** New feature with one embedded defect (item 2). Full one-shot pipeline:
brainstorm → grill → spec → ledger → plan → implement → close. Item 2 additionally runs the
`diagnosing-bugs` loop, because it is a reported wrong behaviour with a user-visible symptom.

---

## Relevant skills (bound)

Scanned the installed skill list against the full request and each of the three sub-goals.

| Skill | Why it is bound |
| --- | --- |
| `superpowers:brainstorming` | Pipeline step 1 — two ways to produce an editor-format graph, and where the interpolation choice lives in the config |
| `grilling` (self-mode) | Pipeline step 2 — the hash-compatibility branch, the fps branch, and the "which node pack" branch all have to be settled before code |
| `superpowers:writing-plans` | Pipeline step 5 — bite-sized TDD plan on disk |
| `roadmap-discipline` → `task-start-roadmap-check` | Ran first: the workspace already holds two ledgers (`2026-08-07-h3lab-phases.md`, `2026-08-08-arena-phases.md`). Both read `Status: Complete` with every checkbox checked, so no execution lock blocks this work |
| `roadmap-discipline` → `phase-ledger-maintenance` | Ledger is the completion contract |
| `roadmap-discipline` → `roadmap-verification` | No completion claim without fresh evidence |
| `diagnosing-bugs` | Item 2 is a defect with a precise symptom ("nodes looked like when you drag an API file"). Phase 1 of that skill — build a tight red-capable loop — is what turns it from a guess into a fix |
| `tdd` | Every unit here has a public seam: a graph transform, a config value, a route, a migration |
| `domain-modeling` | `rife: bool` stops being true when there are three choices. `CONTEXT.md` is this repo's ubiquitous-language artifact; the new term has to land there and then be used in code, on the wire, and in the UI with no synonym |
| `codebase-design` | The editor-format rebuild is a new seam. Whether it is a second implementation of `apply_config` or a projection of its output is the load-bearing decision of this whole task |
| `frontend-design` | A two-state toggle becomes a three-state control, and the run page gains a download action |
| `playwright` | The UI surface is verified by driving the built bundle (`scripts/smoke.py`) when the environment can run it |
| `superpowers:verification-before-completion` | Gate before claiming done |
| `superpowers:finishing-a-development-branch` | Step 8 substitute — `finalize-completed-work` is not installed here |
| `context7-mcp` / `docs-researcher` | **Not bound.** ComfyUI is running on this machine and its source is on disk. `/object_info` and `comfy_extras/nodes_frame_interpolation.py` are a stronger authority than any documentation snapshot, and the repo's own README says the node's `INPUT_TYPES` is the authority |
| `shadcn` | **Not bound.** The three-state control is built from `toggle-group`, already vendored in `web/src/components/ui/` |

Not bound (checked, off-topic): the marketing and growth packs (`ads`, `seo-*`, `emails`,
`social`, `pricing`, `cro`, `launch`, …), cloudflare/workers/durable-objects, hyperframes and
the video-authoring skills (this is a benchmarking tool for video, not a video editor),
atlassian, huggingface, caveman/ponytail.

---

## Surfaces (every surface this work will change)

| Surface | What changes |
| --- | --- |
| **Library / core** | New `h3lab/comfy/editor.py`: projects a patched API prompt back into the editor's node/link format using the template as the source of node metadata. `h3lab/comfy/graph.py` gains the three-way interpolation wiring and the frame-rate rule that follows from it. `h3lab/comfy/nodes.py` gains the two FILM node ids. `h3lab/domain/config.py` replaces `rife: bool` with `interp: "off" \| "film" \| "rife"` and accepts the legacy key. `h3lab/domain/arena.py` and `h3lab/domain/insights.py` follow the rename |
| **HTTP / API** | New `GET /api/runs/{run_id}/workflow` — the editor-format graph for that run, as a downloadable file |
| **UI / frontend** | The Lab form's RIFE switch becomes an Off / FILM / RIFE segmented control; the sweep builder offers the three values on that axis; the Run page gains a "Download workflow" action |
| **Data layer** | Migration `v2`. Renaming a hashed config field changes the canonical form, so every stored `config_hash` and `recipe_hash` would silently stop matching new runs. The migration rewrites each stored config through the model and recomputes both hashes, for `runs` and `presets` |
| **Infra / config** | All three workflow templates (`minimax_h3_{flf2v,t2v,r2v}_workflow.json`) gain a `FrameInterpolationModelLoader` + `FrameInterpolate` pair, bypassed by default, in the renamed "Frame Interpolation" group |
| **Docs / content** | `CONTEXT.md` gains the interpolation term and loses the RIFE-specific wording; `README.md` gains the export and the three-way setting; spec, ledger, plan |

Not changed: the CLI, the event bus, the scoring and leaderboard maths, the arena's selection
algorithm (only the name of one held field moves).

---

## Verification method per surface

| Surface | Method | Bar |
| --- | --- | --- |
| **Library / core** | `pytest tests/test_comfy_editor.py tests/test_comfy_graph.py tests/test_domain_config.py tests/test_domain_arena.py` — load the shipped modules from the test as a fresh consumer and assert real return values: an exported graph whose every link resolves, whose widget values carry the run's settings, and which round-trips back through `to_api_prompt` to the prompt it came from | Round-trip equality, not a shape check. No tautological assertions |
| **HTTP / API** | `pytest tests/test_api.py -k workflow` over `httpx.ASGITransport` against the real app, asserting status, `Content-Disposition`, and **body content** (node count, a widget value that came from the run's config). Then a real `GET` with `curl` against a live `python -m h3lab serve` | Status *and* body asserted, over a real socket at least once |
| **UI / frontend** | Vitest + Testing Library driving the real components (three-state control changes the queued config; the download link points at the run's workflow route), plus Chromium via `scripts/smoke.py` if Playwright can run here. If it cannot, the launcher error is recorded verbatim and the DOM tests stand as the substitute | Assert real DOM output, not a snapshot of props |
| **Data layer** | A test that writes a pre-rename row into a real temp SQLite file, opens the store (running migrations), and asserts the stored config now says `interp` and both hashes equal what the model computes today | Assert stored data after the real migration path |
| **Infra / config** | **A real generation on the live ComfyUI on this machine**, once per interpolation value. Assert the run succeeds, that the produced video's frame rate is the one the setting implies (24 / 48 / 60), and that the PNG ComfyUI saved beside it carries an editor-format `workflow` chunk | A green test suite has never proved a graph runs. This is the only evidence that counts for the templates |
| **Docs / content** | `CONTEXT.md` terms grepped back to shipping identifiers; `pytest tests/test_contract.py` for the route/type seam | Shipped artifact asserted |

### Domain-skill verify bars (stricter, must also be met)

- **`diagnosing-bugs` bar (item 2):** a named, already-run, red-capable command that asserts
  the user's exact symptom — that the PNG saved beside the video contains a `workflow` chunk
  in editor format, not only the API `prompt` chunk. The loop must have been observed red
  against the current code before the fix, and green after.
- **`domain-modeling` bar:** `CONTEXT.md` defines the interpolation term; the same word is
  the config field, the JSON field on the wire, the axis label, and the control's label. No
  synonym anywhere. The old `rife` name survives only as an input alias for stored data, and
  that is stated in the glossary entry.
- **`codebase-design` bar:** the exported editor graph is a *projection of `apply_config`'s
  output*, never a second implementation of its rules. Deleting `editor.py` must remove the
  ability to export a graph, not change what a run does. `editor.py` does no I/O.
- **`frontend-design` bar:** the three-state control reads as one choice, not two toggles; the
  frame rate each option produces is stated in the hint, because "which one is faster" is the
  question a benchmarking user is actually asking.
- **`tdd` bar:** every unit opens with a failing test at a public seam, and the red output is
  quoted in the ledger.

---

## Verification results

Filled in at ledger close, from commands actually run. Nothing is recorded here before it has
been measured. Full detail in `2026-08-08-workflow-export-phases.md`.

| Surface | Evidence | Result |
| --- | --- | --- |
| **Library / core** | `python -m pytest -q` | 506 passed. `tests/test_comfy_editor.py` holds the round trip (`to_api_prompt(to_editor_workflow(template, prompt)) == prompt`) for all three interpolation values and for an r2v run whose loaders `apply_config` mints |
| **HTTP / API** | `curl -D - http://127.0.0.1:8792/api/runs/<id>/workflow` against a live `python -m h3lab serve` | `200`, `content-disposition: attachment; filename="h3lab-<id>.json"`, body 26 nodes / 26 links / 10 groups, `extra.h3lab.run_id` matching, `frame_rate: 48`, seed 4242, steps 20, `film_net_fp16.safetensors`, multiplier 2 — the run's settings, not the template's. A missing id answers `404` |
| **UI / frontend** | `npm test` (111 passed) and `python scripts/smoke.py` — Chromium against the built bundle and the real server | Smoke green on all 15 steps with a clean console, including the new `workflow` step: the download is clicked in the browser, the file captured and parsed, and asserted to be a positioned editor graph holding `FrameInterpolate` and not `RIFEInterpolation`. The `lab` step drives the three-way control and asserts the selection moves. Screenshots at `.smoke/shots/{lab,run-workflow}.png` |
| **Data layer** | `python -m pytest tests/test_storage.py -q` | Migration v2 writes a pre-rename row into a real temp SQLite file, opens the store, and the stored config reads `interp` with both digests equal to what the model computes today. An unparseable config is left byte-identical |
| **Infra / config** | `python scripts/verify_interp.py` — three real generations on the live ComfyUI 0.30.0 (RTX 5090) | All three succeeded. ffprobe on the muxed files: off 24 fps / 56 frames, film 48 fps / 111 frames (FILM's own `(n−1)×2+1`), rife 60 fps / 140 frames. The PNG ComfyUI saved beside each video carries an editor-format `workflow` chunk (24 / 26 / 26 nodes) naming the run |
| **Docs / content** | `CONTEXT.md` and `README.md` edited; `python -m pytest tests/test_contract.py -q` | 7 passed — the generated `schema.ts` matches the live OpenAPI, so `interp` and the new route are the same words on both sides. `rg -i rife` over `h3lab` and `web/src` finds no `rife` field left: only the `Interp` value `"rife"`, the label `"RIFE"`, the `RIFEInterpolation` node's own id and widget order, the legacy-alias translation, and the migration's name |

## Completion criterion

- [x] Relevance pass ran against the full request and the installed skill list
- [x] Every clear-match installed skill is bound with a reason
- [x] Every surface the task will change is named
- [x] Each surface has a matching verification method
- [x] Domain-skill verify bars recorded
- [x] This file exists on disk and is linked from the phase ledger
- [x] Every named surface has fresh evidence recorded above
- [x] Every bound skill was loaded and followed, not merely listed

### The user's own gesture, performed

The reported symptom was "I've tried dragging an image on comfyui and the nodes looked like when
you drag an API file". Every check above is upstream of that gesture, so the gesture itself was
driven: `node web/scripts/comfy-drop.mjs <png> http://127.0.0.1:8189` dispatches a real
`DragEvent` carrying the PNG onto ComfyUI's own canvas and then reads back what the frontend
built. Result for a real film run's saved still:

- 26 nodes, none at the origin, spread over 12 columns — an API import stacks them
- all ten of the template's groups by name, including `Frame Interpolation (FILM Net)`
- 22 nodes keeping the template's own titles (`MS_INPUT_SEED`, `Megapixels`, …)
- `FrameInterpolationModelLoader` and `FrameInterpolate` on the canvas, `RIFEInterpolation` absent
- `extra.h3lab.run_id` naming the run

The file from `GET /api/runs/{id}/workflow` was dropped the same way, with the same result.
Screenshot: `.smoke/shots/comfy-drop-*.png`.
