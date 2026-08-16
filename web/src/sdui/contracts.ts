import type {
  AssetComponent,
  CancelAction,
  Capabilities,
  DeleteAction,
  DownloadComponent,
  GenerationDocument,
  JobDocument,
  LogComponent,
  NumberComponent,
  Predicate,
  PreviewComponent,
  ProgressComponent,
  PublicMediaMetadata,
  RetryCollectionAction,
  SectionComponent,
  SeedComponent,
  SelectComponent,
  StatusComponent,
  SubmitAction,
  TextareaComponent,
  TextComponent,
  ToggleComponent,
  VideoComponent,
} from "@/api/schema"

import {
  capabilityFor,
  supportsCapability,
  type CapabilityScope,
} from "./capabilities"

type JsonObject = Record<string, unknown>
type GenerationComponent = GenerationDocument["components"][number]
type JobComponent = JobDocument["components"][number]
type JobAction = JobDocument["actions"][number]
type KnownItem = GenerationComponent | JobComponent | SubmitAction | JobAction

export type ValidatedDocument<T> = {
  document: T
  diagnostics: string[]
}

export class SduiContractError extends Error {
  readonly issues: readonly string[]

  constructor(issues: string | readonly string[]) {
    const list = typeof issues === "string" ? [issues] : [...issues]
    super(list.join("; "))
    this.name = "SduiContractError"
    this.issues = list
  }
}

export function parseGenerationDocument(
  value: unknown
): ValidatedDocument<GenerationDocument> {
  return parseDocument(value, "generation")
}

export function parseJobDocument(
  value: unknown
): ValidatedDocument<JobDocument> {
  return parseDocument(value, "job")
}

export function parsePublicMediaMetadata(value: unknown): PublicMediaMetadata {
  const raw = object(value, "media")
  string(raw.id, "media.id", 1, 128, OPAQUE_ID)
  const kind = string(raw.kind, "media.kind")
  if (kind !== "asset" && kind !== "artifact")
    fail("media.kind", "must be asset or artifact")
  const mediaKind = string(raw.mediaKind, "media.mediaKind")
  if (!["image", "video", "audio"].includes(mediaKind)) {
    fail("media.mediaKind", "must be image, video, or audio")
  }
  string(
    raw.mime,
    "media.mime",
    1,
    200,
    /^(image|video|audio)\/[A-Za-z0-9.+-]+$/
  )
  integer(raw.size, "media.size", 0)
  string(raw.digest, "media.digest", 71, 71, DIGEST)
  const filename = string(raw.filename, "media.filename", 1, 240)
  if (filename.includes("/") || filename.includes("\\")) {
    fail("media.filename", "must be a leaf filename")
  }
  apiPath(raw.contentUrl, "media.contentUrl")
  return raw as unknown as PublicMediaMetadata
}

