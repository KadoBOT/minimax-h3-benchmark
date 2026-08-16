import { useCallback, useEffect, useRef, useState } from "react"
import { BookmarkPlus, RefreshCw, Trash2 } from "lucide-react"

import type { GenerationDocument, JobSubmission } from "@/api/schema"
import { ApiError } from "@/api/client"
import {
  useEnqueueShared,
  useRunSweep,
  useSharedGeneration,
  useSweepPreview,
} from "@/api/hooks"
import { PageHeader, Section, Spinner } from "@/components/page"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  applyPreset,
  deletePreset,
  listPresets,
  loadDraft,
  saveDraft,
  savePreset,
  type SduiPreset,
} from "@/sdui/authoring"
import { AssetField } from "@/sdui/asset-field"
import { DocumentError } from "@/sdui/document-error"
import { initialValues, type FormValues } from "@/sdui/form-state"
import { SduiGenerationForm } from "@/sdui/generation-form"
import { SduiSweepBuilder } from "@/sdui/sweep-builder"
import { SduiContractError } from "@/sdui/contracts"

import { QueuePanel } from "./queue-panel"

type Draft = {
  document: GenerationDocument
  values: FormValues
  diagnostics: string[]
}

export function SharedLabPage() {
  const generation = useSharedGeneration()
  const parsed = generation.data

  if (generation.isPending) {
    return (
      <>
        <PageHeader
          eyebrow="Generation"
          title="Lab"
          lede="Loading the shared workflow contract."
        />
        <Spinner label="Loading generation controls" />
      </>
    )
  }

  if (generation.error || !parsed) {
    return (
      <>
        <PageHeader eyebrow="Generation" title="Lab" />
        <DocumentError
          title="The generation document could not be used"
          detail={errorDetail(generation.error)}
          issues={errorIssues(generation.error)}
          retrying={generation.isFetching}
          onRetry={() => void generation.refetch()}
        />
      </>
    )
  }

  return (
    <SharedLabDocument
      key={`${parsed.document.schemaRevision}:${parsed.document.workflowRevision}`}
      parsed={parsed}
      generation={generation}
    />
  )
}

