import type { Catalog, Meta } from "@/api/schema"
import { Choice } from "@/components/choice"
import { Section } from "@/components/page"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { attentionMode, type Draft } from "@/lib/config"
import { modelStem } from "@/lib/format"
import { LIMITS } from "@/lib/limits"

const CACHE_FAMILIES = ["spectrum", "easy", "h3"] as const

export function BenchmarkControls({
  draft,
  meta,
  catalog,
  onChange,
}: {
  draft: Draft
  meta: Meta | undefined
  catalog: Catalog | undefined
  onChange: (patch: Partial<Draft>) => void
}) {
  const cacheEnabled = draft.cache_enabled ?? draft.cache !== "none"
  const cacheFamily =
    draft.cache && draft.cache !== "none" ? draft.cache : CACHE_FAMILIES[0]
  const presetLevels = meta?.preset_levels ?? []

  return (
    <Section
      title="Benchmark tuning"
      hint="Lab-owned settings stay comparable even when Studio's controls evolve."
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Weights" hint={catalog?.diffusion_models_source}>
          <Choice
            value={draft.diffusion_model || catalog?.default_diffusion_model || ""}
            options={catalog?.diffusion_models ?? []}
            render={modelStem}
            onChange={(value) => onChange({ diffusion_model: value })}
            label="Weights"
            placeholder="pick a checkpoint"
          />
        </Field>

        {cacheEnabled ? (
          <>
            <Field label="Cache family">
              <Choice
                value={cacheFamily}
                options={[...CACHE_FAMILIES]}
                onChange={(value) =>
                  onChange({
                    cache: value as Draft["cache"],
                    cache_enabled: true,
                  })
                }
                label="Cache family"
              />
            </Field>
            <Field label="Cache preset">
              <Choice
                value={draft.cache_preset ?? "moderate"}
                options={presetLevels}
                onChange={(value) =>
                  onChange({ cache_preset: value as Draft["cache_preset"] })
                }
                label="Cache preset"
              />
            </Field>
          </>
        ) : (
          <p className="text-muted-foreground self-end text-xs">
            Enable cache in Studio to choose its family and preset.
          </p>
        )}

        {attentionMode(draft) === "sol" ? (
          <Field label="Sol attention preset">
            <Choice
              value={draft.sol_preset ?? "moderate"}
              options={presetLevels}
              onChange={(value) =>
                onChange({ sol_preset: value as Draft["sol_preset"] })
              }
              label="Sol attention preset"
            />
          </Field>
        ) : null}

        {draft.turbo ? (
          <Field label="Turbo strength" hint={`${draft.turbo_lora_strength ?? 1}×`}>
            <Input
              type="number"
              inputMode="decimal"
              aria-label="Turbo strength"
              min={LIMITS.turbo_lora_strength.min}
              max={LIMITS.turbo_lora_strength.max}
              step={LIMITS.turbo_lora_strength.step}
              value={String(draft.turbo_lora_strength ?? 1)}
              onChange={(event) => {
                const value = Number(event.target.value)
                if (!Number.isFinite(value)) return
                onChange({
                  turbo_lora_strength: Math.min(
                    LIMITS.turbo_lora_strength.max,
                    Math.max(LIMITS.turbo_lora_strength.min, value)
                  ),
                })
              }}
              className="tabular font-mono"
            />
          </Field>
        ) : null}
      </div>
    </Section>
  )
}

function Field({
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
        <Label className="text-muted-foreground shrink-0 text-xs whitespace-nowrap">
          {label}
        </Label>
        {hint ? (
          <span className="edge-code text-muted-foreground/70 min-w-0 truncate text-right">
            {hint}
          </span>
        ) : null}
      </div>
      {children}
    </div>
  )
}
