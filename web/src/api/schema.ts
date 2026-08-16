/**
 * Generated from the API's OpenAPI schema by `python scripts/gen_types.py`.
 * Do not edit by hand — `tests/test_contract.py` regenerates this file and fails on drift.
 */

export interface ArenaAxis {
  axis: string;
  label: string;
  votes: number;
  standings?: ArenaStanding[];
  verdict: ArenaVerdict;
}

/** A fair pair with both runs attached, so the page can play them without a second call. */
export interface ArenaMatchup {
  matchup: Matchup;
  a: RunView;
  b: RunView;
}

/** One competitor's record: a setting value, or a whole loadout. */
export interface ArenaStanding {
  key: string;
  label: string;
  rating: number;
  wins?: number;
  losses?: number;
  ties?: number;
  seed_matched?: number;
  runs?: number;
  mean_sec_per_it?: number | null;
  rank?: number;
  games: number;
  decided: number;
  win_rate: number | null;
}

export interface ArenaStandings {
  axes?: ArenaAxis[];
  loadouts?: ArenaStanding[];
  votes_counted?: number;
  votes_ignored?: number;
  ignored_reasons?: Record<string, number>;
  pools?: number;
  runs?: number;
  matchups?: number;
  clean_matchups?: number;
}

/** What the votes on one axis support, stated with the record behind it. */
export interface ArenaVerdict {
  kind: "winner" | "inconclusive";
  value?: string | null;
  runner_up?: string | null;
  wins?: number;
  losses?: number;
  ties?: number;
  reason?: string;
}

/** The produced video plus everything derived from it. */
export interface Artifact {
  video_path?: string | null;
  poster_path?: string | null;
  strip_path?: string | null;
  width?: number | null;
  height?: number | null;
  fps?: number | null;
  frame_count?: number | null;
  size_bytes?: number | null;
}

export interface AssetComponent {
  id: string;
  optional?: boolean;
  binding: string;
  label: string;
  description?: string | null;
  required: boolean;
  visibleWhen?: Predicate[] | null;
  kind: "asset";
  accept: ("image" | "video" | "audio")[];
  minimumItems?: number;
  maximumItems: number;
}

export interface AvailabilityReason {
  code: string;
  detail: string;
  retryable: boolean;
}

export interface Available {
  state: "available";
  observedAt: string;
}

export interface AxisDef {
  field: string;
  label: string;
  kind: "categorical" | "numeric" | "boolean";
}

export interface AxisInsight {
  axis: string;
  label: string;
  kind: "categorical" | "numeric" | "boolean";
  total_runs: number;
  values: string[];
  marginal?: MarginalCell[];
  paired?: PairedComparison[];
  quality_verdict: Verdict;
  speed_verdict: Verdict;
  marginal_caveat?: string;
}

export interface BaselineRequest {
  run_id?: string | null;
}

export interface BodyUploadApiUploadsPost {
  file: string;
}

export interface BodyUploadAssetApiSharedAssetsPost {
  file: string;
}

export interface CancelAction {
  id: string;
  label: string;
  endpoint: string;
  optional?: boolean;
  kind: "cancel";
  method: "POST";
}

export interface Capabilities {
  required: string[];
  optional: string[];
}

/** Everything a run form needs to render, with the provenance of each list. */
export interface Catalog {
  comfy_online: boolean;
  comfy_url: string;
  source: string;
  schedulers: string[];
  samplers: string[];
  aspect_ratios: string[];
  diffusion_models: string[];
  diffusion_models_source: string;
  default_diffusion_model: string;
  turbo_loras?: string[];
  turbo_loras_source?: string;
  default_turbo_lora?: string;
  turbo_lora_steps?: Record<string, number>;
  images: string[];
  videos: string[];
  audios: string[];
  media_source: string;
  default_first_frame?: string;
  default_ref_images?: string[];
  modes?: string[];
  preset_levels?: string[];
  reference_limits?: Record<string, number>;
  defaults?: Record<string, unknown>;
}

