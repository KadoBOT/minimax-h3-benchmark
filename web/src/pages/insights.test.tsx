/**
 * The claim this page makes is statistical, so these tests are mostly about restraint: that a
 * thin comparison is reported as inconclusive, and that a confounded average is never dressed
 * up as a result.
 */

import { screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { InsightsPage } from "@/pages/insights"
import type { AxisInsight } from "@/api/schema"
import { BASELINE_ROUTES, fakeApi, renderApp } from "@/test/harness"

const AXES = [{ field: "cache", label: "Cache", kind: "categorical" as const }]

const DECIDED: AxisInsight = {
  axis: "cache",
  label: "Cache",
  kind: "categorical",
  total_runs: 12,
  values: ["h3", "none"],
  marginal: [
    {
      value: "h3",
      n: 6,
      n_rated: 6,
      n_failed: 0,
      mean_stars: 7.5,
      median_stars: 8,
      mean_sec_per_it: 1.1,
      mean_wall_s: 40,
      mean_elo: 1520,
    },
    {
      value: "none",
      n: 6,
      n_rated: 6,
      n_failed: 1,
      mean_stars: 6,
      median_stars: 6,
      mean_sec_per_it: 1.8,
      mean_wall_s: 62,
      mean_elo: 1480,
    },
  ],
  paired: [
    {
      value_a: "h3",
      value_b: "none",
      pair_groups: 4,
      stars: { n: 4, mean: 1.5, stderr: 0.4, better_a: 4, better_b: 0, ties: 0, conclusive: true },
      speed_pct: {
        n: 4,
        mean: 38.9,
        stderr: 3.1,
        better_a: 4,
        better_b: 0,
        ties: 0,
        conclusive: true,
      },
      matched_on: "seed",
      controlled: true,
    },
  ],
  quality_verdict: {
    kind: "winner",
    metric: "stars",
    value: "h3",
    runner_up: "none",
    margin: 1.5,
    pair_groups: 4,
    matched_on: "seed",
    reason: "h3 wins by 1.50★ across 4 seed-matched group(s).",
  },
  speed_verdict: {
    kind: "winner",
    metric: "speed",
    value: "h3",
    runner_up: "none",
    margin: 38.9,
    pair_groups: 4,
    matched_on: "seed",
    reason: "h3 wins by 38.90% faster per step across 4 seed-matched group(s).",
  },
  marginal_caveat: "Marginal averages are confounded.",
}

const THIN: AxisInsight = {
  ...DECIDED,
  paired: [
    {
      ...DECIDED.paired![0]!,
      pair_groups: 1,
      stars: { n: 1, mean: 0.5, stderr: null, better_a: 1, better_b: 0, ties: 0, conclusive: false },
      speed_pct: { n: 0, mean: null, stderr: null, better_a: 0, better_b: 0, ties: 0, conclusive: false },
      matched_on: "recipe",
      controlled: false,
    },
  ],
  quality_verdict: {
    kind: "inconclusive",
    metric: "stars",
    value: null,
    runner_up: null,
    margin: null,
    pair_groups: 1,
    matched_on: "recipe",
    reason: "Only 1 seed-matched group so far — at least 2 are needed before naming a winner.",
  },
  speed_verdict: {
    kind: "inconclusive",
    metric: "speed",
    value: null,
    runner_up: null,
    margin: null,
    pair_groups: 0,
    matched_on: null,
    reason: "No matched pair of Cache values has timed runs on both sides yet.",
  },
}

describe("insights", () => {
  it("leads with the verdict and says how it was controlled", async () => {
    fakeApi({ ...BASELINE_ROUTES, "/api/insights/axes": AXES, "/api/insights/cache": DECIDED })

    renderApp(<InsightsPage />, { route: "/insights/cache" })

    expect(await screen.findByText(/h3 wins by 1\.50/)).toBeInTheDocument()
    expect(screen.getAllByText("seed-matched").length).toBeGreaterThan(0)
  })

  it("says inconclusive rather than naming a near-tie a winner", async () => {
    fakeApi({ ...BASELINE_ROUTES, "/api/insights/axes": AXES, "/api/insights/cache": THIN })

    renderApp(<InsightsPage />, { route: "/insights/cache" })

    expect(await screen.findAllByText(/inconclusive/i)).toHaveLength(2)
    expect(screen.getByText(/at least 2 are needed/i)).toBeInTheDocument()
    expect(screen.queryByText(/h3 wins/)).not.toBeInTheDocument()
  })

  it("marks a seed-pooled comparison as weaker than a seed-matched one", async () => {
    fakeApi({ ...BASELINE_ROUTES, "/api/insights/axes": AXES, "/api/insights/cache": THIN })

    renderApp(<InsightsPage />, { route: "/insights/cache" })
    expect(await screen.findByText("recipe")).toBeInTheDocument()
  })

  it("shows a delta with its spread, so a wide error bar is visible", async () => {
    fakeApi({ ...BASELINE_ROUTES, "/api/insights/axes": AXES, "/api/insights/cache": DECIDED })

    renderApp(<InsightsPage />, { route: "/insights/cache" })
    const row = (await screen.findByText("h3", { selector: "span" })).closest("tr")!
    expect(within(row).getByText(/\+1\.50/)).toBeInTheDocument()
    expect(within(row).getByText(/±0\.40/)).toBeInTheDocument()
  })

  it("labels the marginal table as confounded rather than presenting it as the answer", async () => {
    fakeApi({ ...BASELINE_ROUTES, "/api/insights/axes": AXES, "/api/insights/cache": DECIDED })

    renderApp(<InsightsPage />, { route: "/insights/cache" })
    expect(await screen.findByText(/marginal averages/i)).toBeInTheDocument()
    expect(
      screen.getByText(/every run grouped by its value, ignoring what else differed/i)
    ).toBeInTheDocument()
  })

  it("explains what experiment to run when nothing varies yet", async () => {
    fakeApi({ ...BASELINE_ROUTES, "/api/insights/axes": [] })

    renderApp(<InsightsPage />)
    expect(await screen.findByText(/nothing varies yet/i)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /set up a sweep/i })).toHaveAttribute("href", "/")
  })
})
