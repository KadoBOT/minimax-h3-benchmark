"""The arena: which pairs are fair, and what a vote on one is evidence of.

Every expected number here is worked out by hand from the Elo definition or from the
coin-flip rule, never by calling the code a second way.
"""

from __future__ import annotations

import random

import pytest

from h3lab.domain.arena import (
    CONTESTED_FIELDS,
    HELD_FIELDS,
    IGNORED_FIELDS,
    MIN_DECIDED_VOTES,
    ArenaRun,
    contested_differences,
    held_summary,
    legal_matchups,
    loadout_key,
    loadout_label,
    next_matchup,
    pool_key,
    pool_label,
    standings,
    value_label,
)
from h3lab.domain.config import HASHED_FIELDS
from h3lab.domain.rating import Vote


def run(run_id: str, config, sec_per_it: float | None = None) -> ArenaRun:
    return ArenaRun(run_id=run_id, config=config, sec_per_it=sec_per_it)


def vote(vote_id: str, a: str, b: str, winner: str | None) -> Vote:
    return Vote(id=vote_id, run_a=a, run_b=b, winner=winner)


def wins_for(runs, votes, times: int, *, winner_id: str, a: str, b: str) -> list[Vote]:
    return [vote(f"v{i}", a, b, winner_id) for i in range(times)]


# --- the partition ----------------------------------------------------------


def test_every_config_field_is_classified_exactly_once():
    """A config field added later must be classified, not silently ignored."""
    assert HELD_FIELDS | CONTESTED_FIELDS | IGNORED_FIELDS == set(HASHED_FIELDS)
    assert not HELD_FIELDS & CONTESTED_FIELDS
    assert not HELD_FIELDS & IGNORED_FIELDS
    assert not CONTESTED_FIELDS & IGNORED_FIELDS


def test_presentation_is_held_and_sampling_is_contested():
    # The four the request names: they flatter a clip without improving the generation.
    for field in ("mp", "duration_s", "interp", "upscaler"):
        assert field in HELD_FIELDS
    # The subject has to be the same clip, or the vote is about the scene.
    for field in ("mode", "prompt", "first_frame", "ref_images", "aspect_ratio"):
        assert field in HELD_FIELDS
    for field in ("diffusion_model", "sampler", "scheduler", "steps"):
        assert field in CONTESTED_FIELDS
    # Swapping one distilled LoRA for another changes the sampling and nothing else, which is
    # exactly what the arena exists to rank.
    for field in ("turbo", "turbo_lora", "turbo_lora_strength"):
        assert field in CONTESTED_FIELDS
    # Noise is not a setting, and clearing VRAM cannot change a pixel.
    assert IGNORED_FIELDS == {"seed", "clean_vram"}


# --- pools ------------------------------------------------------------------


def test_a_pool_is_everything_the_voter_must_not_be_able_to_see(base_config):
    same = pool_key(base_config)
    assert pool_key(base_config.merged(sampler="dpmpp_2m")) == same
    assert pool_key(base_config.merged(steps=30)) == same
    assert pool_key(base_config.merged(seed=99)) == same
    assert pool_key(base_config.merged(clean_vram=True)) == same

    assert pool_key(base_config.merged(mp=1.0)) != same
    assert pool_key(base_config.merged(duration_s=8.0)) != same
    assert pool_key(base_config.merged(interp="rife")) != same
    assert pool_key(base_config.merged(interp="film")) != pool_key(
        base_config.merged(interp="rife")
    )
    assert pool_key(base_config.merged(upscaler=True)) != same
    assert pool_key(base_config.merged(prompt="something else entirely")) != same


def test_the_pool_states_what_is_held(base_config):
    held = held_summary(base_config)
    assert held["Megapixels"] == "0.5 MP"
    assert held["Duration"] == "5s"
    assert held["Interpolation"] == "off"
    assert held["Upscaler"] == "off"
    # A contested setting must never appear in the list of what is held.
    assert "Sampler" not in held
    assert "0.5 MP" in pool_label(base_config)
    assert "no interp" in pool_label(base_config)
    assert "film" in pool_label(base_config.merged(interp="film"))


