/**
 * A whole app in a test, minus the network.
 *
 * `fakeApi` is an in-memory stand-in for the real server: it holds runs, ratings, and votes,
 * and answers the same URLs with the same shapes the generated types describe. Tests drive the
 * real components against it, so a test failing means the UI is wrong rather than the mock.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, type RenderOptions } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { vi } from "vitest"

import { EventStreamProvider } from "@/api/events"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { BenchProvider } from "@/lib/bench"
import type {
  Catalog,
  GenerationConfig,
  LabStatus,
  Meta,
  Run,
  RunView,
  QueueState,
} from "@/api/schema"

export function testClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  })
}

export function renderApp(
  ui: React.ReactNode,
  { route = "/", ...options }: RenderOptions & { route?: string } = {}
) {
  const client = testClient()
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <BenchProvider>
          <EventStreamProvider>
            <TooltipProvider>
              <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
              <Toaster />
            </TooltipProvider>
          </EventStreamProvider>
        </BenchProvider>
      </QueryClientProvider>,
      options
    ),
  }
}

// --- fixtures ---------------------------------------------------------------

export const CONFIG: GenerationConfig = {
  mode: "t2v",
  diffusion_model: "minimax_h3_fp8.safetensors",
  prompt: "a lighthouse in fog",
  scheduler: "simple",
  sampler: "euler",
  aspect_ratio: "16:9",
  steps: 20,
  seed: 7,
  mp: 0.5,
  duration_s: 5,
  turbo: false,
  turbo_lora: "",
  turbo_lora_strength: 1,
  interp: "off",
  upscaler: false,
  clean_vram: false,
  cache_enabled: false,
  cache: "none",
  cache_preset: "moderate",
  sol_attn: false,
  sol_preset: "moderate",
  ref_images: [],
  ref_videos: [],
  ref_audios: [],
  ref_video_audios: [],
  first_frame: "",
  last_frame: "",
  ref_image_size: "match",
  widgets: {},
}

let counter = 0

export function makeRun(overrides: Partial<Run> = {}): Run {
  counter += 1
  const id = overrides.id ?? `run${counter}`
  return {
    id,
    seq: counter,
    label: `t2v · euler · ${counter}`,
    status: "succeeded",
    config: { ...CONFIG, seed: counter },
    config_hash: `cfg${counter}`,
    recipe_hash: `rcp${counter}`,
    metrics: { wall_s: 60, sec_per_it: 1.5, steps: 20 },
    artifact: {
      video_path: `${id}.mp4`,
      poster_path: `${id}.jpg`,
      strip_path: `${id}-strip.jpg`,
      width: 832,
      height: 480,
      fps: 24,
      frame_count: 121,
      size_bytes: 2_400_000,
    },
    error: null,
    favourite: false,
    archived: false,
    notes: "",
    tags: [],
    created_at: new Date().toISOString(),
    started_at: null,
    finished_at: null,
    ...overrides,
  }
}

export function makeView(
  overrides: Omit<Partial<RunView>, "run"> & { run?: Partial<Run> } = {}
): RunView {
  const { run, ...rest } = overrides
  return {
    run: makeRun(run),
    stars: null,
    criteria: {},
    elo: null,
    elo_games: 0,
    score: null,
    rank: null,
    duplicate_of: null,
    is_baseline: false,
    ...rest,
  }
}

export const META: Meta = {
  axes: [
    { field: "cache", label: "Cache", kind: "categorical" },
    { field: "steps", label: "Steps", kind: "numeric" },
    { field: "turbo_lora", label: "Turbo LoRA", kind: "categorical" },
  ],
  criteria: ["motion", "adherence", "artifacts", "detail", "consistency"],
  criterion_labels: {
    motion: "Motion",
    adherence: "Prompt adherence",
    artifacts: "Artifact-free",
    detail: "Detail",
    consistency: "Temporal consistency",
  },
  stars: { min: 1, max: 10 },
  seed_strategies: ["fixed", "increment", "random"],
  field_labels: {
    cache: "Cache",
    steps: "Steps",
    turbo: "Turbo",
    turbo_lora: "Turbo LoRA",
    turbo_lora_strength: "Turbo strength",
    sampler: "Sampler",
    seed: "Seed",
    first_frame: "First frame",
    last_frame: "Last frame",
    ref_images: "Ref images",
    ref_videos: "Ref videos",
    ref_audios: "Ref audio",
  },
  modes: [
    { mode: "t2v", label: "Text", requires_all: [], requires_any: [], accepts: ["prompt"] },
    {
      mode: "flf2v",
      label: "Frames",
      requires_all: ["first_frame"],
      requires_any: [],
      accepts: ["first_frame", "last_frame"],
    },
    {
      mode: "r2v",
      label: "Reference",
      requires_all: [],
      requires_any: ["ref_images", "ref_videos"],
      accepts: ["ref_images", "ref_videos", "ref_audios"],
    },
  ],
  caches: ["none", "spectrum", "easy", "h3"],
  interpolations: ["off", "film", "rife"],
  interpolation_labels: { off: "Off", film: "FILM Net", rife: "RIFE" },
  preset_levels: ["conservative", "moderate", "aggressive", "custom"],
  config_fields: Object.keys(CONFIG),
  defaults: CONFIG as unknown as Record<string, unknown>,
  comfy_url: "http://127.0.0.1:8188",
}

export const CATALOG: Catalog = {
  comfy_online: true,
  comfy_url: "http://127.0.0.1:8188",
  source: "comfy",
  schedulers: ["simple", "beta"],
  samplers: ["euler", "dpmpp_2m"],
  aspect_ratios: ["16:9", "1:1"],
  diffusion_models: ["minimax_h3_fp8.safetensors", "minimax_h3_bf16.safetensors"],
  diffusion_models_source: "comfy",
  default_diffusion_model: "minimax_h3_fp8.safetensors",
  turbo_loras: ["minimax_h3_turbo_4step.safetensors", "minimax_h3_turbo_8step.safetensors"],
  turbo_loras_source: "comfy",
  default_turbo_lora: "minimax_h3_turbo_4step.safetensors",
  turbo_lora_steps: {
    "minimax_h3_turbo_4step.safetensors": 4,
    "minimax_h3_turbo_8step.safetensors": 8,
  },
  images: ["a.png", "b.png", "courier.png", "ref-one.png", "ref-two.png"],
  videos: ["clip.mp4"],
  audios: [],
  media_source: "comfy",
  default_first_frame: "courier.png",
  default_ref_images: ["ref-one.png", "ref-two.png"],
  modes: ["t2v", "flf2v", "r2v"],
  preset_levels: ["conservative", "moderate", "aggressive", "custom"],
  reference_limits: { images: 4, videos: 2, audios: 2 },
  defaults: {},
}

export const STATUS: LabStatus = {
  worker_alive: true,
  paused: false,
  active_run_id: null,
  queued: 0,
  comfy_url: "http://127.0.0.1:8188",
  last_error: null,
  counts: { succeeded: 2 },
  total_runs: 2,
  votes: 0,
  rated: 0,
  baseline_run_id: null,
  event_seq: 0,
  criteria: META.criteria,
}

export const EMPTY_QUEUE: QueueState = {
  paused: false,
  worker_alive: true,
  active_run_id: null,
  active: null,
  queued: [],
  total: 0,
}

// --- the fake server --------------------------------------------------------

type Handler = (url: URL, init: RequestInit | undefined) => unknown

/**
 * Route table for the fake server.
 *
 * Keys are matched longest-first against the path, so `/api/runs/x/rating` wins over
 * `/api/runs`. A handler returning `undefined` means "not found", which surfaces in the UI as
 * the same Problem shape the real API sends.
 */
