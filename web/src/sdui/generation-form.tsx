import { useMemo, useState } from "react"

import type {
  AssetComponent,
  GenerationDocument,
  JobSubmission,
  NumberComponent,
  SeedComponent,
  SelectComponent,
  SubmitAction,
  TextareaComponent,
  TextComponent,
  ToggleComponent,
} from "@/api/schema"
import { routes } from "@/api/routes"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

import {
  isInputComponent,
  submissionInput,
  validateValues,
  type FormValue,
  type FormValues,
} from "./form-state"
import { visible } from "./predicates"

type InputComponent = Exclude<
  GenerationDocument["components"][number],
  { kind: "section" }
>

type AssetRenderer = (
  component: AssetComponent,
  ids: string[],
  onChange: (ids: string[]) => void
) => React.ReactNode

export function SduiGenerationForm({
  document,
  values,
  onChange,
  onSubmit,
  uploading = false,
  diagnostics = [],
  externalErrors = {},
  renderAsset,
}: {
  document: GenerationDocument
  values: FormValues
  onChange: (values: FormValues) => void
  onSubmit: (
    submission: JobSubmission,
    action: SubmitAction
  ) => void | Promise<void>
  uploading?: boolean
  diagnostics?: readonly string[]
  externalErrors?: Readonly<Record<string, string>>
  renderAsset?: AssetRenderer
}) {
  const [attempted, setAttempted] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const validation = useMemo(
    () => validateValues(document, values),
    [document, values]
  )
  const errors = { ...validation.errors, ...externalErrors }
  const action = document.actions[0]
  const actionSafe =
    action?.kind === "submit" &&
    action.method === "POST" &&
    action.endpoint === routes.runs()
  const unavailable =
    document.availability.state === "available"
      ? null
      : document.availability.reason.detail
  const errorCount = Object.keys(errors).length
  const disabledReason = unavailable
    ? unavailable
    : !actionSafe
      ? "The document supplied an unsafe or unsupported submit action."
      : uploading
        ? "Wait for uploads to finish before submitting."
        : errorCount > 0
          ? `Fix ${errorCount} field${errorCount === 1 ? "" : "s"} before submitting.`
          : submitting
            ? "Submitting the run."
            : null

  const patch = (binding: string, value: FormValue) => {
    onChange({ ...values, [binding]: value })
  }

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setAttempted(true)
    if (validation.firstError) {
      globalThis.document
        .getElementById(controlId(validation.firstError.componentId))
        ?.focus()
      return
    }
    if (!action || !actionSafe || unavailable || uploading || submitting) return
    setSubmitting(true)
    try {
      await onSubmit(
        {
          workflowRevision: document.workflowRevision,
          schemaRevision: document.schemaRevision,
          input: submissionInput(document, values),
        },
        action
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form
      aria-label={document.title}
      onSubmit={submit}
      noValidate
      className="space-y-4"
    >
      {document.description ? (
        <p className="text-sm text-muted-foreground">{document.description}</p>
      ) : null}

      {groups(document).map((group, groupIndex) => {
        const sectionId = group.section
          ? `sdui-section-${safeId(group.section.id)}`
          : undefined
        return (
          <section
            key={group.section?.id ?? `ungrouped-${groupIndex}`}
            aria-labelledby={sectionId}
            className="rounded-lg border border-rule bg-panel/40 p-4"
          >
            {group.section ? (
              <header className="mb-4">
                <h2 id={sectionId} className="text-sm font-medium text-bone">
                  {group.section.title}
                </h2>
                {group.section.description ? (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {group.section.description}
                  </p>
                ) : null}
              </header>
            ) : null}
            <div className="grid gap-4 sm:grid-cols-2">
              {group.components.map((component) =>
                visible(component.visibleWhen, values) ? (
                  <Field
                    key={component.id}
                    component={component}
                    value={values[component.binding]}
                    error={
                      attempted || externalErrors[component.binding]
                        ? errors[component.binding]
                        : undefined
                    }
                    onChange={(value) => patch(component.binding, value)}
                    renderAsset={renderAsset}
                  />
                ) : null
              )}
            </div>
          </section>
        )
      })}

      {diagnostics.length > 0 ? (
        <aside
          className="rounded border border-signal/30 bg-signal/5 p-3 text-xs"
          aria-label="Compatibility notes"
        >
          <ul className="list-disc space-y-1 pl-4 text-muted-foreground">
            {diagnostics.map((diagnostic) => (
              <li key={diagnostic}>{diagnostic}</li>
            ))}
          </ul>
        </aside>
      ) : null}

      {disabledReason ? (
        <p role="status" aria-live="polite" className="text-sm text-signal">
          {disabledReason}
        </p>
      ) : null}

      <Button type="submit" disabled={disabledReason !== null}>
        {submitting ? "Submitting" : (action?.label ?? "Submit")}
      </Button>
    </form>
  )
}

function Field({
  component,
  value,
  error,
  onChange,
  renderAsset,
}: {
  component: InputComponent
  value: FormValue | undefined
  error?: string
  onChange: (value: FormValue) => void
  renderAsset?: AssetRenderer
}) {
  const id = controlId(component.id)
  const descriptionId = component.description ? `${id}-description` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy =
    [descriptionId, errorId].filter(Boolean).join(" ") || undefined
  const control = renderControl(
    component,
    value,
    onChange,
    id,
    describedBy,
    error,
    renderAsset
  )

  return (
    <div
      className={cn(
        "min-w-0",
        component.kind === "textarea" && "sm:col-span-2"
      )}
    >
      {component.kind === "toggle" ? null : (
        <label
          htmlFor={id}
          className="mb-1.5 block text-xs text-muted-foreground"
        >
          {component.label}
          {component.required ? <span aria-hidden="true"> *</span> : null}
        </label>
      )}
      {control}
      {component.description ? (
        <p id={descriptionId} className="mt-1 text-xs text-muted-foreground">
          {component.description}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="mt-1 text-xs text-crimson">
          {error}
        </p>
      ) : null}
    </div>
  )
}

function renderControl(
  component: InputComponent,
  value: FormValue | undefined,
  onChange: (value: FormValue) => void,
  id: string,
  describedBy: string | undefined,
  error: string | undefined,
  renderAsset: AssetRenderer | undefined
): React.ReactNode {
  const aria: AriaProps = {
    "aria-describedby": describedBy,
    "aria-invalid": error ? true : undefined,
    "aria-required": component.required || undefined,
  }
  switch (component.kind) {
    case "text":
      return (
        <TextField
          component={component}
          value={value}
          onChange={onChange}
          id={id}
          aria={aria}
        />
      )
    case "textarea":
      return (
        <TextareaField
          component={component}
          value={value}
          onChange={onChange}
          id={id}
          aria={aria}
        />
      )
    case "number":
      return (
        <NumberField
          component={component}
          value={value}
          onChange={onChange}
          id={id}
          aria={aria}
        />
      )
    case "select":
      return (
        <SelectField
          component={component}
          value={value}
          onChange={onChange}
          id={id}
          aria={aria}
        />
      )
    case "toggle":
      return (
        <ToggleField
          component={component}
          value={value}
          onChange={onChange}
          id={id}
          aria={aria}
        />
      )
    case "seed":
      return (
        <SeedField
          component={component}
          value={value}
          onChange={onChange}
          id={id}
          aria={aria}
        />
      )
    case "asset": {
      const ids = Array.isArray(value) ? value : []
      return renderAsset ? (
        <div id={id} aria-describedby={describedBy}>
          {renderAsset(component, ids, onChange)}
        </div>
      ) : (
        <p id={id} className="text-xs text-muted-foreground">
          Managed uploads are unavailable.
        </p>
      )
    }
  }
}

type AriaProps = {
  "aria-describedby": string | undefined
  "aria-invalid": true | undefined
  "aria-required": true | undefined
}

function TextField({
  component,
  value,
  onChange,
  id,
  aria,
}: {
  component: TextComponent
  value: FormValue | undefined
  onChange: (value: FormValue) => void
  id: string
  aria: AriaProps
}) {
  return (
    <Input
      {...aria}
      id={id}
      value={typeof value === "string" ? value : ""}
      placeholder={component.placeholder ?? undefined}
      minLength={component.minLength ?? undefined}
      maxLength={component.maxLength ?? undefined}
      required={component.required}
      onChange={(event) => onChange(event.target.value)}
    />
  )
}

function TextareaField({
  component,
  value,
  onChange,
  id,
  aria,
}: {
  component: TextareaComponent
  value: FormValue | undefined
  onChange: (value: FormValue) => void
  id: string
  aria: AriaProps
}) {
  return (
    <Textarea
      {...aria}
      id={id}
      value={typeof value === "string" ? value : ""}
      placeholder={component.placeholder ?? undefined}
      minLength={component.minLength ?? undefined}
      maxLength={component.maxLength ?? undefined}
      rows={component.rows ?? undefined}
      required={component.required}
      onChange={(event) => onChange(event.target.value)}
    />
  )
}

function NumberField({
  component,
  value,
  onChange,
  id,
  aria,
}: {
  component: NumberComponent
  value: FormValue | undefined
  onChange: (value: FormValue) => void
  id: string
  aria: AriaProps
}) {
  return (
    <div className="flex items-center gap-2">
      <Input
        {...aria}
        id={id}
        type="number"
        value={
          typeof value === "number" && Number.isFinite(value)
            ? String(value)
            : ""
        }
        min={component.minimum ?? undefined}
        max={component.maximum ?? undefined}
        step={component.integer ? 1 : (component.step ?? "any")}
        required={component.required}
        onChange={(event) =>
          onChange(
            event.target.value === "" ? Number.NaN : Number(event.target.value)
          )
        }
        className="tabular font-mono"
      />
      {component.unit ? (
        <span aria-hidden="true" className="text-xs text-muted-foreground">
          {component.unit}
        </span>
      ) : null}
    </div>
  )
}

function SelectField({
  component,
  value,
  onChange,
  id,
  aria,
}: {
  component: SelectComponent
  value: FormValue | undefined
  onChange: (value: FormValue) => void
  id: string
  aria: AriaProps
}) {
  const selected = component.options.find((option) => option.value === value)
  return (
    <select
      {...aria}
      id={id}
      value={selected ? optionKey(selected.value) : ""}
      required={component.required}
      onChange={(event) => {
        const option = component.options.find(
          (candidate) => optionKey(candidate.value) === event.target.value
        )
        if (option) onChange(option.value)
      }}
      className="h-8 w-full rounded-md border border-input bg-input/30 px-2 text-sm"
    >
      {!selected ? <option value="">Choose</option> : null}
      {component.options.map((option) => (
        <option
          key={optionKey(option.value)}
          value={optionKey(option.value)}
          disabled={option.disabled}
        >
          {option.label}
          {option.description ? ` — ${option.description}` : ""}
        </option>
      ))}
    </select>
  )
}

function ToggleField({
  component,
  value,
  onChange,
  id,
  aria,
}: {
  component: ToggleComponent
  value: FormValue | undefined
  onChange: (value: FormValue) => void
  id: string
  aria: AriaProps
}) {
  const checked = value === true
  return (
    <label htmlFor={id} className="flex cursor-pointer items-center gap-3">
      <input
        {...aria}
        id={id}
        type="checkbox"
        role="checkbox"
        checked={checked}
        required={component.required}
        onChange={(event) => onChange(event.target.checked)}
        className="size-4 accent-signal"
      />
      <span className="text-sm text-bone">
        {component.label}{" "}
        <span className="text-muted-foreground">
          — {checked ? "On" : "Off"}
        </span>
      </span>
    </label>
  )
}

function SeedField({
  component,
  value,
  onChange,
  id,
  aria,
}: {
  component: SeedComponent
  value: FormValue | undefined
  onChange: (value: FormValue) => void
  id: string
  aria: AriaProps
}) {
  const random = value === null
  const manualDefault = component.defaultValue ?? component.minimum
  return (
    <div className="space-y-2">
      <Input
        {...aria}
        id={id}
        type="number"
        value={typeof value === "number" ? String(value) : ""}
        min={component.minimum}
        max={component.maximum}
        step={1}
        disabled={random}
        required={component.required && !random}
        onChange={(event) =>
          onChange(
            event.target.value === "" ? Number.NaN : Number(event.target.value)
          )
        }
        className="tabular font-mono"
      />
      {component.allowRandom ? (
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={random}
            onChange={(event) =>
              onChange(event.target.checked ? null : manualDefault)
            }
          />
          Random each submission
        </label>
      ) : null}
    </div>
  )
}

function groups(document: GenerationDocument) {
  const result: {
    section?: Extract<
      GenerationDocument["components"][number],
      { kind: "section" }
    >
    components: InputComponent[]
  }[] = []
  let current: (typeof result)[number] = { components: [] }
  result.push(current)
  for (const component of document.components) {
    if (!isInputComponent(component)) {
      current = { section: component, components: [] }
      result.push(current)
    } else {
      current.components.push(component)
    }
  }
  return result.filter((group) => group.section || group.components.length > 0)
}

function optionKey(value: string | number | boolean): string {
  return `${typeof value}:${String(value)}`
}

function controlId(componentId: string): string {
  return `sdui-control-${safeId(componentId)}`
}

function safeId(value: string): string {
  return value.replace(/[^A-Za-z0-9_-]/g, "-")
}