def test_a_setting_this_mode_never_uses_is_left_out_of_the_guarantee(base_config, t2v_config):
    """"Ref image size: match" beside a text-to-video pair is a fact about nothing."""
    assert "Ref image size" not in held_summary(base_config)
    assert "First frame" in held_summary(base_config)
    assert "First frame" not in held_summary(t2v_config)
    assert "Ref image size" in held_summary(
        t2v_config.merged(mode="r2v", ref_images=["one.png"])
    )


# --- what differs -----------------------------------------------------------


def test_only_contested_settings_are_reported_as_differences(base_config):
    other = base_config.merged(sampler="dpmpp_2m", seed=77, clean_vram=True)
    assert [diff.field for diff in contested_differences(base_config, other)] == ["sampler"]


def test_a_derived_field_is_not_counted_as_a_second_difference(base_config):
    """`cache_enabled` follows `cache`; reporting both would make a clean pair look dirty."""
    off = base_config.merged(cache="none")
    on = base_config.merged(cache="spectrum")
    assert [diff.field for diff in contested_differences(off, on)] == ["cache"]


def test_a_pair_that_differs_only_in_the_seed_is_not_a_matchup(base_config):
    pair = [run("a", base_config), run("b", base_config.merged(seed=77))]
    assert legal_matchups(pair) == []


def test_runs_from_different_pools_are_never_a_matchup(base_config):
    pair = [run("a", base_config), run("b", base_config.merged(mp=1.0, sampler="dpmpp_2m"))]
    assert legal_matchups(pair) == []


# --- choosing the next matchup ---------------------------------------------


def test_the_clean_seed_matched_pair_is_offered_before_the_rest(base_config):
    runs = [
        run("clean", base_config.merged(sampler="dpmpp_2m")),
        run("base", base_config),
        run("messy", base_config.merged(sampler="res_2s", steps=30, cache="easy", seed=77)),
    ]
    found = next_matchup(runs, [], rng=random.Random(0))
    assert found is not None
    assert {found.a_run_id, found.b_run_id} == {"base", "clean"}
    assert found.axis == "sampler"
    assert found.seed_matched is True
    assert len(found.differences) == 1


def test_a_matchup_of_several_settings_names_no_axis(base_config):
    runs = [
        run("a", base_config),
        run("b", base_config.merged(sampler="dpmpp_2m", steps=30)),
    ]
    found = next_matchup(runs, [], rng=random.Random(0))
    assert found is not None
    assert found.axis is None
    assert len(found.differences) == 2
    assert "whole configuration" in found.reason


def test_the_least_voted_pair_comes_first(base_config):
    runs = [
        run("a", base_config),
        run("b", base_config.merged(sampler="dpmpp_2m")),
        run("c", base_config.merged(sampler="res_2s")),
    ]
    # a-b and a-c and b-c are all clean. Spend votes on everything but b-c.
    votes = [
        vote("v1", "a", "b", "a"),
        vote("v2", "a", "c", "a"),
        vote("v3", "a", "b", "b"),
    ]
    found = next_matchup(runs, votes, rng=random.Random(1))
    assert found is not None
    assert {found.a_run_id, found.b_run_id} == {"b", "c"}


def test_a_seed_matched_pair_is_preferred_to_a_pooled_one(base_config):
    runs = [
        run("a", base_config),
        run("pooled", base_config.merged(sampler="dpmpp_2m", seed=77)),
        run("matched", base_config.merged(sampler="res_2s")),
    ]
    # Every pair here is clean and unvoted, so the seed decides which is offered.
    found = next_matchup(runs, [], rng=random.Random(3))
    assert found is not None
    assert {found.a_run_id, found.b_run_id} == {"a", "matched"}


