/**
 * The live spine.
 *
 * A dropped stream that silently stops updating is the worst failure this app can have — the
 * page looks fine and is quietly wrong — so the reconnect cursor and the per-event
 * invalidation are both asserted here rather than left to be noticed in use.
 */

import { act, render, screen, waitFor } from "@testing-library/react"
import { QueryClientProvider } from "@tanstack/react-query"
import { Toaster } from "@/components/ui/sonner"
import { describe, expect, it } from "vitest"

import { EventStreamProvider, useStream } from "@/api/events"
import { FakeEventSource } from "@/test/setup"
import { testClient } from "@/test/harness"

function Readout() {
  const { live, seq, progress } = useStream()
  return (
    <div>
      <span data-testid="live">{live ? "live" : "down"}</span>
      <span data-testid="seq">{seq}</span>
      <span data-testid="step">{progress ? `${progress.step}/${progress.stepTotal}` : "idle"}</span>
      <span data-testid="rate">{progress?.secPerIt ?? "—"}</span>
    </div>
  )
}

function mount() {
  const client = testClient()
  render(
    <QueryClientProvider client={client}>
      <EventStreamProvider>
        <Readout />
        <Toaster />
      </EventStreamProvider>
    </QueryClientProvider>
  )
  return { client, source: () => FakeEventSource.instances.at(-1)! }
}

describe("the event stream", () => {
  it("opens one connection and reports it as live", async () => {
    const { source } = mount()
    expect(FakeEventSource.instances).toHaveLength(1)

    act(() => source().onopen?.(new Event("open")))
    await waitFor(() => expect(screen.getByTestId("live")).toHaveTextContent("live"))
  })

  it("tracks progress without refetching anything", async () => {
    const { client, source } = mount()
    const before = client.getQueryCache().getAll().length

    act(() => {
      source().emit({ seq: 1, kind: "run.started", run_id: "a", data: {} })
      source().emit({
        seq: 2,
        kind: "run.progress",
        run_id: "a",
        data: { step: 7, step_total: 20, sec_per_it: 1.25, node_label: "sampler" },
      })
    })

    await waitFor(() => expect(screen.getByTestId("step")).toHaveTextContent("7/20"))
    expect(screen.getByTestId("rate")).toHaveTextContent("1.25")
    expect(client.getQueryCache().getAll()).toHaveLength(before)
  })

  it("keeps the last known rate while the next tick has none", async () => {
    const { source } = mount()
    act(() => {
      source().emit({ seq: 1, kind: "run.started", run_id: "a", data: {} })
      source().emit({ seq: 2, kind: "run.progress", run_id: "a", data: { step: 1, step_total: 20, sec_per_it: 2 } })
      source().emit({ seq: 3, kind: "run.progress", run_id: "a", data: { step: 2, step_total: 20 } })
    })

    await waitFor(() => expect(screen.getByTestId("step")).toHaveTextContent("2/20"))
    expect(screen.getByTestId("rate")).toHaveTextContent("2")
  })

  it("clears progress when the run finishes", async () => {
    const { source } = mount()
    act(() => {
      source().emit({ seq: 1, kind: "run.started", run_id: "a", data: {} })
      source().emit({ seq: 2, kind: "run.progress", run_id: "a", data: { step: 3, step_total: 20 } })
      source().emit({ seq: 3, kind: "run.finished", run_id: "a", data: {} })
    })
    await waitFor(() => expect(screen.getByTestId("step")).toHaveTextContent("idle"))
  })

  it("reconnects from the last sequence it saw, so nothing is missed", async () => {
    const { source } = mount()
    act(() => source().emit({ seq: 12, kind: "heartbeat", data: {} }))
    await waitFor(() => expect(screen.getByTestId("seq")).toHaveTextContent("12"))

    act(() => source().onerror?.(new Event("error")))
    await waitFor(() => expect(screen.getByTestId("live")).toHaveTextContent("down"))

    await waitFor(
      () => {
        expect(FakeEventSource.instances).toHaveLength(2)
        expect(FakeEventSource.instances[1]?.url).toContain("after=12")
      },
      { timeout: 4000 }
    )
  })

  it("ignores a malformed frame rather than tearing the stream down", async () => {
    const { source } = mount()
    act(() => source().onmessage?.({ data: "{not json" } as MessageEvent))
    act(() => source().emit({ seq: 4, kind: "heartbeat", data: {} }))
    await waitFor(() => expect(screen.getByTestId("seq")).toHaveTextContent("4"))
  })

  it("says so when the lab notices a workflow file changed", async () => {
    const { source } = mount()
    act(() =>
      source().emit({
        seq: 1,
        kind: "lab.message",
        data: { text: "the flf2v workflow changed on disk and was reloaded", mode: "flf2v" },
      })
    )
    expect(await screen.findByText(/flf2v workflow changed on disk/i)).toBeInTheDocument()
  })

  it("refreshes the derived views when a run finishes", async () => {
    const { client, source } = mount()
    client.setQueryData(["runs", {}], { items: [], total: 0, limit: 60, offset: 0 })
    client.setQueryData(["leaderboard", 70, 30, 50], { entries: [], considered: 0, unrated: 0 })

    act(() => source().emit({ seq: 1, kind: "run.finished", run_id: "a", data: {} }))

    await waitFor(() => {
      const stale = client
        .getQueryCache()
        .getAll()
        .filter((query) => query.isStale())
      expect(stale.length).toBeGreaterThanOrEqual(2)
    })
  })
})