function SharedLabDocument({
  parsed,
  generation,
}: {
  parsed: NonNullable<ReturnType<typeof useSharedGeneration>["data"]>
  generation: ReturnType<typeof useSharedGeneration>
}) {
  const enqueue = useEnqueueShared()
  const sweepPreview = useSweepPreview()
  const runSweep = useRunSweep()
  const [draft, setDraft] = useState<Draft>(() => {
    const merged = safeLoadDraft(parsed.document)
    return {
      document: parsed.document,
      values: merged.values,
      diagnostics: [...parsed.diagnostics, ...merged.diagnostics],
    }
  })
  const [count, setCount] = useState(1)
  const [uploads, setUploads] = useState<Record<string, boolean>>({})
  const [presetName, setPresetName] = useState("")
  const [presets, setPresets] = useState<SduiPreset[]>(() => safeListPresets())
  const [selectedPreset, setSelectedPreset] = useState("")
  const queueFocus = useRef<HTMLDivElement>(null)

  useEffect(() => {
    try {
      saveDraft(draft.document, draft.values)
    } catch {
      // Private browsing and constrained embeds can reject local storage. Authoring still works.
    }
  }, [draft])

  const uploading = Object.values(uploads).some(Boolean)
  const setUploading = useCallback((binding: string, active: boolean) => {
    setUploads((current) =>
      current[binding] === active ? current : { ...current, [binding]: active }
    )
  }, [])
  const renderAsset = useCallback(
    (
      component: Extract<
        GenerationDocument["components"][number],
        { kind: "asset" }
      >,
      ids: string[],
      onChange: (next: string[]) => void
    ) => (
      <AssetField
        component={component}
        ids={ids}
        onChange={onChange}
        onUploadingChange={(active) => setUploading(component.binding, active)}
      />
    ),
    [setUploading]
  )

  const externalErrors =
    enqueue.error instanceof ApiError
      ? enqueue.error.fields
      : ({} as Record<string, string>)

  const submit = async (submission: JobSubmission) => {
    try {
      await enqueue.mutateAsync({ submission, count })
      queueFocus.current?.focus()
    } catch {
      // Mutation state feeds structured field and document errors back into the form.
    }
  }

  const refreshPresets = () => setPresets(safeListPresets())

  return (
    <>
      <PageHeader
        eyebrow={draft.document.workflowId}
        title={draft.document.title}
        lede={
          draft.document.description ?? "Compose and queue a benchmark run."
        }
      >
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void generation.refetch()}
        >
          <RefreshCw aria-hidden="true" className="size-3.5" />
          Refresh contract
        </Button>
      </PageHeader>

      <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(20rem,0.8fr)]">
        <div className="min-w-0 space-y-4">
          <Section
            title="Generation"
            hint={`Schema ${draft.document.schemaRevision} · workflow ${draft.document.workflowRevision.slice(0, 18)}`}
          >
            <SduiGenerationForm
              document={draft.document}
              values={draft.values}
              onChange={(values) =>
                setDraft((current) =>
                  current ? { ...current, values } : current
                )
              }
              onSubmit={submit}
              uploading={uploading || enqueue.isPending}
              diagnostics={draft.diagnostics}
              externalErrors={externalErrors}
              renderAsset={renderAsset}
            />
          </Section>

          <Section
            title="Sweep"
            hint="Expand visible numeric, select, or toggle fields without encoding workflow rules in this client."
          >
            <SduiSweepBuilder
              document={draft.document}
              values={draft.values}
              disabled={
                uploading ||
                enqueue.isPending ||
                sweepPreview.isPending ||
                runSweep.isPending
              }
              onPreview={(request) => sweepPreview.mutateAsync(request)}
              onRun={async (request) => {
                await runSweep.mutateAsync(request)
                queueFocus.current?.focus()
              }}
            />
          </Section>
        </div>

        <div className="min-w-0 space-y-4">
          <Section
            title="Authoring"
            hint="Drafts and presets keep the pinned raw binding map."
          >
            <label className="grid gap-1 text-xs text-muted-foreground">
              Copies
              <Input
                aria-label="Run copies"
                type="number"
                min={1}
                max={16}
                value={count}
                onChange={(event) =>
                  setCount(
                    Math.max(
                      0,
                      Math.min(16, Math.trunc(Number(event.target.value) || 0))
                    )
                  )
                }
              />
            </label>

            <div className="mt-3 grid grid-cols-[1fr_auto] gap-2">
              <Input
                aria-label="New preset name"
                value={presetName}
                maxLength={120}
                placeholder="Preset name"
                onChange={(event) => setPresetName(event.target.value)}
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!presetName.trim()}
                onClick={() => {
                  try {
                    const preset = savePreset(
                      presetName,
                      draft.document,
                      draft.values
                    )
                    setPresetName("")
                    setSelectedPreset(preset.id)
                    refreshPresets()
                  } catch {
                    // Validation keeps the action disabled for the expected user-facing case.
                  }
                }}
              >
                <BookmarkPlus aria-hidden="true" className="size-3.5" />
                Save
              </Button>
            </div>

            <div className="mt-2 grid grid-cols-[1fr_auto_auto] gap-2">
              <select
                aria-label="Saved preset"
                className="h-8 min-w-0 rounded-md border border-input bg-input/30 px-2 text-xs"
                value={selectedPreset}
                onChange={(event) => setSelectedPreset(event.target.value)}
              >
                <option value="">Choose preset</option>
                {presets.map((preset) => (
                  <option key={preset.id} value={preset.id}>
                    {preset.name}
                  </option>
                ))}
              </select>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!selectedPreset}
                onClick={() => {
                  const preset = presets.find(
                    (candidate) => candidate.id === selectedPreset
                  )
                  if (!preset) return
                  const merged = applyPreset(preset, draft.document)
                  setDraft((current) =>
                    current
                      ? {
                          ...current,
                          values: merged.values,
                          diagnostics: [
                            ...current.diagnostics,
                            ...merged.diagnostics,
                          ],
                        }
                      : current
                  )
                }}
              >
                Apply
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label="Delete selected preset"
                disabled={!selectedPreset}
                onClick={() => {
                  deletePreset(selectedPreset)
                  setSelectedPreset("")
                  refreshPresets()
                }}
              >
                <Trash2 aria-hidden="true" className="size-3.5" />
              </Button>
            </div>
          </Section>

          <div ref={queueFocus} tabIndex={-1}>
            <QueuePanel />
          </div>
        </div>
      </div>
    </>
  )
}

function safeLoadDraft(document: GenerationDocument) {
  try {
    return loadDraft(document)
  } catch {
    return {
      values: initialValues(document),
      diagnostics: [
        "The saved draft could not be read; document defaults were used.",
      ],
    }
  }
}

function safeListPresets(): SduiPreset[] {
  try {
    return listPresets()
  } catch {
    return []
  }
}

function errorDetail(error: unknown): string {
  return error instanceof ApiError
    ? error.detail
    : error instanceof Error
      ? error.message
      : "The shared generation document could not be loaded."
}

function errorIssues(error: unknown): readonly string[] {
  return error instanceof SduiContractError ? error.issues : []
}
