import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { ArenaPage } from "@/pages/arena"
import { StandingsPage } from "@/pages/arena/standings"
import { BASELINE_ROUTES, fakeApi, makeView, renderApp } from "@/test/harness"

const A = makeView({ run: { id: "a", label: "euler" } })
const B = makeView({ run: { id: "b", label: "dpmpp_2m" } })

const MATCHUP = {
  matchup: {
    a_run_id: "a",
    b_run_id: "b",
    pool: "pool1",
    pool_label: "flf2v · 0.5 MP · 5s · 16:9 · no interp · no upscale",
    held: { Megapixels: "0.5 MP", Duration: "5s", Interpolation: "off", Upscaler: "off" },
    differences: [{ field: "sampler", label: "Sampler", values: ["euler", "dpmpp_2m"] }],
    axis: "sampler",
    seed_matched: true,
    reason: "Same seed, and sampler is the only setting that differs.",
  },
  a: A,
  b: B,
}

const STANDINGS = {
  axes: [
    {
      axis: "sampler",
      label: "Sampler",
      votes: 5,
      standings: [
        {
          key: "dpmpp_2m",
          label: "dpmpp_2m",
          rating: 1544.2,
          wins: 4,
          losses: 1,
          ties: 0,
          seed_matched: 5,
          runs: 3,
          mean_sec_per_it: 12.5,
          rank: 1,
          games: 5,
          decided: 5,
          win_rate: 0.8,
        },
        {
          key: "euler",
          label: "euler",
          rating: 1455.8,
          wins: 1,
          losses: 4,
          ties: 0,
          seed_matched: 5,
          runs: 3,
          mean_sec_per_it: 9.5,
          rank: 2,
          games: 5,
          decided: 5,
          win_rate: 0.2,
        },
      ],
      verdict: {
        kind: "winner",
        value: "dpmpp_2m",
        runner_up: "euler",
        wins: 4,
        losses: 1,
        ties: 0,
        reason: "dpmpp_2m beats euler 4–1 across 5 decided votes — more than a coin flip would give.",
      },
    },
  ],
  loadouts: [],
  votes_counted: 5,
  votes_ignored: 0,
  ignored_reasons: {},
  pools: 1,
  runs: 6,
  matchups: 9,
  clean_matchups: 6,
}

const EMPTY_ARENA = new Response(
  JSON.stringify({
    error: "nothing fair to compare yet",
    detail: "Sweep a sampler, scheduler, or set of weights over one recipe to fill it.",
    kind: "not_found",
  }),
  { status: 404, headers: { "Content-Type": "application/json" } }
)

