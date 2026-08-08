from __future__ import annotations

import random

import pytest
from pydantic import ValidationError

from h3lab.domain.config import GenerationConfig, config_hash, recipe_hash
from h3lab.domain.insights import (
    InsightRun,
    analyse,
    available_axes,
    marginal,
    paired,
)
from h3lab.domain.sweeps import SweepAxis, SweepSpec, expand, preview


def make_run(run_id: str, cfg: GenerationConfig, *, stars=None, rate=None, ok=True):
    return InsightRun(
        run_id=run_id,
        config=cfg,
        succeeded=ok,
        stars=stars,
        sec_per_it=rate,
        wall_s=None if rate is None else rate * cfg.effective_steps,
    )


# --- marginal --------------------------------------------------------------


def test_marginal_reports_sample_size_for_every_cell(base_config):
    runs = [
        make_run("a", base_config.merged(cache="spectrum"), stars=8, rate=8.0),
        make_run("b", base_config.merged(cache="spectrum", seed=43), stars=6, rate=9.0),
        make_run("c", base_config.merged(cache="h3"), stars=4, rate=12.0),
    ]
    cells = {cell.value: cell for cell in marginal(runs, "cache")}
    assert cells["spectrum"].n == 2
    assert cells["spectrum"].n_rated == 2
    assert cells["spectrum"].mean_stars == pytest.approx(7.0)
    assert cells["spectrum"].median_stars == pytest.approx(7.0)
    assert cells["h3"].n == 1
    assert all(cell.n >= 1 for cell in cells.values())


def test_marginal_counts_failures_separately(base_config):
    runs = [
        make_run("a", base_config.merged(cache="h3"), ok=False),
        make_run("b", base_config.merged(cache="h3", seed=2), stars=5, rate=10.0),
    ]
    cell = marginal(runs, "cache")[0]
    assert cell.n == 2 and cell.n_failed == 1 and cell.n_rated == 1


# --- paired ----------------------------------------------------------------


def test_paired_groups_only_runs_that_match_on_everything_else(base_config):
    # Two matched groups (steps 20 and steps 30), each holding spectrum and h3.
    runs = []
    for index, steps in enumerate((20, 30)):
        stem = base_config.merged(steps=steps)
        runs.append(make_run(f"s{index}", stem.merged(cache="spectrum"), stars=8, rate=8.0))
        runs.append(make_run(f"h{index}", stem.merged(cache="h3"), stars=7 - index, rate=10.0))

    comparisons = paired(runs, "cache")
    assert len(comparisons) == 1
    comparison = comparisons[0]
    assert comparison.pair_groups == 2
    assert {comparison.value_a, comparison.value_b} == {"spectrum", "h3"}

    # spectrum leads h3 by 1 star in the first group and 2 in the second: mean 1.5.
    sign = 1 if comparison.value_a == "spectrum" else -1
    assert comparison.stars.n == 2
    assert comparison.stars.mean * sign == pytest.approx(1.5)


def test_paired_ignores_groups_with_only_one_axis_value(base_config):
    runs = [
        make_run("a", base_config.merged(cache="spectrum"), stars=8, rate=8.0),
        make_run("b", base_config.merged(steps=30, cache="h3"), stars=4, rate=9.0),
    ]
    assert paired(runs, "cache") == []


def test_paired_speed_delta_is_percent_faster(base_config):
    stem = base_config
    runs = [
        make_run("s", stem.merged(cache="spectrum"), rate=8.0),
        make_run("h", stem.merged(cache="h3"), rate=10.0),
    ]
    comparison = paired(runs, "cache")[0]
    sign = 1 if comparison.value_a == "spectrum" else -1
    # (10 - 8) / 10 = 20% less time per step
    assert comparison.speed_pct.mean * sign == pytest.approx(20.0)


def test_a_pair_is_matched_on_the_seed_so_noise_is_held_constant(base_config):
    stem = base_config
    runs = [
        make_run("s1", stem.merged(cache="spectrum", seed=1), stars=8, rate=8.0),
        make_run("s2", stem.merged(cache="spectrum", seed=2), stars=6, rate=8.0),
        make_run("h1", stem.merged(cache="h3", seed=1), stars=5, rate=10.0),
    ]
    comparison = paired(runs, "cache")[0]
    assert comparison.matched_on == "seed"
    assert comparison.controlled is True
    # Only seed 1 has both values, so only seed 1 is compared: 8 against 5.
    assert comparison.pair_groups == 1
    sign = 1 if comparison.value_a == "spectrum" else -1
    assert comparison.stars.mean * sign == pytest.approx(3.0)


