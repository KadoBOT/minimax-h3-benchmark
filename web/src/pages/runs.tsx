/**
 * The Runs page: scan everything, judge quickly, stage what deserves a closer look.
 *
 * Judging fifty clips is a rhythm, not a series of decisions, so the whole flow is on the
 * keyboard: j/k to move, 1–9 and 0 to rate, f to favourite, c to stage, a to archive. The
 * mouse works too, but the keyboard is what makes a long session bearable.
 */

import { useEffect, useMemo, useRef, useState } from "react"
import { Keyboard, Search, X } from "lucide-react"
import { useNavigate } from "react-router"

import { useClearRating, usePatchRun, useRate, useRuns, useTags } from "@/api/hooks"
import type { Run } from "@/api/schema"
import { Failure, PageHeader, Section, StripSkeleton } from "@/components/page"
import { RunCard } from "@/components/run-card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useBench } from "@/lib/bench"
import { plural } from "@/lib/format"
import { Choice } from "@/pages/lab/config-form"
import type { RunListParams } from "@/api/hooks"

const SORTS: Record<string, string> = {
  recent: "Newest",
  stars: "Best rated",
  speed: "Fastest",
  elo: "Most preferred",
  label: "By label",
}

const STATUSES: Run["status"][] = ["succeeded", "running", "queued", "failed"]