def test_which_side_a_run_appears_on_is_randomised(base_config):
    """A fixed rule would bake position bias into every ranking."""
    runs = [run("a", base_config), run("b", base_config.merged(sampler="dpmpp_2m"))]
    seen = {
        next_matchup(runs, [], rng=random.Random(seed)).a_run_id for seed in range(40)
    }
    assert seen == {"a", "b"}


def test_the_left_hand_values_belong_to_the_left_hand_run(base_config):
    runs = [run("a", base_config), run("b", base_config.merged(sampler="dpmpp_2m"))]
    for seed in range(20):
        found = next_matchup(runs, [], rng=random.Random(seed))
        expected = "euler" if found.a_run_id == "a" else "dpmpp_2m"
        assert found.differences[0].values[0] == expected


def test_a_skipped_run_is_not_offered_again(base_config):
    runs = [
        run("a", base_config),
        run("b", base_config.merged(sampler="dpmpp_2m")),
        run("c", base_config.merged(sampler="res_2s")),
    ]
    found = next_matchup(runs, [], exclude=("a",), rng=random.Random(0))
    assert found is not None
    assert {found.a_run_id, found.b_run_id} == {"b", "c"}
    assert next_matchup(runs, [], exclude=("a", "b", "c"), rng=random.Random(0)) is None


def test_nothing_comparable_answers_with_nothing(base_config):
    assert next_matchup([], [], rng=random.Random(0)) is None
    assert next_matchup([run("a", base_config)], [], rng=random.Random(0)) is None


# --- standings --------------------------------------------------------------


def three_samplers(base_config):
    return [
        run("a", base_config, sec_per_it=8.0),
        run("b", base_config.merged(sampler="dpmpp_2m"), sec_per_it=12.0),
    ]


def test_a_clean_vote_ranks_the_value_that_won(base_config):
    runs = three_samplers(base_config)
    board = standings(runs, [vote("v1", "a", "b", "a")])

    assert board.votes_counted == 1
    axis = next(item for item in board.axes if item.axis == "sampler")
    assert [row.key for row in axis.standings] == ["euler", "dpmpp_2m"]
    assert axis.standings[0].rating == pytest.approx(1512.0)
    assert axis.standings[0].wins == 1
    assert axis.standings[0].rank == 1
    assert axis.standings[1].rating == pytest.approx(1488.0)


def test_speed_travels_beside_the_ranking_and_never_inside_it(base_config):
    board = standings(three_samplers(base_config), [vote("v1", "a", "b", "a")])
    axis = next(item for item in board.axes if item.axis == "sampler")
    by_value = {row.key: row for row in axis.standings}
    assert by_value["euler"].mean_sec_per_it == pytest.approx(8.0)
    assert by_value["dpmpp_2m"].mean_sec_per_it == pytest.approx(12.0)
    # The slower one is not penalised in the rating; that is the point of a guardrail.
    assert by_value["dpmpp_2m"].rating == pytest.approx(1488.0)


def test_a_vote_across_pools_is_ignored_and_says_so(base_config):
    runs = [run("a", base_config), run("b", base_config.merged(mp=1.0, sampler="dpmpp_2m"))]
    board = standings(runs, [vote("v1", "a", "b", "a")])
    assert board.votes_counted == 0
    assert board.votes_ignored == 1
    assert sum(board.ignored_reasons.values()) == 1
    assert board.axes == []


def test_a_vote_between_identical_settings_is_ignored(base_config):
    runs = [run("a", base_config), run("b", base_config.merged(seed=77))]
    board = standings(runs, [vote("v1", "a", "b", "a")])
    assert board.votes_counted == 0
    assert board.votes_ignored == 1


def test_a_vote_on_a_run_that_is_gone_is_ignored(base_config):
    board = standings([run("a", base_config)], [vote("v1", "a", "vanished", "a")])
    assert board.votes_counted == 0
    assert board.votes_ignored == 1


