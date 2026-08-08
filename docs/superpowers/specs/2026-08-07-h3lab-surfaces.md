# H3 Lab — Skill Bind + Surface Map

**Date:** 2026-08-07
**Request:** Refactor the MiniMax H3 ComfyUI benchmark into a 10x better system: more
features, React UI on a real component framework, more robust/less error-prone code,
reworked business logic. Goal: benchmark results, rate and compare them, reuse the runs
I like most, find and compare the best ones, see which configurations work best and which
do not.
**Scope class:** New feature build (full one-shot pipeline), greenfield rewrite of an
existing working product with data migration.

---

## Relevant skills (bound)

Bound by scanning the installed skill list against the full request and each sub-goal.

| Skill | Why it is bound |
| --- | --- |
| `superpowers:brainstorming` | Pipeline step 1 — options and trade-offs for a full rewrite |
| `grilling` (self-mode) | Pipeline step 2 — stress-test every design branch before spec |
| `superpowers:writing-plans` | Pipeline step 5 — implementation plan on disk |
| `roadmap-discipline` → `phase-ledger-maintenance` | Ledger is the completion contract for a build this size |
| `roadmap-discipline` → `roadmap-verification` | No completion claim without fresh evidence |
| `codebase-design` | Request explicitly asks for robust, less error-prone structure. Deep-module vocabulary drives where the seams go (storage, comfy, engine, api) |
| `domain-modeling` | Request asks to "rework the current business logic". Run / Rating / Vote / Preset / Sweep / Axis need precise names; `CONTEXT.md` glossary is the artifact |
| `frontend-design` | Request explicitly asks for a better UI. Visual direction, typography, palette, signature element |
| `shadcn` | Request explicitly asks for React with "a proper component framework". shadcn/ui is the component layer |
| `tdd` / `test-driven-development` | Request asks for stable and less error-prone. Red→green per vertical slice at agreed seams |
| `superpowers:verification-before-completion` | Gate before claiming done |
| `ab-testing` | Sub-goal "see which configurations work best and which do not" is a comparison-methodology problem: paired vs marginal analysis, sample size honesty, avoiding false winners from n=1 |
| `analytics` | Sub-goal "find and compare the best ones" needs a metric definition discipline (what is the north-star score, what is a guardrail) |
| `systematic-debugging` / `diagnosing-bugs` | Conditional — bind on first real defect during implement |

Not bound (checked, off-topic): all marketing/growth/social/video-production skills,
cloudflare/workers skills, hyperframes, atlassian, huggingface, caveman/ponytail packs.

---

## Surfaces (every surface this work will change)

| Surface | What changes |
| --- | --- |
| **UI / frontend** | Complete replacement: vanilla-JS `ui/` → React + TypeScript + Vite + Tailwind + shadcn/ui in `web/`. New pages: Lab, Runs, Compare, Insights, Leaderboard |
| **HTTP / API** | Replacement: stdlib `http.server` → FastAPI. New resources: runs, ratings, votes, presets, sweeps, insights, leaderboard, catalog, events (SSE), uploads, media |
| **Data layer** | New SQLite schema with versioned migrations, row-level writes (no full-suite rewrite), plus a one-shot importer for the existing runs and videos in `results/benchmark.db` (38 runs / 26 videos, counted at import) |
| **Library / core** | New `h3lab` package replacing `bench`: domain (config hash, scoring, Elo, insights), storage, comfy (client/graph/progress), engine (queue/executor/events/artifacts) |
| **CLI** | New entry point `h3lab` / `python -m h3lab` replacing `benchmark_runner.py`, with configurable Comfy URL, models dir, Comfy input dir, port, and data dir |
| **Infra / config** | Settings object driven by env + CLI flags; previously hardcoded absolute Windows paths become defaults |
| **Docs / content** | `README.md` rewrite, `CONTEXT.md` glossary, spec + phases ledger + plan |

---

## Verification method per surface

