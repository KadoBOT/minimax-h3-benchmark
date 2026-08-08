# H3 Lab

A benchmarking lab for MiniMax H3 video generation. Queue runs, judge them, and find out
which settings actually earn their render time.

The old version of this project could run a config and list the result. This one is built
around the harder question: *of everything I have generated, what should I generate next?*

- **Queue, don't babysit.** Runs live in the database with a status. Close the browser,
  restart the machine, and the queue is still there.
- **Sweep instead of clicking.** Pick a base config, pick the axes you want to vary, and
  the lab expands the cartesian product into the queue with the seed strategy you chose.
- **Judge two ways.** 1–10 stars for absolute quality, and pairwise votes for the
  comparisons a star scale is bad at. Votes drive a replayable Elo.
- **Vote on like for like.** The arena only ever shows two clips that already agree on
  subject, resolution, duration, RIFE and upscaling, so the preference you state is about
  the sampler, the scheduler, or the weights — and the standings rank those settings.
- **One score, no black box.** The leaderboard blends normalised quality and normalised
  speed using *your* weights, and always shows both halves plus the guardrails (failure
  rate, wall clock, sample size) beside the number.
- **Comparisons that hold up.** Ask "does the cache setting matter?" and the lab compares
  only runs that are identical apart from that setting — seed-matched wherever it can, and
  says so when it had to pool across seeds. Thin evidence is reported as *inconclusive*
  instead of dressed up as a near-tie.
- **Reuse the good ones.** Save any run's config as a named preset, pin one as the
  baseline, re-run it with one click, or open it in the Lab and change one field.

See [CONTEXT.md](CONTEXT.md) for the glossary these words come from — code, database
columns, and UI labels all use the same terms.

## Requirements

