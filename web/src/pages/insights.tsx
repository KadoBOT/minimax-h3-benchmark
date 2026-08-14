/**
 * Insights: which setting actually made a difference.
 *
 * The verdicts lead because they are the answer. Everything below them is the working: the
 * paired comparisons that support the verdict, then the marginal averages, which are shown
 * last and labelled confounded — they mix runs that also differed elsewhere, and reading them
 * as results is exactly the mistake this page exists to prevent.
 */

import { ArrowRight, CircleHelp, Info } from "lucide-react"
import { Link, useParams } from "react-router"

import { useAxes, useInsight } from "@/api/hooks"
import type { AxisInsight, DeltaStat, MarginalCell, PairedComparison, Verdict } from "@/api/schema"
import { Failure, PageHeader, Section, Spinner } from "@/components/page"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { delta, secPerIt, stars as formatStars } from "@/lib/format"
import { cn } from "@/lib/utils"

export function InsightsPage() {
  const { axis } = useParams<{ axis?: string }>()
  const axes = useAxes()
  const chosen = axis ?? axes.data?.[0]?.field
  const insight = useInsight(chosen)

  if (axes.isLoading) return <Spinner label="Looking for axes that vary" />
  if (axes.isError) {
    return <Failure error={axes.error} what="find the axes" onRetry={() => axes.refetch()} />
  }

  if (!axes.data || axes.data.length === 0) {
    return (
      <>
        <PageHeader eyebrow="Analysis" title="Insights" />
        <Section title="Nothing varies yet">
          <p className="text-muted-foreground text-sm">
            Insights compare runs that differ in exactly one setting. Right now every finished run
            used the same configuration, so there is nothing to compare. Queue a sweep with one
            axis and two values — three repeats at a fixed seed is the cheapest experiment that
            can settle an argument.
          </p>
          <Button className="mt-3" size="sm" render={<Link to="/">Set up a sweep</Link>} />
        </Section>
      </>
    )
  }

  return (
    <>
      <PageHeader
        eyebrow="Analysis"
        title="What actually matters"
        lede="Each axis is compared inside groups of runs that are otherwise identical, so the difference you see is the setting rather than the luck of the seed."
      />

      <nav className="mb-4 flex flex-wrap gap-1.5">
        {axes.data.map((definition) => (
          <Link
            key={definition.field}
            to={`/insights/${definition.field}`}
            className={cn(
              "rounded-sm border px-2.5 py-1 font-mono text-xs transition-colors",
              definition.field === chosen
                ? "border-signal/60 bg-signal/15 text-signal"
                : "border-rule text-muted-foreground hover:text-bone"
            )}
          >
            {definition.label}
          </Link>
        ))}
      </nav>

      {insight.isLoading ? (
        <Spinner label="Working through the comparisons" />
      ) : insight.isError ? (
        <Failure error={insight.error} what="analyse that axis" onRetry={() => insight.refetch()} />
      ) : insight.data ? (
        <AxisReport insight={insight.data} />
      ) : null}
    </>
  )
}

