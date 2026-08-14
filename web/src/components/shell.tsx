/**
 * The app shell: a fixed rail of destinations, the page, and the bench tray.
 *
 * The rail is narrow and permanent because the pages are one workflow, not a set of
 * features — queue something, judge it, compare it, vote on it, read the verdict, check the
 * ranking — and the loop is walked dozens of times a night.
 */

import { useState } from "react"
import { FlaskConical, GitCompare, Layers, ListVideo, Menu, Swords, Trophy, X } from "lucide-react"
import { NavLink } from "react-router"

import { useStatus } from "@/api/hooks"
import { useStream } from "@/api/events"
import { BenchTray } from "@/components/bench-tray"
import { LiveBadge } from "@/components/live-badge"
import { Button } from "@/components/ui/button"
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
  const [mobileOpen, setMobileOpen] = useState(false)
  const { data: status } = useStatus()
  const stream = useStream()
  const active = status?.active_run_id != null

  return (
    <div className="bg-ink flex min-h-dvh flex-col overflow-x-clip lg:flex-row">
      {/* Mobile Top Header */}
      <header className="border-rule bg-sidebar/95 sticky top-0 z-30 flex items-center justify-between gap-2 border-b px-3 py-2.5 backdrop-blur lg:hidden supports-[padding:max(0px)]:pt-[max(0.625rem,env(safe-area-inset-top))]">
        <div className="flex min-w-0 items-center gap-2">
          <Mark active={active} />
          <div className="min-w-0">
            <div className="display text-bone text-base leading-none">H3 Lab</div>
            <div className="edge-code text-muted-foreground text-[10px]">bench for h3</div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <LiveBadge live={stream.live} status={status} compact />
          <Button
            variant="ghost"
            size="icon"
            aria-label={mobileOpen ? "Close navigation menu" : "Open navigation menu"}
            onClick={() => setMobileOpen(!mobileOpen)}
            className="text-bone size-10"
          >
            {mobileOpen ? <X className="size-5" /> : <Menu className="size-5" />}
          </Button>
        </div>
      </header>

      {/* Mobile Nav Overlay Drawer */}
      {mobileOpen ? (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-xs lg:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden
        />
      ) : null}
      <div
        className={cn(
          "border-rule bg-sidebar fixed top-0 bottom-0 left-0 z-50 flex w-72 max-w-[80vw] flex-col border-r p-4 shadow-xl transition-transform duration-200 ease-in-out lg:hidden",
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <div className="mb-4 flex items-center justify-between border-b border-rule/60 pb-3">
          <div className="flex items-center gap-2.5">
            <Mark active={active} />
            <div>
              <div className="display text-bone text-base leading-none">H3 Lab</div>
              <div className="edge-code text-muted-foreground text-xs">bench for h3</div>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label="Close navigation"
            onClick={() => setMobileOpen(false)}
          >
            <X className="size-4" />
          </Button>
        </div>

        <nav aria-label="Mobile sections" className="flex flex-1 flex-col gap-1 overflow-y-auto">
          {DESTINATIONS.map(({ to, label, icon: Icon, hint }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              title={hint}
              onClick={() => setMobileOpen(false)}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2.5 text-sm transition-colors",
                  "text-muted-foreground hover:bg-sidebar-accent hover:text-bone",
                  isActive && "bg-sidebar-accent text-bone font-medium"
                )
              }
            >
              <Icon className="size-4 shrink-0" strokeWidth={1.9} />
              <div className="flex flex-col">
                <span>{label}</span>
                <span className="edge-code text-muted-foreground/70 text-[10px] font-normal">
                  {hint}
                </span>
              </div>
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto border-t border-rule/60 pt-3">
          <LiveBadge live={stream.live} status={status} />
        </div>
      </div>

      {/* Desktop Sidebar Rail */}
      <Rail />

      {/* Main Content Area */}
      <div className="flex min-w-0 flex-1 flex-col overflow-x-clip">
        <main className="min-w-0 flex-1 overflow-x-clip px-3 py-4 pb-36 sm:px-5 sm:py-6 sm:pb-28 lg:px-8 supports-[padding:max(0px)]:pb-[max(9rem,calc(env(safe-area-inset-bottom)+8rem))]">
          {children}
        </main>
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
      className="border-rule bg-sidebar sticky top-0 hidden h-screen w-[13.5rem] shrink-0 flex-col gap-1 border-r px-3 py-3 lg:flex"
    >
      <div className="mb-3 flex items-center gap-2.5 px-1.5">
        <Mark active={active} />
        <div className="min-w-0">
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
              <span>{label}</span>
            </>
          )}
        </NavLink>
      ))}

      <div className="mt-auto">
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
