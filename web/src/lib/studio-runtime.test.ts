import { describe, expect, it, vi } from "vitest"

import type { Draft } from "./config"
import {
  loadStudioRuntime,
  projectStudioInputs,
  studioInputsFromDraft,
  type StudioSession,
} from "./studio-runtime"

function session(overrides: Partial<StudioSession> = {}): StudioSession {
  return {
    contract_version: 1,
    component_version: "1.1.0",
    node_class: "MiniMaxH3Studio",
    module_url: "/api/studio/component.js",
    prepare_url: "/api/studio/prepare",
    workflow: {},
    bindings: {},
    ...overrides,
  }
}

describe("Studio runtime", () => {
  it("rejects an unknown contract before importing code", async () => {
    const importer = vi.fn()
    await expect(
      loadStudioRuntime(
        { ...session(), contract_version: 2 } as unknown as StudioSession,
        importer
      )
    ).rejects.toThrow("contract version")
    expect(importer).not.toHaveBeenCalled()
  })

  it("requires the public mount export", async () => {
    await expect(
      loadStudioRuntime(
        session({ module_url: "/missing-export.js" }),
        async () => ({})
      )
    ).rejects.toThrow("mountMiniMaxH3Studio")
  })

  it("imports one component version once", async () => {
    const mountMiniMaxH3Studio = vi.fn()
    const importer = vi.fn(async () => ({ mountMiniMaxH3Studio }))
    const source = session({ module_url: "/cached-component.js" })
    const first = await loadStudioRuntime(source, importer)
    const second = await loadStudioRuntime(source, importer)
    expect(first).toBe(second)
    expect(importer).toHaveBeenCalledTimes(1)
    expect(importer).toHaveBeenCalledWith(
      "/cached-component.js?h3s_component_version=1.1.0"
    )
  })

  it("loads a changed component version afresh", async () => {
    const importer = vi.fn(async () => ({ mountMiniMaxH3Studio: vi.fn() }))
    await loadStudioRuntime(
      session({
        module_url: "/versioned-component.js",
        component_version: "1.1.0",
      }),
      importer
    )
    await loadStudioRuntime(
      session({
        module_url: "/versioned-component.js",
        component_version: "1.2.0",
      }),
      importer
    )
    expect(importer).toHaveBeenCalledTimes(2)
    expect(importer).toHaveBeenNthCalledWith(
      2,
      "/versioned-component.js?h3s_component_version=1.2.0"
    )
  })
})

describe("Studio input persistence", () => {
  it("projects a draft into the names the mounted component owns", () => {
    const source = session({
      workflow: {
        "42": {
          class_type: "MiniMaxH3Studio",
          inputs: {
            mode: "T2V",
            prompt: "",
            duration: 5,
            interpolation: "none",
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
        interpolation: {
          key: "interp",
          store: "config",
          values: { none: "off", film: "film", rife: "rife", gmfss: "gmfss" },
        },
        cache: { key: "cache_enabled", store: "config" },
        references: { key: "references", store: "references" },
      },
    })
    expect(
      studioInputsFromDraft(source, {
        mode: "flf2v",
        prompt: "a shot",
        duration_s: 8,
        interp: "off",
        cache_enabled: false,
        sol_attn: false,
        ref_images: ["one.png"],
        ref_videos: [],
        ref_video_audios: [],
        ref_audios: ["sound.wav"],
        widgets: { attn: "comfy_kitchen", future_control: 4 },
      })
    ).toEqual({
      attn: "comfy_kitchen",
      future_control: 4,
      mode: "FLF2V",
      prompt: "a shot",
      duration: 8,
      interpolation: "none",
      cache: false,
      references:
        '{"images":["one.png"],"videos":[],"video_audios":[],"audios":["sound.wav"]}',
      sol_attn: false,
    })
  })

  it("projects complete inputs into a minimal draft patch", () => {
    const draft: Draft = {
      mode: "t2v",
      prompt: "old",
      duration_s: 5,
      cache: "spectrum",
      cache_enabled: true,
      widgets: { retained: "yes" },
    }
    const patch = projectStudioInputs(
      {
        mode: "FLF2V",
        prompt: "new",
        duration: 7,
        cache: false,
        attn: "comfy_kitchen",
        sol_attn: false,
        references:
          '{"images":["a.png"],"videos":["v.mp4"],"video_audios":["v.wav"],"audios":["a.wav"]}',
        future_control: { amount: 3 },
      },
      {
        mode: {
          key: "mode",
          store: "config",
          values: { T2V: "t2v", FLF2V: "flf2v", R2V: "r2v" },
        },
        duration: { key: "duration_s", store: "config" },
        cache: { key: "cache_enabled", store: "config" },
        references: { key: "references", store: "references" },
      },
      draft
    )
    expect(patch).toEqual({
      mode: "flf2v",
      prompt: "new",
      duration_s: 7,
      cache_enabled: false,
      ref_images: ["a.png"],
      ref_videos: ["v.mp4"],
      ref_video_audios: ["v.wav"],
      ref_audios: ["a.wav"],
      sol_attn: false,
      widgets: {
        retained: "yes",
        attn: "comfy_kitchen",
        future_control: { amount: 3 },
      },
    })
  })

  it("does not emit fields whose values did not change", () => {
    const draft: Draft = {
      mode: "t2v",
      prompt: "same",
      widgets: { retained: true, future: 1 },
    }
    expect(
      projectStudioInputs(
        { mode: "T2V", prompt: "same", future: 1 },
        {
          mode: {
            key: "mode",
            store: "config",
            values: { T2V: "t2v" },
          },
        },
        draft
      )
    ).toEqual({})
  })
})