def test_each_matching_seed_contributes_its_own_group(base_config):
    stem = base_config
    runs = []
    for seed, spectrum_stars, h3_stars in ((1, 8, 5), (2, 7, 5), (3, 9, 6)):
        runs.append(
            make_run(f"s{seed}", stem.merged(cache="spectrum", seed=seed), stars=spectrum_stars)
        )
        runs.append(make_run(f"h{seed}", stem.merged(cache="h3", seed=seed), stars=h3_stars))
    comparison = paired(runs, "cache")[0]
    assert comparison.pair_groups == 3
    assert comparison.stars.n == 3
    sign = 1 if comparison.value_a == "spectrum" else -1
    # Deltas of 3, 2 and 3 average to 8/3.
    assert comparison.stars.mean * sign == pytest.approx(8 / 3, rel=1e-3)


def test_replicates_at_one_seed_are_averaged_within_their_group(base_config):
    stem = base_config
    runs = [
        make_run("s1a", stem.merged(cache="spectrum", seed=1), stars=8),
        make_run("s1b", stem.merged(cache="spectrum", seed=1), stars=6),
        make_run("h1", stem.merged(cache="h3", seed=1), stars=5),
    ]
    comparison = paired(runs, "cache")[0]
    assert comparison.pair_groups == 1
    sign = 1 if comparison.value_a == "spectrum" else -1
    # The two spectrum runs average to 7, against h3's 5.
    assert comparison.stars.mean * sign == pytest.approx(2.0)


def test_values_never_run_at_a_matching_seed_fall_back_to_pooling(base_config):
    """A weaker comparison is still offered, but it is labelled as uncontrolled."""
    stem = base_config
    runs = [
        make_run("s1", stem.merged(cache="spectrum", seed=1), stars=8, rate=8.0),
        make_run("h2", stem.merged(cache="h3", seed=2), stars=5, rate=10.0),
    ]
    comparison = paired(runs, "cache")[0]
    assert comparison.matched_on == "recipe"
    assert comparison.controlled is False
    assert comparison.pair_groups == 1


def test_a_pooled_only_comparison_cannot_name_a_winner(base_config):
    stem = base_config
    runs = []
    for seed in (1, 2, 3):
        runs.append(make_run(f"s{seed}", stem.merged(cache="spectrum", seed=seed), stars=9))
    for seed in (11, 12, 13):
        runs.append(make_run(f"h{seed}", stem.merged(cache="h3", seed=seed), stars=2))
    insight = analyse(runs, "cache")
    assert insight.quality_verdict.kind == "inconclusive"
    assert insight.quality_verdict.matched_on == "recipe"
    assert "matching seed" in insight.quality_verdict.reason


# --- verdicts --------------------------------------------------------------


def test_two_consistent_matched_groups_name_a_winner(base_config):
    runs = []
    for index, steps in enumerate((20, 30)):
        stem = base_config.merged(steps=steps)
        runs.append(make_run(f"s{index}", stem.merged(cache="spectrum"), stars=8, rate=8.0))
        runs.append(make_run(f"h{index}", stem.merged(cache="h3"), stars=7 - index, rate=10.0))

    insight = analyse(runs, "cache")
    assert insight.quality_verdict.kind == "winner"
    assert insight.quality_verdict.value == "spectrum"
    assert insight.quality_verdict.pair_groups == 2
    assert "matched" in insight.quality_verdict.reason


def test_one_matched_group_is_inconclusive_and_says_why(base_config):
    runs = [
        make_run("s", base_config.merged(cache="spectrum"), stars=9, rate=8.0),
        make_run("h", base_config.merged(cache="h3"), stars=2, rate=20.0),
    ]
    insight = analyse(runs, "cache")
    assert insight.quality_verdict.kind == "inconclusive"
    assert "1 seed-matched group" in insight.quality_verdict.reason
    assert insight.quality_verdict.value is None


def test_noisy_disagreeing_groups_are_inconclusive(base_config):
    # Group one says spectrum is better by 2, group two says h3 is better by 2.
    runs = []
    for index, (steps, spectrum_stars, h3_stars) in enumerate(
        ((20, 8, 6), (30, 6, 8))
    ):
        stem = base_config.merged(steps=steps)
        runs.append(make_run(f"s{index}", stem.merged(cache="spectrum"), stars=spectrum_stars))
        runs.append(make_run(f"h{index}", stem.merged(cache="h3"), stars=h3_stars))

    verdict = analyse(runs, "cache").quality_verdict
    assert verdict.kind == "inconclusive"
    assert "noisy" in verdict.reason or "spread" in verdict.reason


