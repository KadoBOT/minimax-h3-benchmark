import { useEffect, useRef, useState } from "react"

import { api } from "@/api/client"
import { useStudioSession } from "@/api/hooks"
import { routes } from "@/api/routes"
import type { Upload } from "@/api/schema"
import type { Draft } from "@/lib/config"
import {
  loadStudioRuntime,
  projectStudioInputs,
  studioInputsFromDraft,
  type StudioController,
} from "@/lib/studio-runtime"
import "./studio-host.css"

type StudioHostProps = {
  draft: Draft
  onChange: (patch: Partial<Draft>) => void
}

export function StudioHost({ draft, onChange }: StudioHostProps) {
  const session = useStudioSession(draft.mode)
  const containerRef = useRef<HTMLDivElement>(null)
  const controllerRef = useRef<StudioController | null>(null)
  const draftRef = useRef(draft)
  const onChangeRef = useRef(onChange)
  const [runtimeError, setRuntimeError] = useState<Error | null>(null)

  useEffect(() => {
    draftRef.current = draft
    onChangeRef.current = onChange
  }, [draft, onChange])

  useEffect(() => {
    const source = session.data
    const container = containerRef.current
    if (!source || !container) return

    let cancelled = false
    let mounted: StudioController | null = null
    setRuntimeError(null)
    void loadStudioRuntime(source)
      .then((runtime) =>
        runtime.mountMiniMaxH3Studio(container, {
          manifest: source,
          workflow: source.workflow,
          inputs: studioInputsFromDraft(source, draftRef.current),
          onChange: (inputs) => {
            onChangeRef.current(projectStudioInputs(inputs, source.bindings, draftRef.current))
          },
          uploadFile,
          mediaUrl: (filename) => routes.input(filename),
        })
      )
      .then((controller) => {
        if (cancelled) {
          controller.destroy()
          return
        }
        mounted = controller
        controllerRef.current = controller
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setRuntimeError(error instanceof Error ? error : new Error(String(error)))
        }
      })

    return () => {
      cancelled = true
      if (controllerRef.current === mounted) controllerRef.current = null
      mounted?.destroy()
      container.replaceChildren()
    }
  }, [session.data])

  useEffect(() => {
    if (!session.data || !controllerRef.current) return
    controllerRef.current.setInputs(studioInputsFromDraft(session.data, draft), false)
  }, [draft, session.data])

  const error = runtimeError ?? (session.error instanceof Error ? session.error : null)
  return (
    <div className="studio-runtime-frame">
      <div ref={containerRef} className="studio-runtime-host" data-testid="studio-runtime" />
      {!session.data && !error ? (
        <p className="studio-runtime-message" role="status">
          Loading Studio…
        </p>
      ) : null}
      {error ? (
        <div className="studio-runtime-error" role="alert">
          <strong>Studio could not load.</strong>
          <span>{error.message}</span>
        </div>
      ) : null}
    </div>
  )
}

async function uploadFile(file: File): Promise<string> {
  const form = new FormData()
  form.append("file", file)
  const uploaded = await api.post<Upload>(routes.uploads(), form)
  return uploaded.name
}
