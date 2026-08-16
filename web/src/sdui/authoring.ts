import type { GenerationDocument } from "@/api/schema"

import { parseGenerationDocument } from "./contracts"
import {
  initialValues,
  isInputComponent,
  mergeValues,
  type FormValue,
  type FormValues,
  type MergeResult,
} from "./form-state"
import { visible } from "./predicates"

type SweepComponent = Extract<
  GenerationDocument["components"][number],
  { kind: "number" | "select" | "toggle" }
>

export type SduiPreset = {
  id: string
  name: string
  document: GenerationDocument
  values: FormValues
  savedAt: string
}

type StoredDraft = {
  document: GenerationDocument
  values: FormValues
  savedAt: string
}

const DRAFT_PREFIX = "h3lab.sdui.draft."
const PRESET_KEY = "h3lab.sdui.presets"

export function saveDraft(
  document: GenerationDocument,
  values: FormValues,
  storage: Storage = localStorage
): void {
  const draft: StoredDraft = {
    document,
    values: cloneValues(values),
    savedAt: new Date().toISOString(),
  }
  storage.setItem(draftKey(document), JSON.stringify(draft))
}

export function loadDraft(
  document: GenerationDocument,
  storage: Storage = localStorage
): MergeResult {
  const fallback = { values: initialValues(document), diagnostics: [] }
  const exact = readDraft(storage.getItem(draftKey(document)))
  if (exact) return mergeValues(exact.document, exact.values, document)

  const prefix = `${DRAFT_PREFIX}${document.workflowId}.`
  const candidates: StoredDraft[] = []
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index)
    if (!key?.startsWith(prefix)) continue
    const draft = readDraft(storage.getItem(key))
    if (draft) candidates.push(draft)
  }
  const latest = candidates.sort((a, b) =>
    b.savedAt.localeCompare(a.savedAt)
  )[0]
  return latest
    ? mergeValues(latest.document, latest.values, document)
    : fallback
}

export function listPresets(storage: Storage = localStorage): SduiPreset[] {
  try {
    const value: unknown = JSON.parse(storage.getItem(PRESET_KEY) ?? "[]")
    if (!Array.isArray(value)) return []
    return value.flatMap((item) => {
      const preset = readPreset(item)
      return preset ? [preset] : []
    })
  } catch {
    return []
  }
}

export function savePreset(
  name: string,
  document: GenerationDocument,
  values: FormValues,
  storage: Storage = localStorage
): SduiPreset {
  const cleanName = name.trim()
  if (!cleanName || cleanName.length > 120)
    throw new Error("Preset name must be 1-120 characters.")
  const preset: SduiPreset = {
    id: requestId(),
    name: cleanName,
    document,
    values: cloneValues(values),
    savedAt: new Date().toISOString(),
  }
  storage.setItem(PRESET_KEY, JSON.stringify([...listPresets(storage), preset]))
  return preset
}

export function deletePreset(
  id: string,
  storage: Storage = localStorage
): void {
  storage.setItem(
    PRESET_KEY,
    JSON.stringify(listPresets(storage).filter((preset) => preset.id !== id))
  )
}

export function applyPreset(
  preset: SduiPreset,
  document: GenerationDocument
): MergeResult {
  return mergeValues(preset.document, preset.values, document)
}

export function sweepComponents(
  document: GenerationDocument,
  values: Readonly<FormValues>
): SweepComponent[] {
  return document.components.filter(
    (component): component is SweepComponent =>
      isInputComponent(component) &&
      (component.kind === "number" ||
        component.kind === "select" ||
        component.kind === "toggle") &&
      visible(component.visibleWhen, values)
  )
}

function draftKey(document: GenerationDocument): string {
  return `${DRAFT_PREFIX}${document.workflowId}.${document.schemaRevision}`
}

function readDraft(raw: string | null): StoredDraft | null {
  if (!raw) return null
  try {
    const value: unknown = JSON.parse(raw)
    const object = record(value)
    if (!object || typeof object.savedAt !== "string") return null
    const parsed = parseGenerationDocument(object.document).document
    const values = readValues(object.values)
    return values ? { document: parsed, values, savedAt: object.savedAt } : null
  } catch {
    return null
  }
}

function readPreset(value: unknown): SduiPreset | null {
  try {
    const object = record(value)
    if (
      !object ||
      typeof object.id !== "string" ||
      typeof object.name !== "string" ||
      typeof object.savedAt !== "string"
    ) {
      return null
    }
    const document = parseGenerationDocument(object.document).document
    const values = readValues(object.values)
    return values
      ? {
          id: object.id,
          name: object.name,
          savedAt: object.savedAt,
          document,
          values,
        }
      : null
  } catch {
    return null
  }
}

function readValues(value: unknown): FormValues | null {
  const object = record(value)
  if (!object) return null
  const values: FormValues = {}
  for (const [binding, item] of Object.entries(object)) {
    if (
      item === null ||
      typeof item === "string" ||
      typeof item === "boolean" ||
      (typeof item === "number" && Number.isFinite(item))
    ) {
      values[binding] = item
    } else if (
      Array.isArray(item) &&
      item.every((entry) => typeof entry === "string")
    ) {
      values[binding] = [...item]
    } else {
      return null
    }
  }
  return values
}

function cloneValues(values: Readonly<FormValues>): FormValues {
  return Object.fromEntries(
    Object.entries(values).map(([binding, value]) => [
      binding,
      cloneValue(value),
    ])
  )
}

function cloneValue(value: FormValue): FormValue {
  return Array.isArray(value) ? [...value] : value
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function requestId(): string {
  return (
    globalThis.crypto?.randomUUID?.() ?? `preset-${Date.now()}-${Math.random()}`
  )
}
