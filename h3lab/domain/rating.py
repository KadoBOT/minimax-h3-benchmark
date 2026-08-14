"""Human judgement: absolute ratings and relative votes.

Absolute scales drift as a session goes on. Votes do not, which is why both exist: stars
are fast, votes are trustworthy, and the leaderboard can use either.
"""

from __future__ import annotations

from typing import Annotated, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

CriterionName = Literal["motion", "adherence", "artifacts", "detail", "consistency"]

CRITERIA: tuple[CriterionName, ...] = (
    "motion",
    "adherence",
    "artifacts",
    "detail",
    "consistency",
)

CRITERION_LABELS: dict[str, str] = {
    "motion": "Motion",
    "adherence": "Prompt adherence",
    "artifacts": "Artifact-free",
    "detail": "Detail",
    "consistency": "Temporal consistency",
}

STARS_MIN = 1
STARS_MAX = 10
CRITERION_MIN = 1
CRITERION_MAX = 5

ELO_BASE = 1500.0
ELO_K = 24.0


class Rating(BaseModel):
    """One person's absolute judgement of one run.

    ``artifacts`` is scored so higher is better (5 = nothing objectionable), matching every
    other criterion, so a naive mean is meaningful.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    stars: Annotated[int, Field(ge=STARS_MIN, le=STARS_MAX)]
    criteria: dict[str, int] = Field(default_factory=dict)
    updated_at: str | None = None

    @field_validator("criteria")
    @classmethod
    def _valid_criteria(cls, value: dict[str, int]) -> dict[str, int]:
        clean: dict[str, int] = {}
        for name, score in (value or {}).items():
            if name not in CRITERIA:
                raise ValueError(f"unknown criterion {name!r}; expected one of {CRITERIA}")
            number = int(score)
            if not CRITERION_MIN <= number <= CRITERION_MAX:
                raise ValueError(
                    f"criterion {name!r} must be {CRITERION_MIN}–{CRITERION_MAX}"
                )
            clean[name] = number
        return clean

    @property
    def composite(self) -> float:
        """Criteria mean on the stars scale when present, else stars itself."""
        if not self.criteria:
            return float(self.stars)
        mean_5 = sum(self.criteria.values()) / len(self.criteria)
        return (mean_5 - 1.0) / 4.0 * 9.0 + 1.0


class Vote(BaseModel):
    """A relative judgement. ``winner is None`` means the pair was a tie."""

    model_config = ConfigDict(frozen=True)

    id: str
    run_a: str
    run_b: str
    winner: str | None = None
    axis: str | None = None
    created_at: str | None = None

    @property
    def loser(self) -> str | None:
        if self.winner is None:
            return None
        return self.run_b if self.winner == self.run_a else self.run_a

    @property
    def is_tie(self) -> bool:
        return self.winner is None


class EloEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    rating: float = ELO_BASE
    wins: int = 0
    losses: int = 0
    ties: int = 0

    # Computed rather than plain properties: a rating without its sample size invites
    # reading noise as a result, so both travel to the client with the rating.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def games(self) -> int:
        return self.wins + self.losses + self.ties

    @computed_field  # type: ignore[prop-decorator]
    @property
    def win_rate(self) -> float | None:
        decided = self.wins + self.losses
        if decided == 0:
            return None
        return self.wins / decided


class Standing(BaseModel):
    """Pairwise strength of one competitor, whatever the competitor happens to be.

    A run, a single setting value, a whole set of settings: the maths only needs a key and
    a log of games, so it is written once here rather than once per thing being ranked.
    """

    model_config = ConfigDict(frozen=True)

    key: str
    rating: float = ELO_BASE
    wins: int = 0
    losses: int = 0
    ties: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def games(self) -> int:
        return self.wins + self.losses + self.ties

    @computed_field  # type: ignore[prop-decorator]
    @property
    def decided(self) -> int:
        """Games that named a winner. A tie is evidence, but not of a difference."""
        return self.wins + self.losses

    @computed_field  # type: ignore[prop-decorator]
    @property
    def win_rate(self) -> float | None:
        return None if self.decided == 0 else self.wins / self.decided


def _expected(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def replay_pairwise(
    games: Iterable[tuple[str, str, str | None]],
    *,
    k: float = ELO_K,
    base: float = ELO_BASE,
) -> dict[str, Standing]:
    """Elo over ``(left, right, winner)`` triples, replayed from the whole log.

    Replaying rather than incrementing means a deleted or corrected game cannot leave a
    permanently skewed rating behind, and the numbers are reproducible from the log alone.
    Elo is path dependent, so the log order is the answer's order.
    """
    ratings: dict[str, float] = {}
    wins: dict[str, int] = {}
    losses: dict[str, int] = {}
    ties: dict[str, int] = {}

    def seen(key: str) -> None:
        ratings.setdefault(key, base)
        wins.setdefault(key, 0)
        losses.setdefault(key, 0)
        ties.setdefault(key, 0)

    for left, right, winner in games:
        if left == right:
            continue
        seen(left)
        seen(right)
        rating_left = ratings[left]
        rating_right = ratings[right]
        expected_left = _expected(rating_left, rating_right)

        if winner is None:
            score_left = 0.5
            ties[left] += 1
            ties[right] += 1
        elif winner == left:
            score_left = 1.0
            wins[left] += 1
            losses[right] += 1
        elif winner == right:
            score_left = 0.0
            losses[left] += 1
            wins[right] += 1
        else:
            # Winner is not in the pair — a corrupt row, not a reason to abort a replay.
            continue

        delta = k * (score_left - expected_left)
        ratings[left] = rating_left + delta
        ratings[right] = rating_right - delta

    return {
        key: Standing(
            key=key,
            rating=round(value, 4),
            wins=wins[key],
            losses=losses[key],
            ties=ties[key],
        )
        for key, value in ratings.items()
    }


def replay_elo(
    votes: Iterable[Vote],
    *,
    k: float = ELO_K,
    base: float = ELO_BASE,
) -> dict[str, EloEntry]:
    """Every run's rating, recomputed from the whole vote log."""
    table = replay_pairwise(
        ((vote.run_a, vote.run_b, vote.winner) for vote in votes), k=k, base=base
    )
    return {
        run_id: EloEntry(
            run_id=run_id,
            rating=item.rating,
            wins=item.wins,
            losses=item.losses,
            ties=item.ties,
        )
        for run_id, item in table.items()
    }
