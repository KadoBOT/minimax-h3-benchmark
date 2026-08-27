import type { Draft } from "./config"

export type ApiWorkflowNode = {
  class_type: string
  inputs: Record<string, unknown>
  _meta?: { title?: string; [key: string]: unknown }
  [key: string]: unknown
}

export type ApiWorkflow = Record<string, ApiWorkflowNode>

export type StudioBinding = {
  key: string
  store: "config" | "widgets" | "references"
  values?: Record<string, unknown>
}

export type StudioUiControl = {
  key: string
  label: string
  kind: "boolean" | "combo" | "number"
  when?: string
  help?: string
  min?: number
  max?: number
  step?: number
}

export type StudioUiSection = {
  id: string
  title: string
  columns?: number
  controls: StudioUiControl[]
}

export type StudioUiSchema = {
  version: 1
  specialized: string[]
  internal: string[]
  sections: StudioUiSection[]
}

export type StudioTemplateRequirement = {
  kind: "input_not" | "capability"
  key: string
  value?: unknown
  message: string
}

export type StudioTemplate = {
  id: string
  category: string
  name: string
  description: string
  tradeoff: string
  evidence: "measured" | "curated" | "experimental"
  evidence_ref: string | null
  tags: string[]
  requirements: StudioTemplateRequirement[]
  values: Record<string, boolean | number | string>
}

export type StudioTemplateCatalog = {
  version: 1
  managed_keys: string[]
  selector: {
    label: string
    placeholder: string
  }
  categories: {
    id: string
    name: string
  }[]
  templates: StudioTemplate[]
}

export type StudioManifest = {
  contract_version: 1
  component_version: string
  node_class: "MiniMaxH3Studio"
  module_url: string
  prepare_url: string
  input_options?: Record<string, unknown[]>
  ui_schema: StudioUiSchema
  capabilities?: Record<string, unknown>
  template_catalog?: StudioTemplateCatalog | null
  template_catalog_error?: string | null
  [key: string]: unknown
}

export type StudioSession = StudioManifest & {
  workflow: ApiWorkflow
  bindings: Record<string, StudioBinding>
}

export type StudioPrepareResult = {
  contract_version: number
  component_version: string
  workflow: ApiWorkflow
  inputs: Record<string, unknown>
  capabilities: Record<string, unknown>
  warnings: unknown[]
  [key: string]: unknown
}

export type StudioController = {
  getInputs(): Record<string, unknown>
  setInputs(inputs: Record<string, unknown>, emit?: boolean): void
  setWorkflow(workflow: ApiWorkflow): Promise<void> | void
  setPreview(preview: unknown): void
  prepareWorkflow(): Promise<StudioPrepareResult>
  destroy(): void
}

export type StudioMountOptions = {
  manifest: StudioManifest
  workflow: ApiWorkflow
  inputs?: Record<string, unknown>
  onChange?: (inputs: Record<string, unknown>) => void
  onResize?: () => void
  uploadFile?: (file: File) => Promise<string>
  mediaUrl?: (filename: string, type?: string) => string
  fetch?: typeof globalThis.fetch
}

export type StudioRuntimeModule = {
  mountMiniMaxH3Studio(
    container: HTMLElement,
    options: StudioMountOptions
  ): Promise<StudioController>
}

export type StudioImporter = (url: string) => Promise<unknown>

const runtimeCache = new Map<string, Promise<StudioRuntimeModule>>()

const directConfigFields = new Set<keyof Draft>([
  "mode",
  "diffusion_model",
  "prompt",
  "first_frame",
  "last_frame",
  "ref_images",
  "ref_videos",
  "ref_video_audios",
  "ref_audios",
  "ref_image_size",
  "scheduler",
  "sampler",
  "aspect_ratio",
  "steps",
  "seed",
  "mp",
  "duration_s",
  "turbo",
  "turbo_lora",
  "turbo_lora_strength",
  "interp",
  "upscaler",
  "clean_vram",
  "cache_enabled",
  "cache",
  "cache_preset",
  "sol_attn",
  "sol_preset",
])

async function importStudioModule(url: string): Promise<unknown> {
  return import(/* @vite-ignore */ url)
}

export async function loadStudioRuntime(
  session: StudioSession,
  importer: StudioImporter = importStudioModule
): Promise<StudioRuntimeModule> {
  if (session.contract_version !== 1) {
    throw new Error(
      `Unsupported Studio contract version ${session.contract_version}; expected 1`
    )
  }
  if (!session.ui_schema || typeof session.ui_schema !== "object") {
    throw new Error("Studio session has no UI schema")
  }
  if (session.ui_schema.version !== 1) {
    throw new Error(
      `Unsupported Studio UI schema version ${String(session.ui_schema.version)}; expected 1`
    )
  }
  if (!session.module_url || !session.component_version) {
    throw new Error("Studio session has no component module or version")
  }

  const moduleUrl = versionedModuleUrl(session)
  const key = `${moduleUrl}\n${session.component_version}`
  let pending = runtimeCache.get(key)
  if (!pending) {
    pending = importer(moduleUrl).then((loaded) => {
      const module = loaded as Partial<StudioRuntimeModule>
      if (typeof module?.mountMiniMaxH3Studio !== "function") {
        throw new Error("Studio component does not export mountMiniMaxH3Studio")
      }
      return module as StudioRuntimeModule
    })
    runtimeCache.set(key, pending)
    pending.catch(() => runtimeCache.delete(key))
  }
  return pending
}

