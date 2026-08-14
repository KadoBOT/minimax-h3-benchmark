"""The arena: which pairs are fair to compare, and what a vote on one is evidence of.

A preference between two clips is the most reliable judgement this lab can collect, and the
easiest to waste. Show a voter a 1 MP interpolated clip beside a 0.5 MP raw one and they will
pick the first every time — correctly, and about nothing anybody wanted to know.

So the comparison is fixed before the question is asked. Every field of a generation config is
one of three things:

*Held* — the subject and the presentation. Mode, prompt, media, aspect, megapixels, duration,
frame interpolation, the upscaler. Two runs may only meet if all of these are identical.
Interpolation and the upscaler are here rather than in the ranking for the reason they exist:
they make a clip look better without making the generation better, so a voter who can see one
is answering a different question. Megapixels and duration flatter a clip the same way.

*Contested* — how the pixels were sampled. Weights, sampler, scheduler, steps, turbo and which
distilled LoRA it uses, cache, attention. These are allowed to differ, and these are what the
standings rank. A turbo LoRA belongs here for the reason the whole feature exists: swapping one
distilled LoRA for another changes the sampling and nothing about the subject.

*Ignored* — the seed and the VRAM cleanup. Clearing VRAM cannot change a pixel. The seed can
change everything, but it is noise rather than a setting: holding it would be the strongest
possible control and would also empty the arena, because most pairs worth comparing were
never run at a matching seed. So a matchup that happens to share a seed is *seed-matched* and
its difference is purely the setting; one that does not is *seed-pooled* and includes
sampling luck. Both are offered, the first by preference, and both say which they are.

The evidence rule follows from the same care. A vote between two runs differing in one
contested setting is evidence about that setting. A vote between runs differing in four is
evidence about all four together and about none of them individually — so it ranks the
*loadout* and nothing else. Splitting it four ways would be the confounded marginal average
this codebase refuses to draw conclusions from elsewhere.

Nothing here does I/O; the module imports the config vocabulary and the Elo maths and nothing
further.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass
from typing import Iterable, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, computed_field

from h3lab.domain.config import (
    DEFAULT_TURBO_STRENGTH,
    DERIVED_FROM,
    FIELD_LABELS,
    HASHED_FIELDS,
    MODE_NEEDS,
    FieldDiff,
    GenerationConfig,
    canonical_form,
    digest,
    field_display,
    lora_stem,
    model_stem,
)
from h3lab.domain.rating import Vote, replay_pairwise

# What the voter must not be able to tell apart: the subject, and how it is presented.
HELD_FIELDS: frozenset[str] = frozenset(
    {
        "mode",
        "prompt",
        "first_frame",
        "last_frame",
        "ref_images",
        "ref_videos",
        "ref_video_audios",
        "ref_audios",
        "ref_image_size",
        "aspect_ratio",
        "mp",
        "duration_s",
        "interp",
        "upscaler",
        "widgets",
    }
)

# What the arena ranks. `cache_enabled` is derived from `cache`; it is contested with it and
# suppressed when both differ, so one change never reads as two.
CONTESTED_FIELDS: frozenset[str] = frozenset(
    {
        "diffusion_model",
        "sampler",
        "scheduler",
        "steps",
        "turbo",
        "turbo_lora",
        "turbo_lora_strength",
        "cache",
        "cache_enabled",
        "cache_preset",
        "sol_attn",
        "sol_preset",
    }
)

# Noise, and housekeeping that cannot reach the pixels.
IGNORED_FIELDS: frozenset[str] = frozenset({"seed", "clean_vram"})

_UNCLASSIFIED = set(HASHED_FIELDS) - HELD_FIELDS - CONTESTED_FIELDS - IGNORED_FIELDS
if _UNCLASSIFIED:  # pragma: no cover - a partition bug is not a runtime condition
    raise RuntimeError(f"config fields missing an arena class: {sorted(_UNCLASSIFIED)}")

# The order held and contested fields are reported in, so two pages never disagree.
HELD_ORDER: tuple[str, ...] = tuple(f for f in HASHED_FIELDS if f in HELD_FIELDS)
CONTESTED_ORDER: tuple[str, ...] = tuple(f for f in HASHED_FIELDS if f in CONTESTED_FIELDS)

# Four decided votes before a record is allowed to mean anything. Two votes are two votes.
MIN_DECIDED_VOTES = 4


class ArenaRun(BaseModel):
    """The projection of a run the arena needs. Keeps this module free of storage."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    config: GenerationConfig
    sec_per_it: float | None = None


