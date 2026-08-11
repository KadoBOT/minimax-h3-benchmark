/**
 * The arena: two clips, one preference.
 *
 * Everything on this page is arranged around one risk — that the voter answers a question
 * nobody asked. So the pair is drawn from runs that already agree on subject, resolution,
 * duration, interpolation and upscaling; the band across the top states what is held so the guarantee
 * is visible rather than merely true; and the clips carry no label, no rating and no run id,
 * because any of those would tell the eye which one to prefer. The settings that differ are
 * not in the document at all until the viewer asks for them.
 */

import { useCallback, useEffect, useMemo, useState } from "react"
import { SkipForward } from "lucide-react"
import { Link, useSearchParams } from "react-router"

import { ApiError } from "@/api/client"
import { useArenaMatchup, useVote } from "@/api/hooks"
import { routes } from "@/api/routes"
import type { FieldDiff, RunView } from "@/api/schema"
import { Failure, PageHeader, Section, Spinner, Stat } from "@/components/page"
import { Filmstrip } from "@/components/filmstrip"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { ArenaNav, useArenaFilterParam } from "./nav"

export function ArenaPage() {
  const [skipped, setSkipped] = useState<string[]>([])
  const [judged, setJudged] = useState(0)
  const minStars = useArenaFilterParam()
  const query = useArenaMatchup(skipped, minStars)
  const vote = useVote()
  const [, setSearchParams] = useSearchParams()

  const offered = query.data ?? null
  const matchup = offered?.matchup
  const a = offered?.a
  const b = offered?.b

  const cast = useCallback(
    (winner: string | null) => {
      if (!matchup) return
      vote.mutate(
        {
          run_a: matchup.a_run_id,
          run_b: matchup.b_run_id,
          winner,
          ...(matchup.axis ? { axis: matchup.axis } : {}),
        },
        {
          onSuccess: () => {
            setJudged((count) => count + 1)
            void query.refetch()
          },
        }
      )
    },
    [matchup, vote, query]
  )

  const skip = useCallback(() => {
    if (!matchup) return
    setSkipped((current) => [...current, matchup.a_run_id, matchup.b_run_id])
  }, [matchup])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.tagName === "INPUT" || target?.tagName === "TEXTAREA") return
      if (!matchup) return
      if (event.key === "ArrowLeft" || event.key === "a") cast(matchup.a_run_id)
      if (event.key === "ArrowRight" || event.key === "d") cast(matchup.b_run_id)
      if (event.key === "=" || event.key === "t") cast(null)
      if (event.key === "s") skip()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [matchup, cast, skip])

  return (
    <>
      <PageHeader
        eyebrow="Arena"
        title="Which one is better?"
        lede="Both clips ran at the same size, the same length, and the same finishing — only the way they were sampled differs. Pick the one you would keep."
      >
        <Stat label="Judged this session" value={judged} />
      </PageHeader>
      <ArenaNav />

      {query.isLoading ? (
        <Spinner label="Finding a fair pair" />
      ) : query.isError ? (
        <EmptyArena
          error={query.error}
          minStars={minStars}
          onRetry={() => query.refetch()}
          onShowAll={() => setSearchParams({ min_stars: "all" })}
        />
      ) : matchup && a && b ? (
        <div className="space-y-3">
          <HeldBand
            held={matchup.held ?? {}}
            reason={matchup.reason ?? ""}
            seedMatched={matchup.seed_matched ?? false}
          />

          <div className="grid gap-3 lg:grid-cols-2">
            <Clip
              view={a}
              side="left"
              disabled={vote.isPending}
              onWin={() => cast(matchup.a_run_id)}
            />
            <Clip
              view={b}
              side="right"
              disabled={vote.isPending}
              onWin={() => cast(matchup.b_run_id)}
            />
          </div>

          <div className="flex flex-wrap items-center justify-center gap-2">
            <Button variant="outline" disabled={vote.isPending} onClick={() => cast(null)}>
              Too close to call
              <Key label="=" />
            </Button>
            <Button variant="ghost" onClick={skip}>
              <SkipForward data-icon="inline-start" className="size-3.5" />
              Skip this pair
              <Key label="s" />
            </Button>
          </div>

          <Differences differences={matchup.differences ?? []} />
        </div>
      ) : null}
    </>
  )
}

/**
 * The guarantee, stated before the question.
 *
 * This is the whole reason a vote here is worth more than a vote on two clips picked at
 * random, so it sits above the clips rather than in a tooltip. Short facts come first because
 * they are the ones a voter re-reads; the prompt is long and goes last.
 */
