"""Pure domain layer. Nothing here performs I/O or imports storage, comfy, engine, or api."""

from h3lab.domain.config import (
    CACHE_NAMES,
    GEN_MODES,
    GenerationConfig,
    canonical_form,
    config_diff,
    config_hash,
    derive_label,
    field_display,
    recipe_hash,
)
from h3lab.domain.ids import new_id
from h3lab.domain.insights import (
    AXES,
    AxisInsight,
    InsightRun,
    analyse,
    available_axes,
    marginal,
    paired,
)
from h3lab.domain.rating import CRITERIA, EloEntry, Rating, Vote, replay_elo
from h3lab.domain.run import Artifact, Run, RunMetrics, RunProgress, RunStatus
from h3lab.domain.scoring import ScoreInput, ScoreWeights, ScoredRun, percentile_ranks, score_runs
from h3lab.domain.sweeps import SweepAxis, SweepPreview, SweepSpec, expand, preview

__all__ = [
    "AXES",
    "Artifact",
    "AxisInsight",
    "CACHE_NAMES",
    "CRITERIA",
    "EloEntry",
    "GEN_MODES",
    "GenerationConfig",
    "InsightRun",
    "Rating",
    "Run",
    "RunMetrics",
    "RunProgress",
    "RunStatus",
    "ScoreInput",
    "ScoreWeights",
    "ScoredRun",
    "SweepAxis",
    "SweepPreview",
    "SweepSpec",
    "Vote",
    "analyse",
    "available_axes",
    "canonical_form",
    "config_diff",
    "config_hash",
    "derive_label",
    "expand",
    "field_display",
    "marginal",
    "new_id",
    "paired",
    "percentile_ranks",
    "preview",
    "recipe_hash",
    "replay_elo",
    "score_runs",
]
