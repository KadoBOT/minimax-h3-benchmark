/**
 * Every server interaction the app performs, as a hook.
 *
 * Reads are cached by React Query and refreshed by the event stream rather than by polling:
 * a run finishing pushes an event, which invalidates the affected keys. Writes report their
 * own failure through a toast, so no page needs its own error plumbing.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
  type QueryClient,
} from "@tanstack/react-query"
import { toast } from "sonner"

import { api, ApiError } from "./client"
import { derivedKeys, keys } from "./keys"
import { routes } from "./routes"
import type {
  ArenaMatchup,
  ArenaStandings,
  AxisDef,
  AxisInsight,
  Catalog,
  Comparison,
  DryRun,
  GenerationConfig,
  LabStatus,
  Leaderboard,
  Meta,
  Ok,
  PatchRunRequest,
  Preset,
  QueueState,
  RecipeGroup,
  Run,
  RunPage,
  RunView,
  SweepPreview,
  SweepRequest,
  Upload,
  Vote,
} from "./schema"

export type RunListParams = {
  status?: Run["status"][]
  mode?: string
  favourite?: boolean
  archived?: boolean
  rated?: boolean
  with_video?: boolean
  tag?: string
  config_hash?: string
  recipe_hash?: string
  query?: string
  min_stars?: number
  ids?: string[]
  sort?: "recent" | "oldest" | "stars" | "speed" | "elo" | "label"
  limit?: number
  offset?: number
}

// --- reads -----------------------------------------------------------------

/** Vocabulary for the forms. Static for the life of the process, so it never refetches. */
export function useMeta() {
  return useQuery({
    queryKey: keys.meta,
    queryFn: () => api.get<Meta>(routes.meta()),
    staleTime: Infinity,
    gcTime: Infinity,
  })
}

export function useStatus() {
  return useQuery({
    queryKey: keys.status,
    queryFn: () => api.get<LabStatus>(routes.status()),
    // The event stream keeps this fresh; the interval is only a safety net for a dropped
    // stream, which is why it is slow rather than the sub-second poll the old lab used.
    refetchInterval: 30_000,
  })
}

export function useCatalog(refresh = false) {
  return useQuery({
    queryKey: keys.catalog,
    queryFn: () => api.get<Catalog>(routes.catalog(), refresh ? { refresh: true } : undefined),
    staleTime: 60_000,
  })
}

export function useQueue() {
  return useQuery({
    queryKey: keys.queue,
    queryFn: () => api.get<QueueState>(routes.queue()),
  })
}

export function useRuns(params: RunListParams, options?: Partial<UseQueryOptions<RunPage>>) {
  return useQuery({
    queryKey: keys.runs(params),
    queryFn: () => api.get<RunPage>(routes.runs(), params as never),
    ...options,
  })
}

export function useRun(id: string | undefined) {
  return useQuery({
    queryKey: keys.run(id ?? ""),
    queryFn: () => api.get<RunView>(routes.run(id as string)),
    enabled: Boolean(id),
  })
}

export function useComparison(ids: string[]) {
  return useQuery({
    queryKey: keys.compare(ids),
    queryFn: () => api.get<Comparison>(routes.compare(), { ids }),
    enabled: ids.length >= 2,
  })
}

export function useLeaderboard(quality: number, speed: number, limit = 50) {
  return useQuery({
    queryKey: keys.leaderboard(quality, speed, limit),
    queryFn: () => api.get<Leaderboard>(routes.leaderboard(), { quality, speed, limit }),
  })
}

export function useAxes() {
  return useQuery({
    queryKey: keys.axes,
    queryFn: () => api.get<AxisDef[]>(routes.insightAxes()),
  })
}

export function useInsight(axis: string | undefined) {
  return useQuery({
    queryKey: keys.insight(axis ?? ""),
    queryFn: () => api.get<AxisInsight>(routes.insight(axis as string)),
    enabled: Boolean(axis),
  })
}