export function isSafeApiPath(value: string): boolean {
  if (
    !value.startsWith("/api/") ||
    value.startsWith("//") ||
    value.includes("\\")
  )
    return false
  try {
    const rawSegments = decodeURIComponent(value).split(/[/?#]/)
    if (rawSegments.some((part) => part === ".." || part === ".")) return false
    const url = new URL(value, "http://sdui.invalid")
    if (
      url.origin !== "http://sdui.invalid" ||
      url.hash ||
      url.username ||
      url.password
    )
      return false
    return true
  } catch {
    return false
  }
}

function parseDocument(
  value: unknown,
  scope: "generation"
): ValidatedDocument<GenerationDocument>
function parseDocument(
  value: unknown,
  scope: "job"
): ValidatedDocument<JobDocument>
function parseDocument(
  value: unknown,
  scope: CapabilityScope
): ValidatedDocument<GenerationDocument> | ValidatedDocument<JobDocument> {
  const raw = object(value, scope)
  const diagnostics: string[] = []
  documentBase(raw, scope)
  const capabilities = parseCapabilities(
    raw.capabilities,
    `${scope}.capabilities`
  )
  validateSupportedCapabilities(capabilities, scope, diagnostics)

  const rawComponents = array(raw.components, `${scope}.components`)
  if (rawComponents.length === 0)
    fail(`${scope}.components`, "must not be empty")
  const rawActions = array(raw.actions, `${scope}.actions`)
  if (scope === "generation" && rawActions.length === 0) {
    fail("generation.actions", "must not be empty")
  }

  const allIds = [...rawComponents, ...rawActions].map((item, index) =>
    string(
      object(item, `${scope}.items[${index}]`).id,
      `${scope}.items[${index}].id`,
      1,
      128
    )
  )
  unique(allIds, `${scope}.items`, "component and action ids")

  const components: KnownItem[] = []
  for (const [index, item] of rawComponents.entries()) {
    const parsed = parseComponent(
      item,
      scope,
      `${scope}.components[${index}]`,
      diagnostics
    )
    if (parsed) components.push(parsed)
  }

  const actions: KnownItem[] = []
  for (const [index, item] of rawActions.entries()) {
    const parsed = parseAction(
      item,
      scope,
      `${scope}.actions[${index}]`,
      diagnostics
    )
    if (parsed) actions.push(parsed)
  }

  validateDocumentRelations(components, actions, capabilities, scope)

  if (scope === "generation") {
    return {
      document: {
        ...(raw as unknown as GenerationDocument),
        kind: "generation",
        components: components as GenerationComponent[],
        actions: actions as SubmitAction[],
      },
      diagnostics,
    }
  }

  string(raw.jobId, "job.jobId", 1, 128, IDENTIFIER)
  return {
    document: {
      ...(raw as unknown as JobDocument),
      components: components as JobComponent[],
      actions: actions as JobAction[],
    },
    diagnostics,
  }
}

function documentBase(raw: JsonObject, scope: CapabilityScope): void {
  literal(raw.protocolVersion, "1.0", `${scope}.protocolVersion`)
  string(raw.documentId, `${scope}.documentId`, 1, 128, IDENTIFIER)
  string(raw.schemaRevision, `${scope}.schemaRevision`, 1, 128, IDENTIFIER)
  string(raw.workflowId, `${scope}.workflowId`, 1, 128, IDENTIFIER)
  string(raw.workflowRevision, `${scope}.workflowRevision`, 71, 71, DIGEST)
  string(raw.title, `${scope}.title`, 1, 200)
  optionalString(raw.description, `${scope}.description`, 1, 2000)
  parseAvailability(raw.availability, `${scope}.availability`)
  if (scope === "generation") {
    if (raw.kind !== undefined)
      literal(raw.kind, "generation", "generation.kind")
  } else {
    literal(raw.kind, "job", "job.kind")
  }
}

function parseAvailability(value: unknown, path: string): void {
  const raw = object(value, path)
  const state = string(raw.state, `${path}.state`)
  date(raw.observedAt, `${path}.observedAt`)
  if (state === "available") return
  if (state !== "disabled" && state !== "incompatible") {
    fail(`${path}.state`, "must be available, disabled, or incompatible")
  }
  const reason = object(raw.reason, `${path}.reason`)
  string(reason.code, `${path}.reason.code`, 1, 128, CODE)
  string(reason.detail, `${path}.reason.detail`, 1, 2000)
  boolean(reason.retryable, `${path}.reason.retryable`)
}

function parseCapabilities(value: unknown, path: string): Capabilities {
  const raw = object(value, path)
  const required = stringArray(raw.required, `${path}.required`, CAPABILITY)
  const optional = stringArray(raw.optional, `${path}.optional`, CAPABILITY)
  unique(required, `${path}.required`, "capabilities")
  unique(optional, `${path}.optional`, "capabilities")
  const overlap = required.find((capability) => optional.includes(capability))
  if (overlap) fail(path, `${overlap} cannot be both required and optional`)
  return { required, optional }
}

function validateSupportedCapabilities(
  capabilities: Capabilities,
  scope: CapabilityScope,
  diagnostics: string[]
): void {
  const unsupportedRequired = capabilities.required.filter(
    (capability) => !supportsCapability(scope, capability)
  )
  if (unsupportedRequired.length) {
    fail(
      `${scope}.capabilities.required`,
      `unsupported: ${unsupportedRequired.join(", ")}`
    )
  }
  for (const capability of capabilities.optional) {
    if (!supportsCapability(scope, capability)) {
      diagnostics.push(`Ignored unsupported optional capability ${capability}`)
    }
  }
}

function parseComponent(
  value: unknown,
  scope: CapabilityScope,
  path: string,
  diagnostics: string[]
): GenerationComponent | JobComponent | null {
  const raw = object(value, path)
  const kind = string(raw.kind, `${path}.kind`)
  const optional = optionalBoolean(raw.optional, `${path}.optional`) ?? false
  const allowed =
    scope === "generation"
      ? GENERATION_COMPONENT_KINDS.has(kind)
      : JOB_COMPONENT_KINDS.has(kind)
  if (!allowed) {
    if (!optional)
      fail(`${path}.kind`, `unsupported required component ${kind}`)
    diagnostics.push(`Ignored unsupported optional component ${kind}`)
    return null
  }

  componentBase(raw, path)
  if (kind === "section") return parseSection(raw, path)
  if (scope === "generation") {
    inputBase(raw, path)
    switch (kind) {
      case "text":
        return parseText(raw, path, false)
      case "textarea":
        return parseText(raw, path, true)
      case "number":
        return parseNumber(raw, path)
      case "select":
        return parseSelect(raw, path)
      case "toggle":
        boolean(raw.defaultValue, `${path}.defaultValue`)
        return raw as unknown as ToggleComponent
      case "asset":
        return parseAsset(raw, path)
      case "seed":
        return parseSeed(raw, path)
    }
  }

  switch (kind) {
    case "status":
      return parseStatus(raw, path)
    case "progress":
      return parseProgress(raw, path)
    case "log":
      return parseLog(raw, path)
    case "preview":
      return parsePreview(raw, path)
    case "video":
      return parseVideo(raw, path)
    case "download":
      return parseDownload(raw, path)
  }
  fail(`${path}.kind`, `unsupported component ${kind}`)
}

function componentBase(raw: JsonObject, path: string): void {
  string(raw.id, `${path}.id`, 1, 128, COMPONENT_ID)
  optionalBoolean(raw.optional, `${path}.optional`)
}

function inputBase(raw: JsonObject, path: string): void {
  string(raw.binding, `${path}.binding`, 1, 128, BINDING)
  string(raw.label, `${path}.label`, 1, 200)
  optionalString(raw.description, `${path}.description`, 1, 2000)
  boolean(raw.required, `${path}.required`)
  if (raw.visibleWhen !== undefined && raw.visibleWhen !== null) {
    const predicates = array(raw.visibleWhen, `${path}.visibleWhen`)
    if (predicates.length === 0)
      fail(`${path}.visibleWhen`, "must not be empty")
    predicates.forEach((predicate, index) =>
      parsePredicate(predicate, `${path}.visibleWhen[${index}]`)
    )
  }
}

function parsePredicate(value: unknown, path: string): Predicate {
  const raw = object(value, path)
  string(raw.field, `${path}.field`, 1, 128, BINDING)
  const operator = string(raw.operator, `${path}.operator`)
  if (!["equals", "not_equals", "in"].includes(operator)) {
    fail(`${path}.operator`, "must be equals, not_equals, or in")
  }
  if (operator === "in") {
    const values = array(raw.value, `${path}.value`)
    if (values.length === 0) fail(`${path}.value`, "must not be empty")
    values.forEach((item, index) => primitive(item, `${path}.value[${index}]`))
  } else {
    if (Array.isArray(raw.value)) fail(`${path}.value`, "must be a scalar")
    primitive(raw.value, `${path}.value`)
  }
  return raw as unknown as Predicate
}

function parseSection(raw: JsonObject, path: string): SectionComponent {
  string(raw.title, `${path}.title`, 1, 200)
  optionalString(raw.description, `${path}.description`, 1, 2000)
  return raw as unknown as SectionComponent
}

function parseText(
  raw: JsonObject,
  path: string,
  textarea: false
): TextComponent
function parseText(
  raw: JsonObject,
  path: string,
  textarea: true
): TextareaComponent
function parseText(
  raw: JsonObject,
  path: string,
  textarea: boolean
): TextComponent | TextareaComponent {
  optionalString(raw.defaultValue, `${path}.defaultValue`, 0, undefined)
  optionalString(raw.placeholder, `${path}.placeholder`, 0, 500)
  const minimum = optionalInteger(raw.minLength, `${path}.minLength`, 0)
  const maximum = optionalInteger(raw.maxLength, `${path}.maxLength`, 1)
  if (minimum !== undefined && maximum !== undefined && minimum > maximum) {
    fail(path, "minimum text length cannot exceed maximum")
  }
  if (
    typeof raw.defaultValue === "string" &&
    ((minimum !== undefined && raw.defaultValue.length < minimum) ||
      (maximum !== undefined && raw.defaultValue.length > maximum))
  ) {
    fail(`${path}.defaultValue`, "does not satisfy text length constraints")
  }
  if (textarea) optionalInteger(raw.rows, `${path}.rows`, 2, 40)
  return raw as unknown as TextComponent | TextareaComponent
}

function parseNumber(raw: JsonObject, path: string): NumberComponent {
  const minimum = optionalNumber(raw.minimum, `${path}.minimum`)
  const maximum = optionalNumber(raw.maximum, `${path}.maximum`)
  const step = optionalNumber(raw.step, `${path}.step`)
  if (step !== undefined && step <= 0) fail(`${path}.step`, "must be positive")
  const integer = optionalBoolean(raw.integer, `${path}.integer`) ?? false
  const defaultValue = optionalNumber(raw.defaultValue, `${path}.defaultValue`)
  optionalString(raw.unit, `${path}.unit`, 1, 40)
  bounds(minimum, maximum, defaultValue, path)
  if (
    integer &&
    defaultValue !== undefined &&
    !Number.isInteger(defaultValue)
  ) {
    fail(`${path}.defaultValue`, "must be an integer")
  }
  return raw as unknown as NumberComponent
}

function parseSelect(raw: JsonObject, path: string): SelectComponent {
  const options = array(raw.options, `${path}.options`)
  if (options.length === 0) fail(`${path}.options`, "must not be empty")
  const optionKeys: string[] = []
  for (const [index, option] of options.entries()) {
    const item = object(option, `${path}.options[${index}]`)
    const value = optionPrimitive(item.value, `${path}.options[${index}].value`)
    optionKeys.push(primitiveKey(value))
    string(item.label, `${path}.options[${index}].label`, 1, 200)
    optionalString(
      item.description,
      `${path}.options[${index}].description`,
      1,
      2000
    )
    optionalBoolean(item.disabled, `${path}.options[${index}].disabled`)
  }
  unique(optionKeys, `${path}.options`, "option values")
  if (raw.defaultValue !== undefined && raw.defaultValue !== null) {
    const value = optionPrimitive(raw.defaultValue, `${path}.defaultValue`)
    if (!optionKeys.includes(primitiveKey(value))) {
      fail(`${path}.defaultValue`, "must match an option")
    }
  }
  return raw as unknown as SelectComponent
}

function parseAsset(raw: JsonObject, path: string): AssetComponent {
  const accepted = stringArray(raw.accept, `${path}.accept`)
  if (accepted.length === 0) fail(`${path}.accept`, "must not be empty")
  accepted.forEach((kind) => {
    if (!["image", "video", "audio"].includes(kind)) {
      fail(`${path}.accept`, `${kind} is not a supported media family`)
    }
  })
  unique(accepted, `${path}.accept`, "asset kinds")
  const minimum =
    optionalInteger(raw.minimumItems, `${path}.minimumItems`, 0) ?? 0
  const maximum = integer(raw.maximumItems, `${path}.maximumItems`, 1, 32)
  if (minimum > maximum) fail(path, "minimum items cannot exceed maximum items")
  if (raw.required === true && minimum === 0) {
    fail(path, "a required asset must require at least one item")
  }
  return raw as unknown as AssetComponent
}

function parseSeed(raw: JsonObject, path: string): SeedComponent {
  const allowRandom = boolean(raw.allowRandom, `${path}.allowRandom`)
  const minimum = integer(
    raw.minimum,
    `${path}.minimum`,
    0,
    Number.MAX_SAFE_INTEGER
  )
  const maximum = integer(
    raw.maximum,
    `${path}.maximum`,
    0,
    Number.MAX_SAFE_INTEGER
  )
  let defaultValue: number | undefined
  if (raw.defaultValue !== null) {
    defaultValue = integer(
      raw.defaultValue,
      `${path}.defaultValue`,
      0,
      Number.MAX_SAFE_INTEGER
    )
  } else if (!allowRandom) {
    fail(`${path}.defaultValue`, "a null seed requires random support")
  }
  bounds(minimum, maximum, defaultValue, path)
  return raw as unknown as SeedComponent
}

function parseStatus(raw: JsonObject, path: string): StatusComponent {
  const state = string(raw.state, `${path}.state`)
  if (!JOB_STATES.has(state))
    fail(`${path}.state`, `unsupported job state ${state}`)
  string(raw.label, `${path}.label`, 1, 200)
  optionalString(raw.detail, `${path}.detail`, 1, 2000)
  return raw as unknown as StatusComponent
}

function parseProgress(raw: JsonObject, path: string): ProgressComponent {
  const value = number(raw.value, `${path}.value`)
  if (value < 0 || value > 1)
    fail(`${path}.value`, "must be between zero and one")
  optionalString(raw.label, `${path}.label`, 1, 200)
  const current = optionalInteger(raw.current, `${path}.current`, 0)
  const total = optionalInteger(raw.total, `${path}.total`, 1)
  if (current !== undefined && total !== undefined && current > total) {
    fail(path, "current progress cannot exceed total")
  }
  return raw as unknown as ProgressComponent
}

function parseLog(raw: JsonObject, path: string): LogComponent {
  const entries = array(raw.entries, `${path}.entries`)
  if (entries.length > 1000)
    fail(`${path}.entries`, "must contain at most 1000 entries")
  let lastSequence = -1
  for (const [index, entry] of entries.entries()) {
    const item = object(entry, `${path}.entries[${index}]`)
    const sequence = integer(
      item.sequence,
      `${path}.entries[${index}].sequence`,
      0
    )
    if (sequence <= lastSequence)
      fail(`${path}.entries`, "must be ordered by unique sequence")
    lastSequence = sequence
    date(item.at, `${path}.entries[${index}].at`)
    const level = string(item.level, `${path}.entries[${index}].level`)
    if (!["debug", "info", "warning", "error"].includes(level)) {
      fail(`${path}.entries[${index}].level`, "is unsupported")
    }
    string(item.message, `${path}.entries[${index}].message`, 1, 8000)
  }
  return raw as unknown as LogComponent
}

function parsePreview(raw: JsonObject, path: string): PreviewComponent {
  apiPath(raw.src, `${path}.src`)
  string(raw.mime, `${path}.mime`, 1, 200, /^(image|video)\/[a-z0-9.+-]+$/)
  integer(raw.sequence, `${path}.sequence`, 0)
  return raw as unknown as PreviewComponent
}

function parseVideo(raw: JsonObject, path: string): VideoComponent {
  apiPath(raw.src, `${path}.src`)
  string(raw.mime, `${path}.mime`, 1, 200, /^video\/[a-z0-9.+-]+$/)
  if (raw.poster !== undefined && raw.poster !== null)
    apiPath(raw.poster, `${path}.poster`)
  return raw as unknown as VideoComponent
}

function parseDownload(raw: JsonObject, path: string): DownloadComponent {
  apiPath(raw.href, `${path}.href`)
  const filename = string(raw.filename, `${path}.filename`, 1, 240)
  if (filename.includes("/") || filename.includes("\\")) {
    fail(`${path}.filename`, "must be a leaf filename")
  }
  string(raw.label, `${path}.label`, 1, 200)
  return raw as unknown as DownloadComponent
}

function parseAction(
  value: unknown,
  scope: CapabilityScope,
  path: string,
  diagnostics: string[]
): SubmitAction | JobAction | null {
  const raw = object(value, path)
  const kind = string(raw.kind, `${path}.kind`)
  const optional = optionalBoolean(raw.optional, `${path}.optional`) ?? false
  const allowed =
    scope === "generation" ? kind === "submit" : JOB_ACTION_KINDS.has(kind)
  if (!allowed) {
    if (!optional) fail(`${path}.kind`, `unsupported required action ${kind}`)
    diagnostics.push(`Ignored unsupported optional action ${kind}`)
    return null
  }
  string(raw.id, `${path}.id`, 1, 128, COMPONENT_ID)
  string(raw.label, `${path}.label`, 1, 200)
  apiPath(raw.endpoint, `${path}.endpoint`)
  if (kind === "delete") literal(raw.method, "DELETE", `${path}.method`)
  else literal(raw.method, "POST", `${path}.method`)
  return raw as unknown as
    SubmitAction | CancelAction | DeleteAction | RetryCollectionAction
}

function validateDocumentRelations(
  components: KnownItem[],
  actions: KnownItem[],
  capabilities: Capabilities,
  scope: CapabilityScope
): void {
  const inputComponents = components.filter(
    (component): component is GenerationComponent & { binding: string } =>
      "binding" in component
  )
  const bindings = inputComponents.map((component) => component.binding)
  unique(bindings, `${scope}.components`, "input bindings")
  const knownBindings = new Set(bindings)
  for (const component of inputComponents) {
    const predicates = "visibleWhen" in component ? component.visibleWhen : []
    for (const predicate of predicates ?? []) {
      if (!knownBindings.has(predicate.field)) {
        fail(
          `${scope}.components.${component.id}.visibleWhen`,
          `references unknown binding ${predicate.field}`
        )
      }
    }
  }

  const required = new Set(capabilities.required)
  const optional = new Set(capabilities.optional)
  for (const [item, action] of [
    ...components.map((component) => [component, false] as const),
    ...actions.map((current) => [current, true] as const),
  ]) {
    if (item.kind === "section") continue
    const capability = capabilityFor(item.kind, action)
    const expected = item.optional ? optional : required
    if (!expected.has(capability)) {
      fail(`${scope}.capabilities`, `missing declared capability ${capability}`)
    }
  }
}

function object(value: unknown, path: string): JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    fail(path, "must be an object")
  }
  return value as JsonObject
}