describe("the arena", () => {
  it("states what is held identical before it asks for a preference", async () => {
    fakeApi({ ...BASELINE_ROUTES, "/api/arena/next": MATCHUP })
    renderApp(<ArenaPage />)

    expect(await screen.findByText(/held identical/i)).toBeInTheDocument()
    expect(screen.getByText("0.5 MP")).toBeInTheDocument()
    expect(screen.getByText(MATCHUP.matchup.reason)).toBeInTheDocument()
  })

  it("shows two clips and nothing that identifies them", async () => {
    fakeApi({ ...BASELINE_ROUTES, "/api/arena/next": MATCHUP })
    const { container } = renderApp(<ArenaPage />)

    await screen.findByText(/held identical/i)
    expect(container.querySelectorAll("video")).toHaveLength(2)
    // The run labels are the setting names; showing either would answer the question.
    expect(screen.queryByText("euler")).not.toBeInTheDocument()
    expect(screen.queryByText("dpmpp_2m")).not.toBeInTheDocument()
  })

  it("records a vote for the clip the viewer picks", async () => {
    const { calls } = fakeApi({
      ...BASELINE_ROUTES,
      "/api/arena/next": MATCHUP,
      "POST /api/votes": { id: "v1", run_a: "a", run_b: "b", winner: "a" },
      "/api/elo": [],
    })

    renderApp(<ArenaPage />)
    const [left] = await screen.findAllByRole("button", { name: /this one/i })
    await userEvent.click(left)

    await waitFor(() => {
      const vote = calls.find((call) => call.path === "/api/votes")
      expect(vote?.body).toMatchObject({ run_a: "a", run_b: "b", winner: "a", axis: "sampler" })
    })
  })

  it("records a tie when neither clip is better", async () => {
    const { calls } = fakeApi({
      ...BASELINE_ROUTES,
      "/api/arena/next": MATCHUP,
      "POST /api/votes": { id: "v1", run_a: "a", run_b: "b", winner: null },
      "/api/elo": [],
    })

    renderApp(<ArenaPage />)
    await userEvent.click(await screen.findByRole("button", { name: /too close to call/i }))

    await waitFor(() => {
      const vote = calls.find((call) => call.path === "/api/votes")
      expect(vote?.body).toMatchObject({ winner: null })
    })
  })

  it("asks for a different pair, without voting, when a matchup is skipped", async () => {
    const { calls } = fakeApi({ ...BASELINE_ROUTES, "/api/arena/next": MATCHUP })

    renderApp(<ArenaPage />)
    await userEvent.click(await screen.findByRole("button", { name: /skip/i }))

    await waitFor(() => {
      const asked = calls.filter((call) => call.path === "/api/arena/next")
      // The second ask carries the skipped runs, so neither can come back.
      expect(asked.length).toBeGreaterThan(1)
    })
    expect(calls.some((call) => call.path === "/api/votes")).toBe(false)
  })

  it("keeps the settings out of the page until the viewer asks for them", async () => {
    fakeApi({ ...BASELINE_ROUTES, "/api/arena/next": MATCHUP })
    renderApp(<ArenaPage />)

    const reveal = await screen.findByText(/reveal 1 difference/i)
    expect(screen.queryByText("euler")).not.toBeInTheDocument()
    await userEvent.click(reveal)
    expect(await screen.findByText("euler")).toBeInTheDocument()
  })

  it("says what to run when nothing is comparable yet", async () => {
    fakeApi({ ...BASELINE_ROUTES, "/api/arena/next": () => EMPTY_ARENA })
    renderApp(<ArenaPage />)

    expect(await screen.findByText(/nothing fair to compare yet/i)).toBeInTheDocument()
    expect(screen.getByText(/sweep a sampler/i)).toBeInTheDocument()
  })

  it("offers participant filtering control defaulting to score >= 7", async () => {
    fakeApi({ ...BASELINE_ROUTES, "/api/arena/next": MATCHUP })
    renderApp(<ArenaPage />)

    expect(await screen.findByText(/participants:/i)).toBeInTheDocument()
    expect(screen.getByText(/score ≥ 7 \(default\)/i)).toBeInTheDocument()
  })
})

describe("the standings", () => {
  it("leads with the verdict and shows the record behind it", async () => {
    fakeApi({ ...BASELINE_ROUTES, "/api/arena/standings": STANDINGS })
    renderApp(<StandingsPage />)

    expect(await screen.findByText(STANDINGS.axes[0].verdict.reason)).toBeInTheDocument()
    const winner = screen.getAllByText("dpmpp_2m")
    expect(winner.length).toBeGreaterThan(0)
    expect(screen.getByText("4–1–0")).toBeInTheDocument()
    expect(screen.getByText("1544.2")).toBeInTheDocument()
  })

  it("shows the speed of each value beside the ranking, never inside it", async () => {
    fakeApi({ ...BASELINE_ROUTES, "/api/arena/standings": STANDINGS })
    renderApp(<StandingsPage />)

    // The winner is the slower of the two: speed is reported, not rewarded.
    expect(await screen.findByText("12.50 s/it")).toBeInTheDocument()
    expect(screen.getByText("9.50 s/it")).toBeInTheDocument()
  })

  it("says how much of the arena is still unjudged", async () => {
    fakeApi({ ...BASELINE_ROUTES, "/api/arena/standings": STANDINGS })
    renderApp(<StandingsPage />)

    expect(await screen.findByText(/5 votes counted/i)).toBeInTheDocument()
    expect(screen.getByText(/6 clean matchups/i)).toBeInTheDocument()
  })

  it("reports votes it could not count, with the reason", async () => {
    fakeApi({
      ...BASELINE_ROUTES,
      "/api/arena/standings": {
        ...STANDINGS,
        axes: [],
        votes_counted: 0,
        votes_ignored: 2,
        ignored_reasons: { "the two runs were not comparable": 2 },
      },
    })
    renderApp(<StandingsPage />)

    expect(await screen.findByText(/the two runs were not comparable/i)).toBeInTheDocument()
  })

  it("invites the first vote when nothing has been judged", async () => {
    fakeApi({
      ...BASELINE_ROUTES,
      "/api/arena/standings": {
        axes: [],
        loadouts: [],
        votes_counted: 0,
        votes_ignored: 0,
        ignored_reasons: {},
        pools: 0,
        runs: 0,
        matchups: 0,
        clean_matchups: 0,
      },
    })
    renderApp(<StandingsPage />)

    expect(await screen.findByText(/no settings ranked yet/i)).toBeInTheDocument()
  })
})
