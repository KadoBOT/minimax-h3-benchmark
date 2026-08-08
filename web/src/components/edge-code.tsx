/**
 * The line of markings under a filmstrip, set like the edge code printed on film stock.
 *
 * Fixed order, always the same fields, tabular figures: the eye learns the position of each
 * value and stops reading labels. Colour is meaning, not decoration — amber for time, mint
 * for quality, crimson for a failure.
 */

import { Star } from "lucide-react"

import type { Run, RunView } from "@/api/schema"
import { ago, elo, exact, modelStem, moment, secPerIt, shortHash } from "@/lib/format"
import { cn } from "@/lib/utils"

export function EdgeCode({
  view,
  className,
  /** Off where the label is already the heading above the strip, so it is not printed twice. */
  showLabel = true,
}: {
  view: RunView
  className?: string
  showLabel?: boolean
}) {
  const { run } = view
  const failed = run.status === "failed"

  return (
    <div
      className={cn("edge-code text-muted-foreground flex items-center gap-2.5", className)}
      data-testid="edge-code"
    >
      {showLabel ? <span className="text-bone/70 tracking-[0.14em]">{run.label}</span> : null}
      <span className={cn(failed ? "text-crimson" : "text-signal")}>
        {failed ? "failed" : secPerIt(run.metrics?.sec_per_it)}
      </span>
      <span className={cn("flex items-center gap-1", view.stars != null && "text-mint")}>
        <Star className="size-2.5" strokeWidth={2.5} fill={view.stars != null ? "currentColor" : "none"} />
        {view.stars ?? "—"}
      </span>
      {view.elo != null ? <span title={`${view.elo_games ?? 0} comparisons`}>{elo(view.elo)}</span> : null}
      <span className="ml-auto flex items-center gap-2.5">
        <Age run={run} />
        <span className="hidden sm:inline">{modelStem(run.config.diffusion_model)}</span>
        <span className="text-muted-foreground/70" title={`config ${run.config_hash}`}>
          {shortHash(run.config_hash)}
        </span>
      </span>
    </div>
  )
}

/**
 * How long ago the run last did something, which for a finished run is when it finished.
 *
 * A sweep is created in one go, so creation times are all the same and say nothing. The
 * relative form is what gets scanned; the exact moment and which moment it is are on hover,
 * so the line stays one glance wide.
 */
function Age({ run }: { run: Run }) {
  const { at, verb } = moment(run)
  if (!at) return null
  return (
    <span data-testid="run-age" title={`${verb} ${exact(at)}`}>
      {ago(at)}
    </span>
  )
}