class Matchup(BaseModel):
    """One fair pair, ready to be shown. ``a`` is the left-hand side."""

    model_config = ConfigDict(frozen=True)

    a_run_id: str
    b_run_id: str
    pool: str
    pool_label: str
    held: dict[str, str] = Field(default_factory=dict)
    differences: list[FieldDiff] = Field(default_factory=list)
    axis: str | None = None
    seed_matched: bool = False
    reason: str = ""


class ArenaStanding(BaseModel):
    """One competitor's record: a setting value, or a whole loadout."""

    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    rating: float
    wins: int = 0
    losses: int = 0
    ties: int = 0
    seed_matched: int = 0
    runs: int = 0
    mean_sec_per_it: float | None = None
    rank: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def games(self) -> int:
        return self.wins + self.losses + self.ties

    @computed_field  # type: ignore[prop-decorator]
    @property
    def decided(self) -> int:
        return self.wins + self.losses

    @computed_field  # type: ignore[prop-decorator]
    @property
    def win_rate(self) -> float | None:
        return None if self.decided == 0 else self.wins / self.decided


class ArenaVerdict(BaseModel):
    """What the votes on one axis support, stated with the record behind it."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["winner", "inconclusive"]
    value: str | None = None
    runner_up: str | None = None
    wins: int = 0
    losses: int = 0
    ties: int = 0
    reason: str = ""


class ArenaAxis(BaseModel):
    model_config = ConfigDict(frozen=True)

    axis: str
    label: str
    votes: int
    standings: list[ArenaStanding] = Field(default_factory=list)
    verdict: ArenaVerdict


class ArenaStandings(BaseModel):
    model_config = ConfigDict(frozen=True)

    axes: list[ArenaAxis] = Field(default_factory=list)
    loadouts: list[ArenaStanding] = Field(default_factory=list)
    votes_counted: int = 0
    votes_ignored: int = 0
    ignored_reasons: dict[str, int] = Field(default_factory=dict)
    pools: int = 0
    runs: int = 0
    matchups: int = 0
    clean_matchups: int = 0


# --- identity ---------------------------------------------------------------


def pool_key(cfg: GenerationConfig) -> str:
    """Identity of everything that must match. Equal keys mean the pair is comparable."""
    return digest(canonical_form(cfg, exclude=CONTESTED_FIELDS | IGNORED_FIELDS))


def pool_label(cfg: GenerationConfig) -> str:
    """The pool in one line: what both sides of every matchup in it hold."""
    parts = [
        cfg.mode,
        f"{cfg.mp:g} MP",
        f"{cfg.duration_s:g}s",
        cfg.aspect_ratio,
        cfg.interp if cfg.interp != "off" else "no interp",
        "upscaled" if cfg.upscaler else "no upscale",
    ]
    return " · ".join(parts)


# Fields only some modes use. Listing "Ref image size: match" beside a text-to-video pair
# states a fact about nothing, and a guarantee that lists irrelevancies is read past.
_MODE_SPECIFIC: frozenset[str] = frozenset().union(*(set(need.accepts) for need in MODE_NEEDS))
_ACCEPTED_BY: dict[str, frozenset[str]] = {
    need.mode: frozenset(need.accepts) for need in MODE_NEEDS
}


def held_summary(cfg: GenerationConfig) -> dict[str, str]:
    """Every held setting this mode actually uses, labelled, with the empty ones left out."""
    accepted = _ACCEPTED_BY.get(cfg.mode, frozenset())
    out: dict[str, str] = {}
    for field in HELD_ORDER:
        if field in _MODE_SPECIFIC and field not in accepted:
            continue
        shown = field_display(field, getattr(cfg, field))
        if shown == "—":
            continue
        out[FIELD_LABELS.get(field, field)] = shown
    return out


def loadout_key(cfg: GenerationConfig) -> str:
    """Identity of the contested settings — the arena's whole-configuration competitor."""
    return digest(canonical_form(cfg, exclude=HELD_FIELDS | IGNORED_FIELDS))


