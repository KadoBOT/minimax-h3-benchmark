import { useState } from "react"
import { act, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import type { Draft } from "@/lib/config"
import type {
  StudioController,
  StudioMountOptions,
  StudioSession,
} from "@/lib/studio-runtime"
import { BASELINE_ROUTES, CONFIG, fakeApi, renderApp } from "@/test/harness"
import { StudioHost } from "./studio-host"

const runtime = vi.hoisted(() => ({
  load: vi.fn(),
}))

vi.mock("@/lib/studio-runtime", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/studio-runtime")>()
  return { ...actual, loadStudioRuntime: runtime.load }
})

const SESSION: StudioSession = {
  contract_version: 1,
  component_version: "1.1.0",
  node_class: "MiniMaxH3Studio",
  module_url: "/api/studio/component.js",
  prepare_url: "/api/studio/prepare",
  workflow: {
    "42": {
      class_type: "MiniMaxH3Studio",
      inputs: {
        mode: "T2V",
        prompt: "",
        duration: 5,
        cache: true,
        references: "{}",
        sol_attn: true,
      },
    },
  },
  bindings: {
    mode: {
      key: "mode",
      store: "config",
      values: { T2V: "t2v", FLF2V: "flf2v", R2V: "r2v" },
    },
    duration: { key: "duration_s", store: "config" },
    cache: { key: "cache_enabled", store: "config" },
    references: { key: "references", store: "references" },
  },
}

function fakeController(): StudioController {
  return {
    getInputs: vi.fn(() => ({})),
    setInputs: vi.fn(),
    setWorkflow: vi.fn(),
    setPreview: vi.fn(),
    prepareWorkflow: vi.fn(),
    destroy: vi.fn(),
  }
}

describe("Studio host", () => {
  it("mounts the runtime-owned component with source workflow and persisted inputs", async () => {
    const controller = fakeController()
    let options: StudioMountOptions | undefined
    const mount = vi.fn(async (container: HTMLElement, next: StudioMountOptions) => {
      options = next
      container.textContent = "Runtime Studio"
      return controller
    })
    runtime.load.mockResolvedValue({ mountMiniMaxH3Studio: mount })
    fakeApi({ ...BASELINE_ROUTES, "/api/studio/session": SESSION })
    const onChange = vi.fn()
    let setDraft: (draft: Draft) => void = () => {}
    function Harness() {
      const [draft, setCurrent] = useState<Draft>(CONFIG)
      setDraft = setCurrent
      return <StudioHost draft={draft} onChange={onChange} />
    }

    const view = renderApp(<Harness />)
    expect(await screen.findByText("Runtime Studio")).toBeInTheDocument()
    expect(mount).toHaveBeenCalledTimes(1)
    expect(options?.workflow).toEqual(SESSION.workflow)
    expect(options?.inputs).toMatchObject({
      mode: "T2V",
      prompt: CONFIG.prompt,
      duration: CONFIG.duration_s,
      cache: CONFIG.cache_enabled,
    })

    act(() => {
      options?.onChange?.({
        mode: "T2V",
        prompt: "changed in Studio",
        duration: 9,
        cache: false,
        sol_attn: false,
        attn: "comfy_kitchen",
        references: "{}",
        future_control: 3,
      })
    })
    expect(onChange).toHaveBeenCalledWith({
      prompt: "changed in Studio",
      duration_s: 9,
      widgets: { attn: "comfy_kitchen", future_control: 3 },
    })

    act(() => setDraft({ ...CONFIG, prompt: "outside change" }))
    await waitFor(() => {
      expect(controller.setInputs).toHaveBeenCalledWith(
        expect.objectContaining({ prompt: "outside change" }),
        false
      )
    })
    expect(mount).toHaveBeenCalledTimes(1)

    view.unmount()
    expect(controller.destroy).toHaveBeenCalledTimes(1)
  })

  it("shows a usable error when the runtime cannot load", async () => {
    runtime.load.mockRejectedValue(new Error("Unsupported Studio contract version 2"))
    fakeApi({ ...BASELINE_ROUTES, "/api/studio/session": SESSION })
    renderApp(<StudioHost draft={CONFIG} onChange={vi.fn()} />)
    expect(await screen.findByText(/unsupported studio contract version 2/i)).toBeInTheDocument()
  })

  it("requests a new source workflow when the mode changes", async () => {
    const controller = fakeController()
    runtime.load.mockResolvedValue({
      mountMiniMaxH3Studio: vi.fn(async () => controller),
    })
    const { fetchMock } = fakeApi({
      ...BASELINE_ROUTES,
      "/api/studio/session": SESSION,
    })
    let setDraft: (draft: Draft) => void = () => {}
    function Harness() {
      const [draft, setCurrent] = useState<Draft>(CONFIG)
      setDraft = setCurrent
      return <StudioHost draft={draft} onChange={vi.fn()} />
    }
    renderApp(<Harness />)
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("mode=t2v"))).toBe(true)
    )
    act(() => setDraft({ ...CONFIG, mode: "flf2v" }))
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("mode=flf2v"))).toBe(true)
    )
  })
})
