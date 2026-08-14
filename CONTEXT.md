# Context — H3 Lab

Glossary for the MiniMax H3 generation benchmarking lab. Terms here are the ubiquitous
language: identifiers in code, columns in the database, and labels in the UI use these
words and no synonyms.

## Core

**Generation config** — the complete set of knobs that determine a generated video:
mode, weights file, prompt, media references, sampler, scheduler, steps, seed,
megapixels, duration, feature toggles, and cache/attention widget values. A config is a
value: it is never mutated after a run starts.

**Recipe** — a generation config with the seed removed. Two runs of the same recipe with
different seeds are *replicates* of one experiment. Grouping by recipe is how quality is
judged; grouping by config is how exact duplicates are detected.

**Config hash** — stable 128-bit digest of the canonical form of a generation config.
Equal hash means byte-identical sampling inputs.

**Recipe hash** — the same digest computed over the recipe (seed excluded).

**Run** — one execution of one generation config. Carries an immutable config snapshot,
a status, metrics, and at most one artifact. Identified by an opaque time-sortable **run
id**; the human-facing **seq** (monotonic integer) and **label** (derived string) are
display only and never identity.

**Artifact** — the video a completed run produced, plus its derived poster frame,
filmstrip, and probe facts (width, height, fps, frame count, byte size).