def loadout_label(cfg: GenerationConfig) -> str:
    parts = [
        model_stem(cfg.diffusion_model),
        f"{cfg.sampler}/{cfg.scheduler}",
        f"{cfg.effective_steps}st",
        f"{cfg.cache}/{cfg.cache_preset[:3]}" if cfg.cache_active else "nocache",
        f"sol/{cfg.sol_preset[:3]}" if cfg.sol_attn else "nosol",
    ]
    if cfg.turbo:
        turbo = f"turbo/{lora_stem(cfg.turbo_lora_file)}"
        if cfg.turbo_lora_strength != DEFAULT_TURBO_STRENGTH:
            turbo += f"@{cfg.turbo_lora_strength:g}"
        parts.append(turbo)
    return " · ".join(parts)


def value_label(field: str, value: str) -> str:
    """A weights filename is 60 characters of shared prefix; rank it by the rest."""
    if field == "diffusion_model":
        return model_stem(value)
    if field == "turbo_lora":
        return lora_stem(value)
    return value


def contested_differences(a: GenerationConfig, b: GenerationConfig) -> list[FieldDiff]:
    """Only the ranked settings that differ, in canonical order, ``a`` first."""
    found: dict[str, FieldDiff] = {}
    for field in CONTESTED_ORDER:
        values = [field_display(field, getattr(cfg, field)) for cfg in (a, b)]
        if values[0] != values[1]:
            found[field] = FieldDiff(
                field=field, label=FIELD_LABELS.get(field, field), values=values
            )
    for derived, determinants in DERIVED_FROM.items():
        if derived in found and any(name in found for name in determinants):
            del found[derived]
    return [found[field] for field in CONTESTED_ORDER if field in found]


# --- choosing what to show next ---------------------------------------------


@dataclass(frozen=True, slots=True)
class Candidate:
    """A legal pair: same pool, and at least one contested setting apart."""

    a: str
    b: str
    differences: tuple[FieldDiff, ...]
    seed_matched: bool

    @property
    def clean(self) -> bool:
        """Exactly one contested difference — the only shape that can name a setting."""
        return len(self.differences) == 1


def legal_matchups(runs: Sequence[ArenaRun]) -> list[Candidate]:
    """Every pair worth offering. Pairs are enumerated inside a pool, never across them."""
    pools: dict[str, list[ArenaRun]] = {}
    for item in runs:
        pools.setdefault(pool_key(item.config), []).append(item)

    out: list[Candidate] = []
    for members in pools.values():
        for index, first in enumerate(members):
            for second in members[index + 1 :]:
                differences = contested_differences(first.config, second.config)
                if not differences:
                    continue
                out.append(
                    Candidate(
                        a=first.run_id,
                        b=second.run_id,
                        differences=tuple(differences),
                        seed_matched=first.config.seed == second.config.seed,
                    )
                )
    return out


