/**
 * The Runs page: scan everything, judge quickly, stage what deserves a closer look.
 *
 * Judging fifty clips is a rhythm, not a series of decisions, so the whole flow is on the
 * keyboard: j/k to move, 1–9 and 0 to rate, f to favourite, c to stage, a to archive. The
 * mouse works too, but the keyboard is what makes a long session bearable.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Keyboard, Search, X } from "lucide-react"
import { useNavigate, useSearchParams } from "react-router"

import { useClearRating, usePatchRun, useRate, useRuns, useTags } from "@/api/hooks"
import type { Run, RunView } from "@/api/schema"
import { Failure, PageHeader, Section, StripSkeleton } from "@/components/page"
import { RunCard } from "@/components/run-card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useBench } from "@/lib/bench-context"
import { plural } from "@/lib/format"
import { filtersFromSearch, runListParams, searchFromFilters, type RunFilters } from "@/lib/run-filters"
import { Choice } from "@/components/choice"
import type { RunListParams } from "@/api/hooks"

const SORTS: Record<string, string> = {
  recent: "Newest",
  stars: "Best rated",
  speed: "Fastest",
  elo: "Most preferred",
  label: "By label",
}

const STATUSES: Run["status"][] = ["succeeded", "running", "queued", "failed"]
const REST_STATUSES: Run["status"][] = ["succeeded", "failed", "cancelled", "interrupted"]
const QUEUED_PREVIEW = 3
const EMPTY_RUNS: RunView[] = []

export function RunsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = useMemo(() => filtersFromSearch(searchParams), [searchParams])
  const writeFilters = (next: RunFilters, replace = false) => {
    setSearchParams(searchFromFilters(next), { replace })
  }

  const { query, sort, statuses, onlyFavourites, onlyRated, tag, showArchived } = filters
  const [cursor, setCursor] = useState(0)

  const bench = useBench()
  const navigate = useNavigate()
  const tags = useTags()
  const rate = useRate()
  const clearRating = useClearRating()
  const patch = usePatchRun()

  const params: RunListParams = useMemo(() => runListParams(filters), [filters])
  const listing = searchParams.toString()
  const open = useCallback(
    (id: string) => navigate(listing ? `/runs/${id}?${listing}` : `/runs/${id}`),
    [listing, navigate]
  )

  const restStatuses = statuses.length
    ? statuses.filter((status) => REST_STATUSES.includes(status))
    : REST_STATUSES

  const running = useRuns({ status: ["running"], archived: showArchived ? undefined : false, limit: 20 })
  const queued = useRuns({
    status: ["queued"],
    archived: showArchived ? undefined : false,
    sort: "oldest",
    limit: 200,
  })
  const rest = useRuns(
    { ...params, status: restStatuses, limit: 60 },
    { enabled: restStatuses.length > 0 }
  )

  const runningItems = running.data?.items ?? EMPTY_RUNS
  const queuedItems = queued.data?.items ?? EMPTY_RUNS
  const restItems = rest.data?.items ?? EMPTY_RUNS
  const [queueOpen, setQueueOpen] = useState(false)
  const queuedShown = useMemo(
    () => (queueOpen ? queuedItems : queuedItems.slice(0, QUEUED_PREVIEW)),
    [queueOpen, queuedItems]
  )
  const items = useMemo(
    () => [...runningItems, ...queuedShown, ...restItems],
    [queuedShown, restItems, runningItems]
  )
  const lastIndex = Math.max(0, items.length - 1)
  const current = items[Math.min(cursor, lastIndex)]
  const empty = runningItems.length + queuedItems.length + restItems.length === 0
  const loading = (running.isLoading || queued.isLoading || rest.isLoading) && empty
  const failed = running.isError && queued.isError && (rest.isError || restStatuses.length === 0)

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
        setCursor((index) =>
          Math.min(lastIndex, Math.max(0, Math.min(index, lastIndex) + delta))
        )
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
          if (run) open(run.id)
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
        setCursor((index) => Math.min(lastIndex, Math.min(index, lastIndex) + 1))
      }
    }

    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [current, lastIndex, bench, open, patch, rate, clearRating])

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
        eyebrow={
          rest.data
            ? `${plural((rest.data.total ?? 0) + runningItems.length + queuedItems.length, "run")}`
            : "Runs"
        }
        title="Judge the results"
        lede="Every run as a contact strip. Rate with the number keys and the list moves on by itself."
      >
        <KeyboardHint />
      </PageHeader>

      <div className="mb-4 flex flex-col sm:flex-row flex-wrap items-stretch sm:items-center gap-2">
        <div className="relative w-full sm:w-auto sm:min-w-52 flex-1">
          <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2" />
          <Input
            ref={searchBox}
            value={query}
            onChange={(event) => writeFilters({ ...filters, query: event.target.value }, true)}
            aria-label="Search runs"
            placeholder="Search prompts, labels, notes  ( / )"
            className="pl-8"
          />
          {query ? (
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label="Clear the search"
              onClick={() => writeFilters({ ...filters, query: "" }, true)}
              className="absolute top-1/2 right-1.5 -translate-y-1/2"
            >
              <X className="size-3" />
            </Button>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto">
          <Choice
            value={sort ?? "recent"}
            options={Object.keys(SORTS)}
            render={(value) => SORTS[value] ?? value}
            onChange={(value) => writeFilters({ ...filters, sort: value as RunFilters["sort"] })}
            label="Sort runs by"
            size="sm"
            className="w-full sm:w-36 shrink-0"
          />

          {tags.data && tags.data.length > 0 ? (
            <Choice
              value={tag}
              options={tags.data}
              onChange={(value) => writeFilters({ ...filters, tag: value })}
              label="Filter by tag"
              emptyLabel="Any tag"
              placeholder="Any tag"
              size="sm"
              className="w-full sm:w-32 shrink-0"
            />
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-2 overflow-x-auto max-w-full py-0.5">
          <ToggleGroup
            size="sm"
            value={statuses}
            onValueChange={(value) => writeFilters({ ...filters, statuses: value as Run["status"][] })}
            className="flex-wrap sm:flex-nowrap"
          >
            {STATUSES.map((status) => (
              <ToggleGroupItem key={status} value={status} className="capitalize text-xs px-2 sm:px-2.5">
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
              writeFilters({
                ...filters,
                onlyFavourites: picked.has("favourite"),
                onlyRated: picked.has("rated") ? true : picked.has("unrated") ? false : undefined,
                showArchived: picked.has("archived"),
              })
            }}
            className="flex-wrap sm:flex-nowrap"
          >
            <ToggleGroupItem value="favourite" className="text-xs px-2 sm:px-2.5">Favourites</ToggleGroupItem>
            <ToggleGroupItem value="unrated" className="text-xs px-2 sm:px-2.5">Unrated</ToggleGroupItem>
            <ToggleGroupItem value="rated" className="text-xs px-2 sm:px-2.5">Rated</ToggleGroupItem>
            <ToggleGroupItem value="archived" className="text-xs px-2 sm:px-2.5">Archived</ToggleGroupItem>
          </ToggleGroup>

          {active > 0 ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                writeFilters({
                  ...filters,
                  statuses: [],
                  onlyFavourites: false,
                  onlyRated: undefined,
                  tag: "",
                  showArchived: false,
                })
              }
              className="text-xs"
            >
              Clear filters
            </Button>
          ) : null}
        </div>
      </div>

      {failed ? (
        <Failure
          error={rest.error ?? running.error ?? queued.error}
          what="list the runs"
          onRetry={() => {
            void running.refetch()
            void queued.refetch()
            void rest.refetch()
          }}
        />
      ) : loading ? (
        <StripSkeleton rows={6} />
      ) : empty ? (
        <EmptyRuns filtered={active > 0 || query.length > 0} />
      ) : (
        <div className="space-y-4">
          {runningItems.length > 0 ? (
            <Lane title="In flight" hint="What the GPU is doing right now." testId="runs-running">
              {runningItems.map((view) => (
                <RunCard
                  key={view.run.id}
                  view={view}
                  selected={current?.run.id === view.run.id}
                  onFocus={() => setCursor(items.indexOf(view))}
                />
              ))}
            </Lane>
          ) : null}

          {queuedItems.length > 0 ? (
            <Lane
              title="Queued"
              hint={`${plural(queuedItems.length, "run")} waiting.`}
              testId="runs-queued"
              actions={
                queuedItems.length > QUEUED_PREVIEW ? (
                  <Button variant="ghost" size="sm" onClick={() => setQueueOpen((open) => !open)}>
                    {queueOpen
                      ? "Show fewer"
                      : `${queuedItems.length - QUEUED_PREVIEW} more queued`}
                  </Button>
                ) : null
              }
            >
              {groupByBatch(queuedShown).map((group) => (
                <BatchBlock
                  key={group.batchId ?? group.items[0]!.run.id}
                  group={group}
                  items={items}
                  currentId={current?.run.id}
                  onFocus={setCursor}
                />
              ))}
            </Lane>
          ) : null}

          {restItems.length > 0 ? (
            <Lane title="Done" hint="Finished, failed, or cancelled." testId="runs-done">
              {groupByBatch(restItems).map((group) => (
                <BatchBlock
                  key={group.batchId ?? group.items[0]!.run.id}
                  group={group}
                  items={items}
                  currentId={current?.run.id}
                  onFocus={setCursor}
                />
              ))}
            </Lane>
          ) : null}
        </div>
      )}

      {rest.data && rest.data.total > restItems.length ? (
        <p className="text-muted-foreground mt-4 text-center text-sm">
          Showing {restItems.length} of {rest.data.total} finished. Narrow the filters to see the rest.
        </p>
      ) : null}
    </>
  )
}

function Lane({
  title,
  hint,
  testId,
  actions,
  children,
}: {
  title: string
  hint?: string
  testId: string
  actions?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <Section title={title} hint={hint} actions={actions}>
      <div className="space-y-2.5" data-testid={testId}>
        {children}
      </div>
    </Section>
  )
}

function BatchBlock({
  group,
  items,
  currentId,
  onFocus,
}: {
  group: { batchId: string | null; items: RunView[] }
  items: RunView[]
  currentId?: string
  onFocus: (index: number) => void
}) {
  const body = group.items.map((view) => (
    <RunCard
      key={view.run.id}
      view={view}
      selected={currentId === view.run.id}
      onFocus={() => onFocus(items.findIndex((item) => item.run.id === view.run.id))}
    />
  ))
  if (group.items.length === 1) return body
  return (
    <section data-testid="run-batch" className="border-rule/70 space-y-2 rounded-lg border p-2">
      <header className="text-muted-foreground flex items-baseline justify-between px-0.5 text-xs">
        <span className="text-bone/80 font-medium">Queued together</span>
        <span className="edge-code">{plural(group.items.length, "run")}</span>
      </header>
      {body}
    </section>
  )
}

function groupByBatch(items: RunView[]): { batchId: string | null; items: RunView[] }[] {
  const groups: { batchId: string | null; items: RunView[] }[] = []
  for (const view of items) {
    const batchId = view.run.batch_id ?? null
    const last = groups.at(-1)
    if (last && batchId && last.batchId === batchId) {
      last.items.push(view)
    } else {
      groups.push({ batchId, items: [view] })
    }
  }
  return groups
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
