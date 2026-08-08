import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { LeaderboardPage } from "@/pages/leaderboard"
import { BASELINE_ROUTES, fakeApi, makeView, renderApp } from "@/test/harness"

const BOARD = {
  entries: [
    {
      rank: 1,
      view: makeView({ run: { id: "a", label: "h3 · 20st" }, stars: 9 }),
      score: 0.812,
      quality: 0.888,
      speed: 0.64,
      quality_source: "stars",
      unrated: false,
    },
    {
      rank: 2,
      view: makeView({ run: { id: "b", label: "none · 20st" }, stars: 6 }),
      score: 0.541,
      quality: 0.555,
      speed: 0.51,
      quality_source: "stars",
      unrated: false,
    },
    {
      rank: 3,
      view: makeView({ run: { id: "c", label: "never judged" } }),
      score: 0,
      quality: null,
      speed: 0.9,
      quality_source: "none",
      unrated: true,
    },
  ],
  weights: { quality: 0.7, speed: 0.3 },
  considered: 3,
  unrated: 1,
}

describe("the leaderboard", () => {
  it("ranks runs and shows both inputs to the score", async () => {
    fakeApi({ ...BASELINE_ROUTES, "/api/leaderboard": BOARD })

    renderApp(<LeaderboardPage />)

    expect(await screen.findByText("h3 · 20st")).toBeInTheDocument()
    expect(screen.getByText("0.812")).toBeInTheDocument()
    expect(screen.getByText("89%")).toBeInTheDocument()
    expect(screen.getByText("64%")).toBeInTheDocument()
  })

  it("re-asks the server when the quality/speed trade-off moves", async () => {
    const { fetchMock } = fakeApi({ ...BASELINE_ROUTES, "/api/leaderboard": BOARD })

    renderApp(<LeaderboardPage />)
    await screen.findByText("h3 · 20st")

    // Queried by label rather than by role: Base UI keeps the thumb `visibility: hidden` until
    // it can measure itself, and jsdom reports every box as zero, so the role is filtered out
    // as inaccessible here even though it is exposed in a real browser.
    const slider = screen.getByLabelText(/how much quality matters/i)
    slider.focus()
    await userEvent.keyboard("{ArrowLeft}")

    await waitFor(() => {
      const urls = fetchMock.mock.calls.map(([input]) => String(input))
      expect(urls.some((url) => url.includes("quality=65") && url.includes("speed=35"))).toBe(true)
    })
  })

  it("says how many runs nobody has judged rather than scoring them zero", async () => {
    fakeApi({ ...BASELINE_ROUTES, "/api/leaderboard": BOARD })

    renderApp(<LeaderboardPage />)
    expect(await screen.findByText(/1 run at the bottom/i)).toBeInTheDocument()
  })

  it("stages a run for comparison straight from the ranking", async () => {
    fakeApi({ ...BASELINE_ROUTES, "/api/leaderboard": BOARD })

    renderApp(<LeaderboardPage />)
    await screen.findByText("h3 · 20st")
    await userEvent.click(screen.getAllByRole("button", { name: /^stage$/i })[0]!)

    await waitFor(() =>
      expect(JSON.parse(window.localStorage.getItem("h3lab.bench") ?? "[]")).toContain("a")
    )
  })

  it("pins a baseline", async () => {
    const { calls } = fakeApi({
      ...BASELINE_ROUTES,
      "/api/leaderboard": BOARD,
      "PUT /api/baseline": { ok: true, detail: "pinned" },
    })

    renderApp(<LeaderboardPage />)
    await screen.findByText("h3 · 20st")
    await userEvent.click(screen.getAllByRole("button", { name: /pin as the baseline/i })[0]!)

    await waitFor(() => {
      const put = calls.find((call) => call.path === "/api/baseline")
      expect(put?.body).toMatchObject({ run_id: "a" })
    })
  })

  it("groups replicates so one lucky run is not mistaken for a finding", async () => {
    fakeApi({
      ...BASELINE_ROUTES,
      "/api/leaderboard": BOARD,
      "/api/recipes": [
        {
          recipe_hash: "abc123def456",
          label: "h3/mod · 20st",
          n: 3,
          n_rated: 3,
          mean_stars: 8.3,
          mean_sec_per_it: 1.12,
          best_run_id: "a",
          run_ids: ["a", "b", "c"],
        },
        {
          recipe_hash: "999888777666",
          label: "nocache · 20st",
          n: 1,
          n_rated: 1,
          mean_stars: 9,
          mean_sec_per_it: 1.9,
          best_run_id: "d",
          run_ids: ["d"],
        },
      ],
    })

    renderApp(<LeaderboardPage />)
    await userEvent.click(await screen.findByRole("tab", { name: /best recipes/i }))

    expect(await screen.findByText("h3/mod · 20st")).toBeInTheDocument()
    // The single-run recipe is flagged rather than allowed to top the table on one sample.
    expect(screen.getByText("thin")).toBeInTheDocument()
  })

  it("explains the replicate idea when no recipe has been repeated", async () => {
    fakeApi({ ...BASELINE_ROUTES, "/api/leaderboard": BOARD, "/api/recipes": [] })

    renderApp(<LeaderboardPage />)
    await userEvent.click(await screen.findByRole("tab", { name: /best recipes/i }))
    expect(await screen.findByText(/no repeated recipes yet/i)).toBeInTheDocument()
  })
})
