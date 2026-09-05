/**
 * The sweep builder: vary a few settings and queue the matrix they imply.
 *
 * This is where the lab stops being ad hoc. Preview before queue is the point — it says how
 * many runs the matrix is and how many of them you have already produced, so an accidental
 * eighty-run overnight queue is visible before it starts rather than at 3am.
 */

import { useMemo, useState } from "react"
import { Layers, Plus, X } from "lucide-react"

import { useRunSweep, useStudioSession, useSweepPreview } from "@/api/hooks"
import type { GenerationConfig, Meta, SweepRequest } from "@/api/schema"
import { Choice } from "@/components/choice"
import { Section, Stat } from "@/components/page"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { display, label as fieldLabel } from "@/lib/config"
import { plural } from "@/lib/format"
import { studioInputsFromDraft } from "@/lib/studio-runtime"
import {
  CURRENT_TEMPLATE_ID,
  TEMPLATE_CONFLICT_FIELDS,
  sweepable,
  templateIdFromState,
  type SweepCatalog,
  type Sweepable,
} from "./sweep-options"
import { TemplateSweepPicker } from "./template-sweep-picker"

/** Axes that only mean something while another setting is on, and what turns them on. */
const NEEDS_TURBO = new Set(["turbo_lora", "turbo_lora_strength"])
const SWEEP_LABELS: Record<string, string> = {
  attn: "Attention",
  cache_enabled: "Cache",
  er_sde: "ER-SDE",
  template: "Template",
  duration_s: "Duration",
  shift_video: "Video shift",
  shift_audio: "Audio shift",
}

function sweepLabel(meta: Meta | undefined, field: string): string {
  return SWEEP_LABELS[field] ?? fieldLabel(meta, field)
}

const NUMERIC_BOUNDS: Record<
  string,
  { min: number; max: number; integer?: boolean }
> = {
  turbo_lora_strength: { min: 0.0, max: 3.0 },
  steps: { min: 1, max: 200, integer: true },
  mp: { min: 0.05, max: 8.0 },
  duration_s: { min: 0.5, max: 60.0 },
  shift_audio: { min: 0, max: 100, integer: true },
  shift_video: { min: 0, max: 100, integer: true },
  sla_sparsity: { min: 0.0, max: 1.0 },
  sla_dense_last_steps: { min: 0, max: 50, integer: true },
  er_sde_max_stage: { min: 1, max: 10, integer: true },
  er_sde_eta: { min: 0, max: 10 },
  er_sde_s_noise: { min: 0, max: 10 },
}

function isNumericAxis(meta: Meta | undefined, field: string, found?: Sweepable): boolean {
  const def = meta?.axes?.find((axis) => axis.field === field)
  if (def?.kind === "numeric") return true
  if (def?.kind === "boolean" || def?.kind === "categorical") return false
  if (!found || found.values.length === 0) return false
  return found.values.every((value) => typeof value === "number")
}

function examplePlaceholder(field: string): string {
  switch (field) {
    case "turbo_lora_strength":
      return "Custom (e.g. 0.6)"
    case "steps":
      return "Custom (e.g. 10, 14)"
    case "mp":
      return "Custom (e.g. 0.75)"
    case "duration_s":
      return "Custom (e.g. 6.5)"
    case "shift_audio":
    case "shift_video":
      return "Custom (e.g. 4)"
    case "sla_sparsity":
      return "Custom (e.g. 0.88)"
    default:
      return "Custom (e.g. 0.6)"
  }
}

type Picked = { field: string; values: (string | number | boolean)[] }