function HeldBand({
  held,
  reason,
  seedMatched,
}: {
  held: Record<string, string>
  reason: string
  seedMatched: boolean
}) {
  const chips = useMemo(
    () => Object.entries(held).sort(([, first], [, second]) => first.length - second.length),
    [held]
  )

  return (
    <section className="border-rule bg-panel rounded-lg border">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5">
        <span className="edge-code text-mint shrink-0">Held identical</span>
        <ul className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5">
          {chips.map(([label, value]) => (
            <li key={label} className="flex min-w-0 items-baseline gap-1.5">
              <span className="edge-code text-muted-foreground/70">{label}</span>
              <span
                title={value}
                className="text-bone/90 max-w-[18rem] truncate font-mono text-xs"
              >
                {value}
              </span>
            </li>
          ))}
        </ul>
      </div>
      <div className="hairline" />
      <p className="text-muted-foreground flex flex-wrap items-center gap-2 px-4 py-2 text-xs">
        <span
          className={cn(
            "edge-code shrink-0 rounded-sm px-1.5 py-0.5",
            seedMatched ? "bg-mint/10 text-mint" : "bg-secondary text-muted-foreground"
          )}
        >
          {seedMatched ? "seed-matched" : "seed-pooled"}
        </span>
        {reason}
      </p>
    </section>
  )
}

/**
 * One contender.
 *
 * Deliberately anonymous: a run label in this lab reads `#12 fl2va · spectrum/mod · 20st`,
 * which is the answer to the question being asked. Side is all the identity a clip gets.
 */
function Clip({
  view,
  side,
  disabled,
  onWin,
}: {
  view: RunView
  side: "left" | "right"
  disabled: boolean
  onWin: () => void
}) {
  const { run } = view
  const arrow = side === "left" ? "←" : "→"

  return (
    <article className="panel overflow-hidden p-0">
      {run.artifact?.video_path ? (
        <video
          key={run.artifact.video_path}
          src={routes.video(run.artifact.video_path)}
          poster={run.artifact.poster_path ? routes.poster(run.artifact.poster_path) : undefined}
          controls
          loop
          autoPlay
          muted
          playsInline
          aria-label={`The ${side}-hand clip`}
          className="bg-ink aspect-video w-full"
        />
      ) : (
        <Filmstrip run={run} className="aspect-video" />
      )}
      <div className="flex items-center justify-between gap-3 p-3">
        <span className="edge-code text-muted-foreground">{side}</span>
        <Button size="sm" disabled={disabled} onClick={onWin}>
          This one
          <Key label={arrow} />
        </Button>
      </div>
    </article>
  )
}

function Differences({ differences }: { differences: FieldDiff[] }) {
  const [revealed, setRevealed] = useState(false)
  if (differences.length === 0) return null

  return (
    <details
      className="border-rule bg-panel rounded-lg border px-4 py-2.5"
      onToggle={(event) => setRevealed(event.currentTarget.open)}
    >
      <summary className="text-muted-foreground hover:text-bone cursor-pointer text-xs">
        Reveal {differences.length} difference{differences.length === 1 ? "" : "s"} — after you
        have decided
      </summary>
      {revealed ? (
        <table className="mt-3 w-full max-w-2xl text-sm">
          <thead>
            <tr className="edge-code text-muted-foreground border-rule border-b">
              <th className="w-40 py-1.5 pr-3 text-left font-normal">Setting</th>
              <th className="w-1/3 py-1.5 pr-3 text-left font-normal">Left</th>
              <th className="w-1/3 py-1.5 text-left font-normal">Right</th>
            </tr>
          </thead>
          <tbody className="divide-rule/60 divide-y">
            {differences.map((diff) => (
              <tr key={diff.field}>
                <th scope="row" className="text-muted-foreground py-1.5 pr-3 text-left font-normal">
                  {diff.label}
                </th>
                <td className="text-bone py-1.5 pr-3 font-mono text-xs">{diff.values[0]}</td>
                <td className="text-signal py-1.5 font-mono text-xs">{diff.values[1]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </details>
  )
}

/** A 404 here is a state, not a fault: the lab has nothing comparable yet. */
function EmptyArena({
  error,
  minStars,
  onRetry,
  onShowAll,
}: {
  error: unknown
  minStars: number | null
  onRetry: () => void
  onShowAll: () => void
}) {
  const problem = error instanceof ApiError ? error : null
  if (!problem || problem.kind !== "not_found") {
    return <Failure error={error} what="find a fair pair" onRetry={onRetry} />
  }

  return (
    <Section title={problem.message}>
      <p className="text-muted-foreground max-w-prose text-sm">{problem.detail}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {minStars != null ? (
          <Button size="sm" onClick={onShowAll}>
            Show all runs
          </Button>
        ) : (
          <Button size="sm" render={<Link to="/">Set up a sweep</Link>} />
        )}
        <Button variant="ghost" size="sm" onClick={onRetry}>
          Look again
        </Button>
      </div>
    </Section>
  )
}

function Key({ label }: { label: string }) {
  return <kbd className="ml-2 font-mono text-[10px] opacity-70">{label}</kbd>
}
