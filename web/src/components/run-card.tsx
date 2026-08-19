/**
 * One run in a list: the strip, its edge code, and the judgements you make most often.
 *
 * Rating and staging are inline because they are the two actions performed on nearly every
 * run; everything rarer lives on the run's own page.
 */

import { Heart, RotateCw, Rows3 } from "lucide-react"
import { Link, useLocation } from "react-router"

import { useBench } from "@/lib/bench-context"
import { useClearRating, usePatchRun, useRate, useRerun } from "@/api/hooks"
import type { RunView } from "@/api/schema"
import { EdgeCode } from "@/components/edge-code"
import { Filmstrip } from "@/components/filmstrip"
import { LivePreview } from "@/components/live-preview"
import { useLivePreview } from "@/components/use-live-preview"
import { StarRating } from "@/components/stars"
import { StatusChip } from "@/components/status-chip"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

export function RunCard({
  view,
  selected = false,
  onFocus,
}: {
  view: RunView
  selected?: boolean
  onFocus?: () => void
}) {
  const { run } = view
  const location = useLocation()
  const bench = useBench()
  const live = useLivePreview(run.id)
  const staged = bench.has(run.id)
  const rate = useRate()
  const clear = useClearRating()
  const patch = usePatchRun()
  const rerun = useRerun()

  return (
    <article
      onMouseEnter={onFocus}
      data-testid="run-card"
      data-run-id={run.id}
      data-selected={selected || undefined}
      className={cn(
        "border-rule bg-panel rounded-lg border p-2.5 transition-colors",
        selected && "border-signal/70",
        staged && !selected && "border-mint-dim/60"
      )}
    >
      <div className="flex min-w-0 flex-col gap-2.5 sm:flex-row sm:items-start sm:gap-3">
        <Link
          to={{ pathname: `/runs/${run.id}`, search: location.search }}
          className="w-full min-w-0 sm:flex-1"
        >
          {run.status === "running" && live ? (
            <LivePreview
              runId={run.id}
              seq={live.seq}
              mime={live.mime}
              className="border-rule/60 max-h-48 rounded-sm border"
            />
          ) : (
            <Filmstrip run={run} className="rounded-sm" />
          )}
        </Link>
        <div className="border-rule/40 flex w-full min-w-0 shrink-0 flex-wrap items-center justify-between gap-2 border-t pt-2 sm:w-36 sm:flex-col sm:items-end sm:justify-start sm:gap-1.5 sm:border-t-0 sm:pt-0">
          <StatusChip run={run} />
          <StarRating
            value={view.stars}
            size="sm"
            onChange={(stars) => rate.mutate({ id: run.id, stars })}
            onClear={() => clear.mutate(run.id)}
          />
          <div className="flex items-center gap-0.5">
            <IconAction
              label={staged ? "Take off the bench" : "Stage for comparison"}
              active={staged}
              onClick={() => bench.toggle(run.id)}
            >
              <Rows3 className="size-3.5" />
            </IconAction>
            <IconAction
              label={run.favourite ? "Remove from favourites" : "Mark as a favourite"}
              active={run.favourite}
              onClick={() => patch.mutate({ id: run.id, favourite: !run.favourite })}
            >
              <Heart className="size-3.5" fill={run.favourite ? "currentColor" : "none"} />
            </IconAction>
            <IconAction label="Run this again" onClick={() => rerun.mutate({ id: run.id })}>
              <RotateCw className="size-3.5" />
            </IconAction>
          </div>
        </div>
      </div>
      <EdgeCode view={view} className="mt-2 min-w-0" />
    </article>
  )
}

function IconAction({
  label,
  active,
  onClick,
  children,
}: {
  label: string
  active?: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={label}
            aria-pressed={active}
            onClick={onClick}
            className={cn("size-9 sm:size-7", active ? "text-mint" : "text-muted-foreground")}
          >
            {children}
          </Button>
        }
      />
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}