export interface Comparison {
  runs: RunView[];
  differences: FieldDiff[];
  shared: Record<string, string>;
}

export interface CompilerIdentity {
  id: string;
  version: string;
}

export interface DeleteAction {
  id: string;
  label: string;
  endpoint: string;
  optional?: boolean;
  kind: "delete";
  method: "DELETE";
}

/** A paired difference with the evidence behind it. */
export interface DeltaStat {
  n: number;
  mean?: number | null;
  stderr?: number | null;
  better_a?: number;
  better_b?: number;
  ties?: number;
  conclusive: boolean;
}

export interface DownloadComponent {
  id: string;
  optional?: boolean;
  kind: "download";
  href: string;
  filename: string;
  label: string;
}

/** The answer to "would this run work?" without spending GPU time finding out. */
export interface DryRun {
  ok: boolean;
  problems?: string[];
  graph?: GraphSummary | null;
  config_hash: string;
  recipe_hash: string;
  duplicate_of?: string | null;
}

export interface DryRunRequest {
  config: GenerationConfig;
}

export interface EnqueueRequest {
  config: GenerationConfig;
  count?: number;
}

export interface Event {
  seq?: number;
  kind: "run.created" | "run.started" | "run.progress" | "run.log" | "run.preview" | "run.finished" | "run.updated" | "run.deleted" | "queue.changed" | "rating.changed" | "vote.added" | "comfy.status" | "lab.message" | "heartbeat";
  at?: number;
  run_id?: string | null;
  data?: Record<string, unknown>;
}

export interface FieldDiff {
  field: string;
  label: string;
  values: string[];
}

/** Everything that determines a generated video. Immutable once a run starts. */
export interface GenerationConfig {
  mode?: "flf2v" | "t2v" | "r2v";
  execution_backend?: "legacy" | "shared";
  diffusion_model?: string;
  prompt?: string;
  first_frame?: string;
  last_frame?: string;
  ref_images?: string[];
  ref_videos?: string[];
  ref_video_audios?: string[];
  ref_audios?: string[];
  ref_image_size?: "match" | "max";
  scheduler?: string;
  sampler?: string;
  aspect_ratio?: string;
  steps?: number;
  seed?: number;
  mp?: number;
  duration_s?: number;
  turbo?: boolean;
  turbo_lora?: string;
  turbo_lora_strength?: number;
  interp?: "off" | "gmfss" | "film" | "rife";
  upscaler?: boolean;
  upscaler_mode?: "none" | "rtx" | "seedvr2" | null;
  clean_vram?: boolean;
  attention?: "native" | "kitchen" | "sage_sol" | null;
  post_grade?: boolean | null;
  face_refine?: boolean | null;
  filename_prefix?: string;
  shared_workflow_revision?: string;
  shared_schema_revision?: string;
  cache_enabled?: boolean;
  cache?: "none" | "spectrum" | "easy" | "h3";
  cache_preset?: "conservative" | "moderate" | "aggressive" | "custom";
  sol_attn?: boolean;
  sol_preset?: "conservative" | "moderate" | "aggressive" | "custom";
  widgets?: Record<string, unknown>;
  shared_identity?: Record<string, unknown>;
}

export interface GenerationDocument {
  protocolVersion: "1.0";
  documentId: string;
  schemaRevision: string;
  workflowId: string;
  workflowRevision: string;
  title: string;
  description?: string | null;
  availability: Available | Unavailable;
  capabilities: Capabilities;
  kind?: "generation";
  components: (SectionComponent | TextComponent | TextareaComponent | NumberComponent | SelectComponent | ToggleComponent | AssetComponent | SeedComponent)[];
  actions: SubmitAction[];
}

/** What the patched ComfyUI graph turned out to be. */
export interface GraphSummary {
  nodes: number;
  classes?: string[];
  missing_links?: string[];
  files?: string[];
}

