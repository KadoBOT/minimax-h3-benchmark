/**
 * The sweep builder: vary a few settings and queue the matrix they imply.
 *
 * This is where the lab stops being ad hoc. Preview before queue is the point — it says how
 * many runs the matrix is and how many of them you have already produced, so an accidental
 * eighty-run overnight queue is visible before it starts rather than at 3am.
 */

import { useMemo, useState } from "react"
import { Layers, X } from "lucide-react"

import { useRunSweep, useSweepPreview } from "@/api/hooks"
import type { GenerationConfig, Meta, SweepRequest } from "@/api/schema"
import { Section, Stat } from "@/components/page"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { display, label as fieldLabel } from "@/lib/config"
import { plural } from "@/lib/format"
import { Choice } from "./config-form"

/** Fields worth sweeping, with the values each one can take. */
type Sweepable = { field: string; values: (string | number | boolean)[] }

function sweepable(meta: Meta | undefined, catalog: SweepCatalog): Sweepable[] {
  return [
    { field: "cache", values: meta?.caches ?? [] },
    { field: "cache_preset", values: meta?.preset_levels ?? [] },
    { field: "sol_preset", values: meta?.preset_levels ?? [] },
    { field: "sol_attn", values: [true, false] },
    { field: "turbo", values: [true, false] },
    { field: "rife", values: [true, false] },
    { field: "upscaler", values: [true, false] },
    { field: "clean_vram", values: [true, false] },
    { field: "sampler", values: catalog.samplers },
    { field: "scheduler", values: catalog.schedulers },
    { field: "aspect_ratio", values: catalog.aspect_ratios },
    { field: "diffusion_model", values: catalog.diffusion_models },
    { field: "steps", values: [4, 8, 12, 16, 20, 28, 36] },
    { field: "mp", values: [0.25, 0.5, 0.75, 1, 1.5] },
  ].filter((axis) => axis.values.length > 1)
}

type SweepCatalog = {
  samplers: string[]
  schedulers: string[]
  aspect_ratios: string[]
  diffusion_models: string[]
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

  const preview = useSweepPreview()
  const start = useRunSweep()
  const available = useMemo(() => sweepable(meta, catalog), [meta, catalog])

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
    // Seed with the base value plus one alternative, which is the smallest useful comparison.
    const current = base[field as keyof GenerationConfig] as string | number | boolean
    const others = found.values.filter((value) => value !== current)
    setAxes([...axes, { field, values: [current, others[0]].filter((v) => v !== undefined) }])
  }

  return (
    <Section
      title="Sweep"
      hint="Vary a setting or two against the config above; the seed strategy decides how fair the comparison is."
      actions={
        <Choice
          value=""
          options={available.filter((a) => !axes.some((b) => b.field === a.field)).map((a) => a.field)}
          render={(field) => fieldLabel(meta, field)}
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
            return (
              <div key={axis.field}>
                <div className="mb-1.5 flex items-center justify-between">
                  <Label className="text-bone text-xs">{fieldLabel(meta, axis.field)}</Label>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-label={`Stop varying ${fieldLabel(meta, axis.field)}`}
                    onClick={() => setAxes(axes.filter((item) => item.field !== axis.field))}
                  >
                    <X className="size-3" />
                  </Button>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {(found?.values ?? []).map((value) => {
                    const on = axis.values.includes(value)
                    return (
                      <button
                        key={String(value)}
                        onClick={() =>
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
                        }
                        aria-pressed={on}
                        className={
                          on
                            ? "border-signal/60 bg-signal/15 text-signal rounded-sm border px-2 py-1 font-mono text-xs"
                            : "border-rule text-muted-foreground hover:border-rule/80 hover:text-bone rounded-sm border px-2 py-1 font-mono text-xs"
                        }
                      >
                        {display(value)}
                      </button>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      )}

      <div className="border-rule mt-4 grid gap-4 border-t pt-4 sm:grid-cols-2">
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
          >
            {[1, 2, 3, 5, 8].map((count) => (
              <ToggleGroupItem key={count} value={String(count)}>
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
          >
            {(meta?.seed_strategies ?? []).map((strategy) => (
              <ToggleGroupItem key={strategy} value={strategy} className="capitalize">
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

      <div className="border-rule mt-4 flex flex-wrap items-end gap-6 border-t pt-4">
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

        <label className="ml-auto flex cursor-pointer items-center gap-2 text-xs">
          <Switch checked={skipDuplicates} onCheckedChange={setSkipDuplicates} size="sm" />
          <span className="text-muted-foreground">Skip what already ran</span>
        </label>

        <div className="flex gap-1.5">
          <Button
            variant="outline"
            size="sm"
            disabled={blocked || preview.isPending}
            onClick={() => preview.mutate(request)}
          >
            Preview
          </Button>
          <Button
            size="sm"
            disabled={blocked || start.isPending}
            onClick={() => start.mutate(request)}
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
