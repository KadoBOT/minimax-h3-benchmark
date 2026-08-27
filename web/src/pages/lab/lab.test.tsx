import { act, fireEvent, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { StudioMountOptions, StudioTemplateCatalog } from "@/lib/studio-runtime"
import { LabPage } from "@/pages/lab"
import {
  BASELINE_ROUTES,
  CATALOG,
  EMPTY_QUEUE,
  STUDIO_SESSION,
  fakeApi,
  makeView,
  renderApp,
} from "@/test/harness"
import { FakeEventSource } from "@/test/setup"

const studio = vi.hoisted(() => ({
  load: vi.fn(),
  mounts: [] as unknown[],
}))

vi.mock("@/lib/studio-runtime", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/studio-runtime")>()
  return { ...actual, loadStudioRuntime: studio.load }
})

const DRY_RUN = {
  ok: true,
  problems: [],
  graph: { nodes: 42, classes: [], missing_links: [], files: [] },
  config_hash: "abcdef1234567890",
  recipe_hash: "fedcba0987654321",
  duplicate_of: null,
}

const TEMPLATE_CATALOG = {
  version: 1,
  managed_keys: ["steps", "sampler_name", "derope"],
  selector: { label: "Template", placeholder: "Search templates" },
  categories: [
    { id: "essentials", name: "Essentials" },
    { id: "motion", name: "Motion profiles" },
  ],
  templates: [
    {
      id: "essentials/balanced",
      category: "essentials",
      name: "Balanced",
      description: "A balanced starting point.",
      tradeoff: "Moderate speed and detail.",
      evidence: "curated",
      evidence_ref: null,
      tags: ["general"],
      requirements: [],
      values: { steps: 20, sampler_name: "euler", derope: false },
    },
    {
      id: "motion/extreme-action-derope",
      category: "motion",
      name: "Extreme Action",
      description: "Maximum camera and subject motion.",
      tradeoff: "More temporal risk.",
      evidence: "experimental",
      evidence_ref: null,
      tags: ["action", "motion", "derope"],
      requirements: [],
      values: { steps: 28, sampler_name: "res_multistep", derope: true },
    },
  ],
} satisfies StudioTemplateCatalog

function latestMount(): StudioMountOptions {
  return studio.mounts.at(-1) as StudioMountOptions
}

beforeEach(() => {
  studio.mounts.length = 0
  studio.load.mockResolvedValue({
    mountMiniMaxH3Studio: vi.fn(async (container: HTMLElement, options: StudioMountOptions) => {
      studio.mounts.push(options)
      const marker = document.createElement("div")
      marker.textContent = "Shared Studio"
      container.append(marker)
      return {
        getInputs: vi.fn(() => options.inputs ?? {}),
        setInputs: vi.fn(),
        setWorkflow: vi.fn(),
        setPreview: vi.fn(),
        prepareWorkflow: vi.fn(),
        destroy: vi.fn(),
      }
    }),
  })
})

