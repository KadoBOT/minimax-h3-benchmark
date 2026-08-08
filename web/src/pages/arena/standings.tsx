/**
 * Standings: what the votes actually decided.
 *
 * A vote between two clips that differ in one setting is evidence about that setting, so it
 * ranks that setting. A vote between clips that differ in four is evidence about the four
 * together, so it ranks the whole configuration and none of its parts — splitting it four ways
 * would invent a result nobody voted for. The two tables below are that distinction, in order:
 * settings first, whole configurations second.
 *
 * Speed sits in the last column and never in the ranking. Which clip looks better is the
 * question the voter answered; how long it took is a cost to weigh afterwards.
 */

import { useState } from "react"
import { CircleHelp } from "lucide-react"
import { Link } from "react-router"

import { useArenaStandings } from "@/api/hooks"
import type { ArenaAxis, ArenaStanding, ArenaVerdict } from "@/api/schema"
import { Failure, PageHeader, Section, Spinner } from "@/components/page"
import { Button } from "@/components/ui/button"
import { secPerIt } from "@/lib/format"
import { cn } from "@/lib/utils"
import { ArenaNav } from "./nav"

export function StandingsPage() {
  const query = useArenaStandings()
  const [chosen, setChosen] = useState<string | null>(null)

  const board = query.data
  const axes = board?.axes ?? []
  const axis = axes.find((item) => item.axis === chosen) ?? axes[0]

  return (
    <>
      <PageHeader
        eyebrow="Arena"
        title="What the votes decided"
        lede="Every ranking here comes from clips that were identical apart from the setting being ranked, so a lead is the setting rather than the resolution or the seed."
      />
      <ArenaNav />

      {query.isLoading ? (
        <Spinner label="Replaying the votes" />
      ) : query.isError ? (
        <Failure error={query.error} what="read the standings" onRetry={() => query.refetch()} />
      ) : board ? (
        <div className="space-y-4">
          <Coverage
            counted={board.votes_counted ?? 0}
            clean={board.clean_matchups ?? 0}
            matchups={board.matchups ?? 0}
            pools={board.pools ?? 0}
            runs={board.runs ?? 0}
          />

          {axes.length === 0 ? (
            <Section title="No settings ranked yet">
              <p className="text-muted-foreground max-w-prose text-sm">
                A setting is ranked once two clips that differ in it alone have been judged. Cast a
                few votes in the arena and this fills in — four decided votes on one setting is
                enough to separate it from a coin flip.
              </p>
              <Button className="mt-3" size="sm" render={<Link to="/arena">Judge a pair</Link>} />
            </Section>
          ) : (
            <>
              <nav className="flex flex-wrap gap-1.5">
                {axes.map((item) => (
                  <button
                    key={item.axis}
                    type="button"
                    onClick={() => setChosen(item.axis)}
                    aria-current={item.axis === axis?.axis}
                    title={`${item.votes} vote${item.votes === 1 ? "" : "s"} name this setting alone`}
                    className={cn(
                      "rounded-sm border px-2.5 py-1 font-mono text-xs transition-colors",
                      item.axis === axis?.axis
                        ? "border-signal/60 bg-signal/15 text-signal"
                        : "border-rule text-muted-foreground hover:text-bone"
                    )}
                  >
                    {item.label}
                    <span className="text-muted-foreground/70 ml-1.5">{item.votes}</span>
                  </button>
                ))}
              </nav>
              {axis ? <AxisBoard axis={axis} /> : null}
            </>
          )}

          {board.loadouts && board.loadouts.length > 0 ? (
            <Section
              title="Whole configurations"
              hint="Every counted vote, including the ones where too much differed to blame a single setting."
            >
              <Table rows={board.loadouts} what="Configuration" />
            </Section>
          ) : null}

          {board.votes_ignored ? (
            <Ignored total={board.votes_ignored} reasons={board.ignored_reasons ?? {}} />
          ) : null}
        </div>
      ) : null}
    </>
  )
}