def test_no_rated_pair_says_so_explicitly(base_config):
    runs = [
        make_run("s", base_config.merged(cache="spectrum"), rate=8.0),
        make_run("h", base_config.merged(cache="h3"), rate=10.0),
    ]
    verdict = analyse(runs, "cache").quality_verdict
    assert verdict.kind == "inconclusive"
    assert "rated runs" in verdict.reason


def test_speed_verdict_is_independent_of_the_quality_verdict(base_config):
    runs = []
    for index, steps in enumerate((20, 30)):
        stem = base_config.merged(steps=steps)
        runs.append(make_run(f"s{index}", stem.merged(cache="spectrum"), rate=8.0))
        runs.append(make_run(f"h{index}", stem.merged(cache="h3"), rate=10.0 + index))
    insight = analyse(runs, "cache")
    assert insight.quality_verdict.kind == "inconclusive"
    assert insight.speed_verdict.kind == "winner"
    assert insight.speed_verdict.value == "spectrum"


def test_marginal_caveat_is_always_attached(base_config):
    insight = analyse([make_run("a", base_config, stars=5)], "cache")
    assert "confounded" in insight.marginal_caveat


def test_unknown_axis_is_a_key_error(base_config):
    with pytest.raises(KeyError):
        analyse([make_run("a", base_config)], "not_a_field")


def test_available_axes_only_offers_axes_that_actually_vary(base_config):
    runs = [
        make_run("a", base_config.merged(cache="spectrum")),
        make_run("b", base_config.merged(cache="h3")),
    ]
    fields = {axis.field for axis in available_axes(runs)}
    assert "cache" in fields
    assert "sampler" not in fields


# --- sweeps ----------------------------------------------------------------


def test_sweep_expands_the_cartesian_product_times_repeats(base_config):
    spec = SweepSpec(
        base=base_config,
        axes=(
            SweepAxis(field="cache", values=("spectrum", "h3")),
            SweepAxis(field="steps", values=(10, 20, 30)),
        ),
        repeats=2,
        seed_strategy="increment",
    )
    assert spec.combinations == 6
    assert spec.count == 12

    configs = expand(spec)
    assert len(configs) == 12
    assert len({config_hash(c) for c in configs}) == 12
    assert len({recipe_hash(c) for c in configs}) == 6


def test_increment_strategy_walks_the_seed_from_the_base(base_config):
    spec = SweepSpec(
        base=base_config.merged(seed=100),
        axes=(SweepAxis(field="cache", values=("h3",)),),
        repeats=3,
        seed_strategy="increment",
    )
    assert [c.seed for c in expand(spec)] == [100, 101, 102]


def test_fixed_strategy_produces_true_duplicates_for_timing_variance(base_config):
    spec = SweepSpec(
        base=base_config,
        axes=(SweepAxis(field="cache", values=("h3",)),),
        repeats=3,
    )
    hashes = {config_hash(c) for c in expand(spec)}
    assert len(hashes) == 1


def test_random_strategy_draws_distinct_seeds(base_config):
    spec = SweepSpec(
        base=base_config,
        axes=(SweepAxis(field="cache", values=("h3",)),),
        repeats=5,
        seed_strategy="random",
    )
    seeds = [c.seed for c in expand(spec, rng=random.Random(7))]
    assert len(set(seeds)) == 5


def test_sweep_rejects_seed_as_an_axis(base_config):
    with pytest.raises(ValidationError):
        SweepAxis(field="seed", values=(1, 2))


def test_sweep_rejects_an_unknown_field():
    with pytest.raises(ValidationError):
        SweepAxis(field="nope", values=(1, 2))


def test_sweep_refuses_an_absurd_expansion(base_config):
    with pytest.raises(ValidationError):
        SweepSpec(
            base=base_config,
            axes=(SweepAxis(field="steps", values=tuple(range(1, 60))),),
            repeats=20,
        )


def test_invalid_combination_fails_at_preview_not_at_run_time(base_config):
    # Switching mode to r2v without references is impossible; expansion must say so now.
    with pytest.raises(ValidationError):
        expand(
            SweepSpec(
                base=base_config,
                axes=(SweepAxis(field="mode", values=("flf2v", "r2v")),),
            )
        )


def test_preview_marks_configs_that_already_ran(base_config):
    spec = SweepSpec(
        base=base_config,
        axes=(SweepAxis(field="cache", values=("spectrum", "h3")),),
    )
    first = expand(spec)[0]
    result = preview(spec, existing={config_hash(first): "RUN123"})
    assert result.count == 2
    assert result.duplicate_count == 1
    assert result.new_count == 1
    marked = [item for item in result.items if item.already_ran]
    assert marked[0].existing_run_id == "RUN123"
