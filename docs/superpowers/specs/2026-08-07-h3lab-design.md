# H3 Lab — Design

**Date:** 2026-08-07
**Supersedes:** `2026-08-06-comfyui-h3-benchmark-design.md`, `2026-08-07-interactive-h3-bench-design.md`
**Surface map:** `2026-08-07-h3lab-surfaces.md`
**Glossary:** `/CONTEXT.md`

## Goal

A lab for MiniMax H3 video generation where the user can run configurations, judge the
results, and have the system tell them which configurations actually work — with enough
rigour that the answer is trustworthy, and enough ergonomics that judging 50 clips is not
a chore.

Success criteria:

1. Every run is durably recorded with an immutable config snapshot and a stable hash, so
   repeats group and duplicates are detected.
2. Judging a run takes one keystroke; judging a pair takes one click.
3. The system answers "which cache setting is faster / better" with a **paired**
   comparison and a stated sample size, and refuses to name a winner on n=1.
4. A liked run can be re-run, cloned with overrides, or saved as a preset in one action.
5. Comparing runs means frame-locked synchronous playback, not "play A then play B".
6. The queue survives a server restart.

## What is wrong with the current system

Read from the existing code, not assumed:

- **One mutable `Suite` object** shared between HTTP threads and the worker, persisted by
  rewriting *every* run row on every progress tick (~every 2 s). This produced the
  `dedupe_suite_runs` / `_run_keep_score` machinery, the `refusing to overwrite` guard,
  and "ghost queued twins" of completed runs.
- **Run id is a formatted string** (`run_003_model_cache_sol`) so ids collide by
  construction, which is what the dedupe machinery exists to paper over.
- **No server-side config identity.** The browser recomputes a fingerprint in JavaScript,
  so duplicate detection and grouping cannot be trusted or queried.
- **Quality is a single 1–10 integer** with no criteria and no pairwise signal, and the
  Scores tab averages it *marginally* — every number on it is confounded.
- **`bench/matrix.py` is dead**, so there is no systematic sweep mechanism; every run is
  hand-entered.
- **The UI is a 2 100-line vanilla-JS file** with string HTML templating and manual
  `lastListKey` re-render guards.
- **Absolute Windows paths are compiled into `constants.py`.**
- **The queue is an in-memory `deque`** lost on restart, and its worker thread can exit
  silently.

Worth keeping (hard-won ComfyUI knowledge, ported with tests):

- `ProgressCollector`'s plausibility filtering — WebSocket progress arrives in bursts and
  naive inter-arrival timing yields nonsense `0.01 s/it`.
- Graph-execution-cache clearing plus the cache-hit retry, without which `wall_s` is a lie.
- Video-only VHS combine (MiniMax audio latents contain NaN which breaks the AAC mux).
- R2V autogrow inputs must stay dotted (`ref_images.ref_image_0`), never nested.
- `_ensure_node` for loaders the UI graph bypassed out of existence.
- Pruning incomplete `SaveImage` / `SaveAudio` roots or ComfyUI rejects the prompt.

## Approaches considered

**A — Incremental refactor.** Keep `bench/`, bolt React on, fix the store. Lowest risk,
but retains the single-mutable-suite architecture that causes the whole bug family, and
leaves run identity broken. Rejected.

**B — New `h3lab` package, port the ComfyUI knowledge, import the existing data.**
Replaces the fragile core, keeps the 28 existing runs and 20 videos. **Chosen.**

**C — Greenfield with no migration.** Discards real ratings and outputs for no benefit.
Rejected.

## Architecture

