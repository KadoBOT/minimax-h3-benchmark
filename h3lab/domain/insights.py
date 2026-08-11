"""Which configuration actually works: marginal and paired axis analysis.

A marginal average over "every run that used spectrum" is confounded — those runs also
differed in steps, weights, and prompt. A paired comparison holds everything else fixed by
grouping runs that are identical apart from the axis under test. Marginal numbers are still
reported, labelled as confounded, because they are useful for orientation.

Pairs are matched on the seed wherever possible. Two runs at the same seed differing in one
setting is the strongest evidence this data can offer: the sampling noise is the same on
both sides, so the difference is the setting. Where the two sides were never run at a
matching seed, the comparison falls back to pooling across seeds and says so — that is
weaker, and is reported as such rather than being presented as a controlled result.

Nothing here declares a winner on a single observation. Every figure carries its sample
size, and a thin comparison is reported as inconclusive rather than as a near-tie.
"""

from __future__ import annotations

import statistics
from typing import Callable, Iterable, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, computed_field

from h3lab.domain.config import (
    DERIVED_FROM,
    FIELD_LABELS,
    GenerationConfig,
    canonical_form,
    field_display,
    recipe_hash,
)

AxisKind = Literal["categorical", "numeric", "boolean"]
MatchLevel = Literal["seed", "recipe"]

MIN_PAIR_GROUPS = 2


