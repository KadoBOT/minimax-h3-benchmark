/**
 * The leaderboard: one ranked answer to "what should I run tonight?"
 *
 * The weight slider is the page. Nobody agrees on how much speed a star is worth, so rather
 * than picking a constant, the trade-off is a control and the ranking re-sorts as you move it.
 * The recipe view answers the harder question underneath — a single lucky run is not a
 * finding, so replicates of one recipe are grouped and shown with their spread.
 */

import { useState } from "react"
import { Layers, Pin, Sparkles } from "lucide-react"
import { Link } from "react-router"

import { useLeaderboard, useRecipes, useSetBaseline } from "@/api/hooks"
import type { LeaderboardEntry, RecipeGroup } from "@/api/schema"
import { EdgeCode } from "@/components/edge-code"
import { Filmstrip } from "@/components/filmstrip"
import { Failure, PageHeader, Section, Spinner, Stat } from "@/components/page"
import { StarsRead } from "@/components/stars"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useBench } from "@/lib/bench"
import { percent, plural, secPerIt, shortHash } from "@/lib/format"
import { cn } from "@/lib/utils"

export function LeaderboardPage() {
  const [quality, setQuality] = useState(70)

  return (
    <>
      <PageHeader
        eyebrow="Ranking"
        title="What is worth reusing"
        lede="One score, from how good it looked and how fast it ran. Move the slider to say which of the two you care about tonight."
      />

      <Section
        title="The trade-off"
        hint="Runs nobody has judged sink to the bottom rather than scoring zero — unlooked-at is not the same as bad."
        className="mb-4"
      >
        <div className="flex items-center gap-4">
          <span className="edge-code text-mint w-24 shrink-0">quality {quality}</span>
          <Slider
            value={[quality]}
            min={0}
            max={100}
            step={5}
            onValueChange={(value) =>
              setQuality(Array.isArray(value) ? (value[0] ?? 70) : (value as number))
            }
            className="flex-1"
            aria-label="How much quality matters against speed"
          />
          <span className="edge-code text-signal w-24 shrink-0 text-right">
            speed {100 - quality}
          </span>
        </div>
      </Section>

      <Tabs defaultValue="runs">
        <TabsList className="mb-4">
          <TabsTrigger value="runs">
            <Sparkles data-icon="inline-start" className="size-3.5" />
            Best runs
          </TabsTrigger>
          <TabsTrigger value="recipes">
            <Layers data-icon="inline-start" className="size-3.5" />
            Best recipes
          </TabsTrigger>
        </TabsList>
        <TabsContent value="runs">
          <BestRuns quality={quality} speed={100 - quality} />
        </TabsContent>
        <TabsContent value="recipes">
          <BestRecipes />
        </TabsContent>
      </Tabs>
    </>
  )
}

function BestRuns({ quality, speed }: { quality: number; speed: number }) {
  const board = useLeaderboard(quality, speed)

  if (board.isLoading) return <Spinner label="Scoring everything" />
  if (board.isError) {
    return <Failure error={board.error} what="build the leaderboard" onRetry={() => board.refetch()} />
  }
  if (!board.data || board.data.entries.length === 0) {
    return (
      <Section title="Nothing to rank yet">
        <p className="text-muted-foreground text-sm">
          Finish a run or two and rate them. The leaderboard needs at least one judged result
          before it can order anything.
        </p>
      </Section>
    )
  }

  const { entries, considered, unrated } = board.data

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-6">
        <Stat label="Considered" value={considered} />
        <Stat label="Unjudged" value={unrated} tone={unrated ? "signal" : "muted"} />
        {unrated > 0 ? (
          <p className="text-muted-foreground max-w-prose text-xs">
            {plural(unrated, "run")} at the bottom have no stars and no votes. Rating them is the
            cheapest way to make this list mean something.
          </p>
        ) : null}
      </div>

      <div className="space-y-2">
        {entries.map((entry) => (
          <BoardRow key={entry.view.run.id} entry={entry} />
        ))}
      </div>
    </div>
  )
}

