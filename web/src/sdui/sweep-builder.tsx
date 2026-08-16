import { useMemo, useState } from "react"
import { Plus, Trash2, X } from "lucide-react"

import type {
  GenerationDocument,
  SharedSweepRequest,
  SweepPreview,
} from "@/api/schema"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

import { sweepComponents } from "./authoring"
import type { FormValues, ScalarValue } from "./form-state"
import { visible } from "./predicates"

type SweepComponent = ReturnType<typeof sweepComponents>[number]
type PickedAxis = { binding: string; values: ScalarValue[] }
type PreviewState = { key: string; value: SweepPreview }

const valueButton =
  "rounded-md border border-input px-2.5 py-1 text-xs transition-colors aria-pressed:border-primary aria-pressed:bg-primary/15 aria-pressed:text-foreground"

export function SduiSweepBuilder({
  document,
  values,
  disabled = false,
  onPreview,
  onRun,
}: {
  document: GenerationDocument
  values: Readonly<FormValues>
  disabled?: boolean
  onPreview: (request: SharedSweepRequest) => Promise<SweepPreview>
  onRun: (request: SharedSweepRequest) => Promise<void>
}) {
  const eligible = sweepComponents(document, values)
  const allEligible = document.components.filter(
    (component): component is SweepComponent =>
      component.kind === "number" ||
      component.kind === "select" ||
      component.kind === "toggle"
  )
  const [axes, setAxes] = useState<PickedAxis[]>([])
  const [repeats, setRepeats] = useState(1)
  const [seedStrategy, setSeedStrategy] =
    useState<NonNullable<SharedSweepRequest["seed_strategy"]>>("fixed")
  const [skipDuplicates, setSkipDuplicates] = useState(true)
  const [numberDrafts, setNumberDrafts] = useState<Record<string, string>>({})
  const [preview, setPreview] = useState<PreviewState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [queueing, setQueueing] = useState(false)

  const request = useMemo<SharedSweepRequest>(
    () => ({
      base: {
        workflowRevision: document.workflowRevision,
        schemaRevision: document.schemaRevision,
        input: { ...values },
      },
      axes: axes.map((axis) => ({
        binding: axis.binding,
        values: [...axis.values],
      })),
      repeats,
      seed_strategy: seedStrategy,
      skip_duplicates: skipDuplicates,
    }),
    [
      axes,
      document.schemaRevision,
      document.workflowRevision,
      repeats,
      seedStrategy,
      skipDuplicates,
      values,
    ]
  )
  const requestKey = JSON.stringify(request)
  const currentPreview = preview?.key === requestKey ? preview.value : null
  const validAxes = axes.every((axis) => {
    const component = allEligible.find(
      (candidate) => candidate.binding === axis.binding
    )
    return (
      axis.values.length >= 2 &&
      component !== undefined &&
      visibleForEveryCombination(component, axes, values)
    )
  })
  const canPreview =
    !disabled &&
    !previewing &&
    !queueing &&
    validAxes &&
    (axes.length > 0 || repeats > 1)

  const invalidate = () => {
    setPreview(null)
    setError(null)
  }

  const updateAxes = (next: PickedAxis[]) => {
    invalidate()
    setAxes(next)
  }

  const addAxis = () => {
    const used = new Set(axes.map((axis) => axis.binding))
    const component = eligible.find((candidate) => !used.has(candidate.binding))
    if (!component) return
    updateAxes([...axes, defaultAxis(component, values)])
  }

  const previewSweep = async () => {
    if (!canPreview) return
    setPreviewing(true)
    setError(null)
    try {
      const value = await onPreview(request)
      setPreview({ key: requestKey, value })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setPreviewing(false)
    }
  }

  const queueSweep = async () => {
    if (!currentPreview || disabled || queueing) return
    setQueueing(true)
    setError(null)
    try {
      await onRun(request)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setQueueing(false)
    }
  }

  const queueCount = currentPreview
    ? skipDuplicates
      ? currentPreview.new_count
      : currentPreview.count
    : 0

  return (
    <div className="space-y-4">
      <div className="space-y-3">
        {axes.map((axis, index) => {
          const component = allEligible.find(
            (candidate) => candidate.binding === axis.binding
          )
          if (!component) return null
          const conditionallyUnavailable = !visibleForEveryCombination(
            component,
            axes,
            values
          )
          const choices = eligible.some(
            (candidate) => candidate.binding === component.binding
          )
            ? eligible
            : [component, ...eligible]
          return (
            <div
              key={`${axis.binding}-${index}`}
              className="grid gap-2 rounded-lg border border-border/70 p-3"
            >
              <div className="flex items-center gap-2">
                <select
                  aria-label={`Sweep axis ${index + 1}`}
                  className="h-8 min-w-40 rounded-md border border-input bg-input/30 px-2 text-xs"
                  value={axis.binding}
                  onChange={(event) => {
                    const next = eligible.find(
                      (item) => item.binding === event.target.value
                    )
                    if (!next) return
                    updateAxes(
                      axes.map((item, itemIndex) =>
                        itemIndex === index
                          ? defaultAxis(next, values)
                          : item
                      )
                    )
                  }}
                >
                  {choices.map((item) => (
                    <option
                      key={item.binding}
                      value={item.binding}
                      disabled={axes.some(
                        (candidate, candidateIndex) =>
                          candidateIndex !== index &&
                          candidate.binding === item.binding
                      )}
                    >
                      {item.label}
                    </option>
                  ))}
                </select>
                <span className="text-xs text-muted-foreground">
                  {axis.values.length} values
                </span>
                <Button
                  className="ml-auto"
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Remove ${component.label} axis`}
                  onClick={() =>
                    updateAxes(
                      axes.filter((_, itemIndex) => itemIndex !== index)
                    )
                  }
                >
                  <Trash2 aria-hidden="true" className="size-3.5" />
                </Button>
              </div>
              <AxisValues
                axis={axis}
                component={component}
                numberDraft={numberDrafts[axis.binding] ?? ""}
                onNumberDraft={(next) =>
                  setNumberDrafts((current) => ({
                    ...current,
                    [axis.binding]: next,
                  }))
                }
                onChange={(nextValues) =>
                  updateAxes(
                    axes.map((item, itemIndex) =>
                      itemIndex === index
                        ? { ...item, values: nextValues }
                        : item
                    )
                  )
                }
              />
              {axis.values.length < 2 ? (
                <p className="text-xs text-destructive" role="alert">
                  Choose at least two distinct values for {component.label}.
                </p>
              ) : null}
              {conditionallyUnavailable ? (
                <p className="text-xs text-amber-700" role="alert">
                  {component.label} is conditionally unavailable for one or
                  more selected axis values. Narrow the controlling axis or
                  remove {component.label}.
                </p>
              ) : null}
            </div>
          )
        })}
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={axes.length >= eligible.length}
          onClick={addAxis}
        >
          <Plus aria-hidden="true" className="size-3.5" />
          Add axis
        </Button>
        <label className="grid gap-1 text-xs text-muted-foreground">
          Repeats
          <select
            aria-label="Sweep repeats"
            className="h-8 rounded-md border border-input bg-input/30 px-2 text-xs"
            value={repeats}
            onChange={(event) => {
              invalidate()
              setRepeats(Number(event.target.value))
            }}
          >
            {[1, 2, 3, 5, 8, 16, 32].map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs text-muted-foreground">
          Seed strategy
          <select
            aria-label="Seed strategy"
            className="h-8 rounded-md border border-input bg-input/30 px-2 text-xs"
            value={seedStrategy}
            onChange={(event) => {
              invalidate()
              setSeedStrategy(
                event.target.value as NonNullable<
                  SharedSweepRequest["seed_strategy"]
                >
              )
            }}
          >
            <option value="fixed">Fixed for fair comparisons</option>
            <option value="increment">Increment each repeat</option>
            <option value="random">Unique random seeds</option>
          </select>
        </label>
        <label className="flex h-8 items-center gap-2 text-xs text-muted-foreground">
          <input
            aria-label="Skip runs already completed"
            type="checkbox"
            checked={skipDuplicates}
            onChange={(event) => {
              invalidate()
              setSkipDuplicates(event.target.checked)
            }}
          />
          Skip duplicates
        </label>
      </div>

      {error ? (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
      ) : null}

      {currentPreview ? (
        <div
          className="grid grid-cols-2 gap-2 rounded-lg border border-border/70 p-3 text-xs sm:grid-cols-4"
          aria-label="Sweep preview"
        >
          <span>{currentPreview.combinations} combinations</span>
          <span>{currentPreview.count} total runs</span>
          <span>{currentPreview.new_count} new</span>
          <span>{currentPreview.duplicate_count} already run</span>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          Preview on the server to check validation and existing runs before
          queuing.
        </p>
      )}

      <div className="flex flex-wrap justify-end gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!canPreview}
          onClick={() => void previewSweep()}
        >
          {previewing ? "Previewing…" : "Preview sweep"}
        </Button>
        <Button
          type="button"
          size="sm"
          disabled={
            disabled ||
            queueing ||
            !currentPreview ||
            queueCount === 0
          }
          onClick={() => void queueSweep()}
          aria-label={
            currentPreview
              ? `Queue ${queueCount} ${skipDuplicates ? "new " : ""}run${
                  queueCount === 1 ? "" : "s"
                }`
              : "Queue sweep"
          }
        >
          {queueing
            ? "Queueing…"
            : currentPreview
              ? `Queue ${queueCount} ${skipDuplicates ? "new " : ""}run${
                  queueCount === 1 ? "" : "s"
                }`
              : "Queue sweep"}
        </Button>
      </div>
    </div>
  )
}

function AxisValues({
  axis,
  component,
  numberDraft,
  onNumberDraft,
  onChange,
}: {
  axis: PickedAxis
  component: SweepComponent
  numberDraft: string
  onNumberDraft: (value: string) => void
  onChange: (values: ScalarValue[]) => void
}) {
  if (component.kind === "select") {
    return (
      <div className="flex flex-wrap gap-2">
        {component.options
          .filter((option) => !option.disabled)
          .map((option) => {
            const selected = includesValue(axis.values, option.value)
            return (
              <button
                key={`${typeof option.value}:${String(option.value)}`}
                type="button"
                className={valueButton}
                aria-pressed={selected}
                onClick={() =>
                  onChange(
                    selected
                      ? axis.values.filter(
                          (value) => !Object.is(value, option.value)
                        )
                      : [...axis.values, option.value]
                  )
                }
              >
                {option.label}
              </button>
            )
          })}
      </div>
    )
  }
  if (component.kind === "toggle") {
    return (
      <div className="flex flex-wrap gap-2">
        {[
          { value: true, label: "Enabled" },
          { value: false, label: "Disabled" },
        ].map((option) => {
          const selected = includesValue(axis.values, option.value)
          return (
            <button
              key={String(option.value)}
              type="button"
              className={valueButton}
              aria-pressed={selected}
              onClick={() =>
                onChange(
                  selected
                    ? axis.values.filter(
                        (value) => !Object.is(value, option.value)
                      )
                    : [...axis.values, option.value]
                )
              }
            >
              {option.label}
            </button>
          )
        })}
      </div>
    )
  }
  const addNumber = () => {
    const value = Number(numberDraft)
    if (!validNumber(component, value) || includesValue(axis.values, value))
      return
    onChange([...axis.values, value])
    onNumberDraft("")
  }
  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap gap-2">
        {axis.values.map((value) => (
          <span
            key={String(value)}
            className="inline-flex items-center gap-1 rounded-md border border-primary/50 bg-primary/10 px-2 py-1 text-xs"
          >
            {String(value)}
            <button
              type="button"
              aria-label={`Remove ${component.label} value ${String(value)}`}
              onClick={() =>
                onChange(axis.values.filter((candidate) => candidate !== value))
              }
            >
              <X aria-hidden="true" className="size-3" />
            </button>
          </span>
        ))}
      </div>
      <div className="flex max-w-xs gap-2">
        <Input
          aria-label={`Add ${component.label} value`}
          type="number"
          min={component.minimum ?? undefined}
          max={component.maximum ?? undefined}
          step={component.step ?? (component.integer ? 1 : "any")}
          value={numberDraft}
          onChange={(event) => onNumberDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault()
              addNumber()
            }
          }}
        />
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={!validNumber(component, Number(numberDraft))}
          onClick={addNumber}
        >
          Add value
        </Button>
      </div>
    </div>
  )
}

function defaultAxis(
  component: SweepComponent,
  values: Readonly<FormValues>
): PickedAxis {
  if (component.kind === "select") {
    return {
      binding: component.binding,
      values: component.options
        .filter((option) => !option.disabled)
        .slice(0, 2)
        .map((option) => option.value),
    }
  }
  if (component.kind === "toggle") {
    return { binding: component.binding, values: [true, false] }
  }
  const current = values[component.binding]
  const first =
    typeof current === "number"
      ? current
      : (component.defaultValue ?? component.minimum ?? 0)
  const step = component.step ?? (component.integer ? 1 : 0.1)
  const above = first + step
  const below = first - step
  const second = validNumber(component, above)
    ? above
    : validNumber(component, below)
      ? below
      : component.maximum
  return {
    binding: component.binding,
    values:
      typeof second === "number" && !Object.is(first, second)
        ? [first, second]
        : [first],
  }
}

function validNumber(
  component: Extract<SweepComponent, { kind: "number" }>,
  value: number
): boolean {
  if (!Number.isFinite(value)) return false
  if (component.integer && !Number.isInteger(value)) return false
  if (component.minimum != null && value < component.minimum) return false
  if (component.maximum != null && value > component.maximum) return false
  if (component.step != null) {
    const origin = component.minimum ?? 0
    const units = (value - origin) / component.step
    if (Math.abs(units - Math.round(units)) > 1e-9) return false
  }
  return true
}

function includesValue(
  values: readonly ScalarValue[],
  candidate: ScalarValue
): boolean {
  return values.some((value) => Object.is(value, candidate))
}

function visibleForEveryCombination(
  component: SweepComponent,
  axes: readonly PickedAxis[],
  base: Readonly<FormValues>
): boolean {
  let candidates: FormValues[] = [{ ...base }]
  for (const axis of axes) {
    candidates = candidates.flatMap((candidate) =>
      axis.values.map((value) => ({
        ...candidate,
        [axis.binding]: value,
      }))
    )
  }
  return candidates.every((candidate) =>
    visible(component.visibleWhen, candidate)
  )
}
