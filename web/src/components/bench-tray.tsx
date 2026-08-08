/**
 * The bench tray: what is staged for comparison, always visible, never lost on navigation.
 *
 * It sits at the bottom rather than in a panel because it is a holding area, not a page —
 * you fill it while scanning Runs and empty it on Compare.
 */

import { ArrowRight, X } from "lucide-react"
import { useNavigate } from "react-router"

import { useRuns } from "@/api/hooks"
import { Button } from "@/components/ui/button"
import { Filmstrip } from "@/components/filmstrip"
import { BENCH_LIMIT, useBench } from "@/lib/bench"
import { plural } from "@/lib/format"

export function BenchTray() {
  const bench = useBench()
  const navigate = useNavigate()
  const { data } = useRuns({ ids: bench.ids, limit: BENCH_LIMIT, archived: undefined }, {
    enabled: bench.ids.length > 0,
  })

  if (bench.ids.length === 0) return null

  // Keep the tray in the order the runs were staged, not the order the API returned them.
  const staged = bench.ids
    .map((id) => data?.items.find((item) => item.run.id === id))
    .filter((view): view is NonNullable<typeof view> => Boolean(view))

  return (
    <aside
      aria-label="Bench"
      data-testid="bench-tray"
      className="border-rule bg-panel/95 fixed inset-x-0 bottom-0 z-40 border-t backdrop-blur"
    >
      <div className="flex items-center gap-3 px-4 py-2.5">
        <div className="edge-code text-muted-foreground shrink-0">
          Bench · {plural(bench.ids.length, "run")}
        </div>

        <div className="flex min-w-0 flex-1 gap-2 overflow-x-auto">
          {staged.map((view) => (
            <div key={view.run.id} className="group relative w-40 shrink-0">
              <Filmstrip
                run={view.run}
                scrub={false}
                className="rounded-sm"
                onClick={() => navigate(`/runs/${view.run.id}`)}
              />
              <button
                onClick={() => bench.remove(view.run.id)}
                aria-label={`Remove ${view.run.label} from the bench`}
                className="bg-ink/90 text-muted-foreground hover:text-crimson absolute -top-1.5 -right-1.5 grid size-4 place-items-center rounded-full opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
              >
                <X className="size-2.5" />
              </button>
              <div className="edge-code text-muted-foreground mt-1 truncate">{view.run.label}</div>
            </div>
          ))}
          {bench.ids.length > staged.length ? (
            <div className="edge-code text-muted-foreground grid w-40 shrink-0 place-items-center">
              loading…
            </div>
          ) : null}
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          <Button variant="ghost" size="sm" onClick={bench.clear}>
            Clear
          </Button>
          <Button
            size="sm"
            disabled={bench.ids.length < 2}
            onClick={() => navigate("/compare")}
            title={bench.ids.length < 2 ? "Stage a second run to compare" : "Compare the bench"}
          >
            Compare
            <ArrowRight data-icon="inline-end" className="size-3.5" />
          </Button>
        </div>
      </div>
    </aside>
  )
}
