import { describe, expect, it } from "vitest"

import { META } from "@/test/harness"
import { sweepable } from "./sweep-options"

const CATALOG = {
  samplers: ["legacy sampler"],
  schedulers: ["legacy scheduler"],
  aspect_ratios: ["16:9"],
  diffusion_models: ["model.safetensors"],
  turbo_loras: ["legacy-lora.safetensors"],
}

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
})
