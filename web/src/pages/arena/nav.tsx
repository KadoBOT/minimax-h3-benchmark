import { NavLink } from "react-router"

import { cn } from "@/lib/utils"

const STOPS = [
  { to: "/arena", label: "Vote" },
  { to: "/arena/standings", label: "Standings" },
] as const

/** Two halves of one loop — cast a vote, read what the votes decided. */
export function ArenaNav() {
  return (
    <nav aria-label="Arena" className="border-rule mb-4 inline-flex rounded-md border p-0.5">
      {STOPS.map(({ to, label }) => (
        <NavLink
          key={to}
          to={to}
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
  )
}
