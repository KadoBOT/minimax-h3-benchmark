import { describe, expect, it } from "vitest"

import { CATALOG, META } from "@/test/harness"
import {
  acceptedFields,
  changedFields,
  display,
  inertFields,
  mediaDefaults,
  missingInputs,
} from "./config"
import type { Draft } from "./config"

const BASE: Draft = { mode: "t2v", steps: 20, seed: 1, cache: "none", sol_attn: false }

describe("draft configs", () => {
  it("greys out steps once turbo fixes the schedule", () => {
    expect(inertFields({ ...BASE, turbo: true }).has("steps")).toBe(true)
    expect(inertFields(BASE).has("steps")).toBe(false)
  })

  it("greys out a strength control whose feature is off", () => {
    expect(inertFields({ ...BASE, cache: "none" }).has("cache_preset")).toBe(true)
    expect(inertFields({ ...BASE, cache: "h3", cache_enabled: true }).has("cache_preset")).toBe(
      false
    )
    expect(inertFields(BASE).has("sol_preset")).toBe(true)
  })

  it("uses explicit attention rather than its legacy Sol projection", () => {
    expect(
      inertFields({ ...BASE, sol_attn: true, widgets: { attn: "comfy_kitchen" } }).has(
        "sol_preset"
      )
    ).toBe(true)
    expect(
      inertFields({ ...BASE, sol_attn: false, widgets: { attn: "sol" } }).has("sol_preset")
    ).toBe(false)
  })

  it("names what a mode is still missing, in the label the API uses", () => {
    expect(missingInputs({ mode: "t2v" }, META)).toEqual([])
    expect(missingInputs({ mode: "flf2v" }, META)).toEqual(["First frame"])
    expect(missingInputs({ mode: "flf2v", first_frame: "a.png" }, META)).toEqual([])
  })

  it("treats a requires-any mode as satisfied by either input", () => {
    expect(missingInputs({ mode: "r2v" }, META)).toEqual(["Ref images or Ref videos"])
    expect(missingInputs({ mode: "r2v", ref_images: ["a.png"] }, META)).toEqual([])
    expect(missingInputs({ mode: "r2v", ref_videos: ["clip.mp4"] }, META)).toEqual([])
  })

  it("falls back to a readable name for a field the API did not label", () => {
    const bare = { ...META, field_labels: {} }
    expect(missingInputs({ mode: "flf2v" }, bare)).toEqual(["first frame"])
  })

  it("does not count whitespace or an empty list as an answer", () => {
    expect(missingInputs({ mode: "flf2v", first_frame: "   " }, META)).toEqual(["First frame"])
    expect(missingInputs({ mode: "r2v", ref_images: [] }, META)).toEqual([
      "Ref images or Ref videos",
    ])
  })

  it("offers only the fields a mode reads", () => {
    const frames = acceptedFields(META, "flf2v")
    expect(frames.has("first_frame")).toBe(true)
    expect(frames.has("ref_images")).toBe(false)
  })

  it("reports what a preset would change against the current draft", () => {
    expect(changedFields(BASE, BASE)).toEqual([])
    expect(changedFields({ ...BASE, steps: 8 }, BASE)).toEqual(["steps"])
    expect(changedFields({ ...BASE, steps: 8, seed: 9 }, BASE)).toEqual(["seed", "steps"])
  })

  it("fills the input a mode needs from what this machine actually has", () => {
    expect(mediaDefaults({ mode: "flf2v" }, META, CATALOG)).toEqual({
      first_frame: "courier.png",
    })
    expect(mediaDefaults({ mode: "r2v" }, META, CATALOG)).toEqual({
      ref_images: ["ref-one.png", "ref-two.png"],
    })
  })

  it("leaves a mode that needs nothing alone", () => {
    expect(mediaDefaults({ mode: "t2v" }, META, CATALOG)).toEqual({})
  })

  it("never replaces media that is already there", () => {
    expect(mediaDefaults({ mode: "flf2v", first_frame: "mine.png" }, META, CATALOG)).toEqual({})
    expect(mediaDefaults({ mode: "r2v", ref_images: ["mine.png"] }, META, CATALOG)).toEqual({})
  })

  it("counts a sibling list as satisfying a requires-any mode", () => {
    // r2v is happy with videos alone, so pre-filling images would add an input nobody asked
    // for — and every extra reference changes what comes out.
    expect(mediaDefaults({ mode: "r2v", ref_videos: ["clip.mp4"] }, META, CATALOG)).toEqual({})
  })

  it("fills nothing when the machine has nothing to offer", () => {
    const bare = { ...CATALOG, default_first_frame: "", default_ref_images: [] }
    expect(mediaDefaults({ mode: "flf2v" }, META, bare)).toEqual({})
    expect(mediaDefaults({ mode: "r2v" }, META, bare)).toEqual({})
    expect(mediaDefaults({ mode: "flf2v" }, META, undefined)).toEqual({})
  })

  it("renders values the way the API renders them in diffs", () => {
    expect(display(true)).toBe("on")
    expect(display(false)).toBe("off")
    expect(display(null)).toBe("—")
    expect(display("")).toBe("—")
    expect(display([])).toBe("—")
    expect(display(["a.png", "b.png"])).toBe("a.png, b.png")
    expect(display(20)).toBe("20")
  })
})