function array(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) fail(path, "must be an array")
  return value
}

function string(
  value: unknown,
  path: string,
  minimum = 0,
  maximum?: number,
  pattern?: RegExp
): string {
  if (typeof value !== "string") fail(path, "must be a string")
  if (value.length < minimum)
    fail(path, `must have at least ${minimum} characters`)
  if (maximum !== undefined && value.length > maximum) {
    fail(path, `must have at most ${maximum} characters`)
  }
  if (pattern && !pattern.test(value)) fail(path, "has an invalid format")
  return value
}

function optionalString(
  value: unknown,
  path: string,
  minimum = 0,
  maximum?: number
): string | undefined {
  if (value === undefined || value === null) return undefined
  return string(value, path, minimum, maximum)
}

function stringArray(value: unknown, path: string, pattern?: RegExp): string[] {
  return array(value, path).map((item, index) =>
    string(item, `${path}[${index}]`, 1, 128, pattern)
  )
}

function number(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value))
    fail(path, "must be a finite number")
  return value
}

function optionalNumber(value: unknown, path: string): number | undefined {
  if (value === undefined || value === null) return undefined
  return number(value, path)
}

function integer(
  value: unknown,
  path: string,
  minimum?: number,
  maximum?: number
): number {
  const parsed = number(value, path)
  if (!Number.isSafeInteger(parsed)) fail(path, "must be a safe integer")
  if (minimum !== undefined && parsed < minimum)
    fail(path, `must be at least ${minimum}`)
  if (maximum !== undefined && parsed > maximum)
    fail(path, `must be at most ${maximum}`)
  return parsed
}

