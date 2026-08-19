import { act, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Route, Routes } from "react-router"
import { describe, expect, it } from "vitest"

import { RunPage } from "@/pages/run"
import type { RunView } from "@/api/schema"
import { BASELINE_ROUTES, fakeApi, makeView, renderApp } from "@/test/harness"
import { FakeEventSource } from "@/test/setup"

function open(view: RunView = makeView({ run: { id: "r1", label: "h3/mod · 20st", tags: ["keeper"] } })) {
  const api = fakeApi({
    ...BASELINE_ROUTES,
    "/api/runs/r1": view,
    "/api/runs/r1/neighbors": { prev: null, next: null },
    "PUT /api/runs/r1/rating": { ...view, stars: 8 },
    "PATCH /api/runs/r1": view,
    "POST /api/runs/r1/rerun": view,
    "POST /api/presets": { id: "p1", name: "keeper", config: view.run.config, created_at: "" },
  })
  const rendered = renderApp(
    <Routes>
      <Route path="/runs/:runId" element={<RunPage />} />
    </Routes>,
    { route: "/runs/r1" }
  )
  return { ...rendered, ...api }
}

describe("a single run", () => {
  it("links to the previous and next run in the listing", async () => {
    const view = makeView({ run: { id: "r1", label: "h3/mod · 20st" } })
    fakeApi({
      ...BASELINE_ROUTES,
      "/api/runs/r1": view,
      "/api/runs/r1/neighbors": {
        prev: makeView({ run: { id: "r0", label: "older" } }),
        next: makeView({ run: { id: "r2", label: "newer" } }),
      },
    })
    renderApp(
      <Routes>
        <Route path="/runs/:runId" element={<RunPage />} />
      </Routes>,
      { route: "/runs/r1?status=succeeded" }
    )
    await screen.findByText("h3/mod · 20st")
    expect(await screen.findByRole("link", { name: /prev/i })).toHaveAttribute(
      "href",
      "/runs/r0?status=succeeded"
    )
    expect(screen.getByRole("link", { name: /next/i })).toHaveAttribute(
      "href",
      "/runs/r2?status=succeeded"
    )
  })

  it("shows the live preview while the run is still rendering", async () => {
    const view = makeView({
      run: { id: "r1", label: "h3/mod · 20st", status: "running", artifact: {} },
    })
    fakeApi({
      ...BASELINE_ROUTES,
      "/api/runs/r1": view,
      "/api/runs/r1/neighbors": { prev: null, next: null },
    })
    renderApp(
      <Routes>
        <Route path="/runs/:runId" element={<RunPage />} />
      </Routes>,
      { route: "/runs/r1" }
    )
    await screen.findByText("h3/mod · 20st")
    expect(screen.getByText("Rendering…")).toBeInTheDocument()

    const source = FakeEventSource.instances.at(-1)!
    act(() => {
      source.emit({ seq: 1, kind: "run.started", run_id: "r1", data: {} })
      source.emit({
        seq: 2,
        kind: "run.progress",
        run_id: "r1",
        data: { step: 2, step_total: 8, preview_seq: 4, preview_mime: "video/mp4" },
      })
    })

    const clip = await screen.findByLabelText(/preview frame 4/i)
    expect(clip.tagName).toBe("VIDEO")
    expect(clip).toHaveAttribute("src", "/api/runs/r1/preview?f=4")
    expect(screen.getByText(/step 2 of 8/i)).toBeInTheDocument()
  })

  it("plays the video and shows what the run cost", async () => {
    open()
    expect(await screen.findByText("h3/mod · 20st")).toBeInTheDocument()
    const video = document.querySelector("video")
    expect(video).toHaveAttribute("src", "/api/media/videos/r1.mp4")
    expect(video).toHaveAttribute("autoplay")
    expect(video).toHaveAttribute("loop")
    expect(screen.getByText(/1\.50.s\/it/)).toBeInTheDocument()
    expect(screen.getByText("832×480")).toBeInTheDocument()
  })

  it("saves a star rating on the ten-point scale", async () => {
    const { calls } = open()
    await screen.findByText("h3/mod · 20st")

    const rating = screen.getAllByTestId("star-rating")[0]!
    await userEvent.click(within(rating).getByRole("button", { name: "8 out of 10" }))

    await waitFor(() => {
      const put = calls.find((call) => call.method === "PUT")
      expect(put?.path).toBe("/api/runs/r1/rating")
      expect(put?.body).toMatchObject({ stars: 8 })
    })
  })

  it("offers the criteria the API defines rather than a hardcoded list", async () => {
    open()
    await screen.findByText("h3/mod · 20st")

    for (const label of [
      "Motion",
      "Prompt adherence",
      "Artifact-free",
      "Detail",
      "Temporal consistency",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it("saves a criterion alongside a star rating", async () => {
    const { calls } = open()
    await screen.findByText("h3/mod · 20st")

    await userEvent.click(screen.getByRole("button", { name: "Motion: 4 of 5" }))

    await waitFor(() => {
      const put = calls.find((call) => call.method === "PUT")
      expect(put?.body).toMatchObject({ criteria: { motion: 4 } })
    })
  })

  it("adds a tag", async () => {
    const { calls } = open()
    await screen.findByText("h3/mod · 20st")
    expect(screen.getByText("keeper")).toBeInTheDocument()

    await userEvent.type(screen.getByPlaceholderText(/add a tag/i), "overnight{Enter}")

    await waitFor(() => {
      const patch = calls.find((call) => call.method === "PATCH")
      expect(patch?.body).toMatchObject({ tags: ["keeper", "overnight"] })
    })
  })

  it("only offers to save a note once one has been typed", async () => {
    open()
    await screen.findByText("h3/mod · 20st")

    expect(screen.queryByRole("button", { name: /save note/i })).not.toBeInTheDocument()
    await userEvent.type(screen.getByPlaceholderText(/hands melt/i), "grain in the sky")
    expect(await screen.findByRole("button", { name: /save note/i })).toBeInTheDocument()
  })

  it("queues the same config again", async () => {
    const { calls } = open()
    await screen.findByText("h3/mod · 20st")
    await userEvent.click(screen.getByRole("button", { name: /run again/i }))

    await waitFor(() =>
      expect(calls.some((call) => call.path === "/api/runs/r1/rerun")).toBe(true)
    )
  })

  it("saves the run's config as a reusable preset", async () => {
    const { calls } = open()
    await screen.findByText("h3/mod · 20st")
    await userEvent.click(screen.getByRole("button", { name: /save preset/i }))

    await waitFor(() => {
      const post = calls.find((call) => call.path === "/api/presets")
      expect(post?.body).toMatchObject({ name: "h3/mod · 20st", run_id: "r1" })
    })
  })

  it("offers the run's workflow as a file ComfyUI can open", async () => {
    open()
    await screen.findByText("h3/mod · 20st")

    const link = screen.getByRole("link", { name: /download workflow/i })
    expect(link).toHaveAttribute("href", "/api/runs/r1/workflow")
    expect(link).toHaveAttribute("download")
  })

  it("shows the failure text when a run produced nothing", async () => {
    open(
      makeView({
        run: {
          id: "r1",
          label: "failed one",
          status: "failed",
          error: "LoadImage: file not found",
          artifact: {},
        },
      })
    )

    expect(await screen.findByText(/it failed/i)).toBeInTheDocument()
    expect(screen.getByText(/LoadImage: file not found/)).toBeInTheDocument()
    expect(screen.getByText(/this run produced nothing/i)).toBeInTheDocument()
  })
})