export interface Health {
  ok: boolean;
  worker_alive: boolean;
  paused: boolean;
}

export interface ImportReport {
  runs_imported?: number;
  ratings_imported?: number;
  videos_copied?: number;
  previews_built?: number;
  already_present?: number;
  skipped?: string[];
}

export interface JobDocument {
  protocolVersion: "1.0";
  documentId: string;
  schemaRevision: string;
  workflowId: string;
  workflowRevision: string;
  title: string;
  description?: string | null;
  availability: Available | Unavailable;
  capabilities: Capabilities;
  kind: "job";
  jobId: string;
  components: (SectionComponent | StatusComponent | ProgressComponent | LogComponent | PreviewComponent | VideoComponent | DownloadComponent)[];
  actions: (CancelAction | DeleteAction | RetryCollectionAction)[];
}

export interface JobSubmission {
  workflowRevision: string;
  schemaRevision: string;
  input: Record<string, JsonValue>;
}

export type JsonValue = unknown;

/** One poll answers everything the shell shows: worker, queue, and totals. */
export interface LabStatus {
  worker_alive: boolean;
  paused: boolean;
  active_run_id?: string | null;
  queued?: number;
  comfy_url?: string;
  last_error?: string | null;
  counts?: Record<string, number>;
  total_runs?: number;
  votes?: number;
  rated?: number;
  baseline_run_id?: string | null;
  event_seq?: number;
  criteria?: string[];
}

export interface Leaderboard {
  entries: LeaderboardEntry[];
  weights: ScoreWeights;
  considered: number;
  unrated: number;
}

export interface LeaderboardEntry {
  rank: number;
  view: RunView;
  score: number;
  quality: number | null;
  speed: number | null;
  quality_source: string;
  unrated: boolean;
}

export interface LogComponent {
  id: string;
  optional?: boolean;
  kind: "log";
  entries: LogEntry[];
}

export interface LogEntry {
  sequence: number;
  at: string;
  level: "debug" | "info" | "warning" | "error";
  message: string;
}

export interface MarginalCell {
  value: string;
  n: number;
  n_rated: number;
  n_failed: number;
  mean_stars?: number | null;
  median_stars?: number | null;
  mean_sec_per_it?: number | null;
  mean_wall_s?: number | null;
  mean_elo?: number | null;
}

/** One fair pair, ready to be shown. ``a`` is the left-hand side. */
export interface Matchup {
  a_run_id: string;
  b_run_id: string;
  pool: string;
  pool_label: string;
  held?: Record<string, string>;
  differences?: FieldDiff[];
  axis?: string | null;
  seed_matched?: boolean;
  reason?: string;
}

/** Vocabulary the UI needs to render its forms, fetched once and cached forever. */
export interface Meta {
  axes: AxisDef[];
  criteria: string[];
  criterion_labels: Record<string, string>;
  stars: StarRange;
  seed_strategies: string[];
  field_labels: Record<string, string>;
  modes: ModeNeeds[];
  caches: string[];
  interpolations: string[];
  interpolation_labels: Record<string, string>;
  preset_levels: string[];
  config_fields: string[];
  defaults?: Record<string, unknown>;
  comfy_url: string;
}

/** What a mode demands, in a form a form can read. */
export interface ModeNeeds {
  mode: "flf2v" | "t2v" | "r2v";
  label: string;
  requires_all?: string[];
  requires_any?: string[];
  accepts?: string[];
}

export interface NumberComponent {
  id: string;
  optional?: boolean;
  binding: string;
  label: string;
  description?: string | null;
  required: boolean;
  visibleWhen?: Predicate[] | null;
  kind: "number";
  minimum?: number | null;
  maximum?: number | null;
  step?: number | null;
  integer?: boolean;
  defaultValue?: number | null;
  unit?: string | null;
}

export interface Ok {
  ok?: boolean;
  detail?: string;
  count?: number | null;
}

