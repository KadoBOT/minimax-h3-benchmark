import { useStream } from "@/api/event-stream-context"

export function useLivePreview(runId: string) {
  const { progress } = useStream()
  if (progress?.runId !== runId || !progress.previewSeq) return null
  return {
    seq: progress.previewSeq,
    mime: progress.previewMime,
    step: progress.step,
    stepTotal: progress.stepTotal,
    secPerIt: progress.secPerIt,
    node: progress.node,
  }
}