- Python 3.11+ (developed on 3.14)
- Node 20+ (only to build the front end)
- A running [ComfyUI](https://github.com/comfyanonymous/ComfyUI) with the MiniMax H3
  models (`fl2va` for FLF2V/T2V, `ref2va` for R2V)
- `ffmpeg` / `ffprobe` on `PATH` — optional; without them you get videos but no poster
  frames or filmstrips

## Install

```bash
pip install -r requirements.txt
cd web && npm install && npm run build && cd ..
```

## Run

```bash
python -m h3lab serve --open
```

Then open http://127.0.0.1:8787/.

Before the first run, ask what is broken:

```bash
python -m h3lab check
```

It reports the two failures that used to cost the most time — ComfyUI unreachable, and a
workflow template that cannot be patched — plus the model folder, ffmpeg, and whether the
front end is built. Exit code is non-zero only when something fatal is wrong.

### Commands

| Command | Purpose |
|---------|---------|
| `serve` | Run the web app (this is the default, so bare `h3lab` works) |
| `check` | Report what is wrong without queueing anything (`--json` for scripts) |
| `import-legacy` | Pull runs, ratings, and videos out of the previous lab's `benchmark.db` |
| `routes` | List every route the API answers |
| `openapi` | Print the OpenAPI schema the front end's types are generated from |

`serve` takes `--host`, `--port`, `--reload`, `--open`, and `--no-worker` (serve the data
without executing anything — useful for reviewing results while ComfyUI is busy).

### Settings

Every path resolves through `h3lab/settings.py`. Override with a flag or an `H3LAB_*`
environment variable; flags win.

| Setting | Env | Default |
|---------|-----|---------|
| ComfyUI URL | `H3LAB_COMFY_URL` | `http://127.0.0.1:8188` |
| Listen host / port | `H3LAB_HOST` / `H3LAB_PORT` | `127.0.0.1` / `8787` |
| Data directory | `H3LAB_DATA_DIR` | `results/` |
| Diffusion models | `H3LAB_MODELS_DIR` | `E:\AI\Models\diffusion_models` |
| ComfyUI input folder | `H3LAB_COMFY_INPUT_DIR` | ComfyUI's `input/` |
| Workflow templates | `H3LAB_WORKFLOW_DIR` | repo root |
| Built front end | `H3LAB_WEB_DIST` | `web/dist` |
| ffmpeg / ffprobe | `H3LAB_FFMPEG` / `H3LAB_FFPROBE` | `ffmpeg` / `ffprobe` |

The data directory holds `h3lab.db` plus `videos/`, `posters/`, and `strips/`. Nothing
outside it is written.

## Generation modes

| Mode | Template | Needs | Weights family |
|------|----------|-------|----------------|
| **FLF2V** first/last frame | `minimax_h3_flf2v_workflow.json` | first frame (last frame optional) | fl2va |
| **T2V** text to video | `minimax_h3_t2v_workflow.json` | prompt only | fl2va |
| **R2V** references to video | `minimax_h3_r2v_workflow.json` | at least one reference | **ref2va** |

R2V accepts up to **9 images**, **3 videos** (each with an optional paired soundtrack),
and **3 standalone audio** clips. Tag them in the prompt as `<Picture 1>`, `<Video 1>`,
`<Audio 1>` in connection order.

The templates are ComfyUI editor exports. The lab converts them to API prompt format and
patches them per run — wiring the loader implied by the weights filename, and pruning
whole groups (LoRA, attention, caches, RIFE, upscaler) when a toggle is off. Add or remove
model files in the models directory and refresh; nothing about them is hard-coded.

### Picking media

Every image the form offers is shown, not just named: a picked first frame and each
reference image render as a thumbnail served from ComfyUI's own input folder. A filename is
not something you can judge a frame by, and an input folder in real use holds hundreds.

Switching to a mode that needs media fills the gap it opens, so a fresh form is queueable
rather than a list of blanks. The names live in `h3lab/domain/config.py` as
`BASELINE_FIRST_FRAME` and `BASELINE_REF_IMAGES`, and the catalog resolves each one against
the input folder before offering it:

- **first frame** — the baseline still if it is there, otherwise any image, otherwise nothing.
- **reference images** — the baseline set, and only if *all* of it is there. A reference
  says what to generate rather than where to start, so half a set is a different subject and
  an arbitrary substitute produces a confidently wrong video instead of an empty form.

Media already chosen is never replaced, including by switching modes and back. A thumbnail
that cannot load says `not in input/` in place of the image — a stored draft outlives the
folder it named, and the form knows before preflight does.

### Reading a run at a glance

A strip is six frames cut at the same six timecodes for every run, so divergence between two
runs lands at the same x position. Sweeping the pointer across one scrubs it. **Resting on
one opens the clip in a floating card** — sweeping is scanning, stopping is a question, and
the answer to most questions about a generated video is motion that six stills cannot show.

The card floats rather than playing inside the strip because a strip is 6:1 by construction:
the right shape for six frames in a row and the wrong shape for one. It is anchored to the
strip, sized by the video's own aspect ratio, and flips upward or downward to stay on screen.
It takes no pointer events, so it can never steal hover from the strip that opened it. The
clip is muted, loops, and is dropped the moment the pointer leaves; a reduced-motion
preference keeps everything still.

Each strip is dated by **when its run finished**, not when it was queued. A sweep is created
in a single moment, so creation times are identical across a page and say only when you
pressed the button. Runs still in flight fall back to when they started, and queued runs to
when they were queued; the exact time and which of the three it is are on hover.

### Live updates

Every page is driven by one Server-Sent Events stream, so the queue drains, statuses change,
and new runs appear without a reload. Each event invalidates only the queries it affects —
sampler progress is rendered straight from the stream rather than refetching a list fifty
times a second — and a reconnect resumes from the last sequence number seen.

The frames are deliberately unnamed. An SSE frame carrying an `event:` field is delivered to
a listener of that name and never reaches `onmessage`, which is the handler the client sets;
naming them once left the socket open, error-free, and completely silent. The kind travels in
the payload instead. `tests/test_contract.py` pins the wire format against the client, and
`scripts/smoke.py` queues a run from outside the page to prove a real browser still moves.

## Pages

| Page | What it is for |
|------|----------------|
| **Lab** (`/`) | Build a config, dry-run it, queue it, or expand it into a sweep. Watch the queue live. |
| **Runs** (`/runs`) | Everything generated, filterable by tag, status, and text; sortable by score, stars, or speed. |
| **Run** (`/runs/:id`) | One run: video, filmstrip, metrics, full config, rating, and what it differs from the baseline by. |
| **Compare** (`/compare`) | Two to four benched runs side by side, with only the fields that actually differ called out. |
| **Arena** (`/arena`) | Two comparable clips, blind. Pick one, call it a tie, or skip. |
| **Standings** (`/arena/standings`) | What those votes decided, per setting and per whole configuration. |
| **Insights** (`/insights`) | Per-axis verdicts: marginal averages, paired deltas, match level, and an explicit inconclusive. |
| **Leaderboard** (`/leaderboard`) | The ranking, with the quality/speed weight under your control. |

The bench tray at the bottom persists across pages and reloads — stage runs from anywhere,
then compare them.

### The arena

A preference between two clips is the most reliable judgement this lab can collect and the
easiest to waste. Show a 1 MP interpolated clip beside a 0.5 MP raw one and the first wins
every time — correctly, and about nothing anybody wanted to know.

So the comparison is fixed before the question is asked. Every config field is one of three
things:

| Class | Fields | Why |
|-------|--------|-----|
| **Held** | mode, prompt, media, aspect, megapixels, duration, RIFE, upscaler | Must match on both sides. RIFE and the upscaler make a clip *look* better without making the generation better, and size and length flatter a clip the same way — a voter who can see one is answering a different question. |
| **Contested** | weights, sampler, scheduler, steps, turbo, cache, Sol-Attn, presets | Allowed to differ. These are what the standings rank. |
| **Ignored** | seed, clean VRAM | Clearing VRAM cannot change a pixel. The seed can change everything, but holding it would empty the arena, so a matchup says whether it is *seed-matched* or *seed-pooled* instead. |

Runs sharing every held setting form a **pool**, and pairs are only ever drawn from inside
one. The page states what is held before it asks the question, and the clips carry no label,
no rating and no id — the settings that differ are not in the document at all until you open
the disclosure, after you have decided.

A vote between clips differing in exactly one setting ranks that setting. A vote between
clips differing in four ranks the two configurations *as wholes* and no single setting,
because that is all it is evidence of. A winner is declared only once the top two have met
head to head at least four decided times and the margin beats what a coin would give;
anything less says inconclusive and shows the record.

## Migrating from the old benchmark

```bash
python -m h3lab import-legacy
```

Reads `results/benchmark.db`, maps every run, rating, and video into the new schema, and
builds the poster frames and filmstrips the old lab never had. Safe to re-run: runs
already imported are counted and skipped, not duplicated.

## Development

```bash
pip install -r requirements-dev.txt
pytest -q                       # 461 backend tests

cd web
npm run dev                     # Vite on :5173, proxying /api to :8787
npm run typecheck
npm test                        # 107 DOM tests
npm run build
```

The front end's types are generated from the backend's OpenAPI schema:

```bash
python scripts/gen_types.py     # writes web/src/api/schema.ts
```

`tests/test_contract.py` fails if you forget — it regenerates the schema in memory and
compares, and it also checks that every URL the front end calls is a route the API serves
and that no route is left without a caller. That test is the reason a renamed field cannot
reach the browser as `undefined`.

For an end-to-end check against a real browser:

```bash
python scripts/smoke.py         # boots a server on a seeded temp DB, drives it with Playwright
```

It walks every page, fails on console errors, on horizontal overflow, and on the specific
regressions that have bitten before (a disabled sweep that queued anyway, a leaderboard
label overlapping its score, a thumbnail whose `src` resolved but never decoded, a live
stream that stayed open and delivered nothing, a hover preview that autoplay policy refused
to start or that opened off the edge of the screen). It also casts a real vote in the arena
and reads the result on the standings page, and fails if the settings under test are in the
document before the disclosure is opened.

None of that replaces one real generation. The worst bugs found while building this —
including a default cache preset that could not run at all, and a hardcoded text encoder
filename that broke every quantised model — were all invisible to a green test suite,
because a graph can be perfectly wired and still be something the model refuses.

So if you touch `h3lab/comfy/`, or a custom node gets updated underneath you, spend the six
minutes:

```bash
python -u scripts/live_cache_check.py          # every cache family at every level
python -u scripts/live_cache_check.py spectrum # just one family
```

It queues a four-step clip per preset level against your real ComfyUI and fails on any level
the nodes refuse. A node's own `INPUT_TYPES` and its `validate()` are the authority on what
a preset may contain — read them after an update rather than guessing, because the values
move. `docs/superpowers/specs/2026-08-07-spectrum-node-upgrade.md` shows what that looked
like the last time Spectrum changed.

## Layout

```
h3lab/
  domain/    config, sweeps, rating, scoring, insights, arena — no I/O, no framework
  storage/   SQLite repositories, versioned migrations, legacy import
  comfy/     HTTP + WebSocket client, graph patching, catalog, progress
  engine/    durable queue, worker, event bus, artifact processing, Lab facade
  api/       FastAPI routes, dependencies, one Problem shape for every failure
web/         React 19 + TypeScript + Tailwind v4 + Base UI
scripts/     type generation, browser smoke test
```

`domain/` knows nothing about the database, ComfyUI, or HTTP. That is what makes the
scoring and comparison logic testable without a GPU in the room.