def test_a_multi_difference_vote_ranks_the_loadout_and_no_single_setting(base_config):
    runs = [run("a", base_config), run("b", base_config.merged(sampler="dpmpp_2m", steps=30))]
    board = standings(runs, [vote("v1", "a", "b", "a")])

    assert board.votes_counted == 1
    assert board.axes == []
    assert [row.rating for row in board.loadouts] == [
        pytest.approx(1512.0),
        pytest.approx(1488.0),
    ]
    assert board.loadouts[0].label == loadout_label(base_config)


def test_a_clean_vote_ranks_the_loadout_too(base_config):
    board = standings(three_samplers(base_config), [vote("v1", "a", "b", "a")])
    assert len(board.loadouts) == 2
    assert board.loadouts[0].rating == pytest.approx(1512.0)


def test_seed_matched_evidence_is_counted_separately(base_config):
    runs = [
        run("a", base_config),
        run("b", base_config.merged(sampler="dpmpp_2m")),
        run("c", base_config.merged(sampler="dpmpp_2m", seed=77)),
    ]
    board = standings(runs, [vote("v1", "a", "b", "a"), vote("v2", "a", "c", "a")])
    axis = next(item for item in board.axes if item.axis == "sampler")
    euler = next(row for row in axis.standings if row.key == "euler")
    assert euler.games == 2
    assert euler.seed_matched == 1
    assert euler.runs == 1


# --- verdicts ---------------------------------------------------------------


def sampler_board(base_config, results: list[str | None]):
    runs = three_samplers(base_config)
    votes = [
        vote(f"v{index}", "a", "b", winner) for index, winner in enumerate(results)
    ]
    return standings(runs, votes)


def verdict_for(board):
    return next(item for item in board.axes if item.axis == "sampler").verdict


def test_four_nil_names_a_winner(base_config):
    verdict = verdict_for(sampler_board(base_config, ["a"] * MIN_DECIDED_VOTES))
    assert verdict.kind == "winner"
    assert verdict.value == "euler"
    assert verdict.runner_up == "dpmpp_2m"
    assert (verdict.wins, verdict.losses) == (4, 0)
    assert "4–0" in verdict.reason


def test_three_to_one_is_what_a_coin_does(base_config):
    # |3 - 1| = 2, and the standard deviation of a fair coin over 4 votes is also 2.
    verdict = verdict_for(sampler_board(base_config, ["a", "a", "a", "b"]))
    assert verdict.kind == "inconclusive"
    assert "coin" in verdict.reason


def test_two_nil_is_too_few_votes_to_mean_anything(base_config):
    verdict = verdict_for(sampler_board(base_config, ["a", "a"]))
    assert verdict.kind == "inconclusive"
    assert str(MIN_DECIDED_VOTES) in verdict.reason


def test_ties_are_kept_but_decide_nothing(base_config):
    board = sampler_board(base_config, [None, None, None, None])
    axis = next(item for item in board.axes if item.axis == "sampler")
    assert axis.standings[0].ties == 4
    assert axis.standings[0].decided == 0
    assert axis.verdict.kind == "inconclusive"
    assert axis.verdict.ties == 4


def test_one_value_alone_cannot_win(base_config):
    """Two runs, same sampler, different steps: the steps axis has two values, sampler none."""
    runs = [run("a", base_config), run("b", base_config.merged(steps=30))]
    board = standings(runs, [vote("v1", "a", "b", "a")])
    assert [item.axis for item in board.axes] == ["steps"]


def test_a_leader_that_never_met_the_runner_up_is_inconclusive(base_config):
    runs = [
        run("a", base_config),
        run("b", base_config.merged(sampler="dpmpp_2m")),
        run("c", base_config.merged(sampler="res_2s")),
    ]
    # euler beats res_2s five times; dpmpp_2m beats res_2s once and never meets euler.
    votes = [vote(f"v{index}", "a", "c", "a") for index in range(5)]
    votes.append(vote("v9", "b", "c", "b"))
    verdict = verdict_for(standings(runs, votes))
    assert verdict.kind == "inconclusive"
    assert "never met" in verdict.reason