/** ``a`` versus ``b`` across every group where both appear with everything else equal. */
export interface PairedComparison {
  value_a: string;
  value_b: string;
  pair_groups: number;
  stars: DeltaStat;
  speed_pct: DeltaStat;
  matched_on?: "seed" | "recipe";
  controlled: boolean;
}

export interface PatchRunRequest {
  favourite?: boolean | null;
  archived?: boolean | null;
  notes?: string | null;
  label?: string | null;
  tags?: string[] | null;
}

export interface Predicate {
  field: string;
  operator: "equals" | "not_equals" | "in";
  value: string | number | boolean | (string | number | boolean | null)[] | null;
}

export interface Preset {
  id: string;
  name: string;
  config: GenerationConfig;
  source_run_id?: string | null;
  created_at: string;
}

export interface PresetRequest {
  name: string;
  run_id?: string | null;
  config?: GenerationConfig | null;
  replace?: boolean;
}

export interface PreviewComponent {
  id: string;
  optional?: boolean;
  kind: "preview";
  src: string;
  mime: string;
  sequence: number;
}

/** A refusal the UI can render. One shape for every failure. */
export interface Problem {
  error: string;
  detail: string;
  kind?: "not_found" | "invalid" | "conflict" | "comfy_unreachable" | "shared_unavailable" | "shared_protocol" | "shared_uncertain" | "workflow" | "internal";
  fields?: Record<string, string>;
  code?: string | null;
  retryable?: boolean | null;
  errors?: ProblemFieldError[] | null;
}

export interface ProblemFieldError {
  field: string;
  code: string;
  detail: string;
}

export interface ProgressComponent {
  id: string;
  optional?: boolean;
  kind: "progress";
  value: number;
  label?: string | null;
  current?: number | null;
  total?: number | null;
}

export interface PublicJob {
  id: string;
  workflowId: string;
  workflowRevision: string;
  schemaRevision: string;
  state: "accepted" | "queued" | "running" | "cancelling" | "collecting" | "succeeded" | "failed" | "cancelled" | "interrupted" | "collection_failed";
  version: number;
  createdAt: string;
  updatedAt: string;
  provenance?: PublicJobProvenance | null;
  failure?: PublicJobFailure | null;
  artifact?: PublicJobArtifact | null;
  links: PublicJobLinks;
}

export interface PublicJobArtifact {
  id: string;
  mime: string;
  size: number;
  filename: string;
  contentUrl: string;
}

export interface PublicJobFailure {
  code: string;
  detail: string;
  retryable: boolean;
}

export interface PublicJobLinks {
  self: string;
  view: string;
  events: string;
  preview?: string | null;
  cancel?: string | null;
  retryCollection?: string | null;
}

export interface PublicJobProvenance {
  manifestDigest?: string | null;
  compiler?: CompilerIdentity | null;
  catalogRevision?: string | null;
  inputDigest?: string | null;
  resolvedSeed?: number | null;
}

export interface PublicMediaMetadata {
  id: string;
  kind: "asset" | "artifact";
  mediaKind: "image" | "video" | "audio";
  mime: string;
  size: number;
  digest: string;
  filename: string;
  contentUrl: string;
}

export interface QueueState {
  paused: boolean;
  worker_alive: boolean;
  active_run_id?: string | null;
  active?: RunView | null;
  queued?: RunView[];
  total?: number;
}

export interface RateRequest {
  stars: number;
  criteria?: Record<string, number>;
}

/** Replicates of one recipe — the same experiment at different seeds. */
export interface RecipeGroup {
  recipe_hash: string;
  label: string;
  n: number;
  n_rated: number;
  mean_stars?: number | null;
  mean_sec_per_it?: number | null;
  best_run_id?: string | null;
  run_ids?: string[];
}

export interface RerunRequest {
  overrides?: Record<string, unknown>;
}

