/**
 * The live spine: one Server-Sent Events connection for the whole app.
 *
 * Runs are worked by a background thread, so the page is told what changed rather than
 * polling for it. Each event invalidates only the keys it affects — a progress tick updates
 * the live readout without refetching fifty rows — and the last sequence number seen is
 * replayed on reconnect so a dropped socket cannot leave a stale page behind.
 */

import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react"
import { useQueryClient, type QueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

import { keys } from "./keys"
import { routes } from "./routes"
import type { Event as LabEvent } from "./schema"

export type Progress = {
  runId: string
  /** Sampler step, when the active node reports one. */
  step: number | null
  stepTotal: number | null
  secPerIt: number | null
  /** Human name of the node currently executing, e.g. "sampler". */
  node: string | null
}

type Stream = {
  /** Whether the browser currently holds the stream open. */
  live: boolean
  /** Sequence number of the last event applied, mirroring the server's cursor. */
  seq: number
  /** Progress of the run the worker is on, or null between runs. */
  progress: Progress | null
  /** The most recent event, for pages that want to react to one specific kind. */
  last: LabEvent | null
}

const StreamContext = createContext<Stream>({ live: false, seq: 0, progress: null, last: null })

const RETRY_MS = 2_000

export function EventStreamProvider({ children }: { children: React.ReactNode }) {
  const client = useQueryClient()
  const [live, setLive] = useState(false)
  const [seq, setSeq] = useState(0)
  const [progress, setProgress] = useState<Progress | null>(null)
  const [last, setLast] = useState<LabEvent | null>(null)

  // Held in a ref as well as state: the reconnect handler needs the newest value without
  // re-subscribing on every event, which would tear the stream down constantly.
  const cursor = useRef(0)

  useEffect(() => {
    let source: EventSource | null = null
    let retry: ReturnType<typeof setTimeout> | undefined
    let stopped = false

    const open = () => {
      if (stopped) return
      source = new EventSource(`${routes.events()}?after=${cursor.current}`)

      source.onopen = () => setLive(true)

      source.onmessage = (message) => {
        let event: LabEvent
        try {
          event = JSON.parse(message.data) as LabEvent
        } catch {
          return
        }
        if (typeof event.seq === "number" && event.seq > cursor.current) {
          cursor.current = event.seq
          setSeq(event.seq)
        }
        setLast(event)
        setProgress((current) => nextProgress(current, event))
        apply(client, event)
      }

      source.onerror = () => {
        setLive(false)
        source?.close()
        source = null
        // EventSource reconnects on its own, but not with the updated cursor, so drive it.
        retry = setTimeout(open, RETRY_MS)
      }
    }

    open()
    return () => {
      stopped = true
      if (retry) clearTimeout(retry)
      source?.close()
    }
  }, [client])

  const value = useMemo<Stream>(() => ({ live, seq, progress, last }), [live, seq, progress, last])
  return <StreamContext.Provider value={value}>{children}</StreamContext.Provider>
}

export function useStream(): Stream {
  return useContext(StreamContext)
}

function nextProgress(current: Progress | null, event: LabEvent): Progress | null {
  const data = (event.data ?? {}) as Record<string, unknown>
  if (event.kind === "run.progress" && event.run_id) {
    return {
      runId: event.run_id,
      step: number(data.step),
      stepTotal: number(data.step_total),
      // A rate is only published once one is trustworthy; keep the last known one meanwhile.
      secPerIt: number(data.sec_per_it) ?? (current?.runId === event.run_id ? current.secPerIt : null),
      node: text(data.node_label) ?? text(data.node),
    }
  }
  if (event.kind === "run.started" && event.run_id) {
    return { runId: event.run_id, step: null, stepTotal: null, secPerIt: null, node: null }
  }
  if (event.kind === "run.finished" && current?.runId === event.run_id) return null
  return current
}

function number(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

function text(value: unknown): string | null {
  return typeof value === "string" && value ? value : null
}

/**
 * Refresh exactly what an event invalidated.
 *
 * Progress is deliberately absent: it arrives many times a second and is rendered straight
 * from the stream, so invalidating a query for each tick would refetch the run list on every
 * sampler step.
 */
function apply(client: QueryClient, event: LabEvent) {
  const runId = event.run_id

  switch (event.kind) {
    case "run.progress":
      return

    case "run.created":
    case "run.deleted":
    case "queue.changed":
      void client.invalidateQueries({ queryKey: ["runs"] })
      void client.invalidateQueries({ queryKey: keys.queue })
      void client.invalidateQueries({ queryKey: keys.status })
      return

    case "run.started":
      void client.invalidateQueries({ queryKey: keys.queue })
      void client.invalidateQueries({ queryKey: keys.status })
      if (runId) void client.invalidateQueries({ queryKey: keys.run(runId) })
      return

    case "run.finished":
      // A finished run changes the score of every other run, so the derived views go too.
      void client.invalidateQueries({ queryKey: ["runs"] })
      void client.invalidateQueries({ queryKey: ["leaderboard"] })
      void client.invalidateQueries({ queryKey: ["insights"] })
      void client.invalidateQueries({ queryKey: ["recipes"] })
      void client.invalidateQueries({ queryKey: ["compare"] })
      void client.invalidateQueries({ queryKey: keys.queue })
      void client.invalidateQueries({ queryKey: keys.status })
      if (runId) void client.invalidateQueries({ queryKey: keys.run(runId) })
      return

    case "run.updated":
      void client.invalidateQueries({ queryKey: ["runs"] })
      if (runId) void client.invalidateQueries({ queryKey: keys.run(runId) })
      return

    case "rating.changed":
    case "vote.added":
      void client.invalidateQueries({ queryKey: ["runs"] })
      void client.invalidateQueries({ queryKey: ["leaderboard"] })
      void client.invalidateQueries({ queryKey: ["insights"] })
      void client.invalidateQueries({ queryKey: ["pairs"] })
      void client.invalidateQueries({ queryKey: keys.elo })
      void client.invalidateQueries({ queryKey: keys.status })
      if (runId) void client.invalidateQueries({ queryKey: keys.run(runId) })
      return

    case "comfy.status":
      void client.invalidateQueries({ queryKey: keys.status })
      void client.invalidateQueries({ queryKey: keys.catalog })
      return

    // Something happened that nobody asked for: a template re-read after an edit, a preview
    // that could not be downloaded. Worth saying once, out loud, wherever the user is.
    case "lab.message": {
      const said = text((event.data ?? {})["text"])
      if (said) toast.message(said)
      return
    }

    default:
      return
  }
}