def test_a_leader_beaten_head_to_head_is_not_declared_the_winner(base_config):
    """Rating can lead on other opponents; the claim is about these two."""
    runs = [
        run("a", base_config),
        run("b", base_config.merged(sampler="dpmpp_2m")),
        run("c", base_config.merged(sampler="res_2s")),
    ]
    votes = [vote(f"w{index}", "a", "c", "a") for index in range(6)]
    votes += [vote(f"x{index}", "a", "b", "b") for index in range(2)]
    board = standings(runs, votes)
    axis = next(item for item in board.axes if item.axis == "sampler")
    assert axis.standings[0].key == "euler"
    assert axis.verdict.kind == "inconclusive"


# --- counts and labels ------------------------------------------------------


def test_the_board_says_how_much_is_left_to_judge(base_config):
    runs = [
        run("a", base_config),
        run("b", base_config.merged(sampler="dpmpp_2m")),
        run("c", base_config.merged(steps=30)),
        run("d", base_config.merged(mp=1.0)),
    ]
    board = standings(runs, [])
    assert board.runs == 4
    assert board.pools == 2
    # a-b, a-c, b-c are legal; d is alone in its pool at 1 MP.
    assert board.matchups == 3
    # b-c differs in both sampler and steps, so it can name neither.
    assert board.clean_matchups == 2


def test_a_weights_filename_is_ranked_by_the_part_that_distinguishes_it(base_config):
    assert value_label("diffusion_model", "minimax_h3_fl2va_pruned_nvfp4.safetensors") == (
        "fl2va_pruned_nvfp4"
    )
    assert value_label("sampler", "euler") == "euler"


def test_a_loadout_reads_as_the_settings_it_is(base_config):
    label = loadout_label(base_config)
    assert "euler/beta57" in label
    assert "20st" in label
    assert loadout_key(base_config) != loadout_key(base_config.merged(sampler="dpmpp_2m"))
    assert loadout_key(base_config) == loadout_key(base_config.merged(seed=99))


def test_two_turbo_loras_are_two_loadouts_and_read_as_different_ones(base_config):
    first = base_config.merged(turbo=True, turbo_lora="minimax_h3_turbo_a_4step.safetensors")
    second = base_config.merged(turbo=True, turbo_lora="minimax_h3_turbo_b_4step.safetensors")

    assert loadout_key(first) != loadout_key(second)
    assert loadout_label(first) != loadout_label(second)
    assert "turbo/a_4step" in loadout_label(first)
    assert "@0.6" in loadout_label(first.merged(turbo_lora_strength=0.6))


def test_a_vote_between_two_turbo_loras_ranks_the_lora(base_config):
    """The point of the axis: two runs that differ only in which LoRA was loaded."""
    runs = [
        run("a", base_config.merged(turbo=True, turbo_lora="minimax_h3_turbo_a_4step.safetensors")),
        run("b", base_config.merged(turbo=True, turbo_lora="minimax_h3_turbo_b_4step.safetensors")),
    ]
    differences = contested_differences(runs[0].config, runs[1].config)
    assert [item.field for item in differences] == ["turbo_lora"]

    board = standings(runs, [vote("v1", "a", "b", "a")])
    axis = next(item for item in board.axes if item.axis == "turbo_lora")
    assert axis.label == "Turbo LoRA"
    assert [row.label for row in axis.standings] == ["a_4step", "b_4step"]


def test_a_lora_only_names_itself_once_turbo_is_already_the_difference(base_config):
    """Turbo off has no LoRA, so "which LoRA" is not a second thing that changed."""
    differences = contested_differences(
        base_config.merged(turbo=False), base_config.merged(turbo=True)
    )
    assert [item.field for item in differences] == ["turbo"]
