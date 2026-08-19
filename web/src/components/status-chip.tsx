/** A run's status, with the live rate when it is the one on the GPU. */

import { useStream } from "@/api/event-stream-context"
import type { Run } from "@/api/schema"
import { secPerIt } from "@/lib/format"
import { cn } from "@/lib/utils"

const TONE: Record<Run["status"], string> = {
  queued: "text-muted-foreground border-rule",
  running: "text-signal border-signal/50",
  succeeded: "text-mint border-mint-dim/50",
  failed: "text-crimson border-crimson-dim/60",
  cancelled: "text-muted-foreground border-rule",
  interrupted: "text-signal border-signal-dim/60",
}

export function StatusChip({
  run,
  /** Off where a fuller timing readout sits beside the chip, so the number is not printed twice. */
  showRate = true,
}: {
  run: Run
  showRate?: boolean
}) {
  const { progress } = useStream()
  const live = run.status === "running" && progress?.runId === run.id ? progress : null

  const label =
    live && live.step != null && live.stepTotal
      ? `${live.step}/${live.stepTotal}`
      : live?.node
        ? live.node
        : run.status

  const rate = !showRate
    ? null
    : run.status === "running"
      ? live?.secPerIt
      : run.metrics?.sec_per_it

  return (
    <span
      data-testid="status-chip"
      data-status={run.status}
      className={cn(
        "edge-code inline-flex items-center gap-1.5 rounded-sm border px-1.5 py-0.5",
        TONE[run.status]
      )}
    >
      {run.status === "running" ? (
        <span className="bg-signal size-1.5 shrink-0 rounded-full motion-safe:animate-pulse" />
      ) : null}
      {label}
      {rate != null ? <span className="text-muted-foreground">{secPerIt(rate)}</span> : null}
    </span>
  )
}
