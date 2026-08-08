/**
 * The app shell: a fixed rail of destinations, the page, and the bench tray.
 *
 * The rail is narrow and permanent because the pages are one workflow, not a set of
 * features — queue something, judge it, compare it, vote on it, read the verdict, check the
 * ranking — and the loop is walked dozens of times a night.
 */

import { FlaskConical, GitCompare, Layers, ListVideo, Swords, Trophy } from "lucide-react"
import { NavLink } from "react-router"

import { useStatus } from "@/api/hooks"
import { useStream } from "@/api/events"
import { BenchTray } from "@/components/bench-tray"
import { LiveBadge } from "@/components/live-badge"
import { cn } from "@/lib/utils"

const DESTINATIONS = [
  { to: "/", label: "Lab", icon: FlaskConical, hint: "Queue a run or a sweep" },
  { to: "/runs", label: "Runs", icon: ListVideo, hint: "Scan and judge results" },
  { to: "/compare", label: "Compare", icon: GitCompare, hint: "Watch staged runs together" },
  { to: "/arena", label: "Arena", icon: Swords, hint: "Vote on like-for-like pairs" },
  { to: "/insights", label: "Insights", icon: Layers, hint: "What each setting is worth" },
  { to: "/leaderboard", label: "Ranking", icon: Trophy, hint: "Best runs on your weights" },
] as const

export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-ink flex min-h-screen">
      <Rail />
      <div className="flex min-w-0 flex-1 flex-col">
        <main className="min-w-0 flex-1 px-5 py-6 pb-28 lg:px-8">{children}</main>
      </div>
      <BenchTray />
    </div>
  )
}

function Rail() {
  const { data: status } = useStatus()
  const stream = useStream()
  const active = status?.active_run_id != null

  return (
    <nav
      aria-label="Sections"
      className="border-rule bg-sidebar sticky top-0 flex h-screen w-14 shrink-0 flex-col items-center gap-1 border-r py-3 lg:w-[13.5rem] lg:items-stretch lg:px-3"
    >
      <div className="mb-3 flex items-center gap-2.5 px-1 lg:px-1.5">
        <Mark active={active} />
        <div className="hidden min-w-0 lg:block">
          <div className="display text-bone text-[0.95rem] leading-none">H3 Lab</div>
          <div className="edge-code text-muted-foreground mt-1">bench for h3</div>
        </div>
      </div>

      {DESTINATIONS.map(({ to, label, icon: Icon, hint }) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/"}
          title={hint}
          className={({ isActive }) =>
            cn(
              "group relative flex items-center gap-2.5 rounded-md px-2 py-2 text-sm transition-colors",
              "text-muted-foreground hover:bg-sidebar-accent hover:text-bone",
              isActive && "bg-sidebar-accent text-bone"
            )
          }
        >
          {({ isActive }) => (
            <>
              <span
                aria-hidden
                className={cn(
                  "bg-signal absolute top-1.5 bottom-1.5 -left-3 w-[3px] rounded-r opacity-0 transition-opacity",
                  isActive && "opacity-100"
                )}
              />
              <Icon className="size-4 shrink-0" strokeWidth={1.9} />
              <span className="hidden lg:inline">{label}</span>
            </>
          )}
        </NavLink>
      ))}

      <div className="mt-auto hidden lg:block">
        <LiveBadge live={stream.live} status={status} />
      </div>
    </nav>
  )
}

/** The mark breathes only while a run is actually on the GPU. */
function Mark({ active }: { active: boolean }) {
  return (
    <span className="relative grid size-8 shrink-0 place-items-center">
      <svg viewBox="0 0 32 32" className="size-8" aria-hidden>
        <rect width="32" height="32" rx="4" className="fill-panel" />
        <g className="fill-bone/85">
          <rect x="5" y="9" width="7" height="6" rx="1" />
          <rect x="14" y="9" width="7" height="6" rx="1" />
          <rect x="23" y="9" width="4" height="6" rx="1" opacity=".45" />
          <rect x="5" y="18" width="7" height="6" rx="1" opacity=".45" />
        </g>
        <rect
          x="14"
          y="18"
          width="7"
          height="6"
          rx="1"
          className={cn("fill-signal", active && "motion-safe:animate-pulse")}
        />
        <rect x="23" y="18" width="4" height="6" rx="1" className="fill-mint" />
      </svg>
    </span>
  )
}
