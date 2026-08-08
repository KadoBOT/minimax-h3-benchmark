/** Query keys in one place, so a mutation can invalidate exactly what it changed. */

import type { RunListParams } from "./hooks"

export const keys = {
  status: ["status"] as const,
  meta: ["meta"] as const,
  catalog: ["catalog"] as const,
  queue: ["queue"] as const,
  tags: ["tags"] as const,
  presets: ["presets"] as const,
  elo: ["elo"] as const,
  votes: ["votes"] as const,
  recipes: ["recipes"] as const,
  axes: ["insights", "axes"] as const,

  runs: (params: RunListParams) => ["runs", params] as const,
  run: (id: string) => ["runs", "one", id] as const,
  compare: (ids: string[]) => ["compare", [...ids].sort()] as const,
  leaderboard: (quality: number, speed: number, limit: number) =>
    ["leaderboard", quality, speed, limit] as const,
  insight: (axis: string) => ["insights", axis] as const,
  arenaStandings: ["arena", "standings"] as const,
  arenaMatchup: (exclude: string[]) => ["arena", "next", [...exclude].sort()] as const,
} as const

/** Everything derived from the set of runs, invalidated together after a run changes. */
export const derivedKeys = [
  ["runs"],
  ["compare"],
  ["leaderboard"],
  ["insights"],
  ["recipes"],
  ["arena"],
  ["status"],
  ["queue"],
  ["tags"],
] as const