export function SweepBuilder({
  base,
  meta,
  catalog,
  missing = [],
}: {
  base: GenerationConfig
  meta: Meta | undefined
  catalog: SweepCatalog
  /** Inputs the base config still lacks. A sweep of an invalid config is a matrix of 422s. */
  missing?: string[]
}) {
  const [axes, setAxes] = useState<Picked[]>([])
  const [repeats, setRepeats] = useState(1)
  const [seedStrategy, setSeedStrategy] = useState<SweepRequest["seed_strategy"]>("fixed")
  const [skipDuplicates, setSkipDuplicates] = useState(true)
  const [customOptions, setCustomOptions] = useState<Record<string, (string | number)[]>>({})
  const [customInputs, setCustomInputs] = useState<Record<string, string>>({})
  const [inputErrors, setInputErrors] = useState<Record<string, string>>({})

  const preview = useSweepPreview()
  const start = useRunSweep()
  const studio = useStudioSession(base.mode)
  const templateCatalog = studio.data?.template_catalog
  const available = useMemo(
    () => sweepable(meta, catalog, studio.data?.input_options ?? {}, templateCatalog),
    [meta, catalog, studio.data?.input_options, templateCatalog]
  )
  const templateActive = axes.some((axis) => axis.field === "template")
  const conflictingActive = axes.some((axis) => TEMPLATE_CONFLICT_FIELDS.has(axis.field))
  const addable = available.filter((candidate) => {
    if (axes.some((picked) => picked.field === candidate.field)) return false
    if (candidate.field === "template") return !conflictingActive
    return !templateActive || !TEMPLATE_CONFLICT_FIELDS.has(candidate.field)
  })
  const templateInputs = useMemo(
    () => (studio.data ? studioInputsFromDraft(studio.data, base) : {}),
    [studio.data, base]
  )

  const request: SweepRequest = {
    base,
    axes: axes.filter((axis) => axis.values.length > 0).map((axis) => ({ ...axis })),
    repeats,
    seed_strategy: seedStrategy,
    skip_duplicates: skipDuplicates,
  }

  const combinations = request.axes!.reduce((total, axis) => total * axis.values.length, 1)
  const projected = combinations * repeats
  const result = preview.data
  const blocked = axes.length === 0 || missing.length > 0

  const addAxis = (field: string) => {
    const found = available.find((axis) => axis.field === field)
    if (!found || axes.some((axis) => axis.field === field)) return
    if (field === "template") {
      const provenance = templateIdFromState(base.widgets?.h3s_ui)
      const initial =
        provenance &&
        provenance !== CURRENT_TEMPLATE_ID &&
        templateCatalog?.templates.some((template) => template.id === provenance)
          ? provenance
          : (templateCatalog?.templates.find(
              (template) => template.id === "essentials/balanced"
            )?.id ?? templateCatalog?.templates[0]?.id)
      setAxes([
        ...axes,
        {
          field,
          values: [CURRENT_TEMPLATE_ID, initial].filter(
            (value): value is string => value !== undefined
          ),
        },
      ])
      return
    }
    // Seed with the base value plus one alternative, which is the smallest useful comparison.
    const current =
      field === "attn"
        ? ((base.widgets?.attn as string | undefined) ?? (base.sol_attn ? "sol" : "off"))
        : ((base[field as keyof GenerationConfig] ?? base.widgets?.[field]) as
            | string
            | number
            | boolean
            | undefined)

    if (
      current !== undefined &&
      current !== null &&
      current !== "" &&
      !found.values.includes(current)
    ) {
      setCustomOptions((prev) => ({
        ...prev,
        [field]: Array.from(new Set([...(prev[field] ?? []), current as string | number])),
      }))
    }

    const others = found.values.filter((value) => value !== current)
    setAxes([
      ...axes,
      {
        field,
        values: [current, others[0]].filter(
          (v): v is string | number | boolean => v !== undefined
        ),
      },
    ])
  }

  const addCustomValue = (field: string) => {
    const raw = customInputs[field]?.trim()
    if (!raw) return
    const found = available.find((item) => item.field === field)
    const isNumeric = isNumericAxis(meta, field, found)

    if (isNumeric) {
      const tokens = raw.split(/[, ]+/).filter(Boolean)
      const parsed: number[] = []
      const bounds = NUMERIC_BOUNDS[field]

      for (const token of tokens) {
        const num = Number(token)
        if (!Number.isFinite(num)) {
          setInputErrors((prev) => ({ ...prev, [field]: `"${token}" is not a number` }))
          return
        }
        if (bounds) {
          if (num < bounds.min || num > bounds.max) {
            setInputErrors((prev) => ({
              ...prev,
              [field]: `Must be between ${bounds.min} and ${bounds.max}`,
            }))
            return
          }
        }
        const val = bounds?.integer ? Math.round(num) : Math.round(num * 10000) / 10000
        parsed.push(val)
      }

      if (parsed.length === 0) return

      const nonDefaultValues = parsed.filter((val) => !found?.values.includes(val))
      if (nonDefaultValues.length > 0) {
        setCustomOptions((prev) => ({
          ...prev,
          [field]: Array.from(new Set([...(prev[field] ?? []), ...nonDefaultValues])),
        }))
      }

      setAxes((prevAxes) =>
        prevAxes.map((item) =>
          item.field === field
            ? {
                ...item,
                values: Array.from(new Set([...item.values, ...parsed])),
              }
            : item
        )
      )

      setCustomInputs((prev) => ({ ...prev, [field]: "" }))
      setInputErrors((prev) => ({ ...prev, [field]: "" }))
    }
  }

  const removeCustomValue = (field: string, value: string | number | boolean) => {
    setCustomOptions((prev) => ({
      ...prev,
      [field]: (prev[field] ?? []).filter((v) => v !== value),
    }))
    setAxes((prevAxes) =>
      prevAxes.map((item) =>
        item.field === field
          ? {
              ...item,
              values: item.values.filter((v) => v !== value),
            }
          : item
      )
    )
  }

  return (
    <Section
      title="Sweep"
      hint="Vary a setting or two against the config above; the seed strategy decides how fair the comparison is."
      actions={
        <Choice
          value=""
          options={addable.map((axis) => axis.field)}
          render={(field) => sweepLabel(meta, field)}
          onChange={addAxis}
          label="Add a sweep axis"
          placeholder="add an axis"
        />
      }
    >
      {axes.length === 0 ? (
        <p className="text-muted-foreground py-2 text-sm">
          Pick an axis to vary. Two values on one axis with three repeats is the cheapest thing
          that can actually settle an argument.
        </p>
      ) : (
        <div className="space-y-3">
          {axes.map((axis) => {
            const found = available.find((item) => item.field === axis.field)
            const isNumeric = isNumericAxis(meta, axis.field, found)
            const defaults = found?.values ?? []
            const custom = customOptions[axis.field] ?? []
            const fromAxis = axis.values.filter(
              (v) => !defaults.includes(v) && !custom.includes(v as string | number)
            )
            const allOptions = Array.from(new Set([...defaults, ...custom, ...fromAxis]))
            if (isNumeric) {
              allOptions.sort((a, b) => Number(a) - Number(b))
            }

            return (
              <div key={axis.field}>
                <div className="mb-1.5 flex items-center justify-between">
                  <Label className="text-bone text-xs">{sweepLabel(meta, axis.field)}</Label>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-label={`Stop varying ${sweepLabel(meta, axis.field)}`}
                    onClick={() => setAxes(axes.filter((item) => item.field !== axis.field))}
                  >
                    <X className="size-3" />
                  </Button>
                </div>
                {axis.field === "template" && templateCatalog ? (
                  <TemplateSweepPicker
                    catalog={templateCatalog}
                    selected={axis.values}
                    inputs={templateInputs}
                    capabilities={studio.data?.capabilities ?? {}}
                    onChange={(values) =>
                      setAxes(
                        axes.map((item) =>
                          item.field === "template" ? { ...item, values } : item
                        )
                      )
                    }
                  />
                ) : (
                  <div className="space-y-1.5">
                    <div className="flex flex-wrap gap-1.5">
                      {allOptions.map((value) => {
                        const on = axis.values.includes(value)
                        const isCustom = !defaults.includes(value)
                        const toggle = () =>
                          setAxes(
                            axes.map((item) =>
                              item.field === axis.field
                                ? {
                                    ...item,
                                    values: on
                                      ? item.values.filter((v) => v !== value)
                                      : [...item.values, value],
                                  }
                                : item
                            )
                          )

                        if (!isCustom) {
                          return (
                            <button
                              key={String(value)}
                              type="button"
                              onClick={toggle}
                              aria-pressed={on}
                              className={
                                on
                                  ? "border-signal/60 bg-signal/15 text-signal rounded-sm border px-2 py-1 font-mono text-xs cursor-pointer"
                                  : "border-rule text-muted-foreground hover:border-rule/80 hover:text-bone rounded-sm border px-2 py-1 font-mono text-xs cursor-pointer"
                              }
                            >
                              {found?.render ? found.render(value) : display(value)}
                            </button>
                          )
                        }

                        return (
                          <div
                            key={String(value)}
                            className={
                              on
                                ? "border-signal/60 bg-signal/15 text-signal inline-flex items-center rounded-sm border font-mono text-xs"
                                : "border-rule text-muted-foreground hover:border-rule/80 hover:text-bone inline-flex items-center rounded-sm border font-mono text-xs"
                            }
                          >
                            <button
                              type="button"
                              onClick={toggle}
                              aria-pressed={on}
                              className="px-2 py-1 cursor-pointer pr-1"
                            >
                              {found?.render ? found.render(value) : display(value)}
                            </button>
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation()
                                removeCustomValue(axis.field, value)
                              }}
                              aria-label={`Remove custom value ${value}`}
                              className="pr-1.5 pl-0.5 py-1 text-muted-foreground hover:text-signal cursor-pointer transition-colors"
                            >
                              <X className="size-2.5" />
                            </button>
                          </div>
                        )
                      })}
                    </div>
                    {isNumeric ? (
                      <div className="flex flex-wrap items-center gap-2 pt-0.5">
                        <div className="flex items-center gap-1.5">
                          <Input
                            type="text"
                            placeholder={examplePlaceholder(axis.field)}
                            value={customInputs[axis.field] ?? ""}
                            onChange={(e) => {
                              setCustomInputs({ ...customInputs, [axis.field]: e.target.value })
                              if (inputErrors[axis.field]) {
                                setInputErrors({ ...inputErrors, [axis.field]: "" })
                              }
                            }}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") {
                                e.preventDefault()
                                addCustomValue(axis.field)
                              }
                            }}
                            className="h-7 w-36 sm:w-44 font-mono text-xs"
                            aria-label={`Custom value for ${sweepLabel(meta, axis.field)}`}
                          />
                          <Button
                            type="button"
                            variant="outline"
                            size="xs"
                            onClick={() => addCustomValue(axis.field)}
                            disabled={!customInputs[axis.field]?.trim()}
                            className="h-7 px-2 text-xs cursor-pointer"
                          >
                            <Plus className="size-3 mr-0.5" />
                            Add
                          </Button>
                        </div>
                        {inputErrors[axis.field] ? (
                          <span className="text-signal text-xs">{inputErrors[axis.field]}</span>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                )}
                {NEEDS_TURBO.has(axis.field) && !base.turbo ? (
                  <p className="text-signal mt-1.5 text-xs">
                    Turbo is off, so no LoRA is loaded and every run here is the same run. Turn
                    Turbo on above to vary this.
                  </p>
                ) : null}
              </div>
            )
          })}
        </div>
      )}

      <div className="border-rule mt-4 grid gap-4 border-t pt-4 grid-cols-1 sm:grid-cols-2">
        <div>
          <Label className="text-muted-foreground mb-1.5 block text-xs">
            Repeats per combination
          </Label>
          <ToggleGroup
            value={[String(repeats)]}
            onValueChange={(value) => {
              const picked = Number(value[0])
              if (Number.isFinite(picked) && picked > 0) setRepeats(picked)
            }}
            className="w-full flex-wrap sm:flex-nowrap"
          >
            {[1, 2, 3, 5, 8].map((count) => (
              <ToggleGroupItem key={count} value={String(count)} className="flex-1">
                {count}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </div>
        <div>
          <Label className="text-muted-foreground mb-1.5 block text-xs">Seed per repeat</Label>
          <ToggleGroup
            value={[seedStrategy ?? "fixed"]}
            onValueChange={(value) => {
              const picked = value[0]
              if (picked) setSeedStrategy(picked as SweepRequest["seed_strategy"])
            }}
            className="w-full flex-wrap sm:flex-nowrap"
          >
            {(meta?.seed_strategies ?? []).map((strategy) => (
              <ToggleGroupItem key={strategy} value={strategy} className="flex-1 capitalize text-xs">
                {strategy}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <p className="text-muted-foreground mt-1.5 text-xs">
            {seedStrategy === "fixed"
              ? "Same noise every time — the cleanest way to isolate one setting."
              : seedStrategy === "increment"
                ? "Seeds step by one, so replicates share a known ladder."
                : "Fresh noise per run — good for asking what a setting does on average."}
          </p>
        </div>
      </div>

      <div className="border-rule mt-4 flex flex-wrap items-center gap-4 sm:gap-6 border-t pt-4">
        <div className="flex flex-wrap gap-4 sm:gap-6">
          <Stat label="Combinations" value={combinations} />
          <Stat label="Runs" value={projected} tone={projected > 60 ? "signal" : "bone"} />
          {result ? (
            <>
              <Stat label="New" value={result.new_count} tone="mint" />
              <Stat
                label="Already run"
                value={result.duplicate_count}
                tone={result.duplicate_count ? "signal" : "muted"}
              />
            </>
          ) : null}
        </div>

        <label className="w-full sm:w-auto sm:ml-auto flex cursor-pointer items-center gap-2 text-xs">
          <Switch checked={skipDuplicates} onCheckedChange={setSkipDuplicates} size="sm" />
          <span className="text-muted-foreground">Skip what already ran</span>
        </label>

        <div className="flex gap-1.5 w-full sm:w-auto">
          <Button
            variant="outline"
            size="sm"
            disabled={blocked || preview.isPending}
            onClick={() => preview.mutate(request)}
            className="flex-1 sm:flex-none"
          >
            Preview
          </Button>
          <Button
            size="sm"
            disabled={blocked || start.isPending}
            onClick={() => start.mutate(request)}
            className="flex-1 sm:flex-none"
          >
            <Layers data-icon="inline-start" className="size-3.5" />
            Queue {plural(skipDuplicates && result ? result.new_count : projected, "run")}
          </Button>
        </div>
      </div>

      {missing.length > 0 ? (
        <p className="text-signal mt-3 text-sm">
          The config above still needs {missing.join(" and ")}. Every run in the matrix inherits
          it, so there is nothing to sweep until that is set.
        </p>
      ) : null}

      {result && result.duplicate_count > 0 ? (
        <p className="text-muted-foreground mt-3 text-xs">
          {plural(result.duplicate_count, "combination")} in this matrix{" "}
          {result.duplicate_count === 1 ? "has" : "have"} been run before.{" "}
          {skipDuplicates
            ? "They will be skipped."
            : "They will run again — useful for checking whether a timing was a fluke."}
        </p>
      ) : null}
    </Section>
  )
}
