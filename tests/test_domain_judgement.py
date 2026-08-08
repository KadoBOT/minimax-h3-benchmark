from __future__ import annotations

import pytest
from pydantic import ValidationError

from h3lab.domain.ids import ID_LENGTH, is_valid_id, new_id
from h3lab.domain.rating import ELO_BASE, Rating, Vote, replay_elo, replay_pairwise
from h3lab.domain.scoring import (
    ScoreInput,
    ScoreWeights,
    percentile_ranks,
    score_runs,
)


# --- ids -------------------------------------------------------------------


def test_ids_sort_in_creation_order_across_milliseconds():
    early = new_id(now_ms=1_700_000_000_000)
    later = new_id(now_ms=1_700_000_000_001)
    assert early < later


def test_ids_created_in_the_same_millisecond_still_sort_in_call_order():
    stamp = 1_700_000_000_000
    burst = [new_id(now_ms=stamp) for _ in range(50)]
    assert burst == sorted(burst)


def test_ids_are_unique_and_well_formed():
    made = {new_id() for _ in range(10_000)}
    assert len(made) == 10_000
    sample = next(iter(made))
    assert len(sample) == ID_LENGTH
    assert is_valid_id(sample)
    assert not is_valid_id("nope")


# --- ratings ---------------------------------------------------------------


def test_criteria_must_be_known_names_in_range():
    with pytest.raises(ValidationError):
        Rating(run_id="r", stars=5, criteria={"vibes": 3})
    with pytest.raises(ValidationError):
        Rating(run_id="r", stars=5, criteria={"motion": 9})


def test_stars_outside_one_to_ten_are_rejected():
    with pytest.raises(ValidationError):
        Rating(run_id="r", stars=0)
    with pytest.raises(ValidationError):
        Rating(run_id="r", stars=11)


def test_composite_falls_back_to_stars_without_criteria():
    assert Rating(run_id="r", stars=7).composite == 7.0


def test_composite_maps_the_five_point_criteria_scale_onto_stars():
    # All fives is the top of the criteria scale, which is 10 stars.
    top = Rating(run_id="r", stars=4, criteria={"motion": 5, "detail": 5})
    assert top.composite == pytest.approx(10.0)
    # All ones is the bottom, which is 1 star.
    bottom = Rating(run_id="r", stars=9, criteria={"motion": 1, "detail": 1})
    assert bottom.composite == pytest.approx(1.0)
    # Mid scale (3 of 5) lands mid stars (5.5 of 1..10).
    mid = Rating(run_id="r", stars=2, criteria={"motion": 3})
    assert mid.composite == pytest.approx(5.5)


# --- elo -------------------------------------------------------------------


def test_single_win_between_equals_moves_both_by_half_of_k():
    # Both start at 1500, so expected score is 0.5 and the swing is 24 * 0.5 = 12.
    votes = [Vote(id="v1", run_a="a", run_b="b", winner="a")]
    table = replay_elo(votes)
    assert table["a"].rating == pytest.approx(1512.0)
    assert table["b"].rating == pytest.approx(1488.0)
    assert table["a"].wins == 1 and table["b"].losses == 1


def test_tie_between_equals_moves_nothing():
    table = replay_elo([Vote(id="v1", run_a="a", run_b="b", winner=None)])
    assert table["a"].rating == pytest.approx(ELO_BASE)
    assert table["b"].rating == pytest.approx(ELO_BASE)
    assert table["a"].ties == 1


def test_second_win_gains_less_than_the_first():
    votes = [
        Vote(id="v1", run_a="a", run_b="b", winner="a"),
        Vote(id="v2", run_a="a", run_b="b", winner="a"),
    ]
    table = replay_elo(votes)
    # After 1512 vs 1488 the favourite is expected to win, so the second gain is smaller.
    assert 1512.0 < table["a"].rating < 1524.0
    assert table["a"].wins == 2


def test_win_rate_ignores_ties_and_is_none_without_decisions():
    table = replay_elo(
        [
            Vote(id="v1", run_a="a", run_b="b", winner="a"),
            Vote(id="v2", run_a="a", run_b="b", winner=None),
        ]
    )
    assert table["a"].win_rate == pytest.approx(1.0)
    assert table["a"].games == 2
    assert replay_elo([]) == {}


def test_self_vote_and_corrupt_winner_are_skipped_not_fatal():
    votes = [
        Vote(id="v1", run_a="a", run_b="a", winner="a"),
        Vote(id="v2", run_a="a", run_b="b", winner="zzz"),
    ]
    table = replay_elo(votes)
    assert table["a"].rating == pytest.approx(ELO_BASE)
    assert table["a"].games == 0


def test_vote_loser_is_the_other_side():
    vote = Vote(id="v", run_a="a", run_b="b", winner="b")
    assert vote.loser == "a"
    assert not vote.is_tie
    assert Vote(id="v", run_a="a", run_b="b").loser is None