export interface RetryCollectionAction {
  id: string;
  label: string;
  endpoint: string;
  optional?: boolean;
  kind: "retry_collection";
  method: "POST";
}

/** A run's config snapshot is a value: it is never edited after creation. */
export interface Run {
  id: string;
  seq: number;
  label: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted" | "collection_failed";
  config: GenerationConfig;
  config_hash: string;
  recipe_hash: string;
  metrics?: RunMetrics;
  artifact?: Artifact;
  prompt_id?: string | null;
  shared_submission?: JobSubmission | null;
  shared_job_id?: string | null;
  shared_provenance?: PublicJobProvenance | null;
  shared_event_cursor?: number | null;
  shared_failure_kind?: string | null;
  error?: string | null;
  favourite?: boolean;
  archived?: boolean;
  notes?: string;
  tags?: string[];
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
}

/** Measured facts. ``sec_per_it`` is the same unit ComfyUI's tqdm prints. */
export interface RunMetrics {
  wall_s?: number | null;
  sec_per_it?: number | null;
  steps?: number | null;
  sampler_cached?: boolean | null;
  cache_cleared?: boolean | null;
}

export interface RunPage {
  items: RunView[];
  total: number;
  limit: number;
  offset: number;
}

/** A run plus everything the UI shows beside it. */
export interface RunView {
  run: Run;
  stars?: number | null;
  criteria?: Record<string, number>;
  elo?: number | null;
  elo_games?: number;
  score?: number | null;
  rank?: number | null;
  duplicate_of?: string | null;
  is_baseline?: boolean;
}

/** Relative weights, normalised on construction so the score lands in ``[0, 1]``. */
export interface ScoreWeights {
  quality?: number;
  speed?: number;
}

export interface SectionComponent {
  id: string;
  optional?: boolean;
  kind: "section";
  title: string;
  description?: string | null;
}

export interface SeedComponent {
  id: string;
  optional?: boolean;
  binding: string;
  label: string;
  description?: string | null;
  required: boolean;
  visibleWhen?: Predicate[] | null;
  kind: "seed";
  allowRandom: boolean;
  minimum: number;
  maximum: number;
  defaultValue: number | null;
}

export interface SelectComponent {
  id: string;
  optional?: boolean;
  binding: string;
  label: string;
  description?: string | null;
  required: boolean;
  visibleWhen?: Predicate[] | null;
  kind: "select";
  options: SelectOption[];
  defaultValue?: string | number | boolean | null;
}

export interface SelectOption {
  value: string | number | boolean;
  label: string;
  description?: string | null;
  disabled?: boolean;
}

export interface SharedSweepAxisRequest {
  binding: string;
  values: unknown[];
}

export interface SharedSweepRequest {
  base: JobSubmission;
  axes?: SharedSweepAxisRequest[];
  repeats?: number;
  seed_strategy?: "fixed" | "increment" | "random";
  skip_duplicates?: boolean;
}

export interface StarRange {
  min: number;
  max: number;
}

export interface StatusComponent {
  id: string;
  optional?: boolean;
  kind: "status";
  state: "accepted" | "queued" | "running" | "cancelling" | "collecting" | "succeeded" | "failed" | "cancelled" | "interrupted" | "collection_failed";
  label: string;
  detail?: string | null;
}

export interface SubmitAction {
  id: string;
  label: string;
  endpoint: string;
  optional?: boolean;
  kind: "submit";
  method: "POST";
}

export interface SweepAxisRequest {
  field: string;
  values: unknown[];
}

export interface SweepPreview {
  count: number;
  combinations: number;
  repeats: number;
  new_count: number;
  duplicate_count: number;
  items: SweepPreviewItem[];
}

export interface SweepPreviewItem {
  config: GenerationConfig;
  config_hash: string;
  already_ran?: boolean;
  existing_run_id?: string | null;
}

