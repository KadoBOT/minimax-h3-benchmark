# Turbo Steps, Template Parity, and the Live Preview — Implementation Plan

**Spec:** `../specs/2026-08-11-turbo-steps-and-live-preview-design.md`
**Ledger:** `../specs/2026-08-11-turbo-steps-and-live-preview-phases.md`

Each task names the surface it touches and the skill to load before starting it. Tests come first
where a seam exists.

## Phase 1 — The red loop (`domain`, skills: `diagnosing-bugs`, `tdd`)

1. In `tests/test_domain_config.py`, add a test that two turbo configs built with the same LoRA but
   different `steps` produce the same `config_hash`, and one that a turbo config's `steps` equals
   its `effective_steps`. Run them; quote the failure in the ledger.

## Phase 2 — Domain (`domain`, skills: `tdd`, `domain-modeling`)

2. `h3lab/domain/config.py`: in `_mode_coherence`, when `self.turbo`, set `steps` to
   `turbo_steps_for(resolved_lora)` right after the LoRA is resolved. Extend the comment already
   there so the two halves of the rule are stated together.
3. Run `pytest tests/test_domain_config.py tests/test_domain_arena.py tests/test_domain_insights.py
   tests/test_comfy_graph.py` — the graph tests pin what the sampler is handed.

## Phase 3 — Data (`data layer`, skills: `tdd`)

4. `tests/test_storage.py`: write a row whose stored JSON carries `turbo: true` with a leftover
   `steps` and pre-v4 digests into a real temp SQLite file, open the store, assert the corrected
   step count and both digests.
5. `h3lab/storage/migrations.py`: append `Migration(version=4, name="turbo-steps-follow-the-lora",
   fn=_rehash_configs)` with a comment saying what moved and why.
6. Copy `results/h3lab.db` to a timestamped backup, run the migration against the live file through
   the real store, and re-query the 16 queued rows before and after.

## Phase 4 — UI steps memory (`UI`, skills: `frontend-design`, `tdd`)

7. `web/src/pages/lab/lab.test.tsx`: turning turbo on and then off leaves the step count the form
   started with; doing the same from a draft that never had one leaves 20. Red first.
8. `web/src/pages/lab/config-form.tsx`: remember the count from before turbo and hand it back on
   the way out, defaulting to `LIMITS`/meta's 20.

## Phase 5 — Templates (`infra/config`, skills: none beyond the lab's own reader)

9. Write `.smoke/port_r2v_nodes.py`: read all three templates, copy the four node objects out of
   R2V's subgraph definition into the other two, allocate fresh local ids and link ids, splice the
   chain in R2V's order (`sage → mem-efficient sage → … → cache → low-VRAM → chunk FF → preview
   override → guider/scheduler`), and write both files back with the same formatting.
10. Re-read both templates through `h3lab.comfy.workflow`; assert the model chain, that every role
    resolves, and that `build()` produces a prompt containing the four classes with no dangling
    link, for turbo on and off.
11. `python -m h3lab check --roles` against the live ComfyUI.

## Phase 6 — Preview (`library`, `HTTP`, `UI`, skills: `tdd`, `frontend-design`)

12. `tests/test_comfy_client.py`: feed the listener a real binary frame — 4-byte event type `1`,
    4-byte image type `1`, then JPEG bytes — and assert the tracker holds the image and bumps its
    counter; feed an unknown event type and assert it is ignored.
13. `h3lab/comfy/progress.py`: `on_preview(bytes, mime)` stores the newest frame, a counter, and
    the content type; `snapshot()` reports `preview_seq` only. `preview()` returns the pair.
14. `h3lab/comfy/client.py`: decode the header, hand the payload to the tracker, and notify the
    live callback so the browser is told a new frame exists.
15. `h3lab/engine/runner.py`: keep the active run's tracker reachable so the route can read the
    newest frame; drop it when the run finishes.
16. `h3lab/api/routes/runs.py`: `GET /api/runs/{id}/preview` → 200 `image/jpeg` with
    `Cache-Control: no-store`, 404 when the run is not the active one or has no frame yet.
17. `scripts/gen_types.py` if the schema moved; `web/src/api/events.tsx` carries `previewSeq`.
18. `web/src/pages/lab/queue-panel.tsx`: show the frame beside the progress bar, keyed by
    `previewSeq` so the browser refetches, and nothing at all when there is no frame.
19. Tests: `tests/test_api.py` (status and body), `web/src/pages/lab/lab.test.tsx` (DOM).

## Phase 7 — Verification and docs (skills: `superpowers:verification-before-completion`)

20. `python -m pytest -q`, `npm test`, `npm run typecheck`, `npm run build`.
21. `node web/scripts/shots.mjs http://127.0.0.1:8787` against the running lab — pages render, no
    console errors.
22. `CONTEXT.md`: the **Turbo LoRA** entry states the normalisation; a **Preview frame** entry is
    added. `README.md`: the preview, and the corrected step rule.
23. Fill the surface map's results table from commands actually run; close the ledger.