def test_the_same_maths_ranks_anything_with_a_key():
    """Setting values are ranked by the code that ranks runs, not by a second copy of it."""
    table = replay_pairwise(
        [("euler", "dpmpp_2m", "euler"), ("euler", "dpmpp_2m", "euler")]
    )
    # First game between equals: 24 * (1 - 0.5) = 12, so 1512 vs 1488.
    # Second: expected = 1 / (1 + 10 ** (-24 / 400)) = 0.5344822, so the gain is
    # 24 * 0.4655178 = 11.1724.
    assert table["euler"].rating == pytest.approx(1523.1724, abs=1e-3)
    assert table["dpmpp_2m"].rating == pytest.approx(1476.8276, abs=1e-3)
    assert table["euler"].wins == 2
    assert table["euler"].decided == 2
    assert table["dpmpp_2m"].win_rate == pytest.approx(0.0)


def test_a_pairwise_replay_skips_a_self_game_and_an_unknown_winner():
    table = replay_pairwise([("euler", "euler", "euler"), ("euler", "res_2s", "zzz")])
    assert table["euler"].games == 0
    assert table["euler"].rating == pytest.approx(ELO_BASE)


# --- scoring ---------------------------------------------------------------


def test_percentile_ranks_spread_over_zero_to_one():
    assert percentile_ranks([]) == []
    assert percentile_ranks([5]) == [0.5]
    assert percentile_ranks([10, 20, 30]) == [0.0, 0.5, 1.0]


def test_percentile_ranks_average_ties():
    # Two tied smallest values share ranks 0 and 1, averaging to 0.5 of 3 -> 0.25.
    assert percentile_ranks([1, 1, 9]) == [0.25, 0.25, 1.0]


def test_percentile_ranks_resist_a_single_outlier():
    ranks = percentile_ranks([8.0, 10.0, 1000.0])
    assert ranks == [0.0, 0.5, 1.0]


def test_weights_are_normalised_to_sum_to_one():
    weights = ScoreWeights(quality=3, speed=1)
    assert weights.quality == pytest.approx(0.75)
    assert weights.speed == pytest.approx(0.25)
    zeroed = ScoreWeights(quality=0, speed=0)
    assert zeroed.quality == 1.0 and zeroed.speed == 0.0


def test_score_blends_hand_computed_quality_and_speed():
    rows = [
        ScoreInput(run_id="fast_good", stars=10, sec_per_it=8.0),
        ScoreInput(run_id="mid", stars=5, sec_per_it=10.0),
        ScoreInput(run_id="slow_bad", stars=1, sec_per_it=12.0),
    ]
    scored = {row.run_id: row for row in score_runs(rows, ScoreWeights(quality=0.5, speed=0.5))}

    # stars 10 -> (10-1)/9 = 1.0; 5 -> 4/9; 1 -> 0.0
    assert scored["fast_good"].quality == pytest.approx(1.0)
    assert scored["mid"].quality == pytest.approx(4 / 9, abs=1e-4)
    assert scored["slow_bad"].quality == pytest.approx(0.0)
    # sec_per_it percentiles are 0.0/0.5/1.0, inverted into speed 1.0/0.5/0.0
    assert scored["fast_good"].speed == pytest.approx(1.0)
    assert scored["slow_bad"].speed == pytest.approx(0.0)
    assert scored["fast_good"].score == pytest.approx(1.0)
    assert scored["mid"].score == pytest.approx((4 / 9 + 0.5) / 2, abs=1e-4)
    assert scored["slow_bad"].score == pytest.approx(0.0)
    assert scored["fast_good"].rank == 1


def test_weighting_speed_alone_reorders_by_speed():
    rows = [
        ScoreInput(run_id="pretty_slow", stars=10, sec_per_it=20.0),
        ScoreInput(run_id="plain_fast", stars=4, sec_per_it=5.0),
    ]
    by_quality = score_runs(rows, ScoreWeights(quality=1, speed=0))
    by_speed = score_runs(rows, ScoreWeights(quality=0, speed=1))
    assert by_quality[0].run_id == "pretty_slow"
    assert by_speed[0].run_id == "plain_fast"


def test_unrated_runs_are_flagged_and_ranked_last():
    rows = [
        ScoreInput(run_id="unjudged", sec_per_it=1.0),
        ScoreInput(run_id="poor", stars=1, sec_per_it=99.0),
    ]
    scored = score_runs(rows)
    assert scored[0].run_id == "poor"
    assert scored[1].run_id == "unjudged"
    assert scored[1].unrated is True
    assert scored[1].quality_source == "none"


def test_elo_stands_in_for_quality_when_stars_are_absent():
    rows = [
        ScoreInput(run_id="voted_up", elo=1600.0, sec_per_it=10.0),
        ScoreInput(run_id="voted_down", elo=1400.0, sec_per_it=10.0),
    ]
    scored = score_runs(rows)
    assert scored[0].run_id == "voted_up"
    assert scored[0].quality_source == "elo"
    assert scored[0].unrated is False


def test_missing_speed_does_not_drag_the_score_down():
    rows = [
        ScoreInput(run_id="no_timing", stars=10),
        ScoreInput(run_id="timed", stars=10, sec_per_it=9.0),
    ]
    scored = {row.run_id: row for row in score_runs(rows)}
    assert scored["no_timing"].speed is None
    assert scored["no_timing"].score == pytest.approx(1.0)
