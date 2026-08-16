import type {
  AssetComponent,
  GenerationDocument,
  NumberComponent,
  SeedComponent,
  SelectComponent,
  TextareaComponent,
  TextComponent,
} from "@/api/schema"

import { visible } from "./predicates"

type InputComponent = Exclude<
  GenerationDocument["components"][number],
  { kind: "section" }
>

export type ScalarValue = string | number | boolean | null
export type FormValue = ScalarValue | string[]
export type FormValues = Record<string, FormValue>
export type FormErrors = Record<string, string>

export type ValidationResult = {
  errors: FormErrors
  firstError: { binding: string; componentId: string } | null
}

export type MergeResult = {
  values: FormValues
  diagnostics: string[]
}

export function initialValues(document: GenerationDocument): FormValues {
  const values: FormValues = {}
  for (const component of inputs(document)) {
    values[component.binding] = defaultValue(component)
  }
  return values
}

export function submissionInput(
  document: GenerationDocument,
  values: Readonly<FormValues>
): Record<string, ScalarValue | string[]> {
  return Object.fromEntries(
    inputs(document).map((component) => {
      const value = values[component.binding] ?? defaultValue(component)
      return [component.binding, Array.isArray(value) ? [...value] : value]
    })
  )
}

export function validateValues(
  document: GenerationDocument,
  values: Readonly<FormValues>
): ValidationResult {
  const errors: FormErrors = {}
  let firstError: ValidationResult["firstError"] = null

  for (const component of inputs(document)) {
    if (!visible(component.visibleWhen, values)) continue
    const error = validateValue(component, values[component.binding])
    if (!error) continue
    errors[component.binding] = error
    firstError ??= { binding: component.binding, componentId: component.id }
  }
  return { errors, firstError }
}

export function mergeValues(
  previous: GenerationDocument,
  previousValues: Readonly<FormValues>,
  next: GenerationDocument
): MergeResult {
  const values = initialValues(next)
  const diagnostics: string[] = []
  const previousInputs = new Map(
    inputs(previous).map((component) => [component.binding, component])
  )
  const nextInputs = new Map(
    inputs(next).map((component) => [component.binding, component])
  )

  if (previous.schemaRevision !== next.schemaRevision) {
    diagnostics.push(
      `Merged document revision ${previous.schemaRevision} into ${next.schemaRevision}.`
    )
  }

  for (const [binding, component] of previousInputs) {
    const replacement = nextInputs.get(binding)
    if (!replacement) {
      diagnostics.push(`${binding} was removed by the new document.`)
      continue
    }
    const oldValue = previousValues[binding]
    if (
      !sameValueKind(component, replacement) ||
      !compatibleValue(replacement, oldValue)
    ) {
      diagnostics.push(
        `${binding} was reset because its type changed or became incompatible.`
      )
      continue
    }
    values[binding] = cloneValue(oldValue)
  }
  return { values, diagnostics }
}

export function isInputComponent(
  component: GenerationDocument["components"][number]
): component is InputComponent {
  return component.kind !== "section"
}

function inputs(document: GenerationDocument): InputComponent[] {
  return document.components.filter(isInputComponent)
}

function defaultValue(component: InputComponent): FormValue {
  switch (component.kind) {
    case "text":
    case "textarea":
      return component.defaultValue ?? ""
    case "number":
      return component.defaultValue ?? component.minimum ?? 0
    case "select":
      return (
        component.defaultValue ??
        component.options.find((option) => !option.disabled)?.value ??
        null
      )
    case "toggle":
      return component.defaultValue
    case "asset":
      return []
    case "seed":
      return component.defaultValue
  }
}

function validateValue(
  component: InputComponent,
  value: FormValue | undefined
): string | null {
  switch (component.kind) {
    case "text":
    case "textarea":
      return validateText(component, value)
    case "number":
      return validateNumber(component, value)
    case "select":
      return validateSelect(component, value)
    case "toggle":
      return typeof value === "boolean" ? null : "Must be a boolean."
    case "asset":
      return validateAsset(component, value)
    case "seed":
      return validateSeed(component, value)
  }
}

