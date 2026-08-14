# Turbo Steps, Template Parity, and the Live Preview — Skill Bind + Surface Map

**Date:** 2026-08-11
**Request:** in the user's words — "1) fix a bug that when I add 'turbo' to the axis, the amount of
steps are not reduced (16). Also, we should raise the normal amount of steps to 20. 2) I'm not sure
if FL2V and T2V are up-to-date with R2V changes, let's make sure that they are updated. And if
possible (optional), after adding the model preview override to the other two WFs, let's see if we
can display the preview on the UI while it is rendering. 3) there are many queued items, using
turbo, with 16 steps. I dont want to remove them all, if possible change correct the amount of
steps." Followed by: "I just checked the 16 steps is only the UI, the render was 8 steps, so thats
correct."

**Scope class:** Mixed. (1) and (3) are a defect plus a data repair — the `diagnosing-bugs` loop
runs first and no spec is written for them. (2) is a template edit. The optional live preview is a
new feature, so the pipeline (brainstorm → grill → spec → ledger → plan) is run once for the whole
change rather than per item, at a size proportionate to it.

**Measured starting state (2026-08-11, before any change):**

- `python -m pytest -q` → **618 passed**. The suite is green, so the defect is not one the suite
  can currently see — a red test has to be written before the fix.
- The live database (`results/h3lab.db`, 175 runs) holds **16 queued runs, every one with
  `turbo: true` and a stored `steps: 8`**, across three LoRAs: `..._4step_v1.0_768p...` (6 runs),
  `..._turbo_v4_step600_ema...` (6), `..._8step_v1.0...` (4).
- Their `effective_steps` — what the sampler is actually given — is 4, 4 and 8 respectively, so
  the render is right and the **stored `steps` is a stale leftover from before turbo was switched
  on**. It is a hashed field, so two identical turbo runs that arrived with different leftovers
  hash as two different experiments.
- The user's correction confirms the same split: the render was 8, the number on screen was not.
  The number on screen comes from ComfyUI's own progress `max`, which the queue panel prints as
  `step n of 16`; the run page prints `metrics.steps ?? config.steps`, which for these runs is the
  stale 8.
- The three templates diverged: `minimax_h3_r2v_workflow.json` carries four model-chain nodes the
  other two lack — `MiniMaxH3MemoryEfficientSageAttentionPatch`, `MiniMaxLowVRAMAttention`
  (`head_chunks 4`), `MiniMaxChunkFeedForward` (`chunks 2`, `seq_threshold 4096`) and
  `ModelPreviewOverrideKJ` (`tiny_vae taeh3.safetensors`, `preview_fps 12`,
  `suppress_default_preview true`).
- `h3lab/comfy/client.py:509` drops every binary WebSocket frame (`continue  # binary preview
  frames`) and ignores every message type it does not already handle. Nothing downstream has ever
  seen a preview. **Corrected during Phase 6:** the frame this node produces is not a binary one.
  `ComfyUI-KJNodes/nodes/preview_override_node.py` decodes the latent itself and sends a
  `kj_preview_override` message with the JPEG base64 inside, to the client that queued the prompt,
  while patching ComfyUI's own previewer off for the duration. Both channels are read now; on
  these templates only the message one speaks.

---

## Relevant skills (bound)

Scanned the installed skill list against the full request and each sub-goal.

| Skill | Why it is bound |
| --- | --- |
| `diagnosing-bugs` | (1) and (3) are a reported defect. Phase 1 of that skill is why this map opens with a queried database and a measured split between what rendered and what was stored, rather than with a theory about the sweep builder |
| `tdd` | Every unit here has a public seam: a config validator, a migration, a template edit, a WebSocket frame decoder, a route, a component |
| `domain-modeling` | `CONTEXT.md` already states the rule this defect breaks — "the step field is inert while turbo is on" — without saying what an inert hashed field is worth. The fix is a domain rule, and the glossary entry has to say it |
| `superpowers:brainstorming` + `grilling` (self-mode) | The live preview has three real shapes (base64 in the SSE event, a polled endpoint, a raw WebSocket relay) and the choice is load-bearing for the replay buffer |
| `superpowers:writing-plans` | The plan on disk for the feature half |
| `roadmap-discipline` → `task-start-roadmap-check` | Ran first. Every ledger in `docs/superpowers/specs/` reads `Status: Complete`, so nothing holds an execution lock |
| `roadmap-discipline` → `phase-ledger-maintenance` / `roadmap-verification` | The ledger is the completion contract; no claim without fresh evidence |
| `frontend-design` | The preview is a picture that appears inside the queue panel while a run is in flight, and the steps field has to stop hiding a stale number behind a greyed-out control |
| `playwright` | The UI surface is driven in Chromium — `web/scripts/shots.mjs` already does this read-only against the live instance |
| `superpowers:verification-before-completion` | Gate before claiming done |
| `superpowers:finishing-a-development-branch` | Step 8 substitute — `finalize-completed-work` is not installed here |
| `codebase-design` | **Not bound.** No module boundary moves; every change lands inside a module that already owns that job |
| `context7-mcp` / `docs-researcher` | **Not bound.** ComfyUI is running on this machine; its `/object_info` and its own WebSocket frames are a stronger authority than any snapshot |

