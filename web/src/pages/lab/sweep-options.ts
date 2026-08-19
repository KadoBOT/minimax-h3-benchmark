import type { Meta } from "@/api/schema"
import { loraStem, modelStem } from "@/lib/format"

export type Sweepable = {
  field: string
  values: (string | number | boolean)[]
  render?: (value: string | number | boolean) => string
}

export type SweepCatalog = {
  samplers: string[]
  schedulers: string[]
  aspect_ratios: string[]
  diffusion_models: string[]
  turbo_loras?: string[]
}

export function sweepable(
  meta: Meta | undefined,
  catalog: SweepCatalog,
  inputOptions: Record<string, unknown[]> = {}
): Sweepable[] {
  const axes: Sweepable[] = [
    { field: "cache_enabled", values: [true, false] },
    { field: "cache_preset", values: meta?.preset_levels ?? [] },
    { field: "sol_preset", values: meta?.preset_levels ?? [] },
    { field: "attn", values: choices(inputOptions, "attn", ["off", "sol"]) },
    { field: "turbo", values: [true, false] },
    {
      field: "turbo_lora",
      values: choices(inputOptions, "turbo_lora", catalog.turbo_loras ?? []),
      render: (value) => loraStem(String(value)),
    },
    { field: "turbo_lora_strength", values: [0.5, 0.75, 1, 1.25] },
    {
      field: "interp",
      values: choices(inputOptions, "interpolation", meta?.interpolations ?? []).map((value) =>
        value === "none" ? "off" : value
      ),
    },
    { field: "upscaler", values: [true, false] },
    { field: "clean_vram", values: [true, false] },
    { field: "sampler", values: choices(inputOptions, "sampler_name", catalog.samplers) },
    { field: "scheduler", values: choices(inputOptions, "scheduler", catalog.schedulers) },
    {
      field: "aspect_ratio",
      values: choices(inputOptions, "aspect_ratio", catalog.aspect_ratios),
    },
    {
      field: "diffusion_model",
      values: catalog.diffusion_models,
      render: (value) => modelStem(String(value)),
    },
    { field: "steps", values: [4, 8, 12, 16, 20, 28, 36] },
    { field: "mp", values: [0.25, 0.5, 0.75, 1, 1.5] },
  ]
  return axes.filter((axis) => axis.values.length > 1)
}

function choices(
  inputOptions: Record<string, unknown[]>,
  name: string,
  fallback: (string | number | boolean)[]
): (string | number | boolean)[] {
  const values = inputOptions[name]
  if (!Array.isArray(values) || values.length === 0) return fallback
  return values.filter(
    (value): value is string | number | boolean =>
      typeof value === "string" || typeof value === "number" || typeof value === "boolean"
  )
}
