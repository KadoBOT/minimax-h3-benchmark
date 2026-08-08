# Arena — Skill Bind + Surface Map

**Date:** 2026-08-08
**Request:** An "AI arena leaderboard"-like feature (A/B/X). A page showing two videos where
one is chosen, and a leaderboard page ranking the best *settings* from those choices.
Comparisons must be oranges to oranges: the two sides must share megapixels, duration, RIFE
on/off and upscaler on/off (RIFE and upscale bias the eye without improving what the sampler
produced). Different diffusion models, schedulers and samplers are what should be tested
against each other.
**Scope class:** New feature (full one-shot pipeline: brainstorm → grill → spec → ledger →
plan → implement → close).

---

## Relevant skills (bound)

Scanned the installed skill list against the full request and each sub-goal.

| Skill | Why it is bound |
| --- | --- |
| `superpowers:brainstorming` | Pipeline step 1 — approaches and trade-offs for pairing, ranking, and where the pages live |
| `grilling` (self-mode) | Pipeline step 2 — every fairness and statistics branch stress-tested before the spec |
| `superpowers:writing-plans` | Pipeline step 5 — bite-sized TDD plan on disk |
| `roadmap-discipline` → `phase-ledger-maintenance` | Ledger is the completion contract |
| `roadmap-discipline` → `roadmap-verification` | No completion claim without fresh evidence |
| `domain-modeling` | The request introduces new domain terms (pool, matchup, held vs contested setting, loadout, standing). `CONTEXT.md` is this repo's ubiquitous-language artifact and must absorb them without synonyms |
| `codebase-design` | The comparability rule is a new seam. Deciding whether it belongs in `domain/insights.py` or its own module, and what the Lab facade exposes, is a deep-module boundary question |
| `ab-testing` | The request *is* a paired-comparison methodology problem: what makes a matchup fair, when a preference record is a winner rather than a coin flip, how to report sample size honestly |
| `tdd` / `superpowers:test-driven-development` | Every unit of this is pure logic with a testable seam; the repo is test-first throughout |
| `frontend-design` | Two new pages, one of which is the most-repeated interaction in the product |
| `playwright` | The UI surface is verified by driving the built bundle in Chromium (`scripts/smoke.py` already does this and must grow arena steps) |
| `superpowers:verification-before-completion` | Gate before claiming done |
| `superpowers:finishing-a-development-branch` | Step 8 substitute — the `finalize-completed-work` skill named by one-shot is not installed here |
| `shadcn` | Conditional — bind only if a UI primitive not already in `web/src/components/ui/` is needed. The arena is built from `button`, `tabs`, `badge`, `switch`, `tooltip`, all present, so no registry addition was required |
| `systematic-debugging` / `diagnosing-bugs` | Conditional — bind on the first real defect during implement |

Not bound (checked, off-topic): every marketing/growth skill (`ads`, `seo-*`, `emails`,
`social`, `pricing`, `cro`, `launch`, …), cloudflare/workers/durable-objects, hyperframes and
video-production skills (this is a *benchmarking* tool for video, not video authoring),
atlassian, huggingface, caveman/ponytail packs.

---

## Surfaces (every surface this work will change)

| Surface | What changes |
| --- | --- |
| **Library / core** | New `h3lab/domain/arena.py`: the held/contested partition of the config, pool identity, matchup legality and selection, standings and verdicts. `h3lab/domain/rating.py` grows a competitor-agnostic pairwise Elo replay so the arena ranks setting values with the same maths that ranks runs |
| **HTTP / API** | New `GET /api/arena/next` and `GET /api/arena/standings`. `GET /api/pairs/next` is **removed** — it offered pairs that differ in anything at all, which is the unfairness this request exists to fix. Voting keeps using the existing `POST /api/votes` |
| **UI / frontend** | New `/arena` (vote) and `/arena/standings` (ranking) pages, a new rail destination, and removal of the Compare page's "Head to head" tab so there is exactly one way to vote and it is the fair one |
| **Data layer** | **No schema change.** Votes are already `(run_a, run_b, winner, axis)`; fairness is recomputed from each run's stored config at read time, so existing votes are classified correctly and no migration is needed |
| **Docs / content** | `CONTEXT.md` gains the arena vocabulary; `README.md` gains the page and the fairness rule; spec, ledger and plan |

Not changed: CLI, infra/config, the ComfyUI adapter, the engine's queue and worker.

---

## Verification method per surface

| Surface | Method | Bar |
| --- | --- | --- |
| **Library / core** | `pytest tests/test_domain_arena.py` — import the public entry and assert real return values. Elo numbers come from worked examples computed independently of the implementation; the held/contested partition is asserted to cover `HASHED_FIELDS` exactly, so a new config field cannot be silently unclassified | No tautological assertions; every expected value derived by hand |
| **HTTP / API** | `pytest tests/test_api.py -k arena` — real requests through `httpx.ASGITransport` against the real app, asserting **body content** (which runs, which axis, which standings row), including the 404 Problem when nothing comparable exists | Status *and* body asserted per route |
| **UI / frontend** | Vitest + Testing Library driving the real page components against the fake server (`web/src/pages/arena/arena.test.tsx`), **plus** Chromium driving the built bundle against a real server: new arena steps in `web/scripts/smoke.mjs` that cast a real vote and read the standings back | Browser step must cast a vote and observe the standings change; console must stay clean |
| **Data layer** | Covered by the API tests: a vote posted over HTTP is read back by the standings endpoint from real SQLite, and a vote between runs that are not comparable is counted as ignored rather than ranked | Assert stored/returned data |
| **Docs / content** | `CONTEXT.md` terms grepped against the identifiers that ship; README's arena description checked against the routes the API actually serves (`tests/test_contract.py` fails on any orphan route or stale type) | Shipped artifact asserted |