**Metrics** — measured facts about a run: `wall_s` (full pipeline wall clock),
`sec_per_it` (seconds per sampler step, the same unit ComfyUI's tqdm prints), sampler
step count, and whether ComfyUI served the sampler from its execution cache.

**Turbo LoRA** — the distilled LoRA the `turbo` toggle applies, named by the `turbo_lora`
field and scaled by `turbo_lora_strength`. Which file is chosen is part of a run's identity: two
turbo runs with different LoRAs are two experiments, and both fields are hashed, contested in
the arena, and sweepable. A turbo run samples at the step count its LoRA was distilled for,
read from the filename (`..._4step_...` → 4 steps), and the validator writes that count into
`steps`, so the field a person reads is the schedule the sampler was given. With turbo off both
LoRA fields are cleared instead. Either way the derived fields follow the toggle, so two runs
that produce the same pixels hash alike whatever the form happened to be holding.

**Preview frame** — what the `ModelPreviewOverrideKJ` node in every template draws of the latent
while it samples. The templates feed the clip's frame count into that node, so a frame is normally
a short video of the whole shot as it stands rather than a still. The newest one for the run in
flight is held in memory by the worker and served from `GET /api/runs/{id}/preview`; the
`run.progress` event carries only `preview_seq` and `preview_mime`, never the bytes, so the event
bus stays a log of state changes. A preview is a progress indicator, not an artifact: it is never
written to disk and it is gone when the run ends.

**Frame interpolation** — the `interp` field: which interpolator, if any, runs between the
decode and the muxer. One of `off` (24 fps, every frame sampled), `film` (FILM Net doubles
the frames it is given, so 48 fps), `rife` (RIFE resamples to 60 fps). Post-processing, not
generation: it invents frames rather than sampling them, which is why it is a *held setting*
in the arena rather than a contested one.

**Workflow** — a ComfyUI graph in the editor's own format: positioned nodes, links, and
groups. The lab keeps one per mode as a **template** and never edits it at runtime. A template
may contain **subgraphs**: reusable definitions instanced as a single node on the canvas.

**Prompt** — the same graph in ComfyUI's API format, a flat mapping of node id to class and
inputs. This is what a run submits. It carries no layout, so it opens as a heap of boxes;
`workflow` is the form a person can read. A run's **exported workflow** is its prompt
projected back into the template's layout, which is also the graph embedded in the still
saved beside the video.

**Execution id** — the id a node has in a prompt. For a node drawn at the top level it is the
number the editor gave it; for a node inside a subgraph it is the instance path joined with
colons (`169:10` is local node 10 inside instance 169), which is the id ComfyUI's own executor
reports progress and errors against. Ids are addresses, not names: editing a template moves
them, so nothing in the lab may be keyed by one.

**Role** — what a node *is* to the lab, independent of where it sits: `sampler`,
`conditioning`, `turbo_lora`, `video_out`, and so on. Roles are resolved per template by
looking at a node's title tag (`MS_INPUT_STEPS`), then its class, then its wiring, then the id
it had when the lab was written. A title of the form `MS_ROLE:duration` is an explicit override
that beats every guess. `h3lab check --roles` prints the table with the rule that found each
one, and a role found only by *first of class* is reported as a guess.

**Essential role** — a role no prompt can be built without: the diffusion loader,
conditioning, scheduler, guider, sampler, VAE decode, and video output. A template missing one
fails `h3lab check` instead of failing a run.

**Node schema** — the installed ComfyUI's own description of a node class, read from
`/object_info`: its input names, which are required, each combo's options, and the widget
order. It is the authority on how a node's widgets are named, because a node pack can rename
one between two updates. The lab works without it — the widget order saved in the template
answers first — but with it, a renamed widget is reported instead of rejected.

## Judgement

**Rating** — a human's absolute judgement of one run: `stars` 1–10 overall, plus optional
criteria scored 1–5 (`motion`, `adherence`, `artifacts`, `detail`, `consistency`) and free
notes. `artifacts` is scored so that higher is better (5 = no artifacts).

**Vote** — a human's *relative* judgement: given two runs, which one wins, or a tie.
Votes are the more reliable signal because they do not drift the way an absolute scale
does.

**Elo** — a run's strength derived from its votes. Starts at 1500, K-factor 24, replayed
from the vote log so it is always reproducible rather than incrementally drifting.

**Score** — the single primary ranking number: a weighted blend of normalised quality and
normalised speed. Weights are the user's, not the system's. Quality and speed are always
shown next to the score so the blend is never a black box.

**Guardrail** — a metric shown beside the score but never folded into it: failure rate,
wall clock, and sample size.

## Comparison

**Axis** — a config field chosen as the subject of a comparison (`cache`, `sampler`,
`steps`, `diffusion_model`, …).

**Marginal comparison** — averages every run that shares an axis value, ignoring what
else differed. Cheap, confounded, and labelled as such.

**Paired comparison** — compares only runs that are identical apart from the axis under
test, by grouping on the recipe hash with that axis excluded. This is the comparison that
supports a claim.

**Pair group** — the set of runs sharing an excluded-axis recipe hash; the unit of a
paired comparison.

**Match level** — how tightly a paired comparison controlled for the seed.
*Seed-matched* groups hold the seed fixed, so the axis is the only difference and the
comparison is causal. *Seed-pooled* groups mix seeds because no matching pair was ever
run; they are used only as a fallback and are always labelled, because seed noise on this
model is large enough to invert a small delta.

**Inconclusive** — a comparison whose evidence is too thin to name a winner (fewer than
two pair groups, or no rated run on one side). Reported explicitly rather than shown as a
near-tie.

**Insight** — the computed result for one axis: per-value aggregates with sample sizes,
the paired deltas between values, and a verdict that may be inconclusive.

## Arena

**Arena** — the A/B surface where a person is shown two clips and states a preference. Its
one rule is that the pair must be comparable, so a vote is evidence about the settings
rather than about the resolution.

**Held setting** — a config field that must be identical on both sides of a matchup: mode,
prompt, media, aspect, megapixels, duration, frame interpolation, upscaler, widget
overrides. Interpolation and the upscaler are held rather than ranked because they make a
clip look better without making the generation better, so a voter who can see one is
answering a different question.

**Contested setting** — a config field the arena is willing to differ on, and therefore
ranks: weights, sampler, scheduler, steps, turbo, turbo LoRA, turbo LoRA strength, cache, cache
preset, Sol-Attn, Sol preset.

**Ignored setting** — `seed` and `clean_vram`, which are neither held nor ranked. Clearing
VRAM cannot change a pixel; the seed can change everything but is noise rather than a
setting, so it is reported per matchup as *seed-matched* or *seed-pooled* (the same words
insights uses) instead of being held.

**Pool** — the set of runs sharing every held setting. Matchups are only ever drawn from
inside one pool. Identified by a **pool key**, the config digest with the contested and
ignored fields removed.

**Matchup** — one offered pair: two runs from the same pool that differ in at least one
contested setting, with the sides randomly assigned so position cannot become a bias.

**Clean matchup** — a matchup differing in exactly one contested setting. Only a clean
matchup names an **axis**, and only a vote on one can rank a single setting value.

**Loadout** — the whole set of contested settings a run used, taken as one competitor.
A vote on a matchup with several differences ranks the two loadouts and no single setting,
because that is all it is evidence of.

**Standing** — one competitor's record: Elo, wins, losses, ties, how many of its votes were
seed-matched, how many runs it came from, and its mean `sec_per_it`. Speed travels beside
the ranking and is never folded into it.

**Arena verdict** — a winner is declared only when the top two values have met head to head
at least four decided times and `|wins − losses| > √(wins + losses)`; otherwise the verdict
is inconclusive and says why. Fairness is recomputed from each run's stored config at read
time, so an uncountable vote is reported with its reason rather than dropped.

## Reuse

**Preset** — a named, saved generation config. The mechanism for "run that good one
again". Records which run it was captured from.

**Baseline** — the one run currently pinned as the reference. Comparisons and insights
report deltas against it.

**Favourite** — a run the user marked as worth keeping. Orthogonal to rating: a 6-star run
with a lucky motion beat can be a favourite.

**Archived** — a run hidden from lists, leaderboards, and insights without being deleted.
Replaces the older "excluded" flag.

**Sweep** — a declarative request to generate many runs at once: a base config plus one or
more axes with value lists, expanded as a cartesian product, optionally repeated with a
seed strategy.

## Execution

**Job queue** — the ordered set of runs with status `queued`, stored in the database so
the queue survives a restart.

**Worker** — the single thread that takes the next queued run and executes it. One at a
time, because there is one GPU.

**Reconcile** — the startup step that finds runs left in a live status by a crash and marks
them `interrupted`.

**Template reload** — a template is parsed once and held, but its modification time and size
are checked on the way into every run. An edited file is read again and announced as a
`lab.message`; an unchanged one is a cache hit. A run always holds one graph from start to
finish, so an edit mid-sweep cannot change what a finished run claims to have executed.

**Run status** — `queued` → `running` → `succeeded`, or `failed` / `cancelled` /
`interrupted`.

**Event** — a typed message published when state changes, delivered to browsers over
Server-Sent Events: `run.created`, `run.started`, `run.progress`, `run.finished`,
`run.updated`, `run.deleted`, `queue.changed`, `rating.changed`, `vote.added`,
`comfy.status`, `lab.message`, `heartbeat`. Every event carries a monotonic `seq`; a
reconnecting browser sends the last one it saw back as `?after=` and the bus replays the
gap from its buffer.