function optionalInteger(
  value: unknown,
  path: string,
  minimum?: number,
  maximum?: number
): number | undefined {
  if (value === undefined || value === null) return undefined
  return integer(value, path, minimum, maximum)
}

function boolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") fail(path, "must be a boolean")
  return value
}

function optionalBoolean(value: unknown, path: string): boolean | undefined {
  if (value === undefined) return undefined
  return boolean(value, path)
}

function primitive(value: unknown, path: string): void {
  if (
    value !== null &&
    typeof value !== "string" &&
    typeof value !== "number" &&
    typeof value !== "boolean"
  ) {
    fail(path, "must be a primitive value")
  }
  if (typeof value === "number" && !Number.isFinite(value))
    fail(path, "must be finite")
}

function optionPrimitive(
  value: unknown,
  path: string
): string | number | boolean {
  primitive(value, path)
  if (value === null) fail(path, "must not be null")
  return value as string | number | boolean
}

function primitiveKey(value: string | number | boolean): string {
  return `${typeof value}:${String(value)}`
}

function literal(value: unknown, expected: string, path: string): void {
  if (value !== expected) fail(path, `must be ${expected}`)
}

function date(value: unknown, path: string): void {
  const parsed = string(value, path, 1, 100)
  if (Number.isNaN(Date.parse(parsed))) fail(path, "must be an ISO timestamp")
}