class AxisDef(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: str
    label: str
    kind: AxisKind


AXES: tuple[AxisDef, ...] = (
    AxisDef(field="diffusion_model", label="Weights", kind="categorical"),
    AxisDef(field="cache", label="Cache", kind="categorical"),
    AxisDef(field="cache_preset", label="Cache preset", kind="categorical"),
    AxisDef(field="sol_attn", label="Sol-Attn", kind="boolean"),
    AxisDef(field="sol_preset", label="Sol preset", kind="categorical"),
    AxisDef(field="sampler", label="Sampler", kind="categorical"),
    AxisDef(field="scheduler", label="Scheduler", kind="categorical"),
    AxisDef(field="steps", label="Steps", kind="numeric"),
    AxisDef(field="turbo", label="Turbo", kind="boolean"),
    AxisDef(field="turbo_lora", label="Turbo LoRA", kind="categorical"),
    AxisDef(field="turbo_lora_strength", label="Turbo strength", kind="numeric"),
    AxisDef(field="interp", label="Interpolation", kind="categorical"),
    AxisDef(field="upscaler", label="Upscaler", kind="boolean"),
    AxisDef(field="clean_vram", label="Clean VRAM", kind="boolean"),
    AxisDef(field="mp", label="Megapixels", kind="numeric"),
    AxisDef(field="duration_s", label="Duration", kind="numeric"),
    AxisDef(field="aspect_ratio", label="Aspect", kind="categorical"),
    AxisDef(field="mode", label="Mode", kind="categorical"),
)

AXES_BY_FIELD: dict[str, AxisDef] = {axis.field: axis for axis in AXES}


class InsightRun(BaseModel):
    """The projection of a run that analysis needs. Keeps this module free of storage."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    config: GenerationConfig
    succeeded: bool
    stars: int | None = None
    elo: float | None = None
    sec_per_it: float | None = None
    wall_s: float | None = None


class MarginalCell(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: str
    n: int
    n_rated: int
    n_failed: int
    mean_stars: float | None = None
    median_stars: float | None = None
    mean_sec_per_it: float | None = None
    mean_wall_s: float | None = None
    mean_elo: float | None = None


class DeltaStat(BaseModel):
    """A paired difference with the evidence behind it."""

    model_config = ConfigDict(frozen=True)

    n: int
    mean: float | None = None
    stderr: float | None = None
    better_a: int = 0
    better_b: int = 0
    ties: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def conclusive(self) -> bool:
        if self.n < MIN_PAIR_GROUPS or self.mean is None:
            return False
        if self.stderr is None:
            return abs(self.mean) > 0
        return abs(self.mean) > self.stderr


class PairedComparison(BaseModel):
    """``a`` versus ``b`` across every group where both appear with everything else equal."""

    model_config = ConfigDict(frozen=True)

    value_a: str
    value_b: str
    pair_groups: int
    stars: DeltaStat
    speed_pct: DeltaStat
    matched_on: MatchLevel = "seed"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def controlled(self) -> bool:
        """True when both sides were run at the same seed, so noise is held constant."""
        return self.matched_on == "seed"


class Verdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["winner", "inconclusive"]
    metric: Literal["stars", "speed"]
    value: str | None = None
    runner_up: str | None = None
    margin: float | None = None
    pair_groups: int = 0
    matched_on: MatchLevel | None = None
    reason: str


class AxisInsight(BaseModel):
    model_config = ConfigDict(frozen=True)

    axis: str
    label: str
    kind: AxisKind
    total_runs: int
    values: list[str]
    marginal: list[MarginalCell] = Field(default_factory=list)
    paired: list[PairedComparison] = Field(default_factory=list)
    quality_verdict: Verdict
    speed_verdict: Verdict
    marginal_caveat: str = (
        "Marginal averages are confounded: they mix runs that also differed in other "
        "settings. Use the paired verdict to support a claim."
    )


def axis_value(cfg: GenerationConfig, axis: str) -> str:
    return field_display(axis, getattr(cfg, axis))


def _mean(values: Sequence[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def _stderr(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    return round(statistics.stdev(values) / (len(values) ** 0.5), 4)


def marginal(runs: Sequence[InsightRun], axis: str) -> list[MarginalCell]:
    buckets: dict[str, list[InsightRun]] = {}
    for run in runs:
        buckets.setdefault(axis_value(run.config, axis), []).append(run)

    cells: list[MarginalCell] = []
    for value, group in buckets.items():
        stars = [float(r.stars) for r in group if r.stars is not None]
        rates = [r.sec_per_it for r in group if r.sec_per_it]
        walls = [r.wall_s for r in group if r.wall_s]
        elos = [r.elo for r in group if r.elo is not None]
        cells.append(
            MarginalCell(
                value=value,
                n=len(group),
                n_rated=len(stars),
                n_failed=sum(1 for r in group if not r.succeeded),
                mean_stars=_mean(stars),
                median_stars=round(statistics.median(stars), 4) if stars else None,
                mean_sec_per_it=_mean([float(x) for x in rates]),
                mean_wall_s=_mean([float(x) for x in walls]),
                mean_elo=_mean([float(x) for x in elos]),
            )
        )
    cells.sort(key=lambda cell: (-(cell.mean_stars or -1), -cell.n, cell.value))
    return cells


def _held_apart(axis: str) -> set[str]:
    """The axis, plus any field the validator derives from it.

    ``cache_enabled`` follows ``cache``, so two runs differing only in cache differ in two
    fields on paper. Left in the key, that made the cache axis impossible to pair on: no two
    runs ever looked "identical apart from the axis", and the most important comparison in
    the lab silently returned nothing.
    """
    return {axis} | {
        derived for derived, determinant in DERIVED_FROM.items() if determinant == axis
    }


def _seed_matched_key(cfg: GenerationConfig, axis: str) -> str:
    """Identity of everything except the axis — the seed included."""
    return canonical_form(cfg, exclude=_held_apart(axis))


def _recipe_matched_key(cfg: GenerationConfig, axis: str) -> str:
    """Identity of everything except the axis and the seed."""
    return recipe_hash(cfg, also_exclude=_held_apart(axis))


def _delta_stat(
    deltas: Sequence[float],
    *,
    tie_epsilon: float = 1e-9,
) -> DeltaStat:
    if not deltas:
        return DeltaStat(n=0)
    better_a = sum(1 for d in deltas if d > tie_epsilon)
    better_b = sum(1 for d in deltas if d < -tie_epsilon)
    ties = len(deltas) - better_a - better_b
    return DeltaStat(
        n=len(deltas),
        mean=_mean(deltas),
        stderr=_stderr(deltas),
        better_a=better_a,
        better_b=better_b,
        ties=ties,
    )


def _compare_within(
    runs: Sequence[InsightRun],
    axis: str,
    key: Callable[[GenerationConfig, str], str],
    level: MatchLevel,
) -> dict[tuple[str, str], PairedComparison]:
    groups: dict[str, dict[str, list[InsightRun]]] = {}
    for run in runs:
        groups.setdefault(key(run.config, axis), {}).setdefault(
            axis_value(run.config, axis), []
        ).append(run)

    star_deltas: dict[tuple[str, str], list[float]] = {}
    speed_deltas: dict[tuple[str, str], list[float]] = {}
    group_counts: dict[tuple[str, str], int] = {}

    for by_value in groups.values():
        values = sorted(by_value)
        if len(values) < 2:
            continue
        for index, value_a in enumerate(values):
            for value_b in values[index + 1 :]:
                pair = (value_a, value_b)
                group_counts[pair] = group_counts.get(pair, 0) + 1

                stars_a = [float(r.stars) for r in by_value[value_a] if r.stars is not None]
                stars_b = [float(r.stars) for r in by_value[value_b] if r.stars is not None]
                if stars_a and stars_b:
                    star_deltas.setdefault(pair, []).append(
                        statistics.fmean(stars_a) - statistics.fmean(stars_b)
                    )

                rate_a = [r.sec_per_it for r in by_value[value_a] if r.sec_per_it]
                rate_b = [r.sec_per_it for r in by_value[value_b] if r.sec_per_it]
                if rate_a and rate_b:
                    mean_a = statistics.fmean([float(x) for x in rate_a])
                    mean_b = statistics.fmean([float(x) for x in rate_b])
                    slower = max(mean_a, mean_b)
                    if slower > 0:
                        # Share of the slower option's step time that the faster one saves,
                        # so the magnitude reads the same whichever way round the pair is
                        # sorted. Positive means a is the faster side.
                        speed_deltas.setdefault(pair, []).append(
                            (mean_b - mean_a) / slower * 100.0
                        )

    return {
        pair: PairedComparison(
            value_a=pair[0],
            value_b=pair[1],
            pair_groups=count,
            stars=_delta_stat(star_deltas.get(pair, [])),
            speed_pct=_delta_stat(speed_deltas.get(pair, []), tie_epsilon=0.5),
            matched_on=level,
        )
        for pair, count in group_counts.items()
    }


def paired(runs: Sequence[InsightRun], axis: str) -> list[PairedComparison]:
    """Compare axis values only inside groups that are otherwise identical.

    Seed-matched groups are preferred. A value pair that was never run at a matching seed
    falls back to a seed-pooled comparison, which is kept separate via ``matched_on`` so a
    weaker comparison is never mistaken for a controlled one.
    """
    strict = _compare_within(runs, axis, _seed_matched_key, "seed")
    pooled = _compare_within(runs, axis, _recipe_matched_key, "recipe")
    merged = dict(strict)
    for pair, comparison in pooled.items():
        if pair not in merged:
            merged[pair] = comparison

    comparisons = list(merged.values())
    comparisons.sort(
        key=lambda c: (c.matched_on != "seed", -c.pair_groups, c.value_a, c.value_b)
    )
    return comparisons


def _verdict_from(
    comparisons: Sequence[PairedComparison],
    metric: Literal["stars", "speed"],
    axis_label: str,
) -> Verdict:
    stats = [(c, c.stars if metric == "stars" else c.speed_pct) for c in comparisons]
    with_data = [(c, s) for c, s in stats if s.n > 0]

    if not with_data:
        unit = "rated runs" if metric == "stars" else "timed runs"
        return Verdict(
            kind="inconclusive",
            metric=metric,
            reason=(
                f"No matched pair of {axis_label} values has {unit} on both sides yet. "
                "Run the same recipe with two different values to compare."
            ),
        )

    conclusive = [(c, s) for c, s in with_data if s.conclusive]
    if not conclusive:
        best_comparison, best_stat = max(with_data, key=lambda item: item[1].n)
        best_n = best_stat.n
        if best_comparison.matched_on == "recipe":
            reason = (
                f"{best_comparison.value_a} and {best_comparison.value_b} were never run at "
                "a matching seed, so the only comparison available mixes different seeds. "
                "Rerun one of them at the other's seed to get a controlled answer."
            )
        elif best_n < MIN_PAIR_GROUPS:
            reason = (
                f"Only {best_n} seed-matched group so far — at least {MIN_PAIR_GROUPS} are "
                "needed before naming a winner."
            )
        else:
            reason = (
                "The differences are smaller than their own spread across "
                f"{best_n} seed-matched groups: too noisy to call."
            )
        return Verdict(
            kind="inconclusive",
            metric=metric,
            pair_groups=best_n,
            matched_on=best_comparison.matched_on,
            reason=reason,
        )

    # Score each value by how often, and by how much, it wins a conclusive comparison.
    tally: dict[str, float] = {}
    groups_for: dict[str, int] = {}
    for comparison, stat in conclusive:
        mean = stat.mean or 0.0
        winner = comparison.value_a if mean > 0 else comparison.value_b
        loser = comparison.value_b if mean > 0 else comparison.value_a
        tally[winner] = tally.get(winner, 0.0) + abs(mean)
        tally.setdefault(loser, 0.0)
        groups_for[winner] = max(groups_for.get(winner, 0), stat.n)

    ranked = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
    best, margin = ranked[0]
    runner_up = ranked[1][0] if len(ranked) > 1 else None
    unit = "★" if metric == "stars" else "% faster per step"
    level: MatchLevel = (
        "seed" if any(c.matched_on == "seed" for c, _ in conclusive) else "recipe"
    )
    control = "seed-matched" if level == "seed" else "seed-pooled"
    return Verdict(
        kind="winner",
        metric=metric,
        value=best,
        runner_up=runner_up,
        margin=round(margin, 4),
        pair_groups=groups_for.get(best, 0),
        matched_on=level,
        reason=(
            f"{best} wins by {margin:.2f}{unit} across "
            f"{groups_for.get(best, 0)} {control} group(s)."
        ),
    )


def analyse(
    runs: Iterable[InsightRun],
    axis: str,
) -> AxisInsight:
    """Full analysis for one axis: marginal cells, paired comparisons, and verdicts."""
    definition = AXES_BY_FIELD.get(axis)
    if definition is None:
        raise KeyError(f"unknown axis {axis!r}; expected one of {sorted(AXES_BY_FIELD)}")

    rows = [run for run in runs]
    cells = marginal(rows, axis)
    comparisons = paired(rows, axis)
    return AxisInsight(
        axis=axis,
        label=definition.label,
        kind=definition.kind,
        total_runs=len(rows),
        values=[cell.value for cell in cells],
        marginal=cells,
        paired=comparisons,
        quality_verdict=_verdict_from(comparisons, "stars", definition.label),
        speed_verdict=_verdict_from(comparisons, "speed", definition.label),
    )


def available_axes(runs: Sequence[InsightRun]) -> list[AxisDef]:
    """Axes on which the recorded runs actually vary — the only ones worth offering."""
    out: list[AxisDef] = []
    for definition in AXES:
        seen = {axis_value(run.config, definition.field) for run in runs}
        if len(seen) > 1:
            out.append(definition)
    return out


def axis_label(field: str) -> str:
    definition = AXES_BY_FIELD.get(field)
    return definition.label if definition else FIELD_LABELS.get(field, field)
