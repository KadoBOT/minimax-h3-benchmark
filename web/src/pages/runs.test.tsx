/**
 * The judging flow, driven through the real DOM.
 *
 * These assert on what a person sees and does — a rendered strip, a keypress, a request the
 * server would receive — rather than on internal state, because the failure worth catching is
 * "the number keys stopped rating", not "a hook changed shape".
 */

import { act, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { RunsPage } from "@/pages/runs"
import {
  BASELINE_ROUTES,
  fakeApi,
  makeView,
  renderApp,
} from "@/test/harness"
import { FakeEventSource } from "@/test/setup"

function page(views = [makeView(), makeView()]) {
  return { items: views, total: views.length, limit: 60, offset: 0 }
}

/** Serves each /api/runs query only the statuses it asked for, so the three buckets do not duplicate. */
function runsByStatus(views: ReturnType<typeof makeView>[]) {
  return (url: URL) => {
    const wanted = url.searchParams.getAll("status")
    const items = wanted.length ? views.filter((view) => wanted.includes(view.run.status)) : views
    return page(items)
  }
}

describe("the runs list", () => {
  it("groups runs that were queued together", async () => {
    const views = [
      makeView({ run: { id: "a", batch_id: "q1", label: "sweep a" } }),
      makeView({ run: { id: "b", batch_id: "q1", label: "sweep b" } }),
      makeView({ run: { id: "c", batch_id: "q2", label: "lone" } }),
    ]
    fakeApi({ ...BASELINE_ROUTES, "/api/runs": runsByStatus(views) })
    renderApp(<RunsPage />)

    expect(await screen.findByText("sweep a")).toBeInTheDocument()
    expect(screen.getAllByTestId("run-batch")).toHaveLength(1)
    expect(screen.getByText("2 runs")).toBeInTheDocument()
    expect(screen.getByText("lone")).toBeInTheDocument()
  })

  it("pins a running run above finished ones", async () => {
    fakeApi({
      ...BASELINE_ROUTES,
      "/api/runs": runsByStatus([
        makeView({ run: { id: "done", label: "already done", status: "succeeded" } }),
        makeView({ run: { id: "live", label: "in flight", status: "running" } }),
      ]),
    })
    renderApp(<RunsPage />)

    const cards = await screen.findAllByTestId("run-card")
    expect(cards[0]).toHaveAttribute("data-run-id", "live")
    expect(cards[1]).toHaveAttribute("data-run-id", "done")
    expect(screen.getByRole("heading", { name: "In flight" })).toBeInTheDocument()
  })

  it("shows the live preview on a running run once ComfyUI draws a frame", async () => {
    fakeApi({
      ...BASELINE_ROUTES,
      "/api/runs": runsByStatus([
        makeView({ run: { id: "live", label: "in flight", status: "running" } }),
      ]),
    })
    renderApp(<RunsPage />)
    await screen.findByText("in flight")

    const source = FakeEventSource.instances.at(-1)!
    act(() => {
      source.emit({ seq: 1, kind: "run.started", run_id: "live", data: {} })
      source.emit({
        seq: 2,
        kind: "run.progress",
        run_id: "live",
        data: { step: 2, step_total: 4, preview_seq: 3, preview_mime: "image/jpeg" },
      })
    })

    const frame = await screen.findByRole("img", { name: /preview frame 3/i })
    expect(frame).toHaveAttribute("src", "/api/runs/live/preview?f=3")
  })

  it("keeps finished runs visible when the queue is long", async () => {
    const queued = Array.from({ length: 8 }, (_, index) =>
      makeView({ run: { id: `q${index}`, label: `waiting ${index}`, status: "queued" } })
    )
    fakeApi({
      ...BASELINE_ROUTES,
      "/api/runs": runsByStatus([
        ...queued,
        makeView({ run: { id: "done", label: "already done", status: "succeeded" } }),
      ]),
    })
    renderApp(<RunsPage />)

    expect(await screen.findByText("already done")).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Queued" })).toBeInTheDocument()
    expect(screen.getAllByTestId("run-card").length).toBeLessThan(8 + 1)
    expect(screen.getByRole("button", { name: /more queued/i })).toBeInTheDocument()
  })

  it("keeps the filter in the URL so opening a run and going back does not lose it", async () => {
    fakeApi({ ...BASELINE_ROUTES, "/api/runs": runsByStatus([makeView({ run: { id: "a" } })]) })
    renderApp(<RunsPage />, { route: "/runs?status=succeeded" })

    const chip = await screen.findByRole("button", { name: "succeeded" })
    expect(chip.getAttribute("aria-pressed") ?? chip.getAttribute("data-pressed")).toBeTruthy()
    const card = await screen.findByTestId("run-card")
    expect(card.querySelector("a")?.getAttribute("href")).toBe("/runs/a?status=succeeded")
  })

  it("shows a strip and an edge code for every run", async () => {
    const views = [
      makeView({ run: { id: "a", label: "euler · 20 steps" }, stars: 8 }),
      makeView({ run: { id: "b", label: "dpmpp · 20 steps" } }),
    ]
    fakeApi({ ...BASELINE_ROUTES, "/api/runs": runsByStatus(views) })

    renderApp(<RunsPage />)

    expect(await screen.findByText("euler · 20 steps")).toBeInTheDocument()
    expect(screen.getByText("dpmpp · 20 steps")).toBeInTheDocument()
    expect(screen.getAllByTestId("run-card")).toHaveLength(2)
    expect(screen.getAllByTestId("filmstrip")).toHaveLength(2)
  })

  it("dates every card by when its run finished", async () => {
    /**
     * A sweep is queued in one go, so creation times are identical across a page of cards and
     * tell you only when you pressed the button. Two runs from the same batch that finished
     * an hour apart have to read an hour apart.
     */
    const views = [
      makeView({
        run: {
          id: "a",
          status: "succeeded",
          created_at: new Date(Date.now() - 3 * 3_600_000).toISOString(),
          finished_at: new Date(Date.now() - 5 * 60_000).toISOString(),
        },
      }),
      makeView({
        run: {
          id: "b",
          status: "succeeded",
          created_at: new Date(Date.now() - 3 * 3_600_000).toISOString(),
          finished_at: new Date(Date.now() - 2 * 3_600_000).toISOString(),
        },
      }),
    ]
    fakeApi({ ...BASELINE_ROUTES, "/api/runs": runsByStatus(views) })

    renderApp(<RunsPage />)

    const ages = await screen.findAllByTestId("run-age")
    expect(ages.map((node) => node.textContent)).toEqual(["5 min ago", "2h ago"])
    expect(ages[0]).toHaveAttribute("title", expect.stringContaining("finished"))
  })

  it("rates the focused run when a number key is pressed", async () => {
    const views = [makeView({ run: { id: "a" } }), makeView({ run: { id: "b" } })]
    const { calls } = fakeApi({
      ...BASELINE_ROUTES,
      "/api/runs": runsByStatus(views),
      "PUT /api/runs/*/rating": () => views[0],
    })

    renderApp(<RunsPage />)
    await screen.findAllByTestId("run-card")

    await userEvent.keyboard("7")

    await waitFor(() => {
      const rating = calls.find((call) => call.method === "PUT" && call.path.endsWith("/rating"))
      expect(rating).toBeDefined()
      expect(rating?.path).toBe("/api/runs/a/rating")
      expect(rating?.body).toMatchObject({ stars: 7 })
    })
  })

  it("moves to the next run after a rating, so a session is one hand on the keyboard", async () => {
    const views = [makeView({ run: { id: "a" } }), makeView({ run: { id: "b" } })]
    const { calls } = fakeApi({
      ...BASELINE_ROUTES,
      "/api/runs": runsByStatus(views),
      "PUT /api/runs/*/rating": () => views[0],
    })

    renderApp(<RunsPage />)
    await screen.findAllByTestId("run-card")

    await userEvent.keyboard("5")
    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true))

    // The second card now carries the selection marker the first one had.
    await waitFor(() => {
      const cards = screen.getAllByTestId("run-card")
      expect(cards[1]).toHaveAttribute("data-selected")
    })

    await userEvent.keyboard("9")
    await waitFor(() => {
      const rated = calls.filter((call) => call.method === "PUT")
      expect(rated).toHaveLength(2)
      expect(rated[1]?.path).toBe("/api/runs/b/rating")
    })
  })

  it("reads 0 as ten, the way the number row reads left to right", async () => {
    const views = [makeView({ run: { id: "a" } })]
    const { calls } = fakeApi({
      ...BASELINE_ROUTES,
      "/api/runs": runsByStatus(views),
      "PUT /api/runs/*/rating": () => views[0],
    })

    renderApp(<RunsPage />)
    await screen.findAllByTestId("run-card")
    await userEvent.keyboard("0")

    await waitFor(() =>
      expect(calls.find((call) => call.method === "PUT")?.body).toMatchObject({ stars: 10 })
    )
  })

  it("stages a run onto the bench with c, and remembers it across a remount", async () => {
    const views = [makeView({ run: { id: "a" } })]
    fakeApi({ ...BASELINE_ROUTES, "/api/runs": runsByStatus(views) })

    const first = renderApp(<RunsPage />)
    await screen.findAllByTestId("run-card")
    await userEvent.keyboard("c")

    await waitFor(() =>
      expect(JSON.parse(window.localStorage.getItem("h3lab.bench") ?? "[]")).toContain("a")
    )
    first.unmount()

    renderApp(<RunsPage />)
    await screen.findAllByTestId("run-card")
    expect(JSON.parse(window.localStorage.getItem("h3lab.bench") ?? "[]")).toContain("a")
  })

  it("toggles a favourite with f", async () => {
    const views = [makeView({ run: { id: "a", favourite: false } })]
    const { calls } = fakeApi({
      ...BASELINE_ROUTES,
      "/api/runs": runsByStatus(views),
      "PATCH /api/runs/*": () => views[0],
    })

    renderApp(<RunsPage />)
    await screen.findAllByTestId("run-card")
    await userEvent.keyboard("f")

    await waitFor(() => {
      const patch = calls.find((call) => call.method === "PATCH")
      expect(patch?.path).toBe("/api/runs/a")
      expect(patch?.body).toMatchObject({ favourite: true })
    })
  })

  it("does not rate while the search box has focus", async () => {
    const views = [makeView({ run: { id: "a" } })]
    const { calls } = fakeApi({ ...BASELINE_ROUTES, "/api/runs": runsByStatus(views) })

    renderApp(<RunsPage />)
    await screen.findAllByTestId("run-card")

    const search = screen.getByPlaceholderText(/search prompts/i)
    await userEvent.click(search)
    await userEvent.keyboard("7")

    expect(search).toHaveValue("7")
    expect(calls.some((call) => call.method === "PUT")).toBe(false)
  })

  it("asks the server for the filter the user picked", async () => {
    const { fetchMock } = fakeApi({ ...BASELINE_ROUTES, "/api/runs": runsByStatus([]) })

    renderApp(<RunsPage />)
    await screen.findByText(/nothing matches|no runs yet/i)

    await userEvent.click(screen.getByRole("button", { name: /favourites/i }))

    await waitFor(() => {
      const urls = fetchMock.mock.calls.map(([input]) => String(input))
      expect(urls.some((url) => url.includes("/api/runs?") && url.includes("favourite=true"))).toBe(
        true
      )
    })
  })

  it("says what to do when there is nothing to judge", async () => {
    fakeApi({ ...BASELINE_ROUTES, "/api/runs": runsByStatus([]) })
    renderApp(<RunsPage />)
    expect(await screen.findByText(/queue something on the lab page/i)).toBeInTheDocument()
  })

  async function failedCard(error: string) {
    fakeApi({
      ...BASELINE_ROUTES,
      "/api/runs": runsByStatus([
        makeView({
          run: {
            id: "a",
            status: "failed",
            error,
            artifact: {
              video_path: null,
              poster_path: null,
              strip_path: null,
              width: null,
              height: null,
              fps: null,
              frame_count: null,
              size_bytes: null,
            },
          },
        }),
      ]),
    })
    renderApp(<RunsPage />)
    return await screen.findByTestId("filmstrip-placeholder")
  }

  it("shows the reason a run failed, not the bookkeeping around it", async () => {
    // The real string from a real failed generation, once the client puts the cause first.
    const placeholder = await failedCard(
      "execution_error at node 122: bootstrap_first_forecast requires warmup_steps <= 1" +
        " | execution_start | execution_cached"
    )
    expect(placeholder).toHaveTextContent("requires warmup_steps <= 1")
  })

  it("marks an error it had to clip, so a partial reason cannot read as the whole one", async () => {
    const placeholder = await failedCard(
      `execution_error at node 122: ${"a very long torch traceback ".repeat(12)}`
    )
    expect(placeholder.textContent).toContain("…")
    expect(placeholder).toHaveTextContent("execution_error at node 122")
  })

  it("names the failure instead of showing an empty list", async () => {
    fakeApi({
      ...BASELINE_ROUTES,
      "/api/runs": () =>
        new Response(
          JSON.stringify({ error: "the database is locked", detail: "try again", kind: "internal" }),
          { status: 500, headers: { "Content-Type": "application/json" } }
        ),
    })

    renderApp(<RunsPage />)
    const alert = await screen.findByRole("alert")
    expect(within(alert).getByText("the database is locked")).toBeInTheDocument()
  })
})
