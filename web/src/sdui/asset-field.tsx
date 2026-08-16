import { useEffect, useMemo, useRef, useState } from "react"
import { FileUp, X } from "lucide-react"

import type { AssetComponent, PublicMediaMetadata } from "@/api/schema"
import { routes } from "@/api/routes"
import { Button } from "@/components/ui/button"

import { isSafeApiPath, parsePublicMediaMetadata } from "./contracts"
import { uploadSharedAsset, type AssetUploader } from "./asset-upload"

export type { AssetUploader } from "./asset-upload"

type Entry = {
  key: string
  filename: string
  progress: number
  controller: AbortController
  metadata?: PublicMediaMetadata
  error?: string
}

export function AssetField({
  component,
  ids,
  onChange,
  onUploadingChange,
  upload = uploadSharedAsset,
}: {
  component: AssetComponent
  ids: string[]
  onChange: (ids: string[]) => void
  onUploadingChange?: (uploading: boolean) => void
  upload?: AssetUploader
}) {
  const [entries, setEntries] = useState<Entry[]>([])
  const accepted = useRef([...ids])
  const controllers = useRef(new Set<AbortController>())
  const pending = entries.filter(
    (entry) => !entry.metadata && !entry.error
  ).length
  const acceptedCount = new Set([
    ...ids,
    ...entries.flatMap((entry) => (entry.metadata ? [entry.metadata.id] : [])),
  ]).size
  const room = Math.max(0, component.maximumItems - acceptedCount - pending)

  useEffect(() => {
    accepted.current = [...ids]
  }, [ids])

  useEffect(() => {
    onUploadingChange?.(pending > 0)
  }, [onUploadingChange, pending])

  useEffect(
    () => () => {
      for (const controller of controllers.current) controller.abort()
    },
    []
  )

  const existing = useMemo(
    () =>
      ids
        .filter((id) => !entries.some((entry) => entry.metadata?.id === id))
        .map((id) => ({
          id,
          filename: id,
          mediaKind: component.accept[0] ?? "image",
          contentUrl: routes.sharedAssetContent(id),
        })),
    [component.accept, entries, ids]
  )

  const addFiles = (files: FileList | null) => {
    if (!files || room === 0) return
    const selected = Array.from(files).slice(0, room)
    for (const file of selected) {
      const family = mediaFamily(file.type)
      if (!family || !component.accept.includes(family)) {
        const controller = new AbortController()
        setEntries((current) => [
          ...current,
          {
            key: localKey(),
            filename: file.name,
            progress: 0,
            controller,
            error: `The document does not accept ${file.type || "this file type"}.`,
          },
        ])
        continue
      }
      const controller = new AbortController()
      controllers.current.add(controller)
      const key = localKey()
      setEntries((current) => [
        ...current,
        { key, filename: file.name, progress: 0, controller },
      ])
      void upload(file, controller.signal, (progress) => {
        setEntries((current) =>
          current.map((entry) =>
            entry.key === key
              ? { ...entry, progress: clampProgress(progress) }
              : entry
          )
        )
      })
        .then((result) => {
          const metadata = parsePublicMediaMetadata(result)
          if (
            metadata.kind !== "asset" ||
            !component.accept.includes(metadata.mediaKind) ||
            !isSafeApiPath(metadata.contentUrl) ||
            metadata.contentUrl !== routes.sharedAssetContent(metadata.id)
          ) {
            throw new Error(
              "The upload returned unsafe or incompatible asset metadata."
            )
          }
          const next = [...new Set([...accepted.current, metadata.id])]
          accepted.current = next
          setEntries((current) =>
            current.map((entry) =>
              entry.key === key ? { ...entry, progress: 100, metadata } : entry
            )
          )
          onChange(next)
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return
          setEntries((current) =>
            current.map((entry) =>
              entry.key === key
                ? {
                    ...entry,
                    error:
                      error instanceof Error ? error.message : String(error),
                  }
                : entry
            )
          )
        })
        .finally(() => controllers.current.delete(controller))
    }
  }

  const remove = (entry: Entry) => {
    entry.controller.abort()
    controllers.current.delete(entry.controller)
    setEntries((current) =>
      current.filter((candidate) => candidate.key !== entry.key)
    )
    if (entry.metadata) {
      const next = accepted.current.filter((id) => id !== entry.metadata?.id)
      accepted.current = next
      onChange(next)
    }
  }

  const removeExisting = (id: string) => {
    const next = accepted.current.filter((candidate) => candidate !== id)
    accepted.current = next
    onChange(next)
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <label className="inline-flex h-8 cursor-pointer items-center gap-2 rounded-md border border-input bg-input/30 px-3 text-xs hover:bg-input/50">
          <FileUp aria-hidden="true" className="size-3.5" />
          Add media
          <input
            type="file"
            className="sr-only"
            aria-label={`Upload ${component.label}`}
            accept={component.accept.map((kind) => `${kind}/*`).join(",")}
            multiple={component.maximumItems > 1}
            disabled={room === 0}
            onChange={(event) => {
              addFiles(event.target.files)
              event.target.value = ""
            }}
          />
        </label>
        <span className="text-xs text-muted-foreground">
          {acceptedCount} of {component.maximumItems} assets
        </span>
      </div>

      {[...entries].map((entry) => (
        <article
          key={entry.key}
          className="rounded border border-rule bg-ink/40 p-2"
        >
          <div className="flex items-center gap-2">
            {entry.metadata ? <AssetPreview metadata={entry.metadata} /> : null}
            <span className="min-w-0 flex-1 truncate text-xs text-bone">
              {entry.filename}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              aria-label={`Remove ${entry.filename}`}
              onClick={() => remove(entry)}
            >
              <X aria-hidden="true" className="size-3" />
            </Button>
          </div>
          {!entry.metadata && !entry.error ? (
            <progress
              aria-label={`Uploading ${entry.filename}`}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={entry.progress}
              value={entry.progress}
              max={100}
              className="mt-2 h-1.5 w-full"
            />
          ) : null}
          {entry.error ? (
            <p role="alert" className="mt-1 text-xs text-crimson">
              {entry.error}
            </p>
          ) : null}
        </article>
      ))}

      {existing.map((entry) => (
        <article
          key={entry.id}
          className="flex items-center gap-2 rounded border border-rule p-2"
        >
          <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground">
            {entry.filename}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            aria-label={`Remove ${entry.filename}`}
            onClick={() => removeExisting(entry.id)}
          >
            <X aria-hidden="true" className="size-3" />
          </Button>
        </article>
      ))}
    </div>
  )
}

function AssetPreview({ metadata }: { metadata: PublicMediaMetadata }) {
  if (metadata.mediaKind === "image") {
    return (
      <img
        src={metadata.contentUrl}
        alt={metadata.filename}
        className="h-10 w-16 rounded border border-rule object-cover"
      />
    )
  }
  if (metadata.mediaKind === "video") {
    return (
      <video
        src={metadata.contentUrl}
        aria-label={metadata.filename}
        className="h-10 w-16 rounded border border-rule object-cover"
        muted
      />
    )
  }
  return (
    <audio
      src={metadata.contentUrl}
      aria-label={metadata.filename}
      preload="metadata"
    />
  )
}

function mediaFamily(value: string): "image" | "video" | "audio" | null {
  const family = value.split("/", 1)[0]
  return family === "image" || family === "video" || family === "audio"
    ? family
    : null
}

function clampProgress(value: number): number {
  return Math.min(100, Math.max(0, Number.isFinite(value) ? value : 0))
}

function localKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`
}
