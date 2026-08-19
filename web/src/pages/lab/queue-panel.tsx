/**
 * The live queue.
 *
 * The active run shows its own progress from the event stream rather than from a poll, so the
 * seconds-per-step readout moves at the rate ComfyUI reports it.
 */

import { Ban, Pause, Play, X } from "lucide-react"
import { Link } from "react-router"

import { useStream } from "@/api/event-stream-context"
import { useCancelRun, useQueue, useQueueControl } from "@/api/hooks"
import { LivePreview } from "@/components/live-preview"
import { Section, Stat } from "@/components/page"
import { StatusChip } from "@/components/status-chip"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { secPerIt, seconds } from "@/lib/format"

export function QueuePanel() {
  const { data: queue } = useQueue()
  const { progress } = useStream()
  const control = useQueueControl()
  const cancel = useCancelRun()

  const active = queue?.active ?? null
  const waiting = queue?.queued ?? []
  const paused = queue?.paused ?? false

  return (
    <Section
      title="Queue"
      hint={paused ? "Paused — nothing will start until you resume." : "Runs execute one at a time."}
      actions={
        <>
          {paused ? (
            <Button size="sm" variant="outline" onClick={() => control.resume.mutate()}>
              <Play data-icon="inline-start" className="size-3.5" />
              Resume
            </Button>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => control.pause.mutate()}>
              <Pause data-icon="inline-start" className="size-3.5" />
              Pause
            </Button>
          )}
          {waiting.length > 0 ? (
            <Button size="sm" variant="ghost" onClick={() => control.clear.mutate()}>
              <Ban data-icon="inline-start" className="size-3.5" />
              Clear
            </Button>
          ) : null}
        </>
      }
    >
      {active ? (
        <div className="border-signal/30 bg-signal/5 mb-3 rounded-md border p-3">
          <div className="flex items-center justify-between gap-3">
            <Link
              to={`/runs/${active.run.id}`}
              className="text-bone min-w-0 truncate font-mono text-sm hover:underline"
            >
              {active.run.label}
            </Link>
            <div className="flex shrink-0 items-center gap-2">
              <StatusChip run={active.run} />
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label="Interrupt this run"
                onClick={() => cancel.mutate(active.run.id)}
              >
                <X className="size-3" />
              </Button>
            </div>
          </div>

          {progress?.runId === active.run.id && progress.previewSeq ? (
            <LivePreview
              key={active.run.id}
              runId={active.run.id}
              seq={progress.previewSeq}
              mime={progress.previewMime}
              className="border-rule/60 mt-2.5 max-h-56 rounded border"
            />
          ) : null}

          {progress?.runId === active.run.id && progress.step != null && progress.stepTotal ? (
            <div className="mt-2.5">
              {/* `primary` is already the amber accent, so the default indicator is on-palette. */}
              <Progress
                value={(progress.step / progress.stepTotal) * 100}
                className="[&_[data-slot=progress-track]]:bg-rule"
              />
              <div className="edge-code text-muted-foreground mt-1.5 flex justify-between">
                <span>
                  step {progress.step} of {progress.stepTotal}
                  {progress.node ? ` · ${progress.node}` : ""}
                </span>
                <span className="text-signal">
                  {secPerIt(progress.secPerIt)}
                  {progress.secPerIt
                    ? ` · ${seconds((progress.stepTotal - progress.step) * progress.secPerIt)} left`
                    : ""}
                </span>
              </div>
            </div>
          ) : null}
        </div>
      ) : (
        <p className="text-muted-foreground py-1 text-sm">
          {paused
            ? "Paused. Resume to start the next run."
            : waiting.length > 0
              ? "Picking up the next run…"
              : "Nothing running. Queue a config or a sweep."}
        </p>
      )}

      {waiting.length > 0 ? (
        <>
          <div className="mb-2 flex items-center gap-6">
            <Stat label="Waiting" value={queue?.total ?? waiting.length} />
          </div>
          <ol className="divide-rule/60 divide-y">
            {waiting.slice(0, 12).map((view) => (
              <li key={view.run.id} className="flex items-center gap-3 py-1.5">
                <Link
                  to={`/runs/${view.run.id}`}
                  className="text-muted-foreground hover:text-bone min-w-0 flex-1 truncate font-mono text-xs"
                >
                  {view.run.label}
                </Link>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  aria-label={`Cancel ${view.run.label}`}
                  onClick={() => cancel.mutate(view.run.id)}
                >
                  <X className="size-3" />
                </Button>
              </li>
            ))}
          </ol>
          {waiting.length > 12 ? (
            <p className="edge-code text-muted-foreground mt-2">
              and {waiting.length - 12} more
            </p>
          ) : null}
        </>
      ) : null}
    </Section>
  )
}
