/**
 * Working with a draft config in the browser.
 *
 * The API is the authority: it validates, coerces, and hashes. These helpers only keep the
 * form honest before submitting — which fields a mode needs, which controls a toggle makes
 * irrelevant, and what changed against a baseline.
 */

import type { Catalog, GenerationConfig, Meta, ModeNeeds } from "@/api/schema"

export type Draft = GenerationConfig

/** Fields that stop mattering once something else is set, so the form can grey them out. */
export function inertFields(config: Draft): Set<string> {
  const inert = new Set<string>()
  if (config.turbo) inert.add("steps") // the LoRA's own schedule replaces the step count
  if (config.cache === "none" || config.cache_enabled === false) inert.add("cache_preset")
  if (!config.sol_attn) inert.add("sol_preset")
  return inert
}

/** The LoRA a turbo run will load: the one it names, or the machine's default. */
export function turboLora(config: Draft, catalog: Catalog | undefined): string {
  return config.turbo_lora || catalog?.default_turbo_lora || ""
}

/**
 * The schedule a turbo run samples at.
 *
 * A distilled LoRA is trained for a fixed step count and says so in its filename, so picking
 * a different one silently changes the sampling. The count is read on the server and shipped
 * in the catalog rather than parsed again here, so the form and the run cannot disagree.
 */
export function turboSteps(config: Draft, catalog: Catalog | undefined): number | undefined {
  if (!config.turbo) return undefined
  return catalog?.turbo_lora_steps?.[turboLora(config, catalog)]
}

export function needsOf(meta: Meta | undefined, mode: string | undefined): ModeNeeds | undefined {
  return meta?.modes.find((needs) => needs.mode === mode)
}

/** What is still missing before this config could be queued. */
export function missingInputs(config: Draft, meta: Meta | undefined): string[] {
  const needs = needsOf(meta, config.mode)
  if (!needs) return []
  const missing: string[] = []

  for (const field of needs.requires_all ?? []) {
    if (isEmpty(config[field as keyof Draft])) missing.push(label(meta, field))
  }
  const anyOf = needs.requires_any ?? []
  if (anyOf.length > 0 && anyOf.every((field) => isEmpty(config[field as keyof Draft]))) {
    missing.push(anyOf.map((field) => label(meta, field)).join(" or "))
  }
  return missing
}

/** Fields this mode reads. Everything else is hidden rather than shown as inert noise. */
export function acceptedFields(meta: Meta | undefined, mode: string | undefined): Set<string> {
  const needs = needsOf(meta, mode)
  return new Set([...(needs?.accepts ?? []), ...(needs?.requires_all ?? [])])
}

export function label(meta: Meta | undefined, field: string): string {
  return meta?.field_labels[field] ?? field.replace(/_/g, " ")
}

/**
 * Media to pre-fill when a mode starts needing input it does not have.
 *
 * Only ever fills a gap. Switching to a reference mode should not leave the form asking for
 * files with no hint of which ones, but switching back and forth must never quietly replace
 * something already chosen — the config is the experiment, and an unrequested change to it
 * makes two runs incomparable for a reason nobody can see.
 */
export function mediaDefaults(
  draft: Draft,
  meta: Meta | undefined,
  catalog: Catalog | undefined
): Partial<Draft> {
  const needs = needsOf(meta, draft.mode)
  if (!needs || !catalog) return {}
  const patch: Partial<Draft> = {}

  if (
    (needs.requires_all ?? []).includes("first_frame") &&
    isEmpty(draft.first_frame) &&
    catalog.default_first_frame
  ) {
    patch.first_frame = catalog.default_first_frame
  }

  // A reference mode is satisfied by any one of its lists, so only an entirely empty set is
  // a gap worth filling — and images are the only kind there is a default for.
  const anyOf = needs.requires_any ?? []
  if (
    anyOf.includes("ref_images") &&
    anyOf.every((field) => isEmpty(draft[field as keyof Draft])) &&
    catalog.default_ref_images?.length
  ) {
    patch.ref_images = catalog.default_ref_images
  }
  return patch
}

function isEmpty(value: unknown): boolean {
  if (value == null) return true
  if (typeof value === "string") return value.trim() === ""
  if (Array.isArray(value)) return value.length === 0
  return false
}

/** Only the fields that differ from `base`, for showing what a preset actually changes. */
export function changedFields(draft: Draft, base: Draft): string[] {
  const fields = new Set([...Object.keys(draft), ...Object.keys(base)])
  const changed: string[] = []
  for (const field of fields) {
    const mine = draft[field as keyof Draft]
    const theirs = base[field as keyof Draft]
    if (JSON.stringify(mine ?? null) !== JSON.stringify(theirs ?? null)) changed.push(field)
  }
  return changed.sort()
}

export function randomSeed(): number {
  // Seeds are compared and re-entered by hand, so keep them short enough to read aloud.
  return Math.floor(Math.random() * 1_000_000)
}

/** A field's value rendered the way the API renders it in diffs and labels. */
export function display(value: unknown): string {
  if (value == null || value === "") return "—"
  if (typeof value === "boolean") return value ? "on" : "off"
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—"
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
    return entries.length ? entries.map(([key, item]) => `${key}=${item}`).join(", ") : "—"
  }
  return String(value)
}
