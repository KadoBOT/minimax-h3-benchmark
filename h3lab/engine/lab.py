"""The Lab: one object the API talks to, holding every piece of the system together.

Routes stay thin because everything that needs more than one repository lives here. It also
means the same operations are usable from a script or a test without starting a web server.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Sequence

from pydantic import BaseModel, ConfigDict, Field

from h3lab.comfy.catalog import Catalog, CatalogCache
from h3lab.comfy.client import ComfyClient
from h3lab.comfy.editor import run_provenance, to_editor_workflow
from h3lab.comfy.graph import apply_config, describe, missing_links
from h3lab.domain.arena import (
    ArenaRun,
    ArenaStandings,
    Matchup,
    next_matchup,
    standings as arena_table,
)
from h3lab.domain.config import (
    FieldDiff,
    GenerationConfig,
    config_diff,
    config_hash,
    field_display,
    recipe_hash,
)
from h3lab.domain.insights import (
    AXES,
    AxisDef,
    AxisInsight,
    InsightRun,
    analyse,
    available_axes,
)
from h3lab.domain.rating import CRITERIA, EloEntry, Rating, Vote
from h3lab.domain.run import Run
from h3lab.domain.scoring import ScoreInput, ScoredRun, ScoreWeights, score_runs
from h3lab.domain.sweeps import SweepPreview, SweepSpec, expand, preview
from h3lab.engine.events import EventBus
from h3lab.engine.runner import Runner, WorkflowCache, preflight
from h3lab.settings import Settings
from h3lab.storage import open_store
from h3lab.storage.judgement import RatingRepository, VoteRepository
from h3lab.storage.legacy import ImportReport, import_legacy
from h3lab.storage.library import AppState, Preset, PresetRepository
from h3lab.storage.runs import Page, RunFilter, RunNotFound, RunRepository, SortKey


class RunView(BaseModel):
    """A run plus everything the UI shows beside it."""

    model_config = ConfigDict(frozen=True)

    run: Run
    stars: int | None = None
    criteria: dict[str, int] = Field(default_factory=dict)
    elo: float | None = None
    elo_games: int = 0
    score: float | None = None
    rank: int | None = None
    duplicate_of: str | None = None
    is_baseline: bool = False


class RunPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[RunView]
    total: int
    limit: int
    offset: int


class Comparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    runs: list[RunView]
    differences: list[FieldDiff]
    shared: dict[str, str]


class LabStatus(BaseModel):
    """One poll answers everything the shell shows: worker, queue, and totals."""

    model_config = ConfigDict(frozen=True)

    worker_alive: bool
    paused: bool
    active_run_id: str | None = None
    queued: int = 0
    comfy_url: str = ""
    last_error: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    total_runs: int = 0
    votes: int = 0
    rated: int = 0
    baseline_run_id: str | None = None
    event_seq: int = 0
    criteria: list[str] = Field(default_factory=list)


class QueueState(BaseModel):
    model_config = ConfigDict(frozen=True)

    paused: bool
    worker_alive: bool
    active_run_id: str | None = None
    active: RunView | None = None
    queued: list[RunView] = Field(default_factory=list)
    total: int = 0


class GraphSummary(BaseModel):
    """What the patched ComfyUI graph turned out to be."""

    model_config = ConfigDict(frozen=True)

    nodes: int
    classes: list[str] = Field(default_factory=list)
    missing_links: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)


class DryRun(BaseModel):
    """The answer to "would this run work?" without spending GPU time finding out."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    problems: list[str] = Field(default_factory=list)
    graph: GraphSummary | None = None
    config_hash: str
    recipe_hash: str
    duplicate_of: str | None = None


class LeaderboardEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    rank: int
    view: RunView
    score: float
    quality: float | None
    speed: float | None
    quality_source: str
    unrated: bool


class Leaderboard(BaseModel):
    model_config = ConfigDict(frozen=True)

    entries: list[LeaderboardEntry]
    weights: ScoreWeights
    considered: int
    unrated: int


class RecipeGroup(BaseModel):
    """Replicates of one recipe — the same experiment at different seeds."""

    model_config = ConfigDict(frozen=True)

    recipe_hash: str
    label: str
    n: int
    n_rated: int
    mean_stars: float | None = None
    mean_sec_per_it: float | None = None
    best_run_id: str | None = None
    run_ids: list[str] = Field(default_factory=list)