function AxisReport({ insight }: { insight: AxisInsight }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 grid-cols-1 sm:grid-cols-2">
        <VerdictCard verdict={insight.quality_verdict} title="Best looking" />
        <VerdictCard verdict={insight.speed_verdict} title="Fastest" />
      </div>

      {insight.paired && insight.paired.length > 0 ? (
        <Section
          title="Matched comparisons"
          hint="Each row is one value against another, measured only where everything else was held equal."
        >
          <div className="overflow-x-auto max-w-full">
            <table className="w-full min-w-[500px] text-sm">
              <thead>
                <tr className="text-muted-foreground edge-code border-rule border-b">
                  <th className="py-1.5 pr-3 text-left font-normal">Comparison</th>
                  <th className="py-1.5 pr-3 text-right font-normal">Groups</th>
                  <th className="py-1.5 pr-3 text-right font-normal">Δ stars</th>
                  <th className="py-1.5 pr-3 text-right font-normal">Δ speed</th>
                  <th className="py-1.5 text-left font-normal">Matched on</th>
                </tr>
              </thead>
              <tbody className="divide-rule/60 divide-y">
                {insight.paired.map((row) => (
                  <PairedRow key={`${row.value_a}-${row.value_b}`} row={row} />
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-muted-foreground mt-3 text-xs">
            A positive delta favours the first value. Rows matched on the seed are the strong ones:
            both sides ran with identical sampling noise, so the difference is the setting.
          </p>
        </Section>
      ) : (
        <Section title="No matched comparisons yet">
          <p className="text-muted-foreground text-sm">
            {insight.total_runs} finished run{insight.total_runs === 1 ? "" : "s"} used this axis,
            but no two of them were otherwise identical. Rerun one config with only{" "}
            <span className="text-bone">{insight.label.toLowerCase()}</span> changed and this table
            fills in.
          </p>
        </Section>
      )}

      {insight.marginal && insight.marginal.length > 0 ? (
        <Section
          title="Marginal averages"
          hint="Every run grouped by its value, ignoring what else differed."
          actions={
            <Tooltip>
              <TooltipTrigger
                render={
                  <span className="text-muted-foreground">
                    <Info className="size-3.5" />
                  </span>
                }
              />
              <TooltipContent className="max-w-72">{insight.marginal_caveat}</TooltipContent>
            </Tooltip>
          }
        >
          <div className="overflow-x-auto max-w-full">
            <table className="w-full min-w-[520px] text-sm">
              <thead>
                <tr className="text-muted-foreground edge-code border-rule border-b">
                  <th className="py-1.5 pr-3 text-left font-normal">{insight.label}</th>
                  <th className="py-1.5 pr-3 text-right font-normal">Runs</th>
                  <th className="py-1.5 pr-3 text-right font-normal">Rated</th>
                  <th className="py-1.5 pr-3 text-right font-normal">Failed</th>
                  <th className="py-1.5 pr-3 text-right font-normal">Mean ★</th>
                  <th className="py-1.5 pr-3 text-right font-normal">Median ★</th>
                  <th className="py-1.5 text-right font-normal">s/it</th>
                </tr>
              </thead>
              <tbody className="divide-rule/60 divide-y">
                {insight.marginal.map((cell) => (
                  <MarginalRow key={cell.value} cell={cell} best={bestStars(insight.marginal)} />
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      ) : null}
    </div>
  )
}

function VerdictCard({ verdict, title }: { verdict: Verdict; title: string }) {
  const won = verdict.kind === "winner"
  return (
    <div
      className={cn(
        "rounded-lg border p-4",
        won ? "border-mint-dim/50 bg-mint/5" : "border-rule bg-panel"
      )}
    >
      <div className="edge-code text-muted-foreground mb-2 flex items-center gap-1.5">
        {won ? null : <CircleHelp className="size-3" />}
        {title}
      </div>
      <div
        className={cn(
          "display text-lg break-words sm:text-xl",
          won ? "text-mint" : "text-muted-foreground"
        )}
      >
        {won ? verdict.value : "Inconclusive"}
      </div>
      <p className="text-muted-foreground mt-2 text-sm">{verdict.reason}</p>
      {won && verdict.matched_on ? (
        <Badge variant={verdict.matched_on === "seed" ? "outline" : "secondary"} className="mt-2">
          {verdict.matched_on === "seed" ? "seed-matched" : "seed-pooled"}
        </Badge>
      ) : null}
    </div>
  )
}

function PairedRow({ row }: { row: PairedComparison }) {
  return (
    <tr>
      <td className="py-1.5 pr-3">
        <span className="text-bone font-mono text-xs">{row.value_a}</span>
        <ArrowRight className="text-muted-foreground mx-1.5 inline size-3" />
        <span className="text-bone font-mono text-xs">{row.value_b}</span>
      </td>
      <td className="tabular text-muted-foreground py-1.5 pr-3 text-right font-mono text-xs">
        {row.pair_groups}
      </td>
      <DeltaCell stat={row.stars} digits={2} />
      <DeltaCell stat={row.speed_pct} digits={1} suffix="%" />
      <td className="py-1.5">
        <Badge variant={row.controlled ? "outline" : "secondary"} className="text-[10px]">
          {row.matched_on === "seed" ? "seed" : "recipe"}
        </Badge>
      </td>
    </tr>
  )
}

function DeltaCell({
  stat,
  digits,
  suffix = "",
}: {
  stat: DeltaStat
  digits: number
  suffix?: string
}) {
  if (stat.n === 0) {
    return <td className="text-muted-foreground py-1.5 pr-3 text-right font-mono text-xs">—</td>
  }
  const mean = stat.mean ?? 0
  return (
    <td
      className={cn(
        "tabular py-1.5 pr-3 text-right font-mono text-xs",
        !stat.conclusive ? "text-muted-foreground" : mean > 0 ? "text-mint" : "text-crimson"
      )}
      title={
        stat.conclusive
          ? `${stat.better_a} groups favoured the first, ${stat.better_b} the second, ${stat.ties} tied`
          : "smaller than its own spread — not yet a result"
      }
    >
      {delta(mean, digits, suffix)}
      {stat.stderr != null ? (
        <span className="text-muted-foreground/70"> ±{stat.stderr.toFixed(digits)}</span>
      ) : null}
    </td>
  )
}

function MarginalRow({ cell, best }: { cell: MarginalCell; best: number | null }) {
  const isBest = best != null && cell.mean_stars === best
  return (
    <tr>
      <td className={cn("py-1.5 pr-3 font-mono text-xs", isBest ? "text-mint" : "text-bone")}>
        {cell.value}
      </td>
      <td className="tabular text-muted-foreground py-1.5 pr-3 text-right font-mono text-xs">
        {cell.n}
      </td>
      <td className="tabular text-muted-foreground py-1.5 pr-3 text-right font-mono text-xs">
        {cell.n_rated}
      </td>
      <td
        className={cn(
          "tabular py-1.5 pr-3 text-right font-mono text-xs",
          cell.n_failed ? "text-crimson" : "text-muted-foreground"
        )}
      >
        {cell.n_failed}
      </td>
      <td
        className={cn(
          "tabular py-1.5 pr-3 text-right font-mono text-xs",
          isBest ? "text-mint" : "text-bone"
        )}
      >
        {formatStars(cell.mean_stars)}
      </td>
      <td className="tabular text-muted-foreground py-1.5 pr-3 text-right font-mono text-xs">
        {formatStars(cell.median_stars)}
      </td>
      <td className="tabular text-signal py-1.5 text-right font-mono text-xs">
        {secPerIt(cell.mean_sec_per_it)}
      </td>
    </tr>
  )
}

function bestStars(cells: MarginalCell[] | undefined): number | null {
  const rated = (cells ?? []).map((cell) => cell.mean_stars).filter((value): value is number => value != null)
  return rated.length ? Math.max(...rated) : null
}
