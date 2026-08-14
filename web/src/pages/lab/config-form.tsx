/**
 * The config builder.
 *
 * Grouped by what a question is about rather than by which ComfyUI node it lands on: what to
 * make, how to sample it, and what to trade away for speed. Fields a mode ignores are hidden
 * outright, and fields a toggle has made irrelevant are shown inert with the reason.
 */

import { useEffect, useRef, useState } from "react"
import { Dices, Upload, X } from "lucide-react"

import { useUpload } from "@/api/hooks"
import { routes } from "@/api/routes"
import type { Catalog, Meta } from "@/api/schema"
import { Section } from "@/components/page"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import {
  acceptedFields,
  inertFields,
  mediaDefaults,
  randomSeed,
  turboLora,
  turboSteps,
  type Draft,
} from "@/lib/config"
import { loraStem, modelStem } from "@/lib/format"
import { LIMITS } from "@/lib/limits"
import { cn } from "@/lib/utils"

type FormProps = {
  draft: Draft
  onChange: (patch: Partial<Draft>) => void
  meta: Meta | undefined
  catalog: Catalog | undefined
}

export function ConfigForm({ draft, onChange, meta, catalog }: FormProps) {
  const inert = inertFields(draft)
  const accepted = acceptedFields(meta, draft.mode)
  const steps = turboSteps(draft, catalog)
  const normalSteps = useNormalSteps(draft, meta)

  return (
    <div className="space-y-4">
      <Section title="What to make" hint="The mode decides which inputs the graph wires up.">
        <div className="space-y-4">
          <Row label="Mode">
            <ToggleGroup
              value={[draft.mode ?? "flf2v"]}
              onValueChange={(value) => {
                const next = value[0] as Draft["mode"] | undefined
                if (!next) return
                const moved = { ...draft, mode: next }
                onChange({ mode: next, ...mediaDefaults(moved, meta, catalog) })
              }}
              className="w-full max-sm:flex-col max-sm:items-stretch"
            >
              {(meta?.modes ?? []).map((needs) => (
                <ToggleGroupItem key={needs.mode} value={needs.mode} className="w-full flex-1">
                  {needs.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </Row>

          <Row label="Weights" hint={catalog?.diffusion_models_source}>
            <Choice
              value={draft.diffusion_model || catalog?.default_diffusion_model || ""}
              options={catalog?.diffusion_models ?? []}
              render={modelStem}
              onChange={(value) => onChange({ diffusion_model: value })}
              label="Weights"
              placeholder="pick a checkpoint"
            />
          </Row>

          <div>
            <Label htmlFor="prompt" className="text-muted-foreground mb-1.5 text-xs">
              Prompt
            </Label>
            <Textarea
              id="prompt"
              value={draft.prompt ?? ""}
              onChange={(event) => onChange({ prompt: event.target.value })}
              rows={6}
              className="font-mono text-[13px] leading-relaxed"
              placeholder="Describe the shot, then the motion, then what the camera does."
            />
          </div>

          {accepted.has("first_frame") ? (
            <Row label="First frame" hint="required for this mode">
              <MediaPick
                label="First frame"
                value={draft.first_frame ?? ""}
                options={catalog?.images ?? []}
                onChange={(value) => onChange({ first_frame: value })}
              />
            </Row>
          ) : null}

          {accepted.has("last_frame") ? (
            <Row label="Last frame" hint="optional — leave empty to let it end where it wants">
              <MediaPick
                label="Last frame"
                value={draft.last_frame ?? ""}
                options={catalog?.images ?? []}
                onChange={(value) => onChange({ last_frame: value })}
                allowEmpty
              />
            </Row>
          ) : null}

          {accepted.has("ref_images") ? (
            <Row label="Reference images" hint={`up to ${catalog?.reference_limits?.images ?? 4}`}>
              <MediaList
                label="Reference image"
                values={draft.ref_images ?? []}
                options={catalog?.images ?? []}
                limit={catalog?.reference_limits?.images ?? 4}
                onChange={(values) => onChange({ ref_images: values })}
                previews
              />
            </Row>
          ) : null}

          {accepted.has("ref_videos") ? (
            <Row label="Reference videos" hint={`up to ${catalog?.reference_limits?.videos ?? 2}`}>
              <MediaList
                label="Reference video"
                values={draft.ref_videos ?? []}
                options={catalog?.videos ?? []}
                limit={catalog?.reference_limits?.videos ?? 2}
                onChange={(values) => onChange({ ref_videos: values })}
              />
            </Row>
          ) : null}

          {accepted.has("ref_audios") ? (
            <Row label="Reference audio" hint={`up to ${catalog?.reference_limits?.audios ?? 2}`}>
              <MediaList
                label="Reference audio"
                values={draft.ref_audios ?? []}
                options={catalog?.audios ?? []}
                limit={catalog?.reference_limits?.audios ?? 2}
                onChange={(values) => onChange({ ref_audios: values })}
              />
            </Row>
          ) : null}
        </div>
      </Section>

      <Section title="How to sample it" hint="The knobs that change the picture itself.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Row label="Sampler">
            <Choice
              value={draft.sampler ?? ""}
              options={catalog?.samplers ?? []}
              onChange={(value) => onChange({ sampler: value })}
              label="Sampler"
            />
          </Row>
          <Row label="Scheduler">
            <Choice
              value={draft.scheduler ?? ""}
              options={catalog?.schedulers ?? []}
              onChange={(value) => onChange({ scheduler: value })}
              label="Scheduler"
            />
          </Row>
          <Row label="Aspect">
            <Choice
              value={draft.aspect_ratio ?? ""}
              options={catalog?.aspect_ratios ?? []}
              onChange={(value) => onChange({ aspect_ratio: value })}
              label="Aspect ratio"
            />
          </Row>
          <Row
            label="Steps"
            hint={
              inert.has("steps")
                ? steps
                  ? `this LoRA samples at ${steps} steps`
                  : "the turbo LoRA sets the schedule"
                : undefined
            }
          >
            <NumberField
              // A turbo run samples at its LoRA's schedule, so that is the count to show while
              // the field is inert. `draft.steps` is left alone underneath: turning turbo off
              // has to give the number back, not the LoRA's.
              value={(inert.has("steps") ? steps : undefined) ?? draft.steps ?? 20}
              min={LIMITS.steps.min}
              max={LIMITS.steps.max}
              disabled={inert.has("steps")}
              label="Steps"
              onChange={(value) => onChange({ steps: value })}
            />
          </Row>
          <Row label="Seed" hint="same seed, same noise — hold it to compare fairly">
            <div className="flex gap-1.5">
              <NumberField
                value={draft.seed ?? 0}
                min={0}
                max={Number.MAX_SAFE_INTEGER}
                label="Seed"
                onChange={(value) => onChange({ seed: value })}
              />
              <Button
                variant="outline"
                size="icon"
                aria-label="New random seed"
                onClick={() => onChange({ seed: randomSeed() })}
              >
                <Dices className="size-3.5" />
              </Button>
            </div>
          </Row>
          <Row label="Megapixels" hint={`${(draft.mp ?? 0.5).toFixed(2)} MP`}>
            <Slider
              value={[draft.mp ?? 0.5]}
              min={LIMITS.mp.min}
              max={LIMITS.mp.max}
              step={LIMITS.mp.step}
              onValueChange={(value) =>
                onChange({ mp: Array.isArray(value) ? value[0] : (value as number) })
              }
            />
          </Row>
          <Row label="Duration" hint={`${(draft.duration_s ?? 5).toFixed(1)} s`}>
            <Slider
              value={[draft.duration_s ?? 5]}
              min={LIMITS.duration_s.min}
              max={LIMITS.duration_s.max}
              step={LIMITS.duration_s.step}
              onValueChange={(value) =>
                onChange({ duration_s: Array.isArray(value) ? value[0] : (value as number) })
              }
            />
          </Row>
        </div>
      </Section>

      <Section
        title="What to trade for speed"
        hint="Each of these buys time at some cost. Which cost is worth it is what the lab is for."
      >
        <div className="space-y-3">
          <Toggle
            label="Turbo"
            hint="A distilled LoRA samples in a handful of steps instead of twenty. Fast, and it changes the look — which is the thing worth measuring."
            checked={draft.turbo ?? false}
            onChange={(checked) =>
              onChange(checked ? { turbo: true } : { turbo: false, steps: normalSteps() })
            }
          />
          {draft.turbo ? (
            <div className="border-rule ml-5 space-y-3 border-l pl-4">
              <Row
                label="LoRA"
                hint={steps ? `${steps}-step schedule` : catalog?.turbo_loras_source}
              >
                <Choice
                  value={turboLora(draft, catalog)}
                  options={catalog?.turbo_loras ?? []}
                  render={loraStem}
                  onChange={(value) => onChange({ turbo_lora: value })}
                  label="Turbo LoRA"
                  placeholder="pick a LoRA"
                />
              </Row>
              <Row label="Strength" hint={`${(draft.turbo_lora_strength ?? 1).toFixed(2)} ×`}>
                <Slider
                  value={[draft.turbo_lora_strength ?? 1]}
                  min={LIMITS.turbo_lora_strength.min}
                  max={LIMITS.turbo_lora_strength.max}
                  step={LIMITS.turbo_lora_strength.step}
                  aria-label="Turbo strength"
                  onValueChange={(value) =>
                    onChange({
                      turbo_lora_strength: Array.isArray(value) ? value[0] : (value as number),
                    })
                  }
                />
              </Row>
            </div>
          ) : null}
          <Toggle
            label="Sol-Attn"
            hint="Sparse attention. Usually free speed; sometimes softens motion."
            checked={draft.sol_attn ?? false}
            onChange={(checked) => onChange({ sol_attn: checked })}
          />
          {draft.sol_attn ? (
            <Row label="Sol-Attn strength">
              <Levels
                value={draft.sol_preset ?? "moderate"}
                levels={meta?.preset_levels ?? []}
                onChange={(value) => onChange({ sol_preset: value as Draft["sol_preset"] })}
              />
            </Row>
          ) : null}

          <Row label="Cache" hint="Reuses sampler work between steps.">
            <Levels
              value={draft.cache ?? "none"}
              levels={meta?.caches ?? []}
              onChange={(value) =>
                onChange({ cache: value as Draft["cache"], cache_enabled: value !== "none" })
              }
            />
          </Row>
          {!inert.has("cache_preset") ? (
            <Row label="Cache strength">
              <Levels
                value={draft.cache_preset ?? "moderate"}
                levels={meta?.preset_levels ?? []}
                onChange={(value) => onChange({ cache_preset: value as Draft["cache_preset"] })}
              />
            </Row>
          ) : null}

          <Row label="Frame interpolation" hint="Post-processing. 24 → 48 → 60 fps.">
            <Levels
              value={draft.interp ?? "off"}
              levels={meta?.interpolations ?? []}
              render={(value) => meta?.interpolation_labels?.[value] ?? value}
              onChange={(value) => onChange({ interp: value as Draft["interp"] })}
            />
          </Row>
          <Toggle
            label="Upscaler"
            hint="Enlarges the result. Costs time at the end of every run."
            checked={draft.upscaler ?? false}
            onChange={(checked) => onChange({ upscaler: checked })}
          />
          <Toggle
            label="Clear VRAM first"
            hint="Slower and steadier. Use it when timings drift between runs."
            checked={draft.clean_vram ?? false}
            onChange={(checked) => onChange({ clean_vram: checked })}
          />
        </div>
      </Section>
    </div>
  )
}

// --- small controls ---------------------------------------------------------

function Row({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div className="min-w-0">
      <div className="mb-1.5 flex min-w-0 items-baseline justify-between gap-2">
        <Label className="text-muted-foreground shrink-0 text-xs whitespace-nowrap">{label}</Label>
        {hint ? (
          <span className="edge-code text-muted-foreground/70 min-w-0 truncate text-right">{hint}</span>
        ) : null}
      </div>
      {children}
    </div>
  )
}

export function Choice({
  value,
  options,
  onChange,
  render = (item: string) => item,
  placeholder = "choose",
  label,
  emptyLabel,
  size,
  className,
}: {
  value: string
  options: string[]
  onChange: (value: string) => void
  render?: (value: string) => string
  placeholder?: string
  /**
   * What the control is for. The visible `<Label>` beside a select is not associated with
   * it, so without this the trigger's only name is whatever it currently reads.
   */
  label?: string
  /** When set, an explicit "no file" entry is offered under this label. */
  emptyLabel?: string
  size?: "sm" | "default"
  className?: string
}) {
  // A value that came from a preset may not be in the current catalog. Keeping it in the list
  // means loading a preset never silently swaps a setting the user did not change.
  const present = value && !options.includes(value) ? [value, ...options] : options
  const items = [
    ...(emptyLabel ? [{ value: "", label: emptyLabel }] : []),
    ...present.filter(Boolean).map((option) => ({ value: option, label: render(option) })),
  ]

  return (
    <Select value={value} onValueChange={(next) => onChange(String(next ?? ""))} items={items}>
      <SelectTrigger
        size={size}
        aria-label={label ?? placeholder}
        className={cn("w-full min-w-0", className)}
      >
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {items.map((item) => (
          <SelectItem key={item.value || "__empty"} value={item.value}>
            {item.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

/**
 * The step count to come back to when turbo goes off.
 *
 * A turbo config stores the schedule its LoRA was distilled for, so a draft that arrives with
 * turbo already on — from a preset, a stored run, or last night's session — has no normal count
 * left in it. Handing the LoRA's four back is how a bench whose normal is twenty quietly starts
 * running at four, so the last count seen with turbo off is remembered, and the lab's own default
 * stands in when there has not been one.
 */
function useNormalSteps(draft: Draft, meta: Meta | undefined): () => number {
  const typed = useRef<number | undefined>(undefined)
  useEffect(() => {
    if (!draft.turbo && typeof draft.steps === "number") typed.current = draft.steps
  }, [draft.turbo, draft.steps])
  const fallback = (meta?.defaults as Draft | undefined)?.steps ?? 20
  return () => typed.current ?? fallback
}

function Levels({
  value,
  levels,
  onChange,
  render,
}: {
  value: string
  levels: string[]
  onChange: (value: string) => void
  /** For sets whose display names are not their values — `film` reads as "FILM Net". */
  render?: (value: string) => string
}) {
  return (
    <ToggleGroup
      value={[value]}
      onValueChange={(next) => {
        const picked = next[0]
        if (picked) onChange(picked)
      }}
      className="w-full"
    >
      {levels.map((level) => (
        <ToggleGroupItem
          key={level}
          value={level}
          className={cn("min-w-[4.5rem] flex-1 sm:min-w-[60px]", !render && "capitalize")}
        >
          {render ? render(level) : level}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}

function NumberField({
  value,
  min,
  max,
  disabled,
  label,
  onChange,
}: {
  value: number
  min: number
  max: number
  disabled?: boolean
  /** The visible `<Label>` beside the field is not associated with it, so name it here. */
  label: string
  onChange: (value: number) => void
}) {
  return (
    <Input
      type="number"
      inputMode="numeric"
      aria-label={label}
      value={String(value)}
      min={min}
      max={max}
      disabled={disabled}
      onChange={(event) => {
        const parsed = Number(event.target.value)
        if (Number.isFinite(parsed)) onChange(Math.min(max, Math.max(min, Math.trunc(parsed))))
      }}
      className={cn("tabular font-mono", disabled && "opacity-50")}
    />
  )
}

function Toggle({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string
  hint: string
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3">
      <Switch checked={checked} onCheckedChange={onChange} className="mt-0.5 shrink-0" />
      <span className="min-w-0">
        <span className="text-bone block text-sm">{label}</span>
        <span className="text-muted-foreground block text-xs">{hint}</span>
      </span>
    </label>
  )
}

/**
 * The picked file, shown. A frame is chosen by what it looks like, and 138 filenames in a
 * dropdown carry none of that — so the thumbnail is the control's real feedback and the
 * name below it is the caption, not the other way round.
 */
function Thumb({ name, className }: { name: string; className?: string }) {
  const [broken, setBroken] = useState(false)

  if (!name) return null
  if (broken) {
    return (
      <div
        data-testid="thumb-missing"
        className={cn(
          "border-crimson-dim/60 bg-panel/60 flex shrink-0 items-center justify-center border border-dashed",
          className
        )}
      >
        <span className="edge-code text-crimson px-1 text-center">not in input/</span>
      </div>
    )
  }

  return (
    <img
      src={routes.input(name)}
      alt=""
      title={name}
      loading="lazy"
      decoding="async"
      onError={() => setBroken(true)}
      data-testid="thumb"
      data-name={name}
      className={cn("border-rule bg-ink shrink-0 border object-cover", className)}
    />
  )
}

function MediaPick({
  label,
  value,
  options,
  onChange,
  allowEmpty = false,
}: {
  label: string
  value: string
  options: string[]
  onChange: (value: string) => void
  allowEmpty?: boolean
}) {
  return (
    <div className="min-w-0 space-y-1.5">
      <div className="flex min-w-0 gap-1.5">
        <Choice
          value={value}
          options={options}
          onChange={onChange}
          label={label}
          placeholder="pick a file"
          emptyLabel={allowEmpty ? "none" : undefined}
        />
        <UploadButton onDone={onChange} />
      </div>
      <Thumb name={value} className="aspect-video h-24 max-w-full w-auto" />
    </div>
  )
}

function MediaList({
  label,
  values,
  options,
  limit,
  onChange,
  previews = false,
}: {
  label: string
  values: string[]
  options: string[]
  limit: number
  onChange: (values: string[]) => void
  /** Only images can be shown as one; a video or an audio file has nothing to draw. */
  previews?: boolean
}) {
  const room = Math.max(0, limit - values.length)

  return (
    <div className="min-w-0 space-y-1.5">
      {values.map((value, index) => (
        <div key={`${value}-${index}`} className="flex min-w-0 items-center gap-1.5">
          {previews ? <Thumb name={value} className="h-11 w-[4.9rem] shrink-0" /> : null}
          <div className="min-w-0 flex-1">
            <Choice
              value={value}
              options={options}
              onChange={(next) => onChange(values.map((item, at) => (at === index ? next : item)))}
              label={`${label} ${index + 1}`}
            />
          </div>
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Remove ${value}`}
            onClick={() => onChange(values.filter((_, at) => at !== index))}
            className="shrink-0"
          >
            <X className="size-3.5" />
          </Button>
        </div>
      ))}
      {room > 0 ? (
        <div className="flex min-w-0 gap-1.5">
          <Choice
            value=""
            options={options.filter((option) => !values.includes(option))}
            onChange={(next) => next && onChange([...values, next])}
            label={`Add to ${label.toLowerCase()}`}
            placeholder={`add a file — ${room} slot${room === 1 ? "" : "s"} left`}
          />
          <UploadButton onDone={(name) => onChange([...values, name].slice(0, limit))} />
        </div>
      ) : null}
    </div>
  )
}

function UploadButton({ onDone }: { onDone: (name: string) => void }) {
  const upload = useUpload()
  // A real button driving a hidden input, rather than a label styled as one: a label is not a
  // button, and dressing it up as one costs the keyboard and screen-reader behaviour.
  const picker = useRef<HTMLInputElement>(null)

  return (
    <>
      <Button
        variant="outline"
        size="icon"
        disabled={upload.isPending}
        aria-label="Upload a file to ComfyUI's input folder"
        onClick={() => picker.current?.click()}
      >
        <Upload className="size-3.5" />
      </Button>
      <input
        ref={picker}
        type="file"
        tabIndex={-1}
        className="sr-only"
        onChange={async (event) => {
          const input = event.target
          const file = input.files?.[0]
          if (!file) return
          try {
            onDone((await upload.mutateAsync(file)).name)
          } catch {
            // The mutation already reported it; this only keeps the rejection from escaping.
          } finally {
            input.value = ""
          }
        }}
      />
    </>
  )
}