function Coverage({
  counted,
  clean,
  matchups,
  pools,
  runs,
}: {
  counted: number
  clean: number
  matchups: number
  pools: number
  runs: number
}) {
  return (
    <p className="text-muted-foreground text-xs">
      <span className="text-bone">{counted} votes counted</span> · {clean} clean matchups
      available of {matchups} fair pairs · {runs} runs across {pools} pool
      {pools === 1 ? "" : "s"}
    </p>
  )
}

function AxisBoard({ axis }: { axis: ArenaAxis }) {
  return (
    <div className="space-y-3">
      <VerdictCard verdict={axis.verdict} label={axis.label} />
      <Section
        title={axis.label}
        hint="Elo is replayed from the whole vote log, so a deleted vote leaves nothing behind."
      >
        <Table rows={axis.standings ?? []} what={axis.label} />
      </Section>
    </div>
  )
}

function VerdictCard({ verdict, label }: { verdict: ArenaVerdict; label: string }) {
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
        Best {label.toLowerCase()}
      </div>
      <div className={cn("display text-xl", won ? "text-mint" : "text-muted-foreground")}>
        {won ? verdict.value : "Inconclusive"}
      </div>
      <p className="text-muted-foreground mt-2 max-w-prose text-sm">{verdict.reason}</p>
    </div>
  )
}

function Table({ rows, what }: { rows: ArenaStanding[]; what: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-muted-foreground edge-code border-rule border-b">
            <th className="w-8 py-1.5 pr-3 text-right font-normal">#</th>
            <th className="py-1.5 pr-3 text-left font-normal">{what}</th>
            <th className="py-1.5 pr-3 text-right font-normal">Elo</th>
            <th className="py-1.5 pr-3 text-right font-normal">W–L–T</th>
            <th className="py-1.5 pr-3 text-right font-normal">Seed-matched</th>
            <th className="py-1.5 pr-3 text-right font-normal">Runs</th>
            <th className="py-1.5 text-right font-normal">Speed</th>
          </tr>
        </thead>
        <tbody className="divide-rule/60 divide-y">
          {rows.map((row, index) => (
            <tr key={row.key}>
              <td className="tabular text-muted-foreground py-1.5 pr-3 text-right font-mono text-xs">
                {row.rank || index + 1}
              </td>
              <td
                className={cn(
                  "py-1.5 pr-3 font-mono text-xs",
                  index === 0 ? "text-mint" : "text-bone"
                )}
              >
                {row.label}
              </td>
              <td
                className={cn(
                  "tabular py-1.5 pr-3 text-right font-mono text-xs",
                  index === 0 ? "text-mint" : "text-bone"
                )}
              >
                {row.rating.toFixed(1)}
              </td>
              <td className="tabular text-bone py-1.5 pr-3 text-right font-mono text-xs">
                {row.wins ?? 0}–{row.losses ?? 0}–{row.ties ?? 0}
              </td>
              <td
                className="tabular text-muted-foreground py-1.5 pr-3 text-right font-mono text-xs"
                title="Votes where both clips also shared a seed, so the difference was only the setting"
              >
                {row.seed_matched ?? 0}
              </td>
              <td className="tabular text-muted-foreground py-1.5 pr-3 text-right font-mono text-xs">
                {row.runs ?? 0}
              </td>
              <td className="tabular text-signal py-1.5 text-right font-mono text-xs">
                {secPerIt(row.mean_sec_per_it)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Votes that exist but cannot mean anything, named rather than silently dropped. */
function Ignored({ total, reasons }: { total: number; reasons: Record<string, number> }) {
  return (
    <Section
      title={`${total} vote${total === 1 ? "" : "s"} not counted`}
      hint="Fairness is rechecked against the runs as they are now, so an old vote is judged by today's rule."
    >
      <ul className="text-muted-foreground space-y-1 text-xs">
        {Object.entries(reasons).map(([reason, count]) => (
          <li key={reason} className="flex items-baseline justify-between gap-3">
            <span>{reason}</span>
            <span className="tabular text-bone font-mono">{count}</span>
          </li>
        ))}
      </ul>
    </Section>
  )
}
