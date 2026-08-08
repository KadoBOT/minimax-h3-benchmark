/**
 * The Lab page: describe a run, check it, queue it — or sweep a whole matrix.
 *
 * The draft config is the page's only state. Everything else on screen is a reading of it:
 * what is missing, what it hashes to, whether it has been run before.
 */

import { useEffect, useMemo, useState } from "react"
import { AlertTriangle, CheckCircle2, Play, Save, Trash2 } from "lucide-react"
import { Link } from "react-router"

import { useCatalog, useDeletePreset, useDryRun, useEnqueue, useMeta, usePresets, useSavePreset } from "@/api/hooks"
import type { GenerationConfig } from "@/api/schema"
import { Failure, PageHeader, Section, Spinner, Stat } from "@/components/page"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { changedFields, display, label as fieldLabel, missingInputs, type Draft } from "@/lib/config"
import { plural, shortHash } from "@/lib/format"
import { ConfigForm } from "./config-form"
import { QueuePanel } from "./queue-panel"
import { SweepBuilder } from "./sweep-builder"

const DRAFT_KEY = "h3lab.draft"

export function LabPage() {
  const meta = useMeta()
  const catalog = useCatalog()
  const presets = usePresets()
  const enqueue = useEnqueue()
  const dryRun = useDryRun()
  const savePreset = useSavePreset()
  const deletePreset = useDeletePreset()

  const [draft, setDraft] = useState<Draft | null>(null)
  const [count, setCount] = useState(1)
  const [presetName, setPresetName] = useState("")

  // Three layers, weakest first. `meta` gives the full shape, so the form can never offer
  // something the validators would reject. `catalog` narrows it to this machine — the model
  // and media it actually has — which is what makes a fresh draft queueable instead of a
  // list of blanks. A previous session's draft wins over both.
  //
  // The catalog is waited for rather than filled in later: patching a draft the user may
  // already be editing is how a setting changes under someone's hands.
  useEffect(() => {
    if (draft || !meta.data || catalog.isLoading) return
    let stored: Draft | null = null
    try {
      const raw = window.localStorage.getItem(DRAFT_KEY)
      stored = raw ? (JSON.parse(raw) as Draft) : null
    } catch {
      stored = null
    }
    setDraft({
      ...(meta.data.defaults as Draft),
      ...((catalog.data?.defaults ?? {}) as Partial<Draft>),
      ...(stored ?? {}),
    })
  }, [meta.data, catalog.data, catalog.isLoading, draft])

  useEffect(() => {
    if (!draft) return
    try {
      window.localStorage.setItem(DRAFT_KEY, JSON.stringify(draft))
    } catch {
      // Storage being unavailable is not worth interrupting anyone over.
    }
  }, [draft])

  const patch = (change: Partial<Draft>) => setDraft((current) => ({ ...(current as Draft), ...change }))

  const missing = useMemo(() => missingInputs(draft ?? {}, meta.data), [draft, meta.data])
  const check = dryRun.data
  const ready = draft !== null && missing.length === 0

  if (meta.isError) return <Failure error={meta.error} what="load the lab's vocabulary" onRetry={() => meta.refetch()} />
  if (!draft || !meta.data) return <Spinner label="Reading the lab" />

  const model = catalog.data?.default_diffusion_model
  const config: GenerationConfig = {
    ...draft,
    diffusion_model: draft.diffusion_model || model || "",
  }

  return (
    <>
      <PageHeader
        eyebrow="Bench"
        title="Set up a run"
        lede="One config, or a matrix of them. Check it first if you are unsure — a dry run builds the graph without spending a minute of GPU time."
      >
        <Button
          variant="outline"
          size="sm"
          disabled={!ready || dryRun.isPending}
          onClick={() => dryRun.mutate(config)}
        >
          Check
        </Button>
        <Button
          size="sm"
          disabled={!ready || enqueue.isPending}
          onClick={() => enqueue.mutate({ config, count })}
        >
          <Play data-icon="inline-start" className="size-3.5" />
          Queue {count > 1 ? plural(count, "run") : "run"}
        </Button>
      </PageHeader>

      {catalog.data && !catalog.data.comfy_online ? (
        <div className="border-signal/40 bg-signal/5 mb-4 flex items-start gap-3 rounded-lg border p-3">
          <AlertTriangle className="text-signal mt-0.5 size-4 shrink-0" />
          <div className="text-sm">
            <div className="text-bone">ComfyUI is not answering at {catalog.data.comfy_url}</div>
            <p className="text-muted-foreground mt-0.5">
              The lists below are the last known ones. You can still queue runs — they will wait
              and fail with a readable error until ComfyUI is up.
            </p>
          </div>
        </div>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-4">
          <ConfigForm draft={draft} onChange={patch} meta={meta.data} catalog={catalog.data} />
          <SweepBuilder
            base={config}
            meta={meta.data}
            missing={missing}
            catalog={{
              samplers: catalog.data?.samplers ?? [],
              schedulers: catalog.data?.schedulers ?? [],
              aspect_ratios: catalog.data?.aspect_ratios ?? [],
              diffusion_models: catalog.data?.diffusion_models ?? [],
            }}
          />
        </div>

        <div className="space-y-4">
          <QueuePanel />

          <Section title="This config" hint="Identity is what makes two runs comparable.">
            <div className="flex flex-wrap gap-5">
              <Stat
                label="Config hash"
                value={<span className="font-mono text-sm">{shortHash(check?.config_hash, 8)}</span>}
                hint="Every setting that affects the picture, including the seed"
              />
              <Stat
                label="Recipe hash"
                value={<span className="font-mono text-sm">{shortHash(check?.recipe_hash, 8)}</span>}
                hint="The same, minus the seed — replicates share it"
              />
            </div>

            {missing.length > 0 ? (
              <p className="text-signal mt-3 text-sm">
                Still needs {missing.join(" and ")}.
              </p>
            ) : null}

            {check ? (
              <div className="mt-3 space-y-2 text-sm">
                {check.ok ? (
                  <p className="text-mint flex items-center gap-2">
                    <CheckCircle2 className="size-4 shrink-0" />
                    Builds cleanly — {check.graph?.nodes ?? 0} nodes, no dangling links.
                  </p>
                ) : (
                  <ul className="text-crimson space-y-1">
                    {check.problems?.map((problem) => (
                      <li key={problem} className="flex items-start gap-2">
                        <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
                        {problem}
                      </li>
                    ))}
                  </ul>
                )}
                {check.duplicate_of ? (
                  <p className="text-muted-foreground">
                    You have run exactly this before —{" "}
                    <Link to={`/runs/${check.duplicate_of}`} className="text-signal hover:underline">
                      open that run
                    </Link>{" "}
                    or queue it again to check the timing was not a fluke.
                  </p>
                ) : null}
              </div>
            ) : null}

            <div className="border-rule mt-4 flex items-center gap-2 border-t pt-3">
              <span className="text-muted-foreground text-xs">Queue</span>
              <Input
                type="number"
                min={1}
                max={16}
                value={String(count)}
                onChange={(event) => {
                  const parsed = Number(event.target.value)
                  if (Number.isFinite(parsed)) setCount(Math.min(16, Math.max(1, Math.trunc(parsed))))
                }}
                className="tabular w-16 font-mono"
              />
              <span className="text-muted-foreground text-xs">
                {count === 1 ? "copy" : "copies of this exact config"}
              </span>
            </div>
          </Section>

          <Section
            title="Presets"
            hint="A config worth keeping. Saved presets carry every field, seed included."
          >
            <div className="flex gap-1.5">
              <Input
                value={presetName}
                onChange={(event) => setPresetName(event.target.value)}
                placeholder="name this config"
                className="flex-1"
              />
              <Button
                variant="outline"
                size="icon"
                aria-label="Save this config as a preset"
                disabled={!presetName.trim() || savePreset.isPending}
                onClick={() =>
                  savePreset.mutate(
                    { name: presetName.trim(), config },
                    { onSuccess: () => setPresetName("") }
                  )
                }
              >
                <Save className="size-3.5" />
              </Button>
            </div>

            {presets.data && presets.data.length > 0 ? (
              <ul className="divide-rule/60 mt-3 divide-y">
                {presets.data.map((preset) => {
                  const changes = changedFields(preset.config as Draft, draft)
                  return (
                    <li key={preset.id} className="flex items-center gap-2 py-2">
                      <button
                        onClick={() => setDraft({ ...(preset.config as Draft) })}
                        className="min-w-0 flex-1 text-left"
                      >
                        <span className="text-bone block truncate text-sm">{preset.name}</span>
                        <span className="edge-code text-muted-foreground block truncate">
                          {changes.length === 0
                            ? "same as the current draft"
                            : changes
                                .slice(0, 3)
                                .map(
                                  (field) =>
                                    `${fieldLabel(meta.data, field)} ${display(
                                      preset.config[field as keyof GenerationConfig]
                                    )}`
                                )
                                .join(" · ")}
                        </span>
                      </button>
                      <Button
                        variant="ghost"
                        size="icon-xs"
                        aria-label={`Delete ${preset.name}`}
                        onClick={() => deletePreset.mutate(preset.id)}
                      >
                        <Trash2 className="size-3" />
                      </Button>
                    </li>
                  )
                })}
              </ul>
            ) : (
              <p className="text-muted-foreground mt-3 text-xs">
                Nothing saved yet. Presets are how a config you liked survives the night.
              </p>
            )}
          </Section>
        </div>
      </div>
    </>
  )
}