export function fakeApi(routes: Record<string, Handler | unknown>) {
  const calls: { method: string; path: string; body: unknown }[] = []

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const raw = typeof input === "string" ? input : input.toString()
    const url = new URL(raw, "http://localhost")
    const method = (init?.method ?? "GET").toUpperCase()
    const key = `${method} ${url.pathname}`
    let body: unknown = null
    if (typeof init?.body === "string") {
      try {
        body = JSON.parse(init.body)
      } catch {
        body = init.body
      }
    }
    calls.push({ method, path: url.pathname, body })

    // `null` is a legitimate response body, so presence is checked with `in` rather than by
    // testing the value — otherwise a handler returning null reads as "no such route".
    const wildcard = Object.entries(routes)
      .filter(([pattern]) => pattern.includes("*"))
      .sort((a, b) => b[0].length - a[0].length)
      .find(([pattern]) => {
        const [patternMethod, patternPath] = pattern.includes(" ")
          ? pattern.split(" ")
          : ["", pattern]
        if (patternMethod && patternMethod !== method) return false
        return new RegExp(`^${(patternPath ?? "").replace(/\*/g, "[^/]+")}$`).test(url.pathname)
      })

    const found = key in routes ? key : url.pathname in routes ? url.pathname : null
    const match = found !== null ? routes[found] : wildcard?.[1]

    if (found === null && wildcard === undefined) {
      return new Response(
        JSON.stringify({
          error: `no route for ${key}`,
          detail: "the test's fakeApi has no handler for this URL",
          kind: "not_found",
        }),
        { status: 404, headers: { "Content-Type": "application/json" } }
      )
    }

    const payload = typeof match === "function" ? (match as Handler)(url, init) : match
    if (payload instanceof Response) return payload
    return new Response(JSON.stringify(payload ?? null), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })
  })

  vi.stubGlobal("fetch", fetchMock)
  return { calls, fetchMock }
}

/** The reads every page performs on mount, so a test only declares what it cares about. */
export const BASELINE_ROUTES = {
  "/api/meta": META,
  "/api/catalog": CATALOG,
  "/api/status": STATUS,
  "/api/queue": EMPTY_QUEUE,
  "/api/presets": [],
  "/api/tags": [],
  "/api/recipes": [],
  "/api/insights/axes": [],
}