Not bound (checked, off-topic): the marketing and growth packs, cloudflare / workers /
durable-objects, hyperframes and the video-authoring skills, atlassian, huggingface, shadcn
(the preview reuses primitives already vendored).

---

## Surfaces (every surface this work will change)

| Surface | What changes |
| --- | --- |
| **Domain** | `h3lab/domain/config.py` — with turbo on, `steps` is normalised to the schedule the chosen LoRA was distilled for, the mirror of the existing rule that clears `turbo_lora` when turbo is off. `effective_steps` keeps its meaning and becomes equal to `steps` |
| **Data layer** | Migration `v4` re-parses every stored `runs` and `presets` config through the model and recomputes both digests, which is what corrects the 16 queued runs in place instead of deleting them |
| **Library / core** | `h3lab/comfy/client.py` decodes ComfyUI's binary preview frame instead of dropping it and hands the newest one to the tracker; `h3lab/comfy/progress.py` carries it in the snapshot as a counter, not as bytes; `h3lab/engine/runner.py` holds the newest frame for the active run |
| **HTTP / API** | `GET /api/runs/{id}/preview` returns the newest in-flight preview frame as an image; the `run.progress` event grows `preview_seq` so a browser knows when to fetch again |
| **UI / frontend** | The queue panel shows the preview beside the progress bar while a run is in flight; the config form stops leaving a stale step count under the greyed-out field — it restores the count the draft had before turbo, or the lab's default of 20 when there is none |
| **Infra / config (templates)** | `minimax_h3_flf2v_workflow.json` and `minimax_h3_t2v_workflow.json` gain the four model-chain nodes R2V already has, wired in R2V's order, with R2V's widget values. Existing nodes and their values are not touched: a widget the lab does not hash is a silent change to every future comparison |
| **Docs / content** | `CONTEXT.md` — the **Turbo LoRA** entry says the step field is normalised, not merely inert, and a **Preview frame** entry is added. `README.md` gains the preview. Spec, ledger, plan, this map |

Not changed: the scoring, arena and insights maths (`steps` is already contested and hashed — this
changes what is stored in it, not how it is read); the storage schema (migration rewrites values,
not columns); the event bus wire format beyond one integer; the sampler, scheduler and every other
widget the templates already carry.

---

## Verification method per surface

| Surface | Method | Bar |
| --- | --- | --- |
| **Domain** | `pytest tests/test_domain_config.py` — a fresh consumer builds real configs and asserts the stored value, including that two turbo configs differing only in the leftover step count now hash alike | Real return values at the public seam |
| **Data layer** | `pytest tests/test_storage.py` — write a pre-v4 turbo row into a real temp SQLite file, open the store so migrations run, assert the stored config and both digests. Then the same migration against a **copy of the live database**, asserting the 16 queued rows before and after | Assert stored data after the real migration path |
| **Library / core** | `pytest tests/test_comfy_client.py tests/test_comfy_progress.py` — feed a real ComfyUI binary frame (8-byte header + JPEG) through the listener and assert the decoded image and the counter | Real bytes in, real image out |
| **HTTP / API** | `pytest tests/test_api.py` over the real app asserting status **and** body, plus a real `GET` over a socket against `python -m h3lab serve` | Status and body, over a real socket at least once |
| **UI / frontend** | `npm test` driving the real components (the preview appears only while a run is in flight; turning turbo off restores the step count), `npm run typecheck`, `npm run build`, then Chromium against the running lab via `node web/scripts/shots.mjs` | Assert real DOM output. If Chromium cannot launch here the launcher error is recorded verbatim and the DOM tests stand as the substitute |
| **Infra / config (templates)** | `python -m h3lab check --roles` against the live ComfyUI (every role still resolves, `/object_info` objects to nothing), a built prompt for each mode asserting the four new classes are present and no link dangles, and `node web/scripts/comfy-drop.mjs` opening an export on ComfyUI's own canvas | The installed nodes are the judge. A real generation is the stronger bar and is skipped only if the GPU is busy with the user's own queue — recorded either way |
| **Docs / content** | The changed sentences read back from disk; the terms grepped to shipping identifiers | Shipped artifact asserted |