| Surface | Method | Bar |
| --- | --- | --- |
| **UI / frontend** | Vitest + @testing-library/react asserting real rendered DOM for the load-bearing logic (scoring/format/diff utils, filter reducers, compare transport, rating keyboard flow), **plus** a real browser check driving the built app if a headless browser can run here. If Playwright cannot install/run, record the exact launcher error in the ledger and fall back to the DOM-assert bar plus a production `vite build` that must succeed with zero TypeScript errors | Component renders assert visible text/roles, not snapshots of internals |
| **HTTP / API** | `httpx.ASGITransport` against the real FastAPI app: assert status **and** response body content for every route family; SSE asserted by reading real streamed events | Every route family has at least one body-asserting test |
| **Data layer** | Tests against a real temp SQLite file: migrations apply from empty, idempotent re-apply, row-level update does not clobber siblings, legacy-import fixture produces expected rows | Assert stored/returned data, not call counts |
| **Library / core** | Import the public entry (`h3lab.domain`, `h3lab.storage`, …) from tests and assert real return values. Independent-source expected values for hashing/Elo/scoring (worked examples), never recomputed the same way as the code | No tautological assertions |
| **CLI** | Real subprocess invocation of the shipped entry point: `--help`, `--version`, and a `--check` mode that exercises settings + DB open and exits non-zero on failure. Assert exit code **and** stdout content | Real process, asserted output |
| **Infra / config** | Settings resolution test (env override > CLI default) plus the CLI `--check` boot that actually opens the DB and resolves paths | Observable outcome asserted |
| **Docs / content** | README commands are the ones the CLI actually accepts — verified by running the documented commands' `--help`; `CONTEXT.md` terms match the identifiers in code (grep check) | Shipped artifact asserted |

### Domain-skill verify bars (stricter, must also be met)

- **`ab-testing` bar:** any "config X is better than Y" claim in the product must carry
  its sample size and must distinguish **paired** (matched-config) from **marginal**
  (all-runs) comparison. The UI must refuse to declare a winner at n=1 and must show n
  next to every aggregate. Verified by a domain test asserting the insight payload marks
  low-n comparisons as inconclusive.
- **`analytics` bar:** exactly one primary score definition, documented, with its inputs
  visible and its weights user-controlled. Guardrail metrics (speed, failure rate) shown
  alongside, never folded silently into the headline. Verified by a scoring test using a
  worked example.
- **`frontend-design` bar:** design plan (palette / type / layout / signature) recorded in
  the spec before UI code, and reviewed against the three known AI-default looks.
- **`shadcn` bar:** components come from the registry via CLI rather than hand-rolled
  markup; forms use `Field`/`FieldGroup`; spacing uses `gap-*`; colors use semantic tokens.
- **`codebase-design` bar:** every new package module passes the deletion test — deleting
  it must make complexity reappear across callers, not vanish.

---

## Verification results

Recorded at ledger close. Full detail in `2026-08-07-h3lab-phases.md`, Phase 7.

| Surface | Evidence | Result |
| --- | --- | --- |
| **UI / frontend** | `python scripts/smoke.py` — Chromium drives the built bundle against a real server on a real socket, 16 seeded runs with real clips | 10/10 steps, console clean. No env limit needed, so the fallback bar was not used |
| **UI / frontend** | `npm test` (Vitest + @testing-library/react), `npm run typecheck`, `npm run build` | 75 tests / 9 files passed; typecheck exit 0; build succeeded |
| **Generation (end to end)** | `POST /api/runs` against live ComfyUI on an RTX 5090 | Succeeded: 44.4 s wall, 6.73 s/it, video + poster + filmstrip produced. Found 3 defects the green suite had missed |
| **HTTP / API** | `pytest tests/test_api.py -q` — ASGI transport plus in-thread uvicorn for SSE | 74 passed, bodies asserted per route family |
| **Data layer** | `pytest tests/test_storage.py -q` on real temp SQLite files | 36 passed, including sibling-clobber and legacy-import regressions |
| **Library / core** | `pytest tests/test_engine.py -q` → 59 passed, plus the domain and settings suites; whole suite 375 passed | Worked-example expected values, no tautologies |
| **CLI** | `pytest tests/test_cli.py -q` — real `python -m h3lab` subprocesses | 21 passed on exit code and stdout |
| **Infra / config** | `python -m h3lab check` boots settings, patches all three workflow templates, probes ComfyUI, ffmpeg, and `web/dist` | Reports per-check status; non-zero exit only on fatal |
| **Docs / content** | README commands run against the real CLI; `CONTEXT.md` terms grepped against code identifiers | Two glossary drifts found and corrected (see Phase 7) |

Domain-skill bars: the `ab-testing` bar is enforced in code — `MIN_PAIR_GROUPS = 2`, a
`matched_on` label separating seed-matched from seed-pooled evidence, and an explicit
`inconclusive` verdict kind rather than a near-tie. The `analytics` bar holds: one score,
user-owned weights, quality and speed always shown beside it, guardrails never folded in.

## Completion criterion

- [x] Relevance pass ran against the full request and the installed skill list
- [x] Every clear-match installed skill is bound with a reason
- [x] Every surface the task will change is named
- [x] Each surface has a matching verification method
- [x] Domain-skill verify bars recorded
- [x] This file exists on disk and is linked from the phase ledger
- [x] Every named surface has fresh evidence recorded above
- [x] Every bound skill was loaded and followed, not merely listed
