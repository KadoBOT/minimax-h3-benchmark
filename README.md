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
  subject, resolution, duration, interpolation and upscaling, so the preference you state is
  about the sampler, the scheduler, or the weights — and the standings rank those settings.
- **One score, no black box.** The leaderboard blends normalised quality and normalised
  speed using *your* weights, and always shows both halves plus the guardrails (failure
  rate, wall clock, sample size) beside the number.
- **Comparisons that hold up.** Ask "does the cache setting matter?" and the lab compares
  only runs that are identical apart from that setting — seed-matched wherever it can, and
  says so when it had to pool across seeds. Thin evidence is reported as *inconclusive*
  instead of dressed up as a near-tie.
- **Reuse the good ones.** Save any run's config as a named preset, pin one as the
  baseline, re-run it with one click, or open it in the Lab and change one field.
- **Edit the workflows freely.** The templates are yours to re-export from ComfyUI. The lab
  finds the nodes it needs by what they *are*, reads an edited file back without a restart, and
  says which part it no longer recognises instead of failing a run to tell you.

See [CONTEXT.md](CONTEXT.md) for the glossary these words come from — code, database
columns, and UI labels all use the same terms.

## Requirements

- Python 3.11+ (developed on 3.14)
- [uv](https://docs.astral.sh/uv/) for Python environment and package management
- Node 20+ (only to build the front end)
- A running [ComfyUI](https://github.com/comfyanonymous/ComfyUI) with the MiniMax H3
  models (`fl2va` for FLF2V/T2V, `ref2va` for R2V)
- `ComfyUI-MiniMax-H3-Studio` with Studio contract major version 1
- `ffmpeg` / `ffprobe` on `PATH` — optional; without them you get videos but no poster
  frames or filmstrips

## Install

```bash
uv sync
cd web && npm install && npm run build && cd ..
```

## Run

```bash
uv run h3lab serve --open
```

Then open http://127.0.0.1:8787/.

Before the first run, ask what is broken:

```bash
uv run h3lab check
```

It checks ComfyUI, the installed Studio contract, every workflow template, installed node
schemas, the fallback model folder, ffmpeg, ffprobe, and the built front end. Exit code is
non-zero only when a fatal requirement is missing; optional fallback paths remain visible in
the report without blocking the app.

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
| ComfyUI URL | `H3LAB_COMFY_URL` | `https://olares.hake-skink.ts.net:8443` |
| Listen host / port | `H3LAB_HOST` / `H3LAB_PORT` | `127.0.0.1` / `8787` |
| Data directory | `H3LAB_DATA_DIR` | `results/` |
| Diffusion models | `H3LAB_MODELS_DIR` | `E:\AI\Models\diffusion_models` |
| LoRA models | `H3LAB_LORAS_DIR` | `loras/` beside the models directory |
| ComfyUI input folder | `H3LAB_COMFY_INPUT_DIR` | ComfyUI's `input/` |
| Workflow templates | `H3LAB_WORKFLOW_DIR` | repo root |
| Built front end | `H3LAB_WEB_DIST` | `web/dist` |
| ffmpeg / ffprobe | `H3LAB_FFMPEG` / `H3LAB_FFPROBE` | `ffmpeg` / `ffprobe` |

The data directory holds `h3lab.db` plus `videos/`, `posters/`, and `strips/`. Nothing
outside it is written.

## Studio runtime contract

The running MiniMax H3 Studio custom node owns the generation UI and the final workflow
adaptation. H3 Lab proxies its unstyled ES module through `/api/studio/component.js`, mounts
it on the Lab page, and sends the source API workflow to `/api/studio/prepare` immediately
before validation or queueing. The returned workflow is the queue-ready artifact.

H3 Lab still owns benchmark-specific model selection, cache family and preset tuning, Turbo
LoRA strength, run identity, sweeps, and persistence. It does not carry a fallback copy of the
Studio component or its graph-rewrite logic: a missing route or incompatible contract is an
actionable installation error. See the custom node's
[integration skill](../ComfyUI-MiniMax-H3-Studio/docs/SKILL.md) for the public component and
prepare contracts.

## Generation modes

| Mode | Template | Needs | Weights family |
|------|----------|-------|----------------|
| **FLF2V** first/last frame | `minimax_h3_unified_guided_dual.json` | first frame (last frame optional) | fl2va |
| **T2V** text to video | `minimax_h3_unified_guided_dual.json` | prompt only | fl2va |
| **R2V** references to video | `minimax_h3_unified_guided_dual.json` | at least one reference | **ref2va** |

R2V accepts up to **9 images**, **3 videos** (each with an optional paired soundtrack),
and **3 standalone audio** clips. Tag them in the prompt as `<Picture 1>`, `<Video 1>`,
`<Audio 1>` in connection order.

The template is a ComfyUI editor export. H3 Lab converts it to API prompt format and selects
benchmark-owned model/cache tuning. The Studio prepare endpoint then selects attention,
interpolation, upscaling, cleanup, grading, dual-pass, and cache on/off paths.

## Surviving workflow changes

The templates are meant to be edited. Re-export one from ComfyUI and the numbers move: fold a
branch into a subgraph and node 10 becomes `169:10`, rebuild a group and every id shifts. An
earlier version of this lab addressed nodes by id, so one re-export broke every mode at once.

Nothing is addressed by id now. Four rules, each doing one job:

| Rule | Where | What it survives |
|------|-------|------------------|
| Read the graph ComfyUI would execute | `comfy/workflow.py` | Subgraphs, nested subgraphs, both link formats, promoted widgets, bypassed nodes. A template is flattened to the same execution ids ComfyUI's own executor uses. |
| Ask the node what its widgets are called | `comfy/schema.py` | A node pack renaming or adding a widget. `/object_info` is the authority; the order saved in the template answers when ComfyUI is off; a required widget nobody set gets the node's own default. |
| Find nodes by what they are | `comfy/roles.py` | Renumbering, retitling, reordering. A role is resolved from the title tag, then the class, then the wiring, then the id it once had. `MS_ROLE:duration` in a title is an override that beats every guess. |
| Prepare through Studio | `comfy/studio.py` | Tagged optional branches. H3 Lab keeps the source workflow; the custom node returns the selected queue-ready graph. |

What that buys, concretely:

- **Edit a template while the lab is running.** Its modification time is checked on the way into
  every run: an edited file is re-read and announced in the browser, an untouched one is a cache
  hit, and a run always holds one graph from start to finish so a mid-sweep edit cannot rewrite
  what a finished run claims to have executed.
- **Ask what the lab can still see.** `h3lab check --roles` prints the node playing each part and
  the rule that found it. A role found only by *first of class* is reported as a guess, an
  essential role with nobody to play it fails the check, and every template is validated against
  the installed nodes before anything reaches the GPU.
- **Read progress in words.** The live readout names the executing node by its class, so it says
  `Sampler` and not `node 169:10`.
- **Add a node the lab has never heard of.** It is carried through untouched as long as something
  the run needs is downstream of it.

Two things still have to be true of a template: the pipeline must end at a video output node,
and the nodes the lab writes settings into must exist. `check` names both.

### The Turbo LoRA

`turbo` applies a distilled LoRA so a clip takes four steps instead of twenty. Which LoRA is a
setting, not a fixture of the template:

| Field | Meaning |
|-------|---------|
| `turbo` | Whether the LoRA is in the model chain at all |
| `turbo_lora` | Which file — the list comes from the loader node's own combo options |
| `turbo_lora_strength` | How hard it is applied, 0 to 2 |

The picker offers what ComfyUI has, so a LoRA dropped into the folder appears on the next
refresh; when ComfyUI is unreachable the lab scans the LoRA folder instead, and falls back to the
name the template ships with. Both fields are part of a run's identity — two turbo runs with
different LoRAs are two experiments, not replicates — so both are hashed, both are contested in
the arena, and both are sweepable:

```
axis: turbo_lora        → minimax_h3_turbo_4step_comfyui_pruned, minimax_h3_turbo_4step_ema_ckpt850
axis: turbo_lora_strength → 0.6, 0.8, 1.0
```

A turbo run samples at the step count its LoRA was distilled for, read from the filename
(`..._4step_...` → 4 steps), which is why the step field goes inert and says so while turbo is
on — and the count is written into the run rather than left at whatever the form was holding, so
what a stored turbo run says it sampled at is what it sampled at. Turning turbo off clears both
LoRA fields and hands the step count back, so every non-turbo run still hashes alike no matter
which LoRA was picked before.

### Frame interpolation

Between the decode and the muxer a run can put one interpolator, or none:

| `interp` | Graph | Frame rate |
|----------|-------|------------|
| `off` | decode → combine | 24 — every frame sampled |
| `film` | decode → `FrameInterpolate` → combine | 48 — FILM Net doubles the frames it is given |
| `rife` | decode → `RIFEInterpolation` → combine | 60 — RIFE resamples to a rate it is told |

The frame rate is not cosmetic. FILM multiplies the frames it is handed without being told a
target rate, so the muxer has to be told the multiplied rate too — leaving it at 24 produces a
valid file that plays at half speed. RIFE is told its target and the muxer is told the same.

Only the chosen interpolator survives into the prompt. Both branches end at the video node, and
ComfyUI validates an unused one as a graph root all the same, so the loser is dropped rather
than merely left unconnected.

FILM's checkpoint is the template's own `model_name` widget (`film_net_fp16.safetensors` here);
the lab does not choose it, for the same reason it does not choose the CLIP model. The multiplier
is fixed at 2 — the setting exists so a run can be compared with and without interpolation, not
so the factor can be swept.

### Taking a run back to ComfyUI

Every run can be reopened as the graph that produced it, two ways:

- **Download workflow** on the run page (`GET /api/runs/{id}/workflow`) gives you the template's
  own layout with that run's settings applied — nodes, links, groups and all. Not the API prompt,
  which opens as a heap of unpositioned boxes.
- **The still saved beside the video** carries the same graph. The lab sends it as
  `extra_data.extra_pnginfo.workflow` when it queues, which is the key ComfyUI's frontend prefers
  when you drag an image onto the canvas, so a dropped frame reopens as a readable graph.

Both are built by applying benchmark-owned settings to the current source template, preparing
it through the Studio contract, and projecting that exact prepared prompt back into editor
form. That is what makes the downloaded file, the graph in the PNG, and the submitted run one
graph rather than three descriptions of one.

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

The queue panel also shows what the sampler is looking at. Every template carries a preview
override node, and the templates hand it the clip's frame count, so each sampling step comes back
as a couple of hundred milliseconds of video of the whole shot as it stands. The newest one is
held in memory for the run in flight and served from `GET /api/runs/{id}/preview`; the progress
event carries only the frame count and its media type, so the stream never hauls a picture around.
Nothing is written to disk and nothing survives the run — the artifact of a run is still its video.

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
| **Held** | mode, prompt, media, aspect, megapixels, duration, interpolation, upscaler | Must match on both sides. Interpolation and the upscaler make a clip *look* better without making the generation better, and size and length flatter a clip the same way — a voter who can see one is answering a different question. |
| **Contested** | weights, sampler, scheduler, steps, turbo, turbo LoRA and its strength, cache, Sol-Attn, presets | Allowed to differ. These are what the standings rank. |
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
uv run h3lab import-legacy
```

Reads `results/benchmark.db`, maps every run, rating, and video into the new schema, and
builds the poster frames and filmstrips the old lab never had. Safe to re-run: runs
already imported are counted and skipped, not duplicated.

## Development

```bash
uv sync
uv run pytest -q                # 706 backend tests

cd web
npm run dev                     # Vite on :5173, proxying /api to :8787
npm run typecheck
npm test                        # 128 DOM tests
npm run build
```

The front end's types are generated from the backend's OpenAPI schema:

```bash
uv run python scripts/gen_types.py     # writes web/src/api/schema.ts
```

`tests/test_contract.py` fails if you forget — it regenerates the schema in memory and
compares, and it also checks that every URL the front end calls is a route the API serves
and that no route is left without a caller. That test is the reason a renamed field cannot
reach the browser as `undefined`.

For an end-to-end check against a real browser:

```bash
uv run python scripts/smoke.py         # seeded temp DB + the live Studio contract, driven by Playwright
```

It never submits a generation, but it does load the Studio v1 component and call its prepare
endpoint from the configured ComfyUI (override with `--comfy-url`). It walks every page, fails
on console errors, on horizontal overflow, and on the specific
regressions that have bitten before (a disabled sweep that queued anyway, a leaderboard
label overlapping its score, a thumbnail whose `src` resolved but never decoded, a live
stream that stayed open and delivered nothing, a hover preview that autoplay policy refused
to start or that opened off the edge of the screen, a steps field that kept showing the count
a turbo run would ignore). It also casts a real vote in the arena and reads the result on the
standings page, picks a turbo LoRA and sweeps it, and fails if the settings under test are in
the document before the disclosure is opened.

None of that replaces one real generation. The worst bugs found while building this —
including a default cache preset that could not run at all, and a hardcoded text encoder
filename that broke every quantised model — were all invisible to a green test suite,
because a graph can be perfectly wired and still be something the model refuses.

So if you touch `h3lab/comfy/`, or a custom node gets updated underneath you, spend the six
minutes:

```bash
uv run python -u scripts/live_cache_check.py          # every cache family at every level
uv run python -u scripts/live_cache_check.py spectrum # just one family
uv run python -u scripts/verify_interp.py             # one clip per interpolation choice
uv run python -u scripts/verify_workflow.py           # one clip per template, an edited template, two LoRAs
```

`live_cache_check.py` queues a four-step clip per preset level and fails on any level the
nodes refuse. A node's own `INPUT_TYPES` and its `validate()` are the authority on what a
preset may contain — read them after an update rather than guessing, because the values move.
`docs/superpowers/specs/2026-08-07-spectrum-node-upgrade.md` shows what that looked like the
last time Spectrum changed.

`verify_interp.py` queues one clip per interpolation choice and then reads the files: ffprobe
for the frame rate the muxer actually wrote, and the PNG beside each video for the editor
graph it should carry. It checks the frame *count* as well as the rate, because a graph that
silently skipped the interpolator would still produce a file claiming 48 fps.

`verify_workflow.py` is the one to run after editing a template. It generates one clip per mode,
then renumbers a copy of the t2v template on disk *between* two runs and requires the second run
to carry the new ids, then runs two clips differing only in `turbo_lora` and requires each graph
to name its own file and the two configs to hash differently. Finally it reads every export back
into a prompt and asks the installed nodes whether they object to any of it. A suite can only
prove the lab believes its own graph; this asks the GPU.

And if you want to see what ComfyUI makes of a run's graph, hand it one:

```bash
cd web
node scripts/comfy-drop.mjs <png-or-workflow.json> [comfy-url]
```

It performs the actual gesture — a real drag-and-drop onto the canvas — and reports what the
frontend built: how many nodes, whether they have positions, which groups survived. An API
prompt arrives as an unpositioned column with no groups, so the two cases are easy to tell
apart, which is the whole point.

## Layout

```
h3lab/
  domain/    config, sweeps, rating, scoring, insights, arena — no I/O, no framework
  storage/   SQLite repositories, versioned migrations, legacy import
  comfy/     workflow reader, node schemas, roles, graph patching, editor export,
             HTTP + WebSocket client, catalog, progress
  engine/    durable queue, worker, event bus, artifact processing, Lab facade
  api/       FastAPI routes, dependencies, one Problem shape for every failure
web/         React 19 + TypeScript + Tailwind v4 + Base UI
scripts/     type generation, browser smoke test, live verification
```

Inside `comfy/`, the four modules that make a template replaceable are layered and each knows
only about the one below it: `workflow.py` (what nodes exist) → `schema.py` (what they take) →
`roles.py` (which one is which) → `graph.py` (fit them to a config). `editor.py` projects the
result back for a person to read.

`domain/` knows nothing about the database, ComfyUI, or HTTP. That is what makes the
scoring and comparison logic testable without a GPU in the room.