function validateText(
  component: TextComponent | TextareaComponent,
  value: FormValue | undefined
): string | null {
  if (typeof value !== "string") return "Must be text."
  if (component.required && value.length === 0) return "This field is required."
  if (
    component.minLength !== undefined &&
    component.minLength !== null &&
    value.length < component.minLength
  ) {
    return `Must contain at least ${component.minLength} characters.`
  }
  if (
    component.maxLength !== undefined &&
    component.maxLength !== null &&
    value.length > component.maxLength
  ) {
    return `Must contain at most ${component.maxLength} characters.`
  }
  return null
}

function validateNumber(
  component: NumberComponent,
  value: FormValue | undefined
): string | null {
  if (typeof value !== "number" || !Number.isFinite(value))
    return "Must be a finite number."
  if (component.integer && !Number.isInteger(value))
    return "Must be an integer."
  if (
    component.minimum !== undefined &&
    component.minimum !== null &&
    value < component.minimum
  ) {
    return `Must be at least ${component.minimum}.`
  }
  if (
    component.maximum !== undefined &&
    component.maximum !== null &&
    value > component.maximum
  ) {
    return `Must be at most ${component.maximum}.`
  }
  if (component.step !== undefined && component.step !== null) {
    const origin = component.minimum ?? 0
    const increments = (value - origin) / component.step
    if (Math.abs(increments - Math.round(increments)) > 1e-9) {
      return `Must use increments of ${component.step}.`
    }
  }
  return null
}

function validateSelect(
  component: SelectComponent,
  value: FormValue | undefined
): string | null {
  if (Array.isArray(value) || value === null || value === undefined) {
    return component.required ? "Select an option." : null
  }
  const option = component.options.find(
    (candidate) => candidate.value === value
  )
  if (!option) return "Select a listed option."
  if (option.disabled) return "That option is disabled."
  return null
}

function validateAsset(
  component: AssetComponent,
  value: FormValue | undefined
): string | null {
  if (
    !Array.isArray(value) ||
    value.some((id) => typeof id !== "string" || !OPAQUE_ID.test(id))
  ) {
    return "Assets must be opaque asset IDs."
  }
  const minimum = component.minimumItems ?? 0
  if (value.length < minimum)
    return `Choose at least ${minimum} asset${minimum === 1 ? "" : "s"}.`
  if (value.length > component.maximumItems) {
    return `Choose at most ${component.maximumItems} assets.`
  }
  return null
}

function validateSeed(
  component: SeedComponent,
  value: FormValue | undefined
): string | null {
  if (value === null)
    return component.allowRandom ? null : "Random seed mode is not available."
  if (typeof value !== "number" || !Number.isSafeInteger(value)) {
    return "Seed must be a safe integer."
  }
  if (value < component.minimum)
    return `Seed must be at least ${component.minimum}.`
  if (value > component.maximum)
    return `Seed must not exceed the maximum ${component.maximum}.`
  return null
}

function sameValueKind(
  previous: InputComponent,
  next: InputComponent
): boolean {
  return valueKind(previous) === valueKind(next)
}

function valueKind(component: InputComponent): string {
  if (component.kind === "text" || component.kind === "textarea")
    return "string"
  return component.kind
}

function compatibleValue(
  component: InputComponent,
  value: FormValue | undefined
): boolean {
  switch (component.kind) {
    case "text":
    case "textarea":
      return typeof value === "string"
    case "number":
      return typeof value === "number" && Number.isFinite(value)
    case "select":
      return (
        !Array.isArray(value) &&
        value !== null &&
        value !== undefined &&
        component.options.some(
          (option) => !option.disabled && option.value === value
        )
      )
    case "toggle":
      return typeof value === "boolean"
    case "asset":
      return (
        Array.isArray(value) && value.every((item) => typeof item === "string")
      )
    case "seed":
      return value === null ? component.allowRandom : typeof value === "number"
  }
}

function cloneValue(value: FormValue | undefined): FormValue {
  if (Array.isArray(value)) return [...value]
  return value ?? null
}

const OPAQUE_ID =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$/
