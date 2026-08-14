import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { BrowserRouter, Route, Routes } from "react-router"

import { ApiError } from "@/api/client"
import { EventStreamProvider } from "@/api/events"
import { Shell } from "@/components/shell"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { BenchProvider } from "@/lib/bench"
import { ArenaPage } from "@/pages/arena"
import { StandingsPage } from "@/pages/arena/standings"
import { ComparePage } from "@/pages/compare"
import { InsightsPage } from "@/pages/insights"
import { LabPage } from "@/pages/lab"
import { LeaderboardPage } from "@/pages/leaderboard"
import { NotFoundPage } from "@/pages/not-found"
import { RunPage } from "@/pages/run"
import { RunsPage } from "@/pages/runs"

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // The event stream is what keeps data fresh, so refetching on every window focus
        // would be noise. A short stale time still coalesces bursts of navigation.
        refetchOnWindowFocus: false,
        staleTime: 5_000,
        retry: (attempt, error) =>
          // A 404 or a bad field will not become true by asking again.
          attempt < 2 && (!(error instanceof ApiError) || error.transient),
      },
      mutations: { retry: false },
    },
  })
}

const client = makeQueryClient()

export function App() {
  return (
    <QueryClientProvider client={client}>
      <BenchProvider>
        <EventStreamProvider>
          <TooltipProvider delay={400}>
            <BrowserRouter>
              <Shell>
                <Routes>
                  <Route path="/" element={<LabPage />} />
                  <Route path="/runs" element={<RunsPage />} />
                  <Route path="/runs/:runId" element={<RunPage />} />
                  <Route path="/compare" element={<ComparePage />} />
                  <Route path="/arena" element={<ArenaPage />} />
                  <Route path="/arena/standings" element={<StandingsPage />} />
                  <Route path="/insights" element={<InsightsPage />} />
                  <Route path="/insights/:axis" element={<InsightsPage />} />
                  <Route path="/leaderboard" element={<LeaderboardPage />} />
                  <Route path="*" element={<NotFoundPage />} />
                </Routes>
              </Shell>
            </BrowserRouter>
            <Toaster />
          </TooltipProvider>
        </EventStreamProvider>
      </BenchProvider>
    </QueryClientProvider>
  )
}