export interface SweepRequest {
  base: GenerationConfig;
  axes?: SweepAxisRequest[];
  repeats?: number;
  seed_strategy?: "fixed" | "increment" | "random";
  skip_duplicates?: boolean;
}

export interface TextComponent {
  id: string;
  optional?: boolean;
  binding: string;
  label: string;
  description?: string | null;
  required: boolean;
  visibleWhen?: Predicate[] | null;
  kind: "text";
  defaultValue?: string | null;
  placeholder?: string | null;
  minLength?: number | null;
  maxLength?: number | null;
}

export interface TextareaComponent {
  id: string;
  optional?: boolean;
  binding: string;
  label: string;
  description?: string | null;
  required: boolean;
  visibleWhen?: Predicate[] | null;
  kind: "textarea";
  defaultValue?: string | null;
  placeholder?: string | null;
  minLength?: number | null;
  maxLength?: number | null;
  rows?: number | null;
}

export interface ToggleComponent {
  id: string;
  optional?: boolean;
  binding: string;
  label: string;
  description?: string | null;
  required: boolean;
  visibleWhen?: Predicate[] | null;
  kind: "toggle";
  defaultValue: boolean;
}

export interface Unavailable {
  state: "disabled" | "incompatible";
  observedAt: string;
  reason: AvailabilityReason;
}

/** Where the file landed. `name` is what a config field should be set to. */
export interface Upload {
  name: string;
  bytes: number;
  kind: string;
}

export interface Verdict {
  kind: "winner" | "inconclusive";
  metric: "stars" | "speed";
  value?: string | null;
  runner_up?: string | null;
  margin?: number | null;
  pair_groups?: number;
  matched_on?: "seed" | "recipe" | null;
  reason: string;
}

export interface VideoComponent {
  id: string;
  optional?: boolean;
  kind: "video";
  src: string;
  mime: string;
  poster?: string | null;
}

/** A relative judgement. ``winner is None`` means the pair was a tie. */
export interface Vote {
  id: string;
  run_a: string;
  run_b: string;
  winner?: string | null;
  axis?: string | null;
  created_at?: string | null;
}

export interface VoteRequest {
  run_a: string;
  run_b: string;
  winner?: string | null;
  axis?: string | null;
}

/** Every path the API answers, so the client's URLs can be checked against it. */
export const API_PATHS = [
  "/api/arena/next",
  "/api/arena/standings",
  "/api/baseline",
  "/api/catalog",
  "/api/compare",
  "/api/elo",
  "/api/events",
  "/api/events/recent",
  "/api/health",
  "/api/insights/axes",
  "/api/insights/{axis}",
  "/api/leaderboard",
  "/api/legacy-import",
  "/api/media/inputs/{name}",
  "/api/media/posters/{name}",
  "/api/media/strips/{name}",
  "/api/media/videos/{name}",
  "/api/meta",
  "/api/presets",
  "/api/presets/{preset_id}",
  "/api/queue",
  "/api/queue/clear",
  "/api/queue/pause",
  "/api/queue/resume",
  "/api/recipes",
  "/api/runs",
  "/api/runs/dry-run",
  "/api/runs/{run_id}",
  "/api/runs/{run_id}/cancel",
  "/api/runs/{run_id}/preview",
  "/api/runs/{run_id}/rating",
  "/api/runs/{run_id}/rerun",
  "/api/runs/{run_id}/retry-collection",
  "/api/runs/{run_id}/shared",
  "/api/runs/{run_id}/shared-events",
  "/api/runs/{run_id}/shared-preview",
  "/api/runs/{run_id}/shared-video",
  "/api/runs/{run_id}/shared-view",
  "/api/runs/{run_id}/workflow",
  "/api/shared/assets",
  "/api/shared/assets/{asset_id}/content",
  "/api/shared/generation",
  "/api/status",
  "/api/sweeps",
  "/api/sweeps/preview",
  "/api/tags",
  "/api/uploads",
  "/api/votes",
] as const;
