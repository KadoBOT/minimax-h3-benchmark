"""The one primary score, and how runs are ranked by it.

There is exactly one headline number. Its two inputs are always shown beside it, its
weights belong to the user, and guardrails (wall clock, failure counts, sample size) are
reported separately rather than folded in.
"""

from __future__ import annotations

from typing import Annotated, Iterable, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from h3lab.domain.rating import STARS_MAX, STARS_MIN


def percentile_ranks(values: Sequence[float]) -> list[float]:
    """Map values onto ``[0, 1]`` by rank, averaging ties.

    Rank rather than min/max because one 25-minute outlier would otherwise squash every
    real difference into the bottom few percent of the scale.
    """
    count = len(values)
    if count == 0:
        return []
    if count == 1:
        return [0.5]

    order = sorted(range(count), key=lambda i: values[i])
    ranks = [0.0] * count
    position = 0
    while position < count:
        end = position
        while end + 1 < count and values[order[end + 1]] == values[order[position]]:
            end += 1
        average_rank = (position + end) / 2.0
        for index in range(position, end + 1):
            ranks[order[index]] = average_rank / (count - 1)
        position = end + 1
    return ranks


class ScoreWeights(BaseModel):
    """Relative weights, normalised on construction so the score lands in ``[0, 1]``.

    Any non-negative pair is accepted — a slider sending ``70`` and ``30`` means the same
    thing as ``0.7`` and ``0.3``, so callers never have to normalise first.
    """

    model_config = ConfigDict(frozen=True)

    quality: Annotated[float, Field(ge=0.0)] = 0.7
    speed: Annotated[float, Field(ge=0.0)] = 0.3

    @model_validator(mode="after")
    def _normalise(self) -> ScoreWeights:
        total = self.quality + self.speed
        if total <= 0:
            object.__setattr__(self, "quality", 1.0)
            object.__setattr__(self, "speed", 0.0)
            return self
        object.__setattr__(self, "quality", self.quality / total)
        object.__setattr__(self, "speed", self.speed / total)
        return self


class ScoreInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    stars: int | None = None
    elo: float | None = None
    sec_per_it: float | None = None


class ScoredRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    score: float
    quality: float | None
    speed: float | None
    quality_source: str
    unrated: bool
    rank: int = 0


def _quality_from_stars(stars: int) -> float:
    span = STARS_MAX - STARS_MIN
    return (min(max(stars, STARS_MIN), STARS_MAX) - STARS_MIN) / span


def score_runs(
    rows: Iterable[ScoreInput],
    weights: ScoreWeights | None = None,
    *,
    unrated_last: bool = True,
) -> list[ScoredRun]:
    """Rank runs by the primary score.

    Quality prefers stars; where a run has never been starred but has been voted on, its
    Elo percentile stands in. A run with neither is ``unrated`` and ranks last rather than
    being quietly scored zero, because "nobody looked at it" is not "it was bad".
    """
    items = list(rows)
    if not items:
        return []
    weights = weights or ScoreWeights()

    timed = [item for item in items if item.sec_per_it and item.sec_per_it > 0]
    speed_by_run: dict[str, float] = {}
    if timed:
        ranks = percentile_ranks([item.sec_per_it or 0.0 for item in timed])
        for item, rank in zip(timed, ranks):
            speed_by_run[item.run_id] = 1.0 - rank

    voted = [item for item in items if item.stars is None and item.elo is not None]
    elo_quality: dict[str, float] = {}
    if voted:
        ranks = percentile_ranks([item.elo or 0.0 for item in voted])
        for item, rank in zip(voted, ranks):
            elo_quality[item.run_id] = rank

    scored: list[ScoredRun] = []
    for item in items:
        if item.stars is not None:
            quality: float | None = _quality_from_stars(item.stars)
            source = "stars"
        elif item.run_id in elo_quality:
            quality = elo_quality[item.run_id]
            source = "elo"
        else:
            quality = None
            source = "none"

        speed = speed_by_run.get(item.run_id)
        parts: list[tuple[float, float]] = []
        if quality is not None:
            parts.append((weights.quality, quality))
        if speed is not None:
            parts.append((weights.speed, speed))
        weight_sum = sum(weight for weight, _ in parts)
        score = sum(weight * value for weight, value in parts) / weight_sum if weight_sum else 0.0

        scored.append(
            ScoredRun(
                run_id=item.run_id,
                score=round(score, 6),
                quality=None if quality is None else round(quality, 6),
                speed=None if speed is None else round(speed, 6),
                quality_source=source,
                unrated=quality is None,
            )
        )

    scored.sort(
        key=lambda row: (
            (1 if (unrated_last and row.unrated) else 0),
            -row.score,
            row.run_id,
        )
    )
    return [row.model_copy(update={"rank": index + 1}) for index, row in enumerate(scored)]
