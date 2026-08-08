# Arena — Design

**Date:** 2026-08-08
**Surface map:** `2026-08-08-arena-surfaces.md`
**Ledger:** `2026-08-08-arena-phases.md`
**Plan:** `../plans/2026-08-08-arena.md`

## What this is for

Two clips, one choice, repeated. The lab already has stars (absolute, drifts) and a
head-to-head duel (relative, honest per vote) — but the duel offers whatever pair the score
cannot separate, which routinely means comparing a 1 MP upscaled clip against a 0.5 MP raw
one. A vote cast on that pair says "the bigger, smoother one looked better", which was never
in doubt and says nothing about the sampler.

The arena fixes the comparison before asking the question. Two runs may only meet if
everything about *what was asked for* and *how it is presented* is identical: same mode,
same prompt, same media, same aspect, same megapixels, same duration, same RIFE setting,
same upscaler setting. What is allowed to differ is how the pixels were sampled: the weights,
the sampler, the scheduler, the step count, the turbo LoRA, the cache and the attention
preset. Those are what the ranking then ranks.

RIFE and the upscaler are held rather than ranked for the reason the request gives: they make
a clip *look* better without making the generation better, so a voter who sees one of them
will pick it for the wrong reason. The same argument holds for megapixels and duration, which
is why they are held too.

## The fairness rule

Every field in `HASHED_FIELDS` is classified exactly once. The partition is asserted in a
test, so a config field added later cannot slip through unclassified.

| Class | Fields | Why |
| --- | --- | --- |
| **Held** (must be identical) | `mode`, `prompt`, `first_frame`, `last_frame`, `ref_images`, `ref_videos`, `ref_video_audios`, `ref_audios`, `ref_image_size`, `aspect_ratio`, `mp`, `duration_s`, `rife`, `upscaler`, `widgets` | Subject and presentation. Differ, and the voter is judging a different scene or a prettier frame, not a better sampler |
| **Contested** (may differ, and is ranked) | `diffusion_model`, `sampler`, `scheduler`, `steps`, `turbo`, `cache`, `cache_enabled`, `cache_preset`, `sol_attn`, `sol_preset` | How the pixels were sampled. This is what the arena exists to rank |
| **Ignored** | `seed`, `clean_vram` | `seed` is noise, not a setting — it gets its own treatment below. `clean_vram` is VRAM housekeeping and cannot change a pixel; holding it would throw away matchups for nothing |

`cache_enabled` is derived from `cache` by the config validator, so when both differ only the
determinant is reported — the same suppression `config_diff` and the insight pairing already
apply through `DERIVED_FROM`.

**Seed.** Holding the seed would be the strongest control and would also empty the arena:
most sweeps vary one axis at a fixed seed, but two runs of *different* recipes rarely share
one. So the seed is neither held nor contested. A matchup whose two sides share a seed is
**seed-matched** and the difference is purely the setting; a matchup that does not is
**seed-pooled** and includes sampling luck. Both are offered, seed-matched first, and every
matchup and every standing says which it was. This is the vocabulary `CONTEXT.md` already
defines for paired comparisons, reused rather than reinvented.

## Approaches considered

**A. Filter the existing duel.** Add a comparability check to `Lab.next_pair` and rank
setting values inside `domain/insights.py`, which already does paired axis analysis.
*Rejected:* insights answers "what do the stars and the clock say about this axis", keyed on
recipe groups. The arena answers "what did the eye say about this value", keyed on votes.
Bolting the second onto the first would give one module two reasons to change and one
verdict type meaning two things. It also leaves the unfair pair-picker one click away.

**B. A new domain module, votes reused, no schema change.** `domain/arena.py` owns the
held/contested partition, pool identity, matchup legality and selection, and the standings
computed by replaying votes. The votes table is already `(run_a, run_b, winner, axis)`;
fairness is recomputed from each run's stored config when standings are read, so no column,
no migration, and every vote already in the database gets classified correctly the first time
the page loads. **Chosen.**

**C. A separate arena_votes table with a stored pool key and axis.** Faster reads and an
explicit record of what the voter was told they were judging.
*Rejected:* a stored fairness verdict is a fact frozen at write time. Fix a bug in the
partition and every historical row keeps the old answer. Recomputing costs one pass over a
few hundred votes and is always right. It also splits judgement across two tables for one
concept.

**Ranking maths.** Elo replayed from the vote log, exactly as `CONTEXT.md` already defines it
(base 1500, K 24, replayed rather than incremented so a deleted vote cannot leave a skewed
rating behind). A Bradley–Terry fit would be marginally better at separating rarely-met
competitors and would add a second, undocumented notion of strength to the glossary for a
difference nobody judging an evening's runs would notice. The Elo maths is extracted from
`replay_elo` into a competitor-agnostic `replay_pairwise`, so runs and setting values are
ranked by the same tested code.