function apiPath(value: unknown, path: string): string {
  const parsed = string(value, path, 1, 2000)
  if (!isSafeApiPath(parsed)) fail(path, "must be a safe same-origin /api path")
  return parsed
}

function bounds(
  minimum: number | undefined,
  maximum: number | undefined,
  value: number | undefined,
  path: string
): void {
  if (minimum !== undefined && maximum !== undefined && minimum > maximum) {
    fail(path, "minimum cannot exceed maximum")
  }
  if (value !== undefined && minimum !== undefined && value < minimum) {
    fail(`${path}.defaultValue`, "is below the minimum")
  }
  if (value !== undefined && maximum !== undefined && value > maximum) {
    fail(`${path}.defaultValue`, "is above the maximum")
  }
}

function unique(values: readonly string[], path: string, label: string): void {
  if (new Set(values).size !== values.length)
    fail(path, `${label} must be unique`)
}

function fail(path: string, message: string): never {
  throw new SduiContractError(`${path}: ${message}`)
}

const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/
const COMPONENT_ID = /^[a-z][a-z0-9._-]{0,127}$/
const BINDING = /^[A-Za-z][A-Za-z0-9._-]{0,127}$/
const CAPABILITY = /^[a-z][a-z0-9._-]{0,127}$/
const CODE = /^[a-z][a-z0-9_]*$/
const DIGEST = /^sha256:[a-f0-9]{64}$/
const OPAQUE_ID =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$/

const GENERATION_COMPONENT_KINDS = new Set([
  "section",
  "text",
  "textarea",
  "number",
  "select",
  "toggle",
  "asset",
  "seed",
])
const JOB_COMPONENT_KINDS = new Set([
  "section",
  "status",
  "progress",
  "log",
  "preview",
  "video",
  "download",
])
const JOB_ACTION_KINDS = new Set(["cancel", "delete", "retry_collection"])
const JOB_STATES = new Set([
  "accepted",
  "queued",
  "running",
  "cancelling",
  "collecting",
  "succeeded",
  "failed",
  "cancelled",
  "interrupted",
  "collection_failed",
])
