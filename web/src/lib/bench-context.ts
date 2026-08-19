import { createContext, useContext } from "react"

export const BENCH_LIMIT = 4

export type Bench = {
  ids: string[]
  has: (id: string) => boolean
  toggle: (id: string) => void
  add: (id: string) => void
  remove: (id: string) => void
  clear: () => void
  replace: (ids: string[]) => void
  full: boolean
}

export const BenchContext = createContext<Bench | null>(null)

export function useBench(): Bench {
  const value = useContext(BenchContext)
  if (!value) throw new Error("useBench must be used inside a BenchProvider")
  return value
}