function versionedModuleUrl(session: StudioSession): string {
  const hashIndex = session.module_url.indexOf("#")
  const base =
    hashIndex === -1
      ? session.module_url
      : session.module_url.slice(0, hashIndex)
  const hash = hashIndex === -1 ? "" : session.module_url.slice(hashIndex)
  const separator = base.includes("?") ? "&" : "?"
  return `${base}${separator}h3s_component_version=${encodeURIComponent(session.component_version)}${hash}`
}

export function projectStudioInputs(
  inputs: Record<string, unknown>,
  bindings: Record<string, StudioBinding>,
  draft: Draft
): Partial<Draft> {
  const patch: Partial<Draft> = {}
  const widgets = { ...(draft.widgets ?? {}) }
  let widgetsChanged = false

  for (const [name, rawValue] of Object.entries(inputs)) {
    const binding = bindings[name]
    if (binding?.store === "references") {
      const references = parseReferences(rawValue)
      assignIfChanged(patch, draft, "ref_images", references.images)
      assignIfChanged(patch, draft, "ref_videos", references.videos)
      assignIfChanged(patch, draft, "ref_video_audios", references.video_audios)
      assignIfChanged(patch, draft, "ref_audios", references.audios)
      continue
    }

    const value = mappedValue(rawValue, binding?.values)
    if (binding?.store === "config") {
      assignIfChanged(patch, draft, binding.key as keyof Draft, value)
      continue
    }
    if (binding?.store === "widgets") {
      widgetsChanged =
        assignWidget(widgets, draft.widgets, binding.key, value) ||
        widgetsChanged
      continue
    }
    if (directConfigFields.has(name as keyof Draft)) {
      assignIfChanged(patch, draft, name as keyof Draft, value)
      continue
    }
    widgetsChanged =
      assignWidget(widgets, draft.widgets, name, value) || widgetsChanged
  }

  if (patch.cache_enabled === true && draft.cache === "none")
    patch.cache = "spectrum"
  if (widgetsChanged) patch.widgets = widgets
  return patch
}

export function studioInputsFromDraft(
  session: StudioSession,
  draft: Draft
): Record<string, unknown> {
  const studioNodes = Object.values(session.workflow).filter(
    (node) => node.class_type === session.node_class
  )
  if (studioNodes.length !== 1) {
    throw new Error(
      `Studio session must contain exactly one ${session.node_class} node`
    )
  }

  const userFacing = new Set([
    ...session.ui_schema.specialized,
    ...session.ui_schema.sections.flatMap((section) =>
      section.controls.map((control) => control.key)
    ),
    "h3s_ui",
  ])
  const sourceInputs = Object.fromEntries(
    Object.entries(studioNodes[0].inputs).filter(([name]) =>
      userFacing.has(name)
    )
  )
  const projected: Record<string, unknown> = {
    ...sourceInputs,
    ...(draft.widgets ?? {}),
  }
  for (const name of Object.keys(studioNodes[0].inputs)) {
    const binding = session.bindings[name]
    if (binding?.store === "references") {
      projected[name] = JSON.stringify({
        images: draft.ref_images ?? [],
        videos: draft.ref_videos ?? [],
        video_audios: draft.ref_video_audios ?? [],
        audios: draft.ref_audios ?? [],
      })
      continue
    }

    let value: unknown
    if (binding?.store === "config") {
      value = draft[binding.key as keyof Draft]
      if (binding.key === "cache_enabled" && value === undefined)
        value = draft.cache !== "none"
      value = reverseMappedValue(value, binding.values)
    } else if (binding?.store === "widgets") {
      value = draft.widgets?.[binding.key]
    } else if (directConfigFields.has(name as keyof Draft)) {
      value = draft[name as keyof Draft]
    }
    if (value !== undefined) projected[name] = value
  }
  return projected
}

function mappedValue(
  value: unknown,
  values: Record<string, unknown> | undefined
): unknown {
  if (!values) return value
  const key = String(value)
  return Object.prototype.hasOwnProperty.call(values, key) ? values[key] : value
}

function reverseMappedValue(
  value: unknown,
  values: Record<string, unknown> | undefined
): unknown {
  if (!values) return value
  const match = Object.entries(values).find(([, mapped]) =>
    sameValue(mapped, value)
  )
  return match?.[0] ?? value
}

function assignIfChanged<K extends keyof Draft>(
  patch: Partial<Draft>,
  draft: Draft,
  key: K,
  value: unknown
) {
  if (!sameValue(draft[key], value)) {
    ;(patch as Record<string, unknown>)[key] = value
  }
}

function assignWidget(
  next: Record<string, unknown>,
  current: Record<string, unknown> | undefined,
  key: string,
  value: unknown
): boolean {
  if (sameValue(current?.[key], value)) return false
  next[key] = value
  return true
}

function sameValue(left: unknown, right: unknown): boolean {
  return JSON.stringify(left ?? null) === JSON.stringify(right ?? null)
}

function parseReferences(value: unknown): {
  images: string[]
  videos: string[]
  video_audios: string[]
  audios: string[]
} {
  const parsed = typeof value === "string" ? JSON.parse(value) : value
  const references =
    parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {}
  return {
    images: stringList(references.images),
    videos: stringList(references.videos),
    video_audios: stringList(references.video_audios),
    audios: stringList(references.audios),
  }
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : []
}
