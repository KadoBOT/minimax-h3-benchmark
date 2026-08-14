/**
 * The bench: runs staged for comparison.
 *
 * It outlives navigation on purpose. Picking candidates happens while scanning the Runs list,
 * but the comparison happens on another page — losing the selection in between was the single
 * most annoying thing about the old lab. Persisted to `localStorage` so a reload keeps it too.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react"

const STORAGE_KEY = "h3lab.bench"
export const BENCH_LIMIT = 4

type Bench = {
  ids: string[]
  has: (id: string) => boolean
  toggle: (id: string) => void
  add: (id: string) => void
  remove: (id: string) => void
  clear: () => void
  replace: (ids: string[]) => void
  full: boolean
}

const BenchContext = createContext<Bench | null>(null)

function load(): string[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : null
    return Array.isArray(parsed) ? parsed.filter((id) => typeof id === "string") : []
  } catch {
    return []
  }
}

export function BenchProvider({ children }: { children: React.ReactNode }) {
  const [ids, setIds] = useState<string[]>(load)

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(ids))
    } catch {
      // A private window with storage denied is not a reason to break the page.
    }
  }, [ids])

  const add = useCallback((id: string) => {
    setIds((current) =>
      current.includes(id) || current.length >= BENCH_LIMIT ? current : [...current, id]
    )
  }, [])

  const remove = useCallback((id: string) => {
    setIds((current) => current.filter((item) => item !== id))
  }, [])

  const toggle = useCallback((id: string) => {
    setIds((current) => {
      if (current.includes(id)) return current.filter((item) => item !== id)
      // Staging a fifth run drops the oldest rather than silently doing nothing.
      const next = current.length >= BENCH_LIMIT ? current.slice(1) : current
      return [...next, id]
    })
  }, [])

  const value = useMemo<Bench>(
    () => ({
      ids,
      has: (id: string) => ids.includes(id),
      toggle,
      add,
      remove,
      clear: () => setIds([]),
      replace: (next: string[]) => setIds(next.slice(0, BENCH_LIMIT)),
      full: ids.length >= BENCH_LIMIT,
    }),
    [ids, toggle, add, remove]
  )

  return <BenchContext.Provider value={value}>{children}</BenchContext.Provider>
}

export function useBench(): Bench {
  const value = useContext(BenchContext)
  if (!value) throw new Error("useBench must be used inside a BenchProvider")
  return value
}
