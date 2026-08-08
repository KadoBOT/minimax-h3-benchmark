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
prompt, media, aspect, megapixels, duration, RIFE, upscaler, widget overrides. RIFE and the
upscaler are held rather than ranked because they make a clip look better without making
the generation better, so a voter who can see one is answering a different question.

**Contested setting** — a config field the arena is willing to differ on, and therefore
ranks: weights, sampler, scheduler, steps, turbo, cache, cache preset, Sol-Attn, Sol
preset.

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

**Run status** — `queued` → `running` → `succeeded`, or `failed` / `cancelled` /
`interrupted`.

**Event** — a typed message published when state changes, delivered to browsers over
Server-Sent Events: `run.created`, `run.started`, `run.progress`, `run.finished`,
`run.updated`, `run.deleted`, `queue.changed`, `rating.changed`, `vote.added`,
`comfy.status`, `lab.message`, `heartbeat`. Every event carries a monotonic `seq`; a
reconnecting browser sends the last one it saw back as `?after=` and the bus replays the
gap from its buffer.