function BoardRow({ entry }: { entry: LeaderboardEntry }) {
  const { view } = entry
  const { run } = view
  const bench = useBench()
  const baseline = useSetBaseline()
  const staged = bench.has(run.id)

  return (
    <article
      className={cn(
        "border-rule bg-panel flex items-center gap-3 rounded-lg border p-2.5",
        entry.rank === 1 && !entry.unrated && "border-mint-dim/60",
        view.is_baseline && "border-signal/60"
      )}
    >
      <div
        className={cn(
          "tabular w-8 shrink-0 text-center font-mono text-lg",
          entry.rank === 1 && !entry.unrated ? "text-mint" : "text-muted-foreground"
        )}
      >
        {entry.rank}
      </div>

      <Link to={`/runs/${run.id}`} className="w-44 shrink-0">
        <Filmstrip run={run} scrub={false} className="rounded-sm" />
      </Link>

      <div className="min-w-0 flex-1">
        {/* Two lines rather than one: what a label ends with is what distinguishes it. */}
        <Link
          to={`/runs/${run.id}`}
          className="text-bone line-clamp-2 font-mono text-sm hover:underline"
        >
          {run.label}
        </Link>
        <EdgeCode view={view} showLabel={false} className="mt-1" />
      </div>

      <div className="flex shrink-0 items-center gap-5">
        <Stat
          label="Score"
          value={entry.unrated ? "—" : entry.score.toFixed(3)}
          tone={entry.unrated ? "muted" : "bone"}
          hint={
            entry.quality_source === "elo"
              ? "quality taken from head-to-head votes"
              : entry.quality_source === "stars"
                ? "quality taken from the star rating"
                : "never judged"
          }
        />
        <Stat label="Quality" value={percent(entry.quality)} tone="mint" />
        <Stat label="Speed" value={percent(entry.speed)} tone="signal" />
        <div className="flex gap-1">
          <Button
            variant={staged ? "secondary" : "ghost"}
            size="sm"
            onClick={() => bench.toggle(run.id)}
          >
            {staged ? "Staged" : "Stage"}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Pin as the baseline"
            onClick={() => baseline.mutate(run.id)}
            className={view.is_baseline ? "text-signal" : undefined}
          >
            <Pin className="size-3.5" />
          </Button>
        </div>
      </div>
    </article>
  )
}

function BestRecipes() {
  const recipes = useRecipes()

  if (recipes.isLoading) return <Spinner label="Grouping the replicates" />
  if (recipes.isError) {
    return <Failure error={recipes.error} what="group the recipes" onRetry={() => recipes.refetch()} />
  }
  if (!recipes.data || recipes.data.length === 0) {
    return (
      <Section title="No repeated recipes yet">
        <p className="text-muted-foreground text-sm">
          A recipe is a config without its seed. Run the same settings at three seeds and this
          page will tell you whether the result holds up or whether you got lucky once.
        </p>
      </Section>
    )
  }

  return (
    <Section
      title="Recipes by mean rating"
      hint="Every run that shares a recipe, averaged. More replicates means more trust."
    >
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted-foreground edge-code border-rule border-b">
              <th className="py-1.5 pr-3 text-left font-normal">Recipe</th>
              <th className="py-1.5 pr-3 text-right font-normal">Runs</th>
              <th className="py-1.5 pr-3 text-right font-normal">Rated</th>
              <th className="py-1.5 pr-3 text-right font-normal">Mean ★</th>
              <th className="py-1.5 pr-3 text-right font-normal">Mean s/it</th>
              <th className="py-1.5 text-right font-normal">Best</th>
            </tr>
          </thead>
          <tbody className="divide-rule/60 divide-y">
            {recipes.data.map((group) => (
              <RecipeRow key={group.recipe_hash} group={group} />
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  )
}

function RecipeRow({ group }: { group: RecipeGroup }) {
  const thin = group.n_rated < 2
  return (
    <tr>
      <td className="py-2 pr-3">
        <span className="text-bone block truncate text-sm">{group.label}</span>
        <span className="edge-code text-muted-foreground">{shortHash(group.recipe_hash, 10)}</span>
      </td>
      <td className="tabular py-2 pr-3 text-right font-mono text-xs">
        {group.n}
        {thin ? (
          <Badge variant="secondary" className="ml-1.5 text-[10px]">
            thin
          </Badge>
        ) : null}
      </td>
      <td className="tabular text-muted-foreground py-2 pr-3 text-right font-mono text-xs">
        {group.n_rated}
      </td>
      <td className="py-2 pr-3 text-right">
        <StarsRead value={group.mean_stars != null ? Number(group.mean_stars.toFixed(1)) : null} />
      </td>
      <td className="tabular text-signal py-2 pr-3 text-right font-mono text-xs">
        {secPerIt(group.mean_sec_per_it)}
      </td>
      <td className="py-2 text-right">
        {group.best_run_id ? (
          <Button variant="ghost" size="sm" render={<Link to={`/runs/${group.best_run_id}`}>Open</Link>} />
        ) : (
          <span className="text-muted-foreground text-xs">—</span>
        )}
      </td>
    </tr>
  )
}