## The grill

Every branch, with the answer taken.

**Is a vote between two runs that differ in three contested settings evidence about any one
of them?** No. Attributing it to each field separately is exactly the confounded marginal
average this codebase refuses elsewhere. So per-value ranking is built **only** from *clean
matchups* — pairs differing in exactly one contested setting. Multi-difference matchups still
count, but for the thing they are actually evidence about: the whole **loadout**.

**Then should multi-difference matchups be offered at all?** Only when nothing cleaner
exists. The selector sorts clean matchups ahead of every multi-difference one, so an ordinary
sweep produces nothing but per-setting evidence. A collection where no two runs differ in
exactly one setting still gets an arena, and it still ranks loadouts.

**Does the same pair get served forever?** No. Among clean matchups the selector prefers the
pair with the fewest votes cast on it, so it sweeps the whole set before asking anything
twice, then sweeps again — repeats of one question are replication, which a noisy preference
signal wants.

**Which side does a run appear on?** Randomised per matchup, by the server. Position bias is
real and a fixed rule (say, older run on the left) would bake it into the ranking.

**Can the voter see the settings before voting?** No. The contested differences ship with the
matchup but sit behind a disclosure, the way the existing duel already handles it. A visible
"nvfp4 vs Q4_K_M" label decides the vote before the video plays.

**When is a leader a winner?** When a coin flip would not produce its record. For a decided
record of *W* wins and *L* losses, the standard deviation of *W − L* under a fair coin is
`√(W + L)`, so the arena names a winner only when `|W − L| > √(W + L)` **and** at least
`MIN_DECIDED_VOTES = 4` decided votes exist. 4–0 is a result; 3–1 is not; 2–0 is not, because
two votes are two votes. This is the same shape as the `abs(mean) > stderr` rule
`DeltaStat.conclusive` already uses.

**Which record does the verdict test — the leader's overall, or head to head?** Head to head
against the runner-up. "euler beat dpmpp_2m 5–1" is a claim about euler and dpmpp_2m. A
leader's overall record mixes opponents of different strengths, and the two might never have
met, which is itself worth saying out loud rather than papering over.

**Ties.** A tie is recorded as a vote with a null winner, which is what `Vote` already means.
It moves both Elo ratings toward each other and is excluded from the coin-flip test, which is
about decided votes. It is still displayed, because "these two were indistinguishable eleven
times" is a finding.

**Skip.** Not a vote and not recorded. The voter presses it when a clip will not play or they
cannot judge it; the page asks for a different matchup, telling the server not to offer those
two runs again until a vote is cast.

**What happens to the existing duel?** It goes. Keeping it would leave two head-to-head
voting surfaces, one of which produces the confounded votes this feature exists to stop
collecting, feeding the same vote log. `GET /api/pairs/next`, `Lab.next_pair` and the Compare
page's "Head to head" tab are removed; the Compare page keeps the bench, which does a
different job (read several configs side by side).

**Do the old votes still count?** Yes, and correctly. Every vote is re-judged against the
current runs' configs when standings are read: comparable ones count, the rest are reported
as ignored with the reason. Nothing is silently dropped.

**What ranks — values, or whole configurations?** Both, with per-value primary. "Which
sampler should I use" is the question the request asks, and it aggregates evidence across
every pool. "Which combination won" is the question you ask before queueing tonight's batch,
and it falls out of the same vote log for the cost of a second key.

**Does speed belong in the ranking?** No. The arena ranks what the eye preferred; folding a
clock into it would make the one number mean two things. Mean seconds per step travels beside
every row as a guardrail, which is the rule the score on the existing leaderboard already
follows.

**Where do the pages live?** `/arena` and `/arena/standings`, one rail destination, a
segmented link pair between them. The standings are a page rather than a tab because the
request asks for a leaderboard page and because it is worth linking to.

## Design

### `h3lab/domain/arena.py` — no I/O, no framework

Imports `domain/config.py` and `domain/rating.py` and nothing else.