### Domain-skill verify bars (stricter, must also be met)

- **`ab-testing` bar:** no winner may be named from a record that a coin flip would produce.
  The arena calls a winner only when the leader's net wins exceed the standard deviation of a
  fair coin over the same number of decided votes (`|W − L| > √(W + L)`) *and* a minimum
  number of decided votes has been reached. Every row carries its sample size; thin evidence
  reads as *inconclusive* with a reason, never as a near-tie. Verified by domain tests that
  assert a 2–0 record is inconclusive and a 5–0 record is not.
- **`domain-modeling` bar:** every new term appears in `CONTEXT.md`, and the identifiers in
  code, the JSON field names on the wire, and the UI labels use that word and no synonym.
- **`frontend-design` bar:** the contested settings stay hidden until the vote is cast (a
  label must not bias the eye), the two clips are presented identically, and the side each
  run appears on is randomised per matchup so position bias cannot favour a setting.
- **`codebase-design` bar:** `domain/arena.py` passes the deletion test — deleting it must
  scatter the comparability rule across the Lab, the routes and the browser, not make it
  vanish. It does no I/O and imports no storage.

---

## Verification results

Filled in at ledger close, from commands actually run. Nothing is recorded here before it
has been measured. Full detail in `2026-08-08-arena-phases.md`, Phase 4.

| Surface | Evidence | Result |
| --- | --- | --- |
| **Library / core** | `python -m pytest tests/test_domain_arena.py tests/test_domain_judgement.py -q` → **35 + 9 passed**. Opened red with `ModuleNotFoundError: No module named 'h3lab.domain.arena'` and `ImportError: cannot import name 'replay_pairwise'`. Elo values (1523.1724 / 1476.8276) hand-derived in the test comments; `test_every_config_field_is_classified_exactly_once` asserts the partition covers `HASHED_FIELDS` | pass |
| **HTTP / API** | `python -m pytest tests/test_api.py -q` → **83 passed**, over `httpx.ASGITransport` against the real app. Bodies asserted: `test_the_arena_offers_a_matchup_of_two_watchable_runs` (axis, `seed_matched`, held line, video path), `test_the_arena_never_offers_runs_from_different_pools` (404 + Problem detail), `test_the_standings_rank_the_setting_the_votes_chose` (winning key, rating order, verdict), `test_the_duel_that_ignored_fairness_is_gone` | pass |
| **Data layer** | Same suite: votes are posted over HTTP into real SQLite and read back by `GET /api/arena/standings`. `test_a_vote_across_pools_is_reported_rather_than_ranked` proves a stored vote between incomparable runs is counted as ignored with its reason rather than ranked. No migration was needed and none was written | pass |
| **UI / frontend** | `npm test` → **107 passed** (12 of them `web/src/pages/arena/arena.test.tsx`, opened red with "Failed to resolve import"); `npm run typecheck` and `npm run build` clean. Chromium: `python scripts/smoke.py` → every step `ok`, console clean, including the new `arena` step (two decoded clips, settings absent from the document before the disclosure, a real `POST /api/votes` answering 201) and `arena-standings` (Elo table with ≥2 rows and a verdict). Screenshots at `.smoke/shots/arena.png` and `arena-standings.png` | pass |
| **Docs / content** | `CONTEXT.md` gained an Arena section; every term grepped back to a shipping identifier (`pool_key`, `HELD_FIELDS`, `CONTESTED_FIELDS`, `IGNORED_FIELDS`, `loadout_key`, `clean_matchups`, `seed_matched`, `MIN_DECIDED_VOTES`). `README.md` gained the arena rows in the page table and the held/contested/ignored table. `python -m pytest tests/test_contract.py -q` → **7 passed**, so no route is orphaned and `schema.ts` is not stale | pass |

## Completion criterion

- [x] Relevance pass ran against the full request and the installed skill list
- [x] Every clear-match installed skill is bound with a reason
- [x] Every surface the task will change is named
- [x] Each surface has a matching verification method
- [x] Domain-skill verify bars recorded
- [x] This file exists on disk and is linked from the phase ledger
- [x] Every named surface has fresh evidence recorded above
- [x] Every bound skill was loaded and followed, not merely listed

### How each bound skill was applied

- `brainstorming`, `grilling`, `writing-plans`, `phase-ledger-maintenance` — produced the
  design spec, the phase ledger and the implementation plan on disk before any code.
- `tdd` — every unit opened with a failing test; the three red states are quoted above.
- `domain-modeling` — new vocabulary in `CONTEXT.md`, carried unchanged into identifiers,
  JSON field names and UI labels.
- `codebase-design` — `h3lab/domain/arena.py` owns the whole comparability rule, does no
  I/O, and imports only `domain/config.py` and `domain/rating.py`. The Elo maths was
  generalised rather than copied, so setting values and runs are ranked by one function.
- `ab-testing` — `test_four_nil_names_a_winner` and `test_three_to_one_is_what_a_coin_does`
  hold the bar; `test_two_nil_is_too_few_votes_to_mean_anything` holds the minimum.
- `frontend-design` — the clips carry no label, rating or id; the sides are randomised in
  `next_matchup`; the contested values are not rendered into the DOM until the disclosure is
  opened, which the Chromium step asserts. Screenshots reviewed, and two faults fixed from
  them: a held chip that meant nothing in text-to-video mode, and a stretched difference
  table.
- `playwright` — the arena steps in `web/scripts/smoke.mjs` drive the built bundle.
- `verification-before-completion` — this table, filled only from commands actually run.
- `shadcn` — not needed; every primitive used was already vendored.
- `systematic-debugging` — not needed; no defect outlived its own test run.