export function useRecipes() {
  return useQuery({
    queryKey: keys.recipes,
    queryFn: () => api.get<RecipeGroup[]>(routes.recipes()),
  })
}

export function usePresets() {
  return useQuery({
    queryKey: keys.presets,
    queryFn: () => api.get<Preset[]>(routes.presets()),
  })
}

export function useTags() {
  return useQuery({
    queryKey: keys.tags,
    queryFn: () => api.get<string[]>(routes.tags()),
  })
}

/**
 * The next fair pair to judge.
 *
 * `exclude` is the list of runs skipped this session. It is part of the key, so a skip is a
 * different question rather than a refetch of the same one — the skipped clip cannot come back
 * from the cache.
 */
export function useArenaMatchup(exclude: string[] = []) {
  return useQuery({
    queryKey: keys.arenaMatchup(exclude),
    queryFn: () =>
      api.get<ArenaMatchup>(routes.arenaNext(), exclude.length ? { exclude } : undefined),
    // An empty arena is a 404 that says what to run; retrying will not change the answer.
    retry: false,
    staleTime: 0,
    gcTime: 0,
  })
}

export function useArenaStandings() {
  return useQuery({
    queryKey: keys.arenaStandings,
    queryFn: () => api.get<ArenaStandings>(routes.arenaStandings()),
  })
}

export function useVotes() {
  return useQuery({
    queryKey: keys.votes,
    queryFn: () => api.get<Vote[]>(routes.votes()),
  })
}

// --- writes ----------------------------------------------------------------

function invalidateRunWorld(client: QueryClient) {
  for (const key of derivedKeys) void client.invalidateQueries({ queryKey: key })
}

/** One place where a failed write becomes something readable on screen. */
function complain(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    toast.error(error.message || fallback, { description: error.detail })
    return
  }
  toast.error(fallback, { description: error instanceof Error ? error.message : String(error) })
}

export function useEnqueue() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { config: GenerationConfig; count?: number }) =>
      api.post<RunView[]>(routes.runs(), input),
    onSuccess: (created) => {
      invalidateRunWorld(client)
      const first = created[0]
      toast.success(
        created.length === 1 ? `Queued ${first?.run.label ?? "run"}` : `Queued ${created.length} runs`
      )
    },
    onError: (error) => complain(error, "could not queue that run"),
  })
}

export function useDryRun() {
  return useMutation({
    mutationFn: (config: GenerationConfig) => api.post<DryRun>(routes.dryRun(), { config }),
    onError: (error) => complain(error, "could not check that config"),
  })
}

export function useRerun() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { id: string; overrides?: Record<string, unknown> }) =>
      api.post<RunView>(routes.runRerun(input.id), { overrides: input.overrides ?? {} }),
    onSuccess: (view) => {
      invalidateRunWorld(client)
      toast.success(`Queued ${view.run.label} again`)
    },
    onError: (error) => complain(error, "could not run that again"),
  })
}

export function usePatchRun() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { id: string } & PatchRunRequest) => {
      const { id, ...body } = input
      return api.patch<RunView>(routes.run(id), body)
    },
    onSuccess: (view) => {
      client.setQueryData(keys.run(view.run.id), view)
      invalidateRunWorld(client)
    },
    onError: (error) => complain(error, "could not save that change"),
  })
}

export function useRate() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { id: string; stars: number; criteria?: Record<string, number> }) =>
      api.put<RunView>(routes.runRating(input.id), {
        stars: input.stars,
        criteria: input.criteria ?? {},
      }),
    onSuccess: (view) => {
      client.setQueryData(keys.run(view.run.id), view)
      invalidateRunWorld(client)
    },
    onError: (error) => complain(error, "could not save that rating"),
  })
}