export function RunsPage() {
  const [query, setQuery] = useState("")
  const [sort, setSort] = useState<RunListParams["sort"]>("recent")
  const [statuses, setStatuses] = useState<Run["status"][]>([])
  const [onlyFavourites, setOnlyFavourites] = useState(false)
  const [onlyRated, setOnlyRated] = useState<boolean | undefined>(undefined)
  const [tag, setTag] = useState("")
  const [showArchived, setShowArchived] = useState(false)
  const [cursor, setCursor] = useState(0)

  const bench = useBench()
  const navigate = useNavigate()
  const tags = useTags()
  const rate = useRate()
  const clearRating = useClearRating()
  const patch = usePatchRun()

  const params: RunListParams = useMemo(
    () => ({
      query: query.trim() || undefined,
      sort,
      status: statuses.length ? statuses : undefined,
      favourite: onlyFavourites ? true : undefined,
      rated: onlyRated,
      tag: tag || undefined,
      archived: showArchived ? undefined : false,
      limit: 60,
    }),
    [query, sort, statuses, onlyFavourites, onlyRated, tag, showArchived]
  )

  const runs = useRuns(params)
  const items = runs.data?.items ?? []
  const current = items[Math.min(cursor, Math.max(0, items.length - 1))]

  // Keep the cursor inside the list when a filter shortens it.
  useEffect(() => {
    if (cursor > items.length - 1) setCursor(Math.max(0, items.length - 1))
  }, [items.length, cursor])

  const searchBox = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      const typing =
        target?.tagName === "INPUT" || target?.tagName === "TEXTAREA" || target?.isContentEditable
      if (typing) {
        if (event.key === "Escape") target?.blur()
        return
      }
      if (event.metaKey || event.ctrlKey || event.altKey) return

      const run = current?.run
      const move = (delta: number) => {
        event.preventDefault()
        setCursor((index) => Math.min(items.length - 1, Math.max(0, index + delta)))
      }

      switch (event.key) {
        case "j":
        case "ArrowDown":
          return move(1)
        case "k":
        case "ArrowUp":
          return move(-1)
        case "/":
          event.preventDefault()
          return searchBox.current?.focus()
        case "Enter":
          if (run) navigate(`/runs/${run.id}`)
          return
        case "c":
          if (run) bench.toggle(run.id)
          return
        case "f":
          if (run) patch.mutate({ id: run.id, favourite: !run.favourite })
          return
        case "a":
          if (run) patch.mutate({ id: run.id, archived: !run.archived })
          return
        case "x":
          if (run) clearRating.mutate(run.id)
          return
        default:
          break
      }

      // 1–9 rate directly; 0 means ten, the way a keypad row reads left to right.
      if (/^[0-9]$/.test(event.key) && run) {
        const stars = event.key === "0" ? 10 : Number(event.key)
        rate.mutate({ id: run.id, stars })
        setCursor((index) => Math.min(items.length - 1, index + 1))
      }
    }

    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [current, items.length, bench, navigate, patch, rate, clearRating])

  // Keep the focused card on screen as the cursor moves.
  useEffect(() => {
    if (!current) return
    document
      .querySelector(`[data-run-id="${current.run.id}"]`)
      ?.scrollIntoView({ block: "nearest", behavior: "smooth" })
  }, [current])

  const active =
    statuses.length + (onlyFavourites ? 1 : 0) + (onlyRated !== undefined ? 1 : 0) + (tag ? 1 : 0)

  return (
    <>
      <PageHeader
        eyebrow={runs.data ? `${plural(runs.data.total, "run")}` : "Runs"}
        title="Judge the results"
        lede="Every run as a contact strip. Rate with the number keys and the list moves on by itself."
      >
        <KeyboardHint />
      </PageHeader>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-52 flex-1">
          <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2" />
          <Input
            ref={searchBox}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Search runs"
            placeholder="Search prompts, labels, notes  ( / )"
            className="pl-8"
          />
          {query ? (
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label="Clear the search"
              onClick={() => setQuery("")}
              className="absolute top-1/2 right-1.5 -translate-y-1/2"
            >
              <X className="size-3" />
            </Button>
          ) : null}
        </div>

        <Choice
          value={sort ?? "recent"}
          options={Object.keys(SORTS)}
          render={(value) => SORTS[value] ?? value}
          onChange={(value) => setSort(value as RunListParams["sort"])}
          label="Sort runs by"
          size="sm"
          className="w-36 shrink-0"
        />

        <ToggleGroup
          size="sm"
          value={statuses}
          onValueChange={(value) => setStatuses(value as Run["status"][])}
        >
          {STATUSES.map((status) => (
            <ToggleGroupItem key={status} value={status} className="capitalize">
              {status}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>

        <ToggleGroup
          size="sm"
          value={[
            ...(onlyFavourites ? ["favourite"] : []),
            ...(onlyRated === true ? ["rated"] : []),
            ...(onlyRated === false ? ["unrated"] : []),
            ...(showArchived ? ["archived"] : []),
          ]}
          onValueChange={(value) => {
            const picked = new Set(value as string[])
            setOnlyFavourites(picked.has("favourite"))
            setOnlyRated(picked.has("rated") ? true : picked.has("unrated") ? false : undefined)
            setShowArchived(picked.has("archived"))
          }}
        >
          <ToggleGroupItem value="favourite">Favourites</ToggleGroupItem>
          <ToggleGroupItem value="unrated">Unrated</ToggleGroupItem>
          <ToggleGroupItem value="rated">Rated</ToggleGroupItem>
          <ToggleGroupItem value="archived">Archived</ToggleGroupItem>
        </ToggleGroup>

        {tags.data && tags.data.length > 0 ? (
          <Choice
            value={tag}
            options={tags.data}
            onChange={setTag}
            label="Filter by tag"
            emptyLabel="Any tag"
            placeholder="Any tag"
            size="sm"
            className="w-32 shrink-0"
          />
        ) : null}

        {active > 0 ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setStatuses([])
              setOnlyFavourites(false)
              setOnlyRated(undefined)
              setTag("")
              setShowArchived(false)
            }}
          >
            Clear filters
          </Button>
        ) : null}
      </div>

      {runs.isError ? (
        <Failure error={runs.error} what="list the runs" onRetry={() => runs.refetch()} />
      ) : runs.isLoading ? (
        <StripSkeleton rows={6} />
      ) : items.length === 0 ? (
        <EmptyRuns filtered={active > 0 || query.length > 0} />
      ) : (
        <div className="space-y-2.5">
          {items.map((view, index) => (
            <RunCard
              key={view.run.id}
              view={view}
              selected={current?.run.id === view.run.id}
              onFocus={() => setCursor(index)}
            />
          ))}
        </div>
      )}

      {runs.data && runs.data.total > items.length ? (
        <p className="text-muted-foreground mt-4 text-center text-sm">
          Showing {items.length} of {runs.data.total}. Narrow the filters to see the rest.
        </p>
      ) : null}
    </>
  )
}

function EmptyRuns({ filtered }: { filtered: boolean }) {
  return (
    <Section title={filtered ? "Nothing matches" : "No runs yet"}>
      <p className="text-muted-foreground text-sm">
        {filtered
          ? "Loosen a filter, or clear them all. Archived runs are hidden unless you ask for them."
          : "Queue something on the Lab page. One config with three repeats is enough to start comparing."}
      </p>
    </Section>
  )
}

function KeyboardHint() {
  const keys: [string, string][] = [
    ["j / k", "move"],
    ["1–9, 0", "rate"],
    ["c", "stage"],
    ["f", "favourite"],
    ["a", "archive"],
    ["x", "unrate"],
    ["↵", "open"],
  ]
  return (
    <div className="border-rule bg-panel/60 hidden items-center gap-3 rounded-md border px-3 py-1.5 lg:flex">
      <Keyboard className="text-muted-foreground size-3.5 shrink-0" />
      {keys.map(([key, what]) => (
        <span key={key} className="edge-code text-muted-foreground whitespace-nowrap">
          <kbd className="text-bone/80">{key}</kbd> {what}
        </span>
      ))}
    </div>
  )
}