class ArenaMatchup(BaseModel):
    """A fair pair with both runs attached, so the page can play them without a second call."""

    model_config = ConfigDict(frozen=True)

    matchup: Matchup
    a: RunView
    b: RunView


class Lab:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: ComfyClient | None = None,
        start_worker: bool = True,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.settings.ensure_dirs()
        self.store = open_store(self.settings.db_path)

        self.runs = RunRepository(self.store)
        self.ratings = RatingRepository(self.store)
        self.votes = VoteRepository(self.store)
        self.presets = PresetRepository(self.store)
        self.state = AppState(self.store)

        self.events = EventBus()
        self.catalog_cache = CatalogCache(self.settings)
        self.workflows = WorkflowCache(self.settings, events=self.events)
        self.client = client or ComfyClient(
            self.settings.comfy_url, run_timeout_s=self.settings.comfy_timeout_s
        )
        self.runner = Runner(
            runs=self.runs,
            settings=self.settings,
            events=self.events,
            client=self.client,
            workflows=self.workflows,
        )
        if start_worker:
            self.runner.start()

    def close(self) -> None:
        self.runner.stop()
        self.client.close()
        self.events.close()

    # --- catalog and status ------------------------------------------------

    def catalog(self, *, refresh: bool = False) -> Catalog:
        return self.catalog_cache.get(refresh=refresh)

    def status(self) -> LabStatus:
        counts = self.runs.status_counts()
        return LabStatus(
            **self.runner.status(),
            counts=counts,
            total_runs=sum(counts.values()),
            votes=self.votes.count(),
            rated=len(self.ratings.stars_map()),
            baseline_run_id=self.state.baseline_run_id,
            event_seq=self.events.last_seq,
            criteria=list(CRITERIA),
        )

    def queue_state(self) -> QueueState:
        pending = self.list_runs(
            RunFilter(status=("queued",), archived=None), sort="oldest", limit=200
        )
        active_id = self.runner.active_run_id
        return QueueState(
            paused=self.runner.paused,
            worker_alive=self.runner.running,
            active_run_id=active_id,
            active=self.get_run(active_id) if active_id else None,
            queued=pending.items,
            total=pending.total,
        )

    # --- projections -------------------------------------------------------

    def _context(self) -> tuple[dict[str, int], dict[str, EloEntry], dict[str, str], str | None]:
        return (
            self.ratings.stars_map(),
            self.votes.elo(),
            self.runs.hashes(),
            self.state.baseline_run_id,
        )

    def view(self, run: Run) -> RunView:
        rating = self.ratings.get(run.id)
        elo = self.votes.elo().get(run.id)
        first_with_hash = self.runs.hashes().get(run.config_hash)
        return RunView(
            run=run,
            stars=rating.stars if rating else None,
            criteria=rating.criteria if rating else {},
            elo=elo.rating if elo else None,
            elo_games=elo.games if elo else 0,
            duplicate_of=first_with_hash if first_with_hash != run.id else None,
            is_baseline=run.id == self.state.baseline_run_id,
        )

    def _views(self, runs: Sequence[Run]) -> list[RunView]:
        stars, elo, hashes, baseline = self._context()
        ratings = self.ratings.all_map()
        out: list[RunView] = []
        for run in runs:
            entry = elo.get(run.id)
            rating = ratings.get(run.id)
            owner = hashes.get(run.config_hash)
            out.append(
                RunView(
                    run=run,
                    stars=stars.get(run.id),
                    criteria=rating.criteria if rating else {},
                    elo=entry.rating if entry else None,
                    elo_games=entry.games if entry else 0,
                    duplicate_of=owner if owner and owner != run.id else None,
                    is_baseline=run.id == baseline,
                )
            )
        return out

    def list_runs(
        self,
        filter_: RunFilter | None = None,
        *,
        sort: SortKey = "recent",
        limit: int = 100,
        offset: int = 0,
    ) -> RunPage:
        page: Page = self.runs.list(filter_, sort=sort, limit=limit, offset=offset)
        return RunPage(
            items=self._views(page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    def get_run(self, run_id: str) -> RunView:
        return self.view(self.runs.require(run_id))

    def insight_rows(self, filter_: RunFilter | None = None) -> list[InsightRun]:
        """Only runs that produced something can inform an insight."""
        runs = self.runs.all(filter_ or RunFilter(archived=False))
        stars = self.ratings.stars_map()
        elo = self.votes.elo()
        rows: list[InsightRun] = []
        for run in runs:
            if run.status not in ("succeeded", "failed"):
                continue
            entry = elo.get(run.id)
            rows.append(
                InsightRun(
                    run_id=run.id,
                    config=run.config,
                    succeeded=run.status == "succeeded",
                    stars=stars.get(run.id),
                    elo=entry.rating if entry else None,
                    sec_per_it=run.metrics.sec_per_it,
                    wall_s=run.metrics.wall_s,
                )
            )
        return rows

    # --- queueing ----------------------------------------------------------

    def _announce(self, created: Sequence[Run]) -> list[RunView]:
        for run in created:
            # run_seq, not seq: the run's ordinal is not the event stream's position.
            self.events.publish(
                "run.created", run_id=run.id, label=run.label, run_seq=run.seq, status=run.status
            )
        self.events.publish("queue.changed")
        self.runner.nudge()
        return self._views(created)

    def enqueue(self, config: GenerationConfig, *, count: int = 1) -> list[RunView]:
        return self._announce([self.runs.create(config) for _ in range(max(1, count))])

    def enqueue_many(self, configs: Iterable[GenerationConfig]) -> list[RunView]:
        return self._announce([self.runs.create(config) for config in configs])

    def rerun(self, run_id: str, *, overrides: dict[str, Any] | None = None) -> RunView:
        """Queue the same experiment again, optionally with a change. The origin is kept."""
        source = self.runs.require(run_id)
        config = source.config.merged(**(overrides or {}))
        created = self.enqueue(config)[0]
        note = f"reran from {source.label}" if not overrides else f"variant of {source.label}"
        self.runs.patch_flags(created.run.id, notes=note)
        return self.get_run(created.run.id)

    def preview_sweep(self, spec: SweepSpec) -> SweepPreview:
        return preview(spec, existing=self.runs.hashes())

    def run_sweep(self, spec: SweepSpec, *, skip_duplicates: bool = True) -> list[RunView]:
        known = self.runs.hashes() if skip_duplicates else {}
        wanted = [
            config for config in expand(spec) if config_hash(config) not in known
        ]
        return self.enqueue_many(wanted)

    def dry_run(self, config: GenerationConfig) -> DryRun:
        """Build the graph without submitting it, and report anything already wrong."""
        problems = preflight(config, self.settings)
        identity = {"config_hash": config_hash(config), "recipe_hash": recipe_hash(config)}
        try:
            workflow = self.workflows.get(config.mode)
            prompt = apply_config(workflow, config, output_tag="dry-run")
        except Exception as exc:  # noqa: BLE001 - a broken template is a reportable answer
            return DryRun(ok=False, problems=[*problems, str(exc)], **identity)
        dangling = missing_links(prompt)
        return DryRun(
            ok=not problems and not dangling,
            problems=[*problems, *(f"dangling link {item}" for item in dangling)],
            graph=GraphSummary(**describe(prompt)),
            duplicate_of=self.runs.hashes().get(config_hash(config)),
            **identity,
        )

    def workflow_for_run(self, run_id: str) -> dict[str, Any]:
        """The run's graph as a ComfyUI editor workflow, ready to open.

        Built from the template as it is on disk now rather than stored per run: a run is its
        config, and the config is what the export applies. If the template has since changed,
        the export follows it — which is the same graph the lab would submit if the run were
        queued again today, and so the honest answer to "give me this run's workflow".
        """
        run = self.runs.require(run_id)
        workflow = self.workflows.get(run.config.mode)
        prompt = apply_config(workflow, run.config, output_tag=run.id)
        return to_editor_workflow(workflow, prompt, provenance=run_provenance(run))

    def cancel(self, run_id: str) -> bool:
        return self.runner.cancel(run_id)

    def cancel_all(self) -> int:
        return self.runner.cancel_all()

    def pause(self) -> None:
        self.runner.pause()

    def resume(self) -> None:
        self.runner.resume()

    # --- judgement ---------------------------------------------------------

    def rate(self, run_id: str, stars: int, criteria: dict[str, int] | None = None) -> RunView:
        self.ratings.put(run_id, stars, criteria)
        self.events.publish("rating.changed", run_id=run_id, stars=stars)
        return self.get_run(run_id)

    def unrate(self, run_id: str) -> RunView:
        self.ratings.delete(run_id)
        self.events.publish("rating.changed", run_id=run_id, stars=None)
        return self.get_run(run_id)

    def vote(self, run_a: str, run_b: str, winner: str | None, *, axis: str | None = None) -> Vote:
        vote = self.votes.add(run_a, run_b, winner, axis=axis)
        self.events.publish("vote.added", run_id=winner, data={"a": run_a, "b": run_b})
        return vote

    def elo_table(self) -> dict[str, EloEntry]:
        return self.votes.elo()

    def rating_of(self, run_id: str) -> Rating | None:
        return self.ratings.get(run_id)

    # --- flags, tags, presets ---------------------------------------------

    def patch(
        self,
        run_id: str,
        *,
        favourite: bool | None = None,
        archived: bool | None = None,
        notes: str | None = None,
        label: str | None = None,
        tags: Sequence[str] | None = None,
    ) -> RunView:
        self.runs.patch_flags(
            run_id, favourite=favourite, archived=archived, notes=notes, label=label
        )
        if tags is not None:
            self.runs.set_tags(run_id, tags)
        view = self.get_run(run_id)
        self.events.publish("run.updated", run_id=run_id, status=view.run.status)
        return view

    def delete_run(self, run_id: str) -> bool:
        run = self.runs.get(run_id)
        if run is None:
            return False
        for path in self._artifact_paths(run):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        removed = self.runs.delete(run_id)
        if removed:
            if self.state.baseline_run_id == run_id:
                self.state.set_baseline(None)
            self.events.publish("run.deleted", run_id=run_id)
        return removed

    def _artifact_paths(self, run: Run) -> list[Path]:
        paths: list[Path] = []
        if run.artifact.video_path:
            paths.append(self.settings.videos_dir / run.artifact.video_path)
        if run.artifact.poster_path:
            paths.append(self.settings.posters_dir / run.artifact.poster_path)
        if run.artifact.strip_path:
            paths.append(self.settings.strips_dir / run.artifact.strip_path)
        return paths

    def set_baseline(self, run_id: str | None) -> str | None:
        if run_id is not None:
            self.runs.require(run_id)
        self.state.set_baseline(run_id)
        self.events.publish("run.updated", run_id=run_id, baseline=True)
        return run_id

    def save_preset(
        self, name: str, run_id: str | None = None, config: GenerationConfig | None = None, *,
        replace: bool = False,
    ) -> Preset:
        if config is None:
            if run_id is None:
                raise ValueError("saving a preset needs either a run or a config")
            config = self.runs.require(run_id).config
        return self.presets.create(name, config, source_run_id=run_id, replace=replace)

    def tags(self) -> list[str]:
        return self.runs.tags()

    # --- analysis ----------------------------------------------------------

    def leaderboard(
        self,
        *,
        weights: ScoreWeights | None = None,
        filter_: RunFilter | None = None,
        limit: int = 50,
    ) -> Leaderboard:
        base = filter_ or RunFilter(status=("succeeded",), archived=False)
        runs = self.runs.all(base)
        stars = self.ratings.stars_map()
        elo = self.votes.elo()
        scored: list[ScoredRun] = score_runs(
            [
                ScoreInput(
                    run_id=run.id,
                    stars=stars.get(run.id),
                    elo=elo[run.id].rating if run.id in elo else None,
                    sec_per_it=run.metrics.sec_per_it,
                )
                for run in runs
            ],
            weights,
        )
        views = {view.run.id: view for view in self._views(runs)}
        entries = [
            LeaderboardEntry(
                rank=item.rank,
                view=views[item.run_id],
                score=item.score,
                quality=item.quality,
                speed=item.speed,
                quality_source=item.quality_source,
                unrated=item.unrated,
            )
            for item in scored[:limit]
            if item.run_id in views
        ]
        return Leaderboard(
            entries=entries,
            weights=weights or ScoreWeights(),
            considered=len(runs),
            unrated=sum(1 for item in scored if item.unrated),
        )

    def compare(self, run_ids: Sequence[str]) -> Comparison:
        runs = [self.runs.require(run_id) for run_id in run_ids]
        views = self._views(runs)
        diffs = config_diff([run.config for run in runs])
        shared = {}
        if runs:
            differing = {item.field for item in diffs}
            for field, label in _COMPARABLE_FIELDS:
                if field in differing:
                    continue
                shared[label] = field_display(field, getattr(runs[0].config, field))
        return Comparison(runs=views, differences=diffs, shared=shared)

    def axes(self) -> list[AxisDef]:
        rows = self.insight_rows()
        found = available_axes(rows)
        return found or list(AXES)

    def insight(self, axis: str, *, filter_: RunFilter | None = None) -> AxisInsight:
        return analyse(self.insight_rows(filter_), axis)

    def recipes(self, *, limit: int = 100) -> list[RecipeGroup]:
        """Group runs by recipe so replicates of one experiment read as one row."""
        runs = self.runs.all(RunFilter(status=("succeeded",), archived=False))
        stars = self.ratings.stars_map()
        buckets: dict[str, list[Run]] = {}
        for run in runs:
            buckets.setdefault(run.recipe_hash, []).append(run)

        groups: list[RecipeGroup] = []
        for digest, group in buckets.items():
            rated = [stars[run.id] for run in group if run.id in stars]
            rates = [run.metrics.sec_per_it for run in group if run.metrics.sec_per_it]
            best = max(group, key=lambda run: stars.get(run.id, -1))
            groups.append(
                RecipeGroup(
                    recipe_hash=digest,
                    label=group[0].label,
                    n=len(group),
                    n_rated=len(rated),
                    mean_stars=round(sum(rated) / len(rated), 2) if rated else None,
                    mean_sec_per_it=(
                        round(sum(rates) / len(rates), 3) if rates else None  # type: ignore[arg-type]
                    ),
                    best_run_id=best.id if rated else None,
                    run_ids=[run.id for run in group],
                )
            )
        groups.sort(key=lambda group: (group.mean_stars is None, -(group.mean_stars or 0)))
        return groups[:limit]

    # --- the arena ---------------------------------------------------------

    def arena_runs(self, min_stars: int | None = None) -> list[ArenaRun]:
        """The runs the arena is allowed to work with: finished, watchable, not archived.

        A voter cannot compare what will not play, so a run without a video is not in the
        arena at all — not offered, and not counted in what is left to judge.
        """
        filter_min = min_stars if min_stars is not None and min_stars > 0 else None
        return [
            ArenaRun(run_id=run.id, config=run.config, sec_per_it=run.metrics.sec_per_it)
            for run in self.runs.all(RunFilter(status=("succeeded",), archived=False, min_stars=filter_min))
            if run.artifact.has_video
        ]

    def arena_matchup(
        self, *, exclude: Sequence[str] = (), min_stars: int | None = None
    ) -> ArenaMatchup | None:
        """The next fair pair to show, or nothing if no two runs are comparable yet."""
        chosen = next_matchup(
            self.arena_runs(min_stars=min_stars), self.votes.list(limit=5000), exclude=exclude
        )
        if chosen is None:
            return None
        return ArenaMatchup(
            matchup=chosen,
            a=self.get_run(chosen.a_run_id),
            b=self.get_run(chosen.b_run_id),
        )

    def arena_standings(self, min_stars: int | None = None) -> ArenaStandings:
        """What every vote so far is evidence about, replayed against today's runs."""
        return arena_table(self.arena_runs(min_stars=min_stars), self.votes.list(limit=5000))

    # --- maintenance -------------------------------------------------------

    def import_legacy(self) -> ImportReport:
        report = import_legacy(
            self.settings.legacy_db_path,
            runs=self.runs,
            ratings=self.ratings,
            state=self.state,
            settings=self.settings,
            legacy_videos_dir=self.settings.legacy_videos_dir,
        )
        if report.runs_imported:
            self.events.publish(
                "lab.message", text=f"imported {report.runs_imported} run(s) from the old lab"
            )
        return report

    def reconcile(self) -> int:
        recovered = self.runs.reconcile()
        if recovered:
            self.events.publish("queue.changed")
        return recovered


_COMPARABLE_FIELDS: tuple[tuple[str, str], ...] = (
    ("mode", "Mode"),
    ("diffusion_model", "Weights"),
    ("cache", "Cache"),
    ("cache_preset", "Cache preset"),
    ("sol_attn", "Sol-Attn"),
    ("sol_preset", "Sol preset"),
    ("scheduler", "Scheduler"),
    ("sampler", "Sampler"),
    ("steps", "Steps"),
    ("turbo_lora", "Turbo LoRA"),
    ("turbo_lora_strength", "Turbo strength"),
    ("mp", "Megapixels"),
    ("duration_s", "Duration"),
    ("aspect_ratio", "Aspect"),
)


__all__ = [
    "ArenaMatchup",
    "Comparison",
    "Lab",
    "Leaderboard",
    "LeaderboardEntry",
    "RecipeGroup",
    "RunPage",
    "RunView",
    "RunNotFound",
]