```
h3lab/
  settings.py        Settings: env + CLI, all paths configurable
  domain/            pure functions and value objects, zero I/O
    config.py        GenerationConfig, config_hash, recipe_hash, canonical form
    run.py           Run, RunMetrics, RunStatus, Artifact
    rating.py        Rating, Vote, Elo replay
    scoring.py       normalisation, Score, leaderboard ordering
    insights.py      marginal + paired axis analysis, verdicts
    sweeps.py        SweepSpec expansion
  storage/
    migrations.py    forward-only versioned schema
    db.py            connect(), transaction(), WAL + busy_timeout
    runs.py          RunRepository  (row-level writes)
    judgement.py     RatingRepository, VoteRepository
    library.py       PresetRepository, SettingsRepository (baseline pin)
    legacy.py        one-shot import from results/benchmark.db + benchmark.json
  comfy/
    client.py        HTTP client: queue, history, view, interrupt, object_info
    progress.py      ProgressTracker (ported s/it derivation)
    graph.py         Graph: ui->api conversion, set/link/drop/chain/prune
    nodes.py         node id constants grouped by role
    modes.py         per-mode media wiring (flf2v / t2v / r2v)
    prompt.py        build_prompt(ui, config, tag) — the single public entry
    catalog.py       samplers/schedulers/aspects/models discovery + TTL cache
  engine/
    events.py        EventBus, typed events, SSE subscription
    artifacts.py     ffprobe facts, poster frame, filmstrip (fail-soft)
    executor.py      execute one run end to end
    queue.py         DB-backed queue + single worker + reconcile
  api/
    app.py           FastAPI factory, SPA static mount
    deps.py          dependency wiring
    schemas.py       request/response models
    routes/          runs, judgement, presets, sweeps, analysis, catalog,
                     media, uploads, events
  cli.py             `python -m h3lab` / `h3lab`
web/                 Vite + React + TS + Tailwind v4 + shadcn/ui
```

Each package is a deep module: `comfy.prompt.build_prompt` is one function hiding 300
lines of node surgery; `storage.runs.RunRepository` hides SQL behind intention-named
methods; `engine.queue.JobQueue` hides the worker lifecycle behind `enqueue` / `abort` /
`reconcile`.

### Data model

```sql
runs(id TEXT PK, seq INT UNIQUE, label TEXT, status TEXT, mode TEXT,
     config_json TEXT, config_hash TEXT, recipe_hash TEXT,
     wall_s REAL, sec_per_it REAL, steps INT, sampler_cached INT,
     cache_cleared INT, prompt_id TEXT, error TEXT,
     video_path TEXT, poster_path TEXT, strip_path TEXT,
     width INT, height INT, fps REAL, frame_count INT, size_bytes INT,
     favourite INT, archived INT, notes TEXT,
     created_at TEXT, started_at TEXT, finished_at TEXT)
run_tags(run_id TEXT, tag TEXT, PK(run_id, tag))
ratings(run_id TEXT PK, stars INT, criteria_json TEXT, updated_at TEXT)
votes(id TEXT PK, run_a TEXT, run_b TEXT, winner TEXT NULL, axis TEXT NULL, created_at TEXT)
presets(id TEXT PK, name TEXT UNIQUE, config_json TEXT, source_run_id TEXT, created_at TEXT)
app_state(key TEXT PK, value TEXT)        -- baseline pin, schema version
```

Indices on `status`, `config_hash`, `recipe_hash`, `favourite`, `archived`, `seq`.

Writes are row-level and transactional. There is no whole-suite rewrite, therefore no
anti-wipe guard and no dedupe pass.

### Identity

- `id` — 26-char time-sortable ULID-style string, generated from `time_ns` + `secrets`.
- `seq` — `MAX(seq)+1` allocated inside the insert transaction.
- `label` — derived for display: `#12 int8 · spectrum/mod · sol/mod · 20st`.
- `config_hash` — BLAKE2b-128 over canonical JSON of sampling-relevant fields.
- `recipe_hash` — the same with `seed` removed.

### Judgement and ranking

`stars` 1–10 plus optional criteria 1–5. Votes recorded as an append-only log; Elo is
**replayed** from the log on read (cached by log length) so it is always reproducible.

Primary score:

```
quality  = stars present ? (stars - 1) / 9
                         : elo present ? percentile(elo) : none
speed    = 1 - percentile(sec_per_it)          # percentile, so outliers cannot crush it
score    = w_quality * quality + w_speed * speed
```

Defaults `w_quality = 0.7`, `w_speed = 0.3`, both user-controlled. Runs with no quality
signal are ranked last and marked `unrated` rather than silently scored 0. Guardrails
(`wall_s`, failure rate, n) render beside the score.

### Axis analysis

For axis `A` and the set of non-archived runs:

- **Marginal** — group by `A`'s value; report n, mean/median stars, mean `sec_per_it`,
  mean Elo. Labelled confounded.