def _pair_id(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def _vote_counts(votes: Iterable[Vote]) -> tuple[dict[tuple[str, str], int], dict[str, int]]:
    per_pair: dict[tuple[str, str], int] = {}
    per_run: dict[str, int] = {}
    for item in votes:
        pair = _pair_id(item.run_a, item.run_b)
        per_pair[pair] = per_pair.get(pair, 0) + 1
        per_run[item.run_a] = per_run.get(item.run_a, 0) + 1
        per_run[item.run_b] = per_run.get(item.run_b, 0) + 1
    return per_pair, per_run


def next_matchup(
    runs: Sequence[ArenaRun],
    votes: Sequence[Vote],
    *,
    exclude: Iterable[str] = (),
    rng: random.Random | None = None,
) -> Matchup | None:
    """The most useful fair pair available, with its sides randomised.

    Preference order: a pair differing in exactly one setting, because that is the only vote
    that can name a setting; then the pair asked about least, so the whole set is swept before
    anything is asked twice; then a seed-matched pair over a seed-pooled one; then the runs
    the arena has seen least. Ties are broken at random, and so is which run goes on the left —
    a fixed side would bake position bias into every ranking.
    """
    generator = rng or random.Random()
    blocked = set(exclude)
    by_id = {item.run_id: item for item in runs}
    candidates = [
        candidate
        for candidate in legal_matchups(runs)
        if candidate.a not in blocked and candidate.b not in blocked
    ]
    if not candidates:
        return None

    per_pair, per_run = _vote_counts(votes)

    def cost(candidate: Candidate) -> tuple[int, int, int, int, float]:
        return (
            0 if candidate.clean else 1,
            per_pair.get(_pair_id(candidate.a, candidate.b), 0),
            0 if candidate.seed_matched else 1,
            per_run.get(candidate.a, 0) + per_run.get(candidate.b, 0),
            generator.random(),
        )

    chosen = min(candidates, key=cost)
    left, right = (
        (chosen.a, chosen.b) if generator.random() < 0.5 else (chosen.b, chosen.a)
    )
    first, second = by_id[left], by_id[right]
    differences = contested_differences(first.config, second.config)
    axis = differences[0].field if len(differences) == 1 else None

    if axis is not None and chosen.seed_matched:
        reason = (
            f"Same seed, and {differences[0].label.lower()} is the only setting that differs."
        )
    elif axis is not None:
        reason = (
            f"{differences[0].label} is the only setting that differs, but the seeds are not "
            "the same, so sampling luck is part of what you are seeing."
        )
    else:
        reason = (
            f"{len(differences)} settings differ, so this vote ranks the whole configuration "
            "rather than any one of them."
        )

    return Matchup(
        a_run_id=left,
        b_run_id=right,
        pool=pool_key(first.config),
        pool_label=pool_label(first.config),
        held=held_summary(first.config),
        differences=differences,
        axis=axis,
        seed_matched=chosen.seed_matched,
        reason=reason,
    )


# --- what the votes add up to -----------------------------------------------

IGNORED_MISSING = "a run was deleted or archived"
IGNORED_OFF_POOL = "the two runs were not comparable"
IGNORED_SAME_SETTINGS = "the two runs used the same settings"


@dataclass(slots=True)
class _Tally:
    """Everything one competitor accumulates that Elo does not carry."""

    seed_matched: int = 0
    runs: set[str] = None  # type: ignore[assignment]
    rates: list[float] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.runs = set()
        self.rates = []

    def saw(self, run: ArenaRun, *, seed_matched: bool) -> None:
        if seed_matched:
            self.seed_matched += 1
        self.runs.add(run.run_id)
        if run.sec_per_it:
            self.rates.append(float(run.sec_per_it))


def _mean(values: Sequence[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def _record(
    head_to_head: dict[tuple[str, str, str], list[int]],
    axis: str,
    left: str,
    right: str,
) -> tuple[int, int, int]:
    """``left``'s wins, losses and ties against ``right`` alone."""
    low, high = (left, right) if left <= right else (right, left)
    wins_low, wins_high, ties = head_to_head.get((axis, low, high), [0, 0, 0])
    return (wins_low, wins_high, ties) if left == low else (wins_high, wins_low, ties)


def _decisive(wins: int, losses: int) -> bool:
    """More than a coin flip would give.

    The standard deviation of ``wins − losses`` when both sides are equally good is the square
    root of the number of decided votes, so anything inside that is noise wearing a lead.
    """
    decided = wins + losses
    return decided >= MIN_DECIDED_VOTES and abs(wins - losses) > math.sqrt(decided)


def _verdict(
    axis: str,
    label: str,
    rows: Sequence[ArenaStanding],
    head_to_head: dict[tuple[str, str, str], list[int]],
) -> ArenaVerdict:
    if len(rows) < 2:
        only = rows[0] if rows else None
        return ArenaVerdict(
            kind="inconclusive",
            value=only.key if only else None,
            reason=(
                f"Only one {label.lower()} value has been in the arena. Run the same recipe "
                "with a second value and the comparison becomes possible."
            ),
        )

    leader, runner_up = rows[0], rows[1]
    wins, losses, ties = _record(head_to_head, axis, leader.key, runner_up.key)
    decided = wins + losses

    if decided == 0:
        return ArenaVerdict(
            kind="inconclusive",
            value=leader.key,
            runner_up=runner_up.key,
            ties=ties,
            reason=(
                f"{leader.label} and {runner_up.label} lead the table but have never met head "
                "to head, so the gap between them is inferred rather than observed."
            ),
        )
    if decided < MIN_DECIDED_VOTES:
        return ArenaVerdict(
            kind="inconclusive",
            value=leader.key,
            runner_up=runner_up.key,
            wins=wins,
            losses=losses,
            ties=ties,
            reason=(
                f"{leader.label} leads {runner_up.label} {wins}–{losses}, on fewer than "
                f"{MIN_DECIDED_VOTES} decided votes. That is too few to be anything yet."
            ),
        )
    if wins <= losses or not _decisive(wins, losses):
        return ArenaVerdict(
            kind="inconclusive",
            value=leader.key,
            runner_up=runner_up.key,
            wins=wins,
            losses=losses,
            ties=ties,
            reason=(
                f"{leader.label} and {runner_up.label} stand {wins}–{losses} over {decided} "
                "decided votes, which a coin lands on often enough to mean nothing."
            ),
        )
    return ArenaVerdict(
        kind="winner",
        value=leader.key,
        runner_up=runner_up.key,
        wins=wins,
        losses=losses,
        ties=ties,
        reason=(
            f"{leader.label} beats {runner_up.label} {wins}–{losses} across {decided} decided "
            "votes — more than a coin flip would give."
        ),
    )


def _table(
    games: Sequence[tuple[str, str, str | None]],
    tallies: dict[str, _Tally],
    labels: dict[str, str],
) -> list[ArenaStanding]:
    replayed = replay_pairwise(games)
    ordered = sorted(replayed.values(), key=lambda item: (-item.rating, item.key))
    rows: list[ArenaStanding] = []
    for index, item in enumerate(ordered):
        tally = tallies.get(item.key) or _Tally()
        rows.append(
            ArenaStanding(
                key=item.key,
                label=labels.get(item.key, item.key),
                rating=item.rating,
                wins=item.wins,
                losses=item.losses,
                ties=item.ties,
                seed_matched=tally.seed_matched,
                runs=len(tally.runs),
                mean_sec_per_it=_mean(tally.rates),
                rank=index + 1,
            )
        )
    return rows


def standings(runs: Sequence[ArenaRun], votes: Sequence[Vote]) -> ArenaStandings:
    """Replay every vote against the runs as they are now.

    Fairness is recomputed here rather than stored at vote time, so a vote cast before this
    module existed is judged by the same rule as one cast a minute ago, and a correction to
    the rule reaches the whole history. A vote that cannot be counted is reported with its
    reason instead of being quietly dropped.
    """
    by_id = {item.run_id: item for item in runs}

    axis_games: dict[str, list[tuple[str, str, str | None]]] = {}
    axis_tallies: dict[str, dict[str, _Tally]] = {}
    axis_labels: dict[str, dict[str, str]] = {}
    head_to_head: dict[tuple[str, str, str], list[int]] = {}

    loadout_games: list[tuple[str, str, str | None]] = []
    loadout_tallies: dict[str, _Tally] = {}
    loadout_labels: dict[str, str] = {}

    counted = 0
    ignored: dict[str, int] = {}

    def ignore(reason: str) -> None:
        ignored[reason] = ignored.get(reason, 0) + 1

    for item in votes:
        left, right = by_id.get(item.run_a), by_id.get(item.run_b)
        if left is None or right is None or left.run_id == right.run_id:
            ignore(IGNORED_MISSING)
            continue
        if item.winner is not None and item.winner not in (item.run_a, item.run_b):
            ignore(IGNORED_MISSING)
            continue
        if pool_key(left.config) != pool_key(right.config):
            ignore(IGNORED_OFF_POOL)
            continue
        differences = contested_differences(left.config, right.config)
        if not differences:
            ignore(IGNORED_SAME_SETTINGS)
            continue

        counted += 1
        seed_matched = left.config.seed == right.config.seed
        won_by_left = item.winner == item.run_a
        won_by_right = item.winner == item.run_b

        key_left, key_right = loadout_key(left.config), loadout_key(right.config)
        loadout_labels[key_left] = loadout_label(left.config)
        loadout_labels[key_right] = loadout_label(right.config)
        loadout_games.append(
            (
                key_left,
                key_right,
                key_left if won_by_left else key_right if won_by_right else None,
            )
        )
        for key, source in ((key_left, left), (key_right, right)):
            loadout_tallies.setdefault(key, _Tally()).saw(source, seed_matched=seed_matched)

        if len(differences) != 1:
            continue

        axis = differences[0].field
        value_left, value_right = differences[0].values
        axis_labels.setdefault(axis, {})[value_left] = value_label(axis, value_left)
        axis_labels[axis][value_right] = value_label(axis, value_right)
        axis_games.setdefault(axis, []).append(
            (
                value_left,
                value_right,
                value_left if won_by_left else value_right if won_by_right else None,
            )
        )
        tallies = axis_tallies.setdefault(axis, {})
        tallies.setdefault(value_left, _Tally()).saw(left, seed_matched=seed_matched)
        tallies.setdefault(value_right, _Tally()).saw(right, seed_matched=seed_matched)

        low, high = sorted((value_left, value_right))
        record = head_to_head.setdefault((axis, low, high), [0, 0, 0])
        if item.winner is None:
            record[2] += 1
        else:
            winning_value = value_left if won_by_left else value_right
            record[0 if winning_value == low else 1] += 1

    axes: list[ArenaAxis] = []
    for axis in CONTESTED_ORDER:
        games = axis_games.get(axis)
        if not games:
            continue
        rows = _table(games, axis_tallies.get(axis, {}), axis_labels.get(axis, {}))
        axes.append(
            ArenaAxis(
                axis=axis,
                label=FIELD_LABELS.get(axis, axis),
                votes=len(games),
                standings=rows,
                verdict=_verdict(axis, FIELD_LABELS.get(axis, axis), rows, head_to_head),
            )
        )

    candidates = legal_matchups(runs)
    return ArenaStandings(
        axes=axes,
        loadouts=_table(loadout_games, loadout_tallies, loadout_labels),
        votes_counted=counted,
        votes_ignored=sum(ignored.values()),
        ignored_reasons=ignored,
        pools=len({pool_key(item.config) for item in runs}),
        runs=len(runs),
        matchups=len(candidates),
        clean_matchups=sum(1 for candidate in candidates if candidate.clean),
    )


__all__ = [
    "ArenaAxis",
    "ArenaRun",
    "ArenaStanding",
    "ArenaStandings",
    "ArenaVerdict",
    "CONTESTED_FIELDS",
    "HELD_FIELDS",
    "IGNORED_FIELDS",
    "MIN_DECIDED_VOTES",
    "Matchup",
    "contested_differences",
    "held_summary",
    "legal_matchups",
    "loadout_key",
    "loadout_label",
    "next_matchup",
    "pool_key",
    "pool_label",
    "standings",
    "value_label",
]