describe("the lab", () => {
  it("mounts the runtime component with the session's source workflow", async () => {
    fakeApi({ ...BASELINE_ROUTES })
    renderApp(<LabPage />)
    expect(await screen.findByText("Shared Studio")).toBeInTheDocument()
    expect(latestMount().workflow).toEqual(STUDIO_SESSION.workflow)
    expect(latestMount().inputs).toMatchObject({
      mode: "T2V",
      prompt: "a lighthouse in fog",
      duration: 5,
    })
  })

  it("queues complete component edits, including additive controls", async () => {
    const { calls } = fakeApi({ ...BASELINE_ROUTES, "POST /api/runs": [makeView()] })
    renderApp(<LabPage />)
    await screen.findByText("Shared Studio")

    act(() => {
      latestMount().onChange?.({
        mode: "T2V",
        prompt: "a kestrel over a motorway",
        duration: 7,
        aspect_ratio: "4:5 (Portrait)",
        cache: false,
        references: "{}",
        sol_attn: false,
        attn: "comfy_kitchen",
        dual: true,
        future_control: 0.35,
      })
    })
    await userEvent.click(screen.getByRole("button", { name: /queue run/i }))

    await waitFor(() => {
      const queued = calls.find((call) => call.method === "POST" && call.path === "/api/runs")
      const config = (queued?.body as { config: Record<string, unknown> })?.config
      expect(config).toMatchObject({
        prompt: "a kestrel over a motorway",
        duration_s: 7,
        aspect_ratio: "4:5 (Portrait)",
        cache_enabled: false,
        sol_attn: false,
        widgets: {
          attn: "comfy_kitchen",
          dual: true,
          future_control: 0.35,
        },
      })
    })
  })

  it("keeps benchmark-owned tuning editable beside Studio", async () => {
    const { calls } = fakeApi({ ...BASELINE_ROUTES, "POST /api/runs": [makeView()] })
    renderApp(<LabPage />)
    await screen.findByText("Shared Studio")

    act(() => {
      latestMount().onChange?.({
        cache: true,
        turbo: true,
        turbo_lora: "minimax_h3_turbo_4step.safetensors",
        attn: "sol",
        sol_attn: true,
      })
    })

    await userEvent.click(screen.getByRole("combobox", { name: "Cache family" }))
    await userEvent.click(await screen.findByRole("option", { name: "easy" }))
    await userEvent.click(screen.getByRole("combobox", { name: "Cache preset" }))
    await userEvent.click(await screen.findByRole("option", { name: "aggressive" }))
    await userEvent.click(screen.getByRole("combobox", { name: "Sol attention preset" }))
    await userEvent.click(await screen.findByRole("option", { name: "conservative" }))
    fireEvent.change(screen.getByRole("spinbutton", { name: "Turbo strength" }), {
      target: { value: "0.75" },
    })
    await userEvent.click(screen.getByRole("button", { name: /queue run/i }))

    await waitFor(() => {
      const queued = calls.find((call) => call.method === "POST" && call.path === "/api/runs")
      const config = (queued?.body as { config: Record<string, unknown> })?.config
      expect(config).toMatchObject({
        cache: "easy",
        cache_enabled: true,
        cache_preset: "aggressive",
        sol_preset: "conservative",
        turbo: true,
        turbo_lora_strength: 0.75,
      })
    })
  })

  it("checks a config without queueing it, and reports the graph it built", async () => {
    const { calls } = fakeApi({ ...BASELINE_ROUTES, "POST /api/runs/dry-run": DRY_RUN })
    renderApp(<LabPage />)
    await userEvent.click(await screen.findByRole("button", { name: /^check$/i }))
    expect(await screen.findByText(/builds cleanly — 42 nodes/i)).toBeInTheDocument()
    expect(screen.getByText("abcdef12")).toBeInTheDocument()
    expect(calls.some((call) => call.path === "/api/runs")).toBe(false)
  })

  it("names graph problems from a dry run", async () => {
    fakeApi({
      ...BASELINE_ROUTES,
      "POST /api/runs/dry-run": {
        ...DRY_RUN,
        ok: false,
        graph: null,
        problems: ["LoadImage.image points at a file ComfyUI does not have"],
      },
    })
    renderApp(<LabPage />)
    await userEvent.click(await screen.findByRole("button", { name: /^check$/i }))
    expect(
      await screen.findByText(/points at a file ComfyUI does not have/i)
    ).toBeInTheDocument()
  })

  it("points at the earlier run when this exact config ran before", async () => {
    fakeApi({
      ...BASELINE_ROUTES,
      "POST /api/runs/dry-run": { ...DRY_RUN, duplicate_of: "run7" },
    })
    renderApp(<LabPage />)
    await userEvent.click(await screen.findByRole("button", { name: /^check$/i }))
    expect(await screen.findByRole("link", { name: /open that run/i })).toHaveAttribute(
      "href",
      "/runs/run7"
    )
  })

  it("offers Studio attention and aspect values as sweep axes", async () => {
    fakeApi({ ...BASELINE_ROUTES })
    renderApp(<LabPage />)

    await userEvent.click(await screen.findByRole("combobox", { name: "Add a sweep axis" }))
    await userEvent.click(await screen.findByRole("option", { name: /attention/i }))
    expect(await screen.findByRole("button", { name: "off" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "sol" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "comfy_kitchen" })).toBeInTheDocument()

    await userEvent.click(screen.getByRole("button", { name: /stop varying attention/i }))
    await userEvent.click(screen.getByRole("combobox", { name: "Add a sweep axis" }))
    await userEvent.click(await screen.findByRole("option", { name: /aspect ratio/i }))
    expect(await screen.findByRole("button", { name: "4:5 (Portrait)" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "1.91:1 (Landscape)" })).toBeInTheDocument()
  })

  it("offers every installed model as a sweep axis value", async () => {
    fakeApi({ ...BASELINE_ROUTES })
    renderApp(<LabPage />)

    await userEvent.click(await screen.findByRole("combobox", { name: "Add a sweep axis" }))
    await userEvent.click(await screen.findByRole("option", { name: /diffusion model/i }))

    expect(await screen.findByRole("button", { name: "fp8" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "bf16" })).toBeInTheDocument()
  })

  it("previews selected Template arms by their catalog ids", async () => {
    const { calls } = fakeApi({
      ...BASELINE_ROUTES,
      "/api/studio/session": {
        ...STUDIO_SESSION,
        template_catalog: TEMPLATE_CATALOG,
        capabilities: {},
      },
      "POST /api/sweeps/preview": {
        count: 2,
        combinations: 2,
        repeats: 1,
        new_count: 2,
        duplicate_count: 0,
        items: [],
      },
    })
    renderApp(<LabPage />)

    await userEvent.click(await screen.findByRole("combobox", { name: "Add a sweep axis" }))
    await userEvent.click(await screen.findByRole("option", { name: "Template" }))
    await userEvent.click(screen.getByRole("button", { name: /balanced/i }))
    await userEvent.type(
      screen.getByRole("searchbox", { name: "Search template axis" }),
      "Extreme Action"
    )
    await userEvent.click(screen.getByRole("button", { name: /extreme action/i }))
    await userEvent.click(screen.getByRole("button", { name: "Preview" }))

    await waitFor(() => {
      const request = calls.find(
        (call) => call.method === "POST" && call.path === "/api/sweeps/preview"
      )
      expect(request?.body).toMatchObject({
        axes: [
          {
            field: "template",
            values: ["__current__", "motion/extreme-action-derope"],
          },
        ],
      })
    })
  })

  it("keeps Template mutually exclusive with managed axes", async () => {
    fakeApi({
      ...BASELINE_ROUTES,
      "/api/studio/session": {
        ...STUDIO_SESSION,
        template_catalog: TEMPLATE_CATALOG,
        capabilities: {},
      },
    })
    renderApp(<LabPage />)

    await userEvent.click(await screen.findByRole("combobox", { name: "Add a sweep axis" }))
    await userEvent.click(await screen.findByRole("option", { name: "Template" }))
    await userEvent.click(screen.getByRole("combobox", { name: "Add a sweep axis" }))
    expect(screen.queryByRole("option", { name: "Steps" })).not.toBeInTheDocument()

    await userEvent.keyboard("{Escape}")
    await userEvent.click(screen.getByRole("button", { name: "Stop varying Template" }))
    await userEvent.click(screen.getByRole("combobox", { name: "Add a sweep axis" }))
    expect(await screen.findByRole("option", { name: "Steps" })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: "ER-SDE" })).toBeInTheDocument()
    await userEvent.click(screen.getByRole("option", { name: "Steps" }))
    await userEvent.click(screen.getByRole("combobox", { name: "Add a sweep axis" }))
    expect(screen.queryByRole("option", { name: "Template" })).not.toBeInTheDocument()
  })

  it("seeds Template from the draft's sweep provenance", async () => {
    window.localStorage.setItem(
      "h3lab.draft",
      JSON.stringify({
        ...CATALOG.defaults,
        mode: "t2v",
        diffusion_model: CATALOG.default_diffusion_model,
        widgets: {
          h3s_ui: JSON.stringify({
            version: 1,
            template_id: "motion/extreme-action-derope",
            source: "sweep",
          }),
        },
      })
    )
    fakeApi({
      ...BASELINE_ROUTES,
      "/api/studio/session": {
        ...STUDIO_SESSION,
        template_catalog: TEMPLATE_CATALOG,
        capabilities: {},
      },
    })
    renderApp(<LabPage />)

    await userEvent.click(await screen.findByRole("combobox", { name: "Add a sweep axis" }))
    await userEvent.click(await screen.findByRole("option", { name: "Template" }))

    expect(screen.getByRole("button", { name: /current settings/i })).toHaveAttribute(
      "aria-pressed",
      "true"
    )
    expect(screen.getByRole("button", { name: /extreme action/i })).toHaveAttribute(
      "aria-pressed",
      "true"
    )
    expect(screen.getByRole("button", { name: /balanced/i })).toHaveAttribute(
      "aria-pressed",
      "false"
    )
  })

  it("shows the frame ComfyUI is drawing while a run is in flight", async () => {
    const active = makeView({ run: { id: "r-live", label: "#9 r2v · 4st", status: "running" } })
    fakeApi({
      ...BASELINE_ROUTES,
      "/api/queue": { ...EMPTY_QUEUE, active_run_id: "r-live", active, queued: [], total: 0 },
    })
    renderApp(<LabPage />)
    await screen.findByText("#9 r2v · 4st")
    expect(screen.queryByRole("img", { name: /preview frame/i })).not.toBeInTheDocument()

    const source = FakeEventSource.instances.at(-1)!
    act(() => {
      source.emit({ seq: 1, kind: "run.started", run_id: "r-live", data: {} })
      source.emit({
        seq: 2,
        kind: "run.progress",
        run_id: "r-live",
        data: { step: 2, step_total: 4, preview_seq: 3, preview_mime: "image/jpeg" },
      })
    })
    expect(await screen.findByRole("img", { name: /preview frame 3/i })).toHaveAttribute(
      "src",
      "/api/runs/r-live/preview?f=3"
    )
  })

  it("plays a video preview", async () => {
    const active = makeView({ run: { id: "r-live", label: "#9 r2v · 4st", status: "running" } })
    fakeApi({
      ...BASELINE_ROUTES,
      "/api/queue": { ...EMPTY_QUEUE, active_run_id: "r-live", active, queued: [], total: 0 },
    })
    renderApp(<LabPage />)
    await screen.findByText("#9 r2v · 4st")

    act(() => {
      FakeEventSource.instances.at(-1)!.emit({
        seq: 2,
        kind: "run.progress",
        run_id: "r-live",
        data: { step: 1, step_total: 4, preview_seq: 1, preview_mime: "video/mp4" },
      })
    })
    const clip = await screen.findByLabelText(/preview frame 1/i)
    expect(clip.tagName).toBe("VIDEO")
    expect(clip).toHaveAttribute("src", "/api/runs/r-live/preview?f=1")
    expect((clip as HTMLVideoElement).muted).toBe(true)
  })

  it("recovers after a preview frame cannot be displayed", async () => {
    const active = makeView({ run: { id: "r-live", label: "#9 r2v · 4st", status: "running" } })
    fakeApi({
      ...BASELINE_ROUTES,
      "/api/queue": { ...EMPTY_QUEUE, active_run_id: "r-live", active, queued: [], total: 0 },
    })
    renderApp(<LabPage />)
    await screen.findByText("#9 r2v · 4st")
    const source = FakeEventSource.instances.at(-1)!
    const progress = (seq: number) => ({
      seq,
      kind: "run.progress" as const,
      run_id: "r-live",
      data: { step: seq, step_total: 4, preview_seq: seq, preview_mime: "image/jpeg" },
    })

    act(() => source.emit(progress(1)))
    fireEvent.error(await screen.findByAltText(/preview frame 1/i))
    expect(screen.queryByAltText(/preview frame/i)).not.toBeInTheDocument()
    act(() => source.emit(progress(2)))
    expect(await screen.findByAltText(/preview frame 2/i)).toBeInTheDocument()
  })

  it("warns when ComfyUI is unreachable but still permits queueing", async () => {
    fakeApi({
      ...BASELINE_ROUTES,
      "/api/catalog": { ...CATALOG, comfy_online: false },
    })
    renderApp(<LabPage />)
    expect(await screen.findByText(/comfyui is not answering/i)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /queue run/i })).not.toBeDisabled()
  })

  it("restores component inputs from the saved draft", async () => {
    fakeApi({ ...BASELINE_ROUTES })
    const first = renderApp(<LabPage />)
    await screen.findByText("Shared Studio")
    act(() => {
      latestMount().onChange?.({
        mode: "T2V",
        prompt: "held across a reload",
        duration: 5,
        cache: false,
        references: "{}",
        sol_attn: false,
        attn: "off",
      })
    })
    await waitFor(() =>
      expect(window.localStorage.getItem("h3lab.draft")).toContain("held across a reload")
    )
    first.unmount()

    renderApp(<LabPage />)
    await waitFor(() => expect(studio.mounts).toHaveLength(2))
    expect(latestMount().inputs).toMatchObject({ prompt: "held across a reload" })
  })

  it("replaces a persisted model that is no longer installed", async () => {
    const installed = "minimax-h3/MiniMax_H3_FL2VA_pruned_int8_convrot.safetensors"
    window.localStorage.setItem(
      "h3lab.draft",
      JSON.stringify({
        ...CATALOG.defaults,
        mode: "t2v",
        diffusion_model: "minimax_h3_fl2va_pruned_nvfp4.safetensors",
      })
    )
    fakeApi({
      ...BASELINE_ROUTES,
      "/api/catalog": {
        ...CATALOG,
        diffusion_models: [installed, "minimax-h3/custom_variant.safetensors"],
        default_diffusion_model: installed,
        defaults: { ...CATALOG.defaults, diffusion_model: installed },
      },
    })

    renderApp(<LabPage />)

    const weights = await screen.findByRole("combobox", { name: "Weights" })
    expect(weights).toHaveTextContent("FL2VA_pruned_int8_convrot")
    expect(weights).not.toHaveTextContent("nvfp4")
    await waitFor(() => {
      const saved = JSON.parse(window.localStorage.getItem("h3lab.draft") ?? "{}")
      expect(saved.diffusion_model).toBe(installed)
    })
  })
})