- **Paired** — compute each run's *pair key* = recipe hash with `A` excluded. Within each
  pair key, take every ordered pair of distinct `A` values and record the delta in stars
  and in `sec_per_it`. Aggregate deltas per value pair: n pair groups, mean delta,
  standard error, and a sign count.
- **Verdict** — `winner` only when pair groups ≥ 2 **and** the mean delta exceeds its
  standard error; otherwise `inconclusive` with the reason. n is always in the payload.

### Execution

`JobQueue` reads `status='queued'` ordered by `created_at`. A single worker claims a run
in a transaction (`queued` → `running`), executes, and writes terminal state. On startup
`reconcile()` flips any `running` row to `interrupted`. Abort sets a `threading.Event`,
interrupts ComfyUI, clears the ComfyUI queue, and marks remaining `queued` rows
`cancelled`. Because the queue is the `runs` table, a restart resumes it.

`execute(run)`:

1. Publish `run.progress` with stage `preparing`.
2. Clear the ComfyUI graph-execution cache (warn, do not fail, if unavailable).
3. Build the prompt, queue it, stream WebSocket progress into `ProgressTracker`, publish
   throttled `run.progress` events.
4. If the result looks graph-cached (`sampler_cached` or `wall_s < 2 s`), clear and retry
   once; fail if it still looks cached.
5. Download the video, probe it, derive poster + filmstrip (fail-soft).
6. Write metrics and `succeeded`.

### Live updates

`GET /api/events` is an SSE stream of typed JSON events. The browser uses React Query for
data and the SSE stream to invalidate or patch cache entries. If the stream drops, React
Query falls back to a 5 s poll until it reconnects.

### API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Lab + ComfyUI reachability, queue depth, versions |
| GET | `/api/catalog` | samplers, schedulers, aspect ratios, models, modes, R2V limits, defaults |
| GET | `/api/runs` | filter (status, mode, favourite, archived, tag, rated, hash, q), sort, paginate |
| POST | `/api/runs` | enqueue one or many configs |
| GET | `/api/runs/{id}` | one run with rating, tags, duplicates |
| PATCH | `/api/runs/{id}` | favourite, archived, notes, tags, label |
| DELETE | `/api/runs/{id}` | delete run and its files |
| POST | `/api/runs/{id}/rerun` | clone config with optional overrides |
| PUT | `/api/runs/{id}/rating` | stars + criteria |
| DELETE | `/api/runs/{id}/rating` | clear |
| GET/POST | `/api/votes` | pairwise vote log |
| GET | `/api/leaderboard` | ranked runs for given weights |
| GET | `/api/insights` | axis analysis (marginal + paired) |
| GET | `/api/analysis/diff` | config diff across N run ids |
| GET/POST/DELETE | `/api/presets` | preset library |
| POST | `/api/sweeps/preview` | expand a sweep, flag configs that already ran |
| GET | `/api/queue` · POST `/api/queue/abort` | queue state and cancel |
| POST | `/api/uploads` | media into the ComfyUI input folder |
| GET | `/api/media/{id}/{kind}` | video / poster / strip with Range support |
| GET | `/api/events` | SSE |

Every request and response body is a pydantic model, so a malformed config is a 422 with
field paths instead of a silently coerced run.

## Frontend

### Design plan

**Subject:** a colourist's bench for judging machine-generated video. The artefacts are
five-second clips; the instruments are timing readouts and A/B decks.
**Audience:** one power user, at night, on a large monitor, comparing near-identical clips.
**The page's single job:** make the better configuration obvious.

**Palette** — warm graphite ground with two semantically assigned accents:

| Token | Hex | Role |
| --- | --- | --- |
| `ink` | `#100E0C` | ground, brown-shifted near-black |
| `panel` | `#1A1714` | raised surfaces |
| `rule` | `#302A24` | hairlines |
| `bone` | `#F0E9DD` | primary text, warm paper |
| `signal` | `#FF7A29` | time / speed / active state |
| `mint` | `#57D9B4` | quality / positive delta |
| `crimson` | `#E5484D` | failure / negative delta |

**Type** — Archivo Expanded 700 for display and verdicts, Archivo 400–600 for UI, Martian
Mono with tabular figures for every number, hash, and seed. One family with a width axis
plus one technical mono; not the Inter/JetBrains default pairing.