export function useClearRating() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.del<RunView>(routes.runRating(id)),
    onSuccess: (view) => {
      client.setQueryData(keys.run(view.run.id), view)
      invalidateRunWorld(client)
    },
    onError: (error) => complain(error, "could not clear that rating"),
  })
}

export function useVote() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { run_a: string; run_b: string; winner: string | null; axis?: string }) =>
      api.post<Vote>(routes.votes(), input),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.elo })
      void client.invalidateQueries({ queryKey: keys.votes })
      invalidateRunWorld(client)
    },
    onError: (error) => complain(error, "could not record that vote"),
  })
}

export function useCancelRun() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.post<Ok>(routes.runCancel(id)),
    onSuccess: (result) => {
      invalidateRunWorld(client)
      toast[result.ok ? "success" : "message"](result.detail || "cancelled")
    },
    onError: (error) => complain(error, "could not cancel that run"),
  })
}

export function useDeleteRun() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.del<Ok>(routes.run(id)),
    onSuccess: () => {
      invalidateRunWorld(client)
      toast.success("Run deleted")
    },
    onError: (error) => complain(error, "could not delete that run"),
  })
}

export function useQueueControl() {
  const client = useQueryClient()
  const after = (message: string) => () => {
    invalidateRunWorld(client)
    toast.success(message)
  }
  return {
    pause: useMutation({
      mutationFn: () => api.post<Ok>(routes.queuePause()),
      onSuccess: after("Queue paused"),
      onError: (error: unknown) => complain(error, "could not pause the queue"),
    }),
    resume: useMutation({
      mutationFn: () => api.post<Ok>(routes.queueResume()),
      onSuccess: after("Queue resumed"),
      onError: (error: unknown) => complain(error, "could not resume the queue"),
    }),
    clear: useMutation({
      mutationFn: () => api.post<Ok>(routes.queueClear()),
      onSuccess: (result: Ok) => {
        invalidateRunWorld(client)
        toast.success(result.detail || "Queue cleared")
      },
      onError: (error: unknown) => complain(error, "could not clear the queue"),
    }),
  }
}

export function useSweepPreview() {
  return useMutation({
    mutationFn: (body: SweepRequest) => api.post<SweepPreview>(routes.sweepPreview(), body),
    onError: (error) => complain(error, "could not work out that sweep"),
  })
}

export function useRunSweep() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: SweepRequest) => api.post<RunView[]>(routes.sweeps(), body),
    onSuccess: (created) => {
      invalidateRunWorld(client)
      toast.success(`Queued ${created.length} run${created.length === 1 ? "" : "s"}`)
    },
    onError: (error) => complain(error, "could not start that sweep"),
  })
}

export function useSavePreset() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: {
      name: string
      run_id?: string
      config?: GenerationConfig
      replace?: boolean
    }) => api.post<Preset>(routes.presets(), input),
    onSuccess: (preset) => {
      void client.invalidateQueries({ queryKey: keys.presets })
      toast.success(`Saved “${preset.name}”`)
    },
    onError: (error) => complain(error, "could not save that preset"),
  })
}

export function useDeletePreset() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.del<Ok>(routes.preset(id)),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.presets })
      toast.success("Preset deleted")
    },
    onError: (error) => complain(error, "could not delete that preset"),
  })
}

export function useSetBaseline() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (runId: string | null) => api.put<Ok>(routes.baseline(), { run_id: runId }),
    onSuccess: (_result, runId) => {
      invalidateRunWorld(client)
      toast.success(runId ? "Baseline pinned" : "Baseline cleared")
    },
    onError: (error) => complain(error, "could not pin that baseline"),
  })
}

export function useUpload() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData()
      form.append("file", file)
      return api.post<Upload>(routes.uploads(), form)
    },
    onSuccess: (result) => {
      void client.invalidateQueries({ queryKey: keys.catalog })
      toast.success(`Uploaded ${result.name}`)
    },
    onError: (error) => complain(error, "could not upload that file"),
  })
}