### Domain-skill verify bars (stricter, must also be met)

- **`diagnosing-bugs` bar:** the loop is a test that goes red on *this* defect — two turbo configs
  that differ only in a leftover step count hashing differently, and a stored queued run reporting
  a step count the render did not use. Red output quoted in the ledger before the fix.
- **`domain-modeling` bar:** `CONTEXT.md` states the normalisation rule in the same words the
  validator uses, and no synonym for it appears in code or UI.
- **`frontend-design` bar:** the preview reads as part of the run in flight rather than as a new
  panel, degrades to nothing (not to a broken image) when a template has no preview override, and
  never leaves a stale frame from the previous run on screen.
- **`tdd` bar:** every unit opens with a failing test at a public seam; the red output is quoted.

---

## Verification results

Filled in at ledger close, from commands actually run. Nothing is recorded here before it has been
measured. Full detail in `2026-08-11-turbo-steps-and-live-preview-phases.md`.

| Surface | Evidence | Result |
| --- | --- | --- |
| **Domain** | `pytest tests/test_domain_config.py tests/test_domain_arena.py tests/test_domain_insights.py`. Red first: `assert 16 == 4`, then two turbo configs differing only in the leftover hashing apart. `DERIVED_FROM` gained `steps: (turbo, turbo_lora)` and the diffing readers with it | Pass — a turbo config stores the schedule its LoRA was distilled for, and two of them hash alike |
| **Data layer** | `pytest tests/test_storage.py` (a pre-v4 turbo row through a real temp SQLite file), then the live `results/h3lab.db`: migration v4, and a second in-place repair for the eight rows an old still-running server wrote past it — `steps 20 → 4` and `20 → 8`, both digests recomputed, backup `h3lab.bak-20260811-212100.db`, the running row untouched | Pass — no run deleted, no status changed |
| **Library / core** | `pytest tests/test_comfy_progress.py`, plus the wire itself: a logging build of the listener recorded `kj_preview_override` step `0/4` (JPEG of the noise) then `1/4`…`4/4` at `video/mp4`, 60–141 KB. Frame shapes cross-read from the installed ComfyUI's `protocol.py` and `server.py` | Pass — and it corrected the design: the frame is a message, usually a clip, not a binary still |
| **HTTP / API** | `pytest tests/test_api.py`, then over a real socket against a scratch `python -m h3lab serve`: `GET /api/runs/{id}/preview` → 200 `image/jpeg` 53 KB, `Cache-Control: no-store`, `X-Preview-Seq: 1` while rendering; 404 once the run ended | Pass — status and body, on a socket |
| **UI / frontend** | `npm test` (124), `npm run typecheck`, `npm run build`, `python scripts/smoke.py` (every page, console clean), then Chrome against the live scratch lab: `<img>` 608×352 at `?f=1`, `<video>` at `?f=2` with `readyState 4`, `paused false`, playhead 0.12 → 0.48 s, console clean | Pass — Playwright's bundled Chromium has no H.264, so the check runs in an installed Chrome; the panel drops a frame it cannot decode and shows the next one |
| **Infra / config (templates)** | All three templates re-read: FLF2V and T2V carry the four R2V nodes with R2V's widget values, every role resolves, both modes build a prompt with no dangling link. Six real generations off the edited T2V template on the installed ComfyUI | Pass — the stronger bar was met, not skipped |
| **Docs / content** | `CONTEXT.md` **Turbo LoRA** and a new **Preview frame** entry, `README.md` turbo and live-updates sections, read back from disk; the design doc and this map carry the corrected preview channel | Pass |

## Completion criterion

- [x] Relevance pass ran against the full request and the installed skill list
- [x] Every clear-match installed skill is bound with a reason
- [x] Every surface the task will change is named
- [x] Each surface has a matching verification method
- [x] Domain-skill verify bars recorded
- [x] This file exists on disk and is linked from the phase ledger
- [x] Every named surface has fresh evidence recorded above
- [x] Every bound skill was loaded and followed, not merely listed