**Layout** — fixed left rail (five destinations), centre column per page, and a persistent
right-hand **Bench tray** holding the runs staged for comparison. The tray survives
navigation, so candidates picked in Runs are still staged when you reach Compare.

**Signature** — the **filmstrip row**. Every run is a six-frame contact strip pulled from
its video with an edge-code baseline beneath it in Martian Mono (`seq · s/it · ★ · elo`),
set like film edge markings. Fifty runs become scannable without pressing play, and in
Compare the strips stack so divergence is visible per timecode. Compare then gives all
selected clips one shared amber transport bar — frame-locked gang sync, the way a grading
suite compares takes.

**Self-review against AI defaults:** this is a dark UI with accents, adjacent to the
common "near-black plus one bright accent" look. Deliberate divergences: the ground is
warm brown-black rather than neutral or blue-black; there are two accents and each carries
a fixed meaning (amber = time, mint = quality) so colour is data, not decoration; text is
warm paper rather than `#fff`; radius is 4 px equipment-style rather than pill-shaped; and
the memorable element is structural (contact strips and a shared transport), not chromatic.
Boldness is spent only on the strips and the transport; everything else is flat panels and
hairlines.

### Pages

1. **Lab** — config builder (mode, model, prompt, media, sampling, features, cache/attention
   presets), preset library, sweep builder with live expansion count and "already ran"
   flags, and the live queue with per-run progress.
2. **Runs** — filmstrip list with filters, sort, inline rating, favourite, tags, quick
   preview, and a keyboard flow (`j/k` move, `1–9`/`0` rate, `f` favourite, `c` stage for
   compare, `a` archive, `Enter` open).
3. **Compare** — 2–4 staged runs, gang-synced transport, stacked filmstrips, config diff
   table highlighting only what differs, and vote buttons that write to the vote log.
4. **Insights** — pick an axis; see the paired verdict first with its sample size, the
   marginal table second and labelled confounded, and a delta chart per value.
5. **Leaderboard** — ranked runs with the two weight sliders, the score decomposed into
   quality and speed bars, and guardrails beside it.

### Frontend stack

Vite 7, React 19, TypeScript strict, Tailwind v4, shadcn/ui (Button, Card, Tabs, Select,
Slider, Switch, Dialog, Sheet, Badge, Table, Tooltip, Toggle Group, Field, Sonner,
Separator, ScrollArea, Skeleton, Empty, Chart), `@tanstack/react-query`,
`react-router-dom`, `lucide-react`. Built to `web/dist` and served by FastAPI with an SPA
fallback.

## Migration

`storage/legacy.py` reads the existing `results/benchmark.db` (and
`benchmark.json.migrated` if present), maps each legacy run to the new schema —
`rating` → `ratings.stars`, `excluded` → `archived`, `timed_s` → `wall_s`, legacy id →
`label`, new ULID id — copies `results/videos/*` to the new artifact layout, and derives
posters and filmstrips for anything with a video. Import is idempotent, keyed on the
legacy id recorded in `app_state`.

## Error handling

- Config validation at the API edge (pydantic) — 422 with field paths.
- ComfyUI unreachable — catalog serves fallbacks and marks `source: "fallback"`; enqueue
  still succeeds; the run fails with a readable error naming the URL.
- ffmpeg missing or failing — artifact derivation is skipped, the run still succeeds, the
  UI falls back to the video element.
- ComfyUI returning a cached graph — one retry, then a failure that names the fix.
- Crash mid-run — `reconcile()` marks it `interrupted` at startup, never eternal `running`.
- Every route family has an explicit failure test.

## Testing

Per the surface map: `httpx.ASGITransport` body assertions for every route family;
real-temp-file SQLite tests for migrations, row-level isolation, and legacy import;
worked-example tests for hashing, Elo, scoring, and insight verdicts; subprocess tests for
the CLI; Vitest + Testing Library DOM assertions plus a clean `tsc --noEmit` and `vite
build` for the UI, with a real browser smoke test if one can run in this environment.

## Out of scope

Multi-GPU or multi-worker execution, authentication, remote/multi-user use, editing
ComfyUI workflow JSON from the UI, and training or fine-tuning.
