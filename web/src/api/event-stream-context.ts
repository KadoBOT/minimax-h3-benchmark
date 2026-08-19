import { createContext, useContext } from "react"

import type { Event as LabEvent } from "./schema"

export type Progress = {
  runId: string
  step: number | null
  stepTotal: number | null
  secPerIt: number | null
  node: string | null
  previewSeq: number | null
  previewMime: string | null
}

export type EventStream = {
  live: boolean
  seq: number
  progress: Progress | null
  last: LabEvent | null
}

export const EventStreamContext = createContext<EventStream>({
  live: false,
  seq: 0,
  progress: null,
  last: null,
})

export function useStream(): EventStream {
  return useContext(EventStreamContext)
}
