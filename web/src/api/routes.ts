/**
 * Every URL the app calls, in one table.
 *
 * `tests/test_contract.py` reads this file and asserts each entry is a route the API
 * actually serves, so a renamed endpoint fails the test suite instead of the browser.
 *
 * Paths only — query strings are the caller's business, passed to the client as `params`.
 */

export const routes = {
  health: () => `/api/health`,
  status: () => `/api/status`,
  catalog: () => `/api/catalog`,
  meta: () => `/api/meta`,

  runs: () => `/api/runs`,
  run: (id: string) => `/api/runs/${id}`,
  runRating: (id: string) => `/api/runs/${id}/rating`,
  runRerun: (id: string) => `/api/runs/${id}/rerun`,
  runCancel: (id: string) => `/api/runs/${id}/cancel`,
  runWorkflow: (id: string) => `/api/runs/${id}/workflow`,
  dryRun: () => `/api/runs/dry-run`,

  queue: () => `/api/queue`,
  queuePause: () => `/api/queue/pause`,
  queueResume: () => `/api/queue/resume`,
  queueClear: () => `/api/queue/clear`,

  sweeps: () => `/api/sweeps`,
  sweepPreview: () => `/api/sweeps/preview`,

  votes: () => `/api/votes`,
  elo: () => `/api/elo`,
  arenaNext: () => `/api/arena/next`,
  arenaStandings: () => `/api/arena/standings`,

  compare: () => `/api/compare`,
  leaderboard: () => `/api/leaderboard`,
  recipes: () => `/api/recipes`,
  insightAxes: () => `/api/insights/axes`,
  insight: (axis: string) => `/api/insights/${axis}`,

  presets: () => `/api/presets`,
  preset: (id: string) => `/api/presets/${id}`,
  baseline: () => `/api/baseline`,
  tags: () => `/api/tags`,
  uploads: () => `/api/uploads`,

  events: () => `/api/events`,

  video: (name: string) => `/api/media/videos/${encodeURIComponent(name)}`,
  poster: (name: string) => `/api/media/posters/${encodeURIComponent(name)}`,
  strip: (name: string) => `/api/media/strips/${encodeURIComponent(name)}`,
  input: (name: string) => `/api/media/inputs/${encodeURIComponent(name)}`,
} as const