```
HELD_FIELDS, CONTESTED_FIELDS, IGNORED_FIELDS : frozenset[str]   # partition HASHED_FIELDS
ARENA_AXES : tuple[AxisDef, ...]                                 # contested fields, labelled

pool_key(cfg)            -> str    # digest over held fields; equal means comparable
pool_label(cfg)          -> str    # "t2v · 0.5 MP · 5s · no rife · no upscale"
held_summary(cfg)        -> dict[str, str]      # what both sides share, for the page
contested_differences(a, b) -> list[FieldDiff]  # derived fields suppressed
loadout_key(cfg)         -> str
loadout_label(cfg)       -> str    # "int8_convrot · euler/beta57 · 20st · spectrum/mod"
value_label(field, value)-> str    # weights read as their stem, not a 60-character filename

class ArenaRun      # run_id, config, sec_per_it — the projection the domain needs
class Matchup       # a, b (run ids), pool, pool_label, held, differences, axis, matched_on, reason
class ArenaStanding # key, label, rating, wins, losses, ties, games, win_rate,
                    # seed_matched, mean_sec_per_it, runs
class ArenaVerdict  # kind, value, runner_up, wins, losses, ties, reason
class ArenaAxis     # axis, label, standings, votes, verdict
class ArenaStandings# axes, loadouts, votes_counted, votes_ignored, ignored_reasons,
                    # pools, runs, matchups, clean_matchups

legal_matchups(runs)              -> list[Candidate]   # within pools only
next_matchup(runs, votes, *, exclude=(), rng=None) -> Matchup | None
standings(runs, votes)            -> ArenaStandings
```

Selection order, lowest first: **clean before multi-difference**, then **fewest votes on this
exact pair**, then **seed-matched before seed-pooled**, then **fewest votes touching either
run**, then a random tie-break. Sides are then assigned by the same generator, so a test with
a seeded `Random` gets a fixed answer and production does not.

Standings, one pass over the vote log: skip a vote whose runs are gone, archived, in
different pools, or which has no contested difference (each counted under its reason); feed
every surviving vote into the loadout table; feed the clean ones into their axis table. Elo
comes from `replay_pairwise`, so the numbers are reproducible from the log alone.

### `h3lab/domain/rating.py`

`replay_pairwise(games, *, k, base) -> dict[str, Standing]` holds the Elo maths over any
competitor key. `replay_elo(votes)` becomes a thin wrapper that keeps returning `EloEntry`
keyed by run id, so `/api/elo`, `RunView.elo` and every existing test see no change.

### `h3lab/engine/lab.py`

```
arena_runs()                     -> list[ArenaRun]      # succeeded, has video, not archived
arena_matchup(*, exclude=())     -> ArenaMatchup | None # matchup + the two RunViews
arena_standings()                -> ArenaStandings
```
`next_pair` and `PairSuggestion` are deleted.

### `h3lab/api/routes/arena.py`

| Route | Answers |
| --- | --- |
| `GET /api/arena/next?exclude=<run_id>&…` | The matchup, with both `RunView`s so the page can play the clips. `404` Problem when nothing is comparable, whose detail says why: how many runs are eligible, how many pools they fall into, and what would create a matchup |
| `GET /api/arena/standings` | Per-axis and per-loadout standings with verdicts and counts |

Voting stays `POST /api/votes`, with `axis` set to the matchup's contested field when there
is exactly one. `GET /api/pairs/next` is removed.

### Front end

- `web/src/pages/arena/index.tsx` — the vote page. Two clips at equal size, autoplaying
  muted and looping; **A** and **B** markers; `This one` under each; `Too close to call` and
  `Skip` between them; keys `←`/`→`, `=`, `s`. A held-settings line states what is identical
  on both sides. A match-level badge reads `seed-matched` or `seed-pooled`, the latter
  explaining that the difference includes sampling luck. What differs stays behind a
  disclosure. A session counter, and how many matchups remain unjudged.
- `web/src/pages/arena/standings.tsx` — one tab per axis that has votes, plus Loadouts. Each
  panel leads with the verdict sentence, then a table: rank, value, Elo, W–L–T, win rate,
  votes, seed-matched share, and mean s/it as a guardrail. Thin rows are marked.
- `web/src/pages/arena/nav.tsx` — the `Vote` / `Standings` segmented link pair.
- Rail gains **Arena**; Compare loses its duel tab and its tabs entirely.

### Documentation

`CONTEXT.md` gains: Arena, Pool, Held setting, Contested setting, Matchup, Clean matchup,
Loadout, Standing — and the note that Match level is reused. `README.md` gains the page and
the fairness rule.

## Success criteria

1. Two runs differing in megapixels, duration, RIFE or the upscaler are never offered as a
   matchup, and a vote between them is never counted toward any setting's standing.
2. A sweep over sampler at a fixed seed produces clean, seed-matched matchups, and enough
   votes on it names a winner with its record.
3. Four votes one way name a winner; three-to-one does not, and says why.
4. Votes cast before this feature existed are classified by the same rule, with the ignored
   ones counted and explained rather than dropped.
5. The page cannot tell the voter which settings are in play before the vote, and cannot
   systematically put one setting on the same side.
6. Every ranked row shows its sample size, and speed sits beside the ranking, never inside it.

## Out of scope

Bradley–Terry or any second strength model; per-criterion votes (motion vs detail);
multi-user vote attribution; automatic queueing of the sweep that would fill a gap in the
evidence; changes to stars, insights, or the run leaderboard.
