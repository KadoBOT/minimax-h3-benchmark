/**
 * The runs listing's filters, as URL search params.
 *
 * A filter that only lives in React state dies when the person opens a run and hits back.
 * The query string is the list they were looking at, so the same string on `/runs/{id}`
 * is also how next/prev stay inside that list.
 */

import type { Run } from "@/api/schema"
import type { RunListParams } from "@/api/hooks"

export type RunFilters = {
  query: string
  sort: NonNullable<RunListParams["sort"]>
  statuses: Run["status"][]
  onlyFavourites: boolean
  onlyRated: boolean | undefined
  tag: string
  showArchived: boolean
}

const SORTS = new Set<RunFilters["sort"]>(["recent", "oldest", "stars", "speed", "elo", "label"])
const STATUSES = new Set<Run["status"]>(["queued", "running", "succeeded", "failed", "cancelled", "interrupted"])

export function filtersFromSearch(search: URLSearchParams): RunFilters {
  const sort = search.get("sort")
  const rated = search.get("rated")
  return {
    query: search.get("q") ?? "",
    sort: sort && SORTS.has(sort as RunFilters["sort"]) ? (sort as RunFilters["sort"]) : "recent",
    statuses: (search.get("status") ?? "")
      .split(",")
      .filter((value): value is Run["status"] => STATUSES.has(value as Run["status"])),
    onlyFavourites: search.get("fav") === "1",
    onlyRated: rated === "1" ? true : rated === "0" ? false : undefined,
    tag: search.get("tag") ?? "",
    showArchived: search.get("archived") === "1",
  }
}

export function searchFromFilters(filters: RunFilters): URLSearchParams {
  const search = new URLSearchParams()
  if (filters.query.trim()) search.set("q", filters.query.trim())
  if (filters.sort !== "recent") search.set("sort", filters.sort)
  if (filters.statuses.length) search.set("status", filters.statuses.join(","))
  if (filters.onlyFavourites) search.set("fav", "1")
  if (filters.onlyRated === true) search.set("rated", "1")
  if (filters.onlyRated === false) search.set("rated", "0")
  if (filters.tag) search.set("tag", filters.tag)
  if (filters.showArchived) search.set("archived", "1")
  return search
}

export function runListParams(filters: RunFilters): RunListParams {
  return {
    query: filters.query.trim() || undefined,
    sort: filters.sort,
    status: filters.statuses.length ? filters.statuses : undefined,
    favourite: filters.onlyFavourites ? true : undefined,
    rated: filters.onlyRated,
    tag: filters.tag || undefined,
    archived: filters.showArchived ? undefined : false,
    limit: 60,
  }
}

export function neighborParams(search: URLSearchParams): RunListParams {
  const filters = filtersFromSearch(search)
  return { ...runListParams(filters), limit: 500 }
}
