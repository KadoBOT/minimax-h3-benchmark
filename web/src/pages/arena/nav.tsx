import { Filter } from "lucide-react"
import { NavLink, useSearchParams } from "react-router"

import { cn } from "@/lib/utils"

const STOPS = [
  { to: "/arena", label: "Vote" },
  { to: "/arena/standings", label: "Standings" },
] as const

/** Helper to parse minStars from search params: defaults to 7 */
export function useArenaFilterParam(): number | null {
  const [searchParams] = useSearchParams()
  const raw = searchParams.get("min_stars")
  if (raw === "all" || raw === "0") return null
  if (raw && !isNaN(Number(raw))) return Number(raw)
  return 7
}

/** Two halves of one loop — cast a vote, read what the votes decided — with participant filtering. */
export function ArenaNav() {
  const [searchParams, setSearchParams] = useSearchParams()
  const raw = searchParams.get("min_stars")
  const currentValue = raw === "all" || raw === "0" ? "all" : (raw || "7")

  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <nav aria-label="Arena" className="border-rule inline-flex rounded-md border p-0.5">
        {STOPS.map(({ to, label }) => (
          <NavLink
            key={to}
            to={{ pathname: to, search: searchParams.toString() }}
            end
            className={({ isActive }) =>
              cn(
                "rounded-sm px-3 py-1 font-mono text-xs transition-colors",
                isActive ? "bg-signal/15 text-signal" : "text-muted-foreground hover:text-bone"
              )
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="flex items-center gap-2">
        <span className="edge-code text-muted-foreground flex items-center gap-1.5 text-xs">
          <Filter className="size-3.5 text-mint" />
          Participants:
        </span>
        <select
          aria-label="Filter participants by score"
          value={currentValue}
          onChange={(event) => {
            const val = event.target.value
            const nextParams = new URLSearchParams(searchParams)
            if (val === "7") {
              nextParams.delete("min_stars")
            } else {
              nextParams.set("min_stars", val)
            }
            setSearchParams(nextParams)
          }}
          className="border-rule bg-panel text-bone hover:border-mint-dim/60 focus:border-mint h-7 rounded-sm border px-2.5 font-mono text-xs transition-colors outline-none cursor-pointer"
        >
          <option value="7">Score &ge; 7 (Default)</option>
          <option value="8">Score &ge; 8</option>
          <option value="9">Score &ge; 9</option>
          <option value="5">Score &ge; 5</option>
          <option value="all">All runs</option>
        </select>
      </div>
    </div>
  )
}
