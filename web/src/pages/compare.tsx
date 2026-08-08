/**
 * Compare: stage a handful of runs and read what actually differs between them.
 *
 * This page is the deliberate, open-eyed comparison — every setting on the table, as many runs
 * as you like, any two of which may differ in anything at all. It is for understanding a
 * result, not for scoring one: a preference expressed here would be confounded by whatever
 * else differed. Voting lives in the arena, which only ever offers like-for-like pairs.
 */

import { Link } from "react-router"
import { X } from "lucide-react"

import { routes } from "@/api/routes"
import { useComparison } from "@/api/hooks"
import type { FieldDiff, RunView } from "@/api/schema"
import { Filmstrip } from "@/components/filmstrip"
import { Failure, PageHeader, Section, Spinner } from "@/components/page"
import { StarsRead } from "@/components/stars"
import { Button } from "@/components/ui/button"
import { useBench } from "@/lib/bench"
import { secPerIt } from "@/lib/format"
import { cn } from "@/lib/utils"

export function ComparePage() {
  return (
    <>
      <PageHeader
        eyebrow="Judgement"
        title="Compare"
        lede="Stage runs on the bench to read their differences side by side. To pick a winner, use the arena — it only pairs runs that are otherwise identical."
      >
        <Button variant="outline" size="sm" render={<Link to="/arena">Go to the arena</Link>} />
      </PageHeader>
      <BenchCompare />
    </>
  )
}

// --- the bench --------------------------------------------------------------

function BenchCompare() {
  const bench = useBench()
  const query = useComparison(bench.ids)

  if (bench.ids.length < 2) {
    return (
      <Section title="Stage at least two runs">
        <p className="text-muted-foreground text-sm">
          Press <kbd className="text-bone">c</kbd> on the runs list, or use the stage button on any
          run. The bench survives navigation and reloads, so you can collect through a session and
          compare at the end.
        </p>
      </Section>
    )
  }

  if (query.isLoading) return <Spinner label="Lining them up" />
  if (query.isError || !query.data) {
    return <Failure error={query.error} what="compare those runs" onRetry={() => query.refetch()} />
  }

  const { runs, differences, shared } = query.data

  return (
    <div className="space-y-4">
      <div
        className="grid gap-3"
        style={{ gridTemplateColumns: `repeat(${Math.min(runs.length, 4)}, minmax(0, 1fr))` }}
      >
        {runs.map((view) => (
          <CompareCard key={view.run.id} view={view} onRemove={() => bench.remove(view.run.id)} />
        ))}
      </div>

      <Section
        title="What differs"
        hint={
          differences.length === 0
            ? "These configs are identical — any difference in the results is the seed or the machine."
            : `${differences.length} field${differences.length === 1 ? "" : "s"} apart. Everything else is held constant.`
        }
        actions={
          <Button variant="ghost" size="sm" onClick={() => bench.clear()}>
            Clear the bench
          </Button>
        }
      >
        {differences.length > 0 ? (
          <DiffTable differences={differences} count={runs.length} />
        ) : null}

        {Object.keys(shared).length > 0 ? (
          <details className="mt-4">
            <summary className="text-muted-foreground hover:text-bone cursor-pointer text-xs">
              Show the {Object.keys(shared).length} settings they share
            </summary>
            <dl className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
              {Object.entries(shared).map(([field, value]) => (
                <div key={field} className="flex items-baseline justify-between gap-2 text-xs">
                  <dt className="text-muted-foreground truncate">{field.replace(/_/g, " ")}</dt>
                  <dd className="text-bone/80 truncate font-mono">{value}</dd>
                </div>
              ))}
            </dl>
          </details>
        ) : null}
      </Section>
    </div>
  )
}

function DiffTable({ differences, count }: { differences: FieldDiff[]; count: number }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <tbody className="divide-rule/60 divide-y">
          {differences.map((diff) => (
            <tr key={diff.field}>
              <th
                scope="row"
                className="text-muted-foreground w-40 py-1.5 pr-3 text-left font-normal"
              >
                {diff.label}
              </th>
              {Array.from({ length: count }, (_, index) => {
                const value = diff.values[index] ?? "—"
                const first = diff.values[0]
                return (
                  <td
                    key={index}
                    className={cn(
                      "py-1.5 pr-3 font-mono text-xs",
                      index > 0 && value !== first ? "text-signal" : "text-bone"
                    )}
                  >
                    {value}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function CompareCard({ view, onRemove }: { view: RunView; onRemove: () => void }) {
  const { run } = view
  return (
    <article className="panel overflow-hidden p-0">
      <div className="relative">
        {run.artifact?.video_path ? (
          <video
            src={routes.video(run.artifact.video_path)}
            poster={run.artifact.poster_path ? routes.poster(run.artifact.poster_path) : undefined}
            controls
            loop
            muted
            playsInline
            className="bg-ink aspect-video w-full object-cover"
          />
        ) : (
          <Filmstrip run={run} className="aspect-video" />
        )}
        <Button
          variant="ghost"
          size="icon-xs"
          aria-label={`Take ${run.label} off the bench`}
          onClick={onRemove}
          className="bg-ink/70 absolute top-1 right-1"
        >
          <X className="size-3" />
        </Button>
      </div>
      <div className="p-2.5">
        <Link
          to={`/runs/${run.id}`}
          className="text-bone line-clamp-2 font-mono text-xs hover:underline"
        >
          {run.label}
        </Link>
        <div className="mt-1.5 flex items-center justify-between">
          <StarsRead value={view.stars} />
          <span className="edge-code text-signal">{secPerIt(run.metrics?.sec_per_it)}</span>
        </div>
      </div>
    </article>
  )
}
