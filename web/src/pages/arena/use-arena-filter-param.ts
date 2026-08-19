import { useSearchParams } from "react-router"

/** Parse the arena's minimum-star filter, defaulting to seven. */
export function useArenaFilterParam(): number | null {
  const [searchParams] = useSearchParams()
  const raw = searchParams.get("min_stars")
  if (raw === "all" || raw === "0") return null
  if (raw && !Number.isNaN(Number(raw))) return Number(raw)
  return 7
}
