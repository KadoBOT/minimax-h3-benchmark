/**
 * The health corner: is the stream connected, is ComfyUI up, is the worker running.
 *
 * Answering "why is nothing happening?" was the old lab's biggest time sink, so the three
 * things that can be wrong are visible without opening anything.
 */

import { AlertTriangle, Pause, Radio, RadioTower } from "lucide-react"

import type { LabStatus } from "@/api/schema"
import { cn } from "@/lib/utils"

export function LiveBadge({
  live,
  status,
  compact = false,
}: {
  live: boolean
  status?: LabStatus
  /** One-line pill for the mobile header; the full panel stays in the drawer / rail. */
  compact?: boolean
}) {
  const paused = status?.paused ?? false
  const worker = status?.worker_alive ?? false
  const trouble = status?.last_error
  const queued = status?.queued ?? 0

  if (compact) {
    const tone = trouble
      ? "text-crimson"
      : paused
        ? "text-signal"
        : live && worker
          ? "text-mint"
          : "text-muted-foreground"
    const Icon = trouble ? AlertTriangle : paused ? Pause : live ? RadioTower : Radio
    const label = trouble
      ? "Error"
      : paused
        ? "Paused"
        : !live
          ? "Offline"
          : !worker
            ? "No worker"
            : queued > 0
              ? `${queued}q`
              : "Live"
    return (
      <div
        className={cn(
          "border-rule/70 bg-panel/50 inline-flex max-w-[9rem] items-center gap-1.5 rounded-md border px-2 py-1",
          tone
        )}
        data-testid="live-badge"
        title={trouble ?? undefined}
      >
        <Icon className="size-3 shrink-0" strokeWidth={2.2} />
        <span className="edge-code truncate text-[10px]">{label}</span>
      </div>
    )
  }

  return (
    <div className="border-rule/70 bg-panel/50 space-y-1.5 rounded-md border p-2.5" data-testid="live-badge">
      <Row
        icon={live ? RadioTower : Radio}
        tone={live ? "mint" : "muted"}
        label={live ? "Live" : "Reconnecting"}
        detail={live ? `seq ${status?.event_seq ?? 0}` : "stream dropped"}
      />
      <Row
        icon={paused ? Pause : RadioTower}
        tone={paused ? "signal" : worker ? "mint" : "crimson"}
        label={paused ? "Paused" : worker ? "Worker up" : "Worker down"}
        detail={`${queued} queued`}
      />
      {trouble ? (
        <Row icon={AlertTriangle} tone="crimson" label="Last error" detail={trouble.slice(0, 48)} />
      ) : null}
    </div>
  )
}

const TONES = {
  mint: "text-mint",
  signal: "text-signal",
  crimson: "text-crimson",
  muted: "text-muted-foreground",
} as const

function Row({
  icon: Icon,
  tone,
  label,
  detail,
}: {
  icon: typeof Radio
  tone: keyof typeof TONES
  label: string
  detail: string
}) {
  return (
    <div className="flex items-center gap-2">
      <Icon className={cn("size-3 shrink-0", TONES[tone])} strokeWidth={2.2} />
      <span className="text-bone/80 truncate text-xs">{label}</span>
      <span className="edge-code text-muted-foreground ml-auto shrink-0">{detail}</span>
    </div>
  )
}
