import { describe, expect, it } from "vitest"

import type { StudioTemplateCatalog } from "@/lib/studio-runtime"
import { META } from "@/test/harness"
import {
  TEMPLATE_CONFLICT_FIELDS,
  sweepable,
  templateIdFromState,
} from "./sweep-options"

const CATALOG = {
  samplers: ["legacy sampler"],
  schedulers: ["legacy scheduler"],
  aspect_ratios: ["16:9"],
  diffusion_models: ["model.safetensors"],
  turbo_loras: ["legacy-lora.safetensors"],
}

const TEMPLATES = {
  version: 1,
  managed_keys: ["steps", "derope"],
  selector: { label: "Template", placeholder: "Search templates" },
  categories: [{ id: "essentials", name: "Essentials" }],
  templates: [
    {
      id: "essentials/balanced",
      category: "essentials",
      name: "Balanced",
      description: "General settings.",
      tradeoff: "Balanced speed and quality.",
      evidence: "curated",
      evidence_ref: null,
      tags: ["general"],
      requirements: [],
      values: { steps: 20, derope: false },
    },
  ],
} satisfies StudioTemplateCatalog

describe("Studio sweep choices", () => {
  it("uses the Studio session options for node-owned controls", () => {
    const axes = sweepable(META, CATALOG, {
      sampler_name: ["euler", "res_multistep"],
      scheduler: ["simple", "beta"],
      aspect_ratio: ["16:9 (Landscape)", "4:5 (Portrait)", "1.91:1 (Landscape)"],
      interpolation: ["none", "film", "rife"],
      turbo_lora: ["four.safetensors", "eight.safetensors"],
      attn: ["off", "sol", "comfy_kitchen"],
    })
    const values = Object.fromEntries(axes.map((axis) => [axis.field, axis.values]))

    expect(values.sampler).toEqual(["euler", "res_multistep"])
    expect(values.scheduler).toEqual(["simple", "beta"])
    expect(values.aspect_ratio).toContain("4:5 (Portrait)")
    expect(values.aspect_ratio).toContain("1.91:1 (Landscape)")
    expect(values.interp).toEqual(["off", "film", "rife"])
    expect(values.turbo_lora).toEqual(["four.safetensors", "eight.safetensors"])
    expect(values.attn).toEqual(["off", "sol", "comfy_kitchen"])
  })

  it("offers cache as on or off without varying implementation families", () => {
    const axes = sweepable(META, CATALOG, {})
    expect(axes.find((axis) => axis.field === "cache_enabled")?.values).toEqual([true, false])
    expect(axes.some((axis) => axis.field === "cache")).toBe(false)
    expect(axes.some((axis) => axis.field === "sol_attn")).toBe(false)
  })

  it("offers every packaged template plus current settings", () => {
    const axes = sweepable(META, CATALOG, {}, TEMPLATES)

    expect(axes.find((axis) => axis.field === "template")?.values).toEqual([
      "__current__",
      "essentials/balanced",
    ])
  })

  it("does not offer Template without a supported catalog", () => {
    const axes = sweepable(META, CATALOG, {}, null)

    expect(axes.some((axis) => axis.field === "template")).toBe(false)
  })

  it("reads current template provenance without accepting malformed state", () => {
    expect(
      templateIdFromState('{"version":1,"template_id":"essentials/balanced"}')
    ).toBe("essentials/balanced")
    expect(templateIdFromState('{"version":2,"template_id":"old"}')).toBeNull()
    expect(templateIdFromState("{")).toBeNull()
  })

  it("marks managed and dependent fields as Template conflicts", () => {
    expect(TEMPLATE_CONFLICT_FIELDS).toBeInstanceOf(Set)
    for (const field of ["steps", "sampler", "turbo_lora", "cache_preset", "sol_preset", "sla"]) {
      expect(TEMPLATE_CONFLICT_FIELDS.has(field), field).toBe(true)
    }
    expect(TEMPLATE_CONFLICT_FIELDS.has("mp")).toBe(false)
  })

  it("offers duration_s and shift_video as sweepable axes", () => {
    const axes = sweepable(META, CATALOG, {})
    expect(axes.find((axis) => axis.field === "duration_s")?.values).toEqual([3, 5, 8, 10])
    expect(axes.find((axis) => axis.field === "shift_video")?.values).toEqual([3, 6, 9])
  })
})
