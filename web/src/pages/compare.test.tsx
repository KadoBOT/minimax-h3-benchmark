import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { ComparePage } from "@/pages/compare"
import { BASELINE_ROUTES, fakeApi, makeView, renderApp } from "@/test/harness"

const A = makeView({ run: { id: "a", label: "cache none" }, stars: 6 })
const B = makeView({ run: { id: "b", label: "cache h3" }, stars: 8 })

const COMPARISON = {
  runs: [A, B],
  differences: [{ field: "cache", label: "Cache", values: ["none", "h3"] }],
  shared: { sampler: "euler", steps: "20" },
}

describe("compare", () => {
  it("asks for two runs before it will compare anything", async () => {
    fakeApi({ ...BASELINE_ROUTES })
    renderApp(<ComparePage />)
    expect(await screen.findByText(/stage at least two runs/i)).toBeInTheDocument()
  })

  it("lists only the fields that differ, with the shared ones folded away", async () => {
    window.localStorage.setItem("h3lab.bench", JSON.stringify(["a", "b"]))
    fakeApi({ ...BASELINE_ROUTES, "/api/compare": COMPARISON })

    renderApp(<ComparePage />)

    expect(await screen.findByText("Cache")).toBeInTheDocument()
    expect(screen.getByText("none")).toBeInTheDocument()
    expect(screen.getByText("h3")).toBeInTheDocument()

    // The 2 shared settings are behind a disclosure rather than competing for attention.
    const disclosure = screen.getByText(/show the 2 settings they share/i)
    expect(disclosure.closest("details")).not.toHaveAttribute("open")
    await userEvent.click(disclosure)
    expect(disclosure.closest("details")).toHaveAttribute("open")
    expect(screen.getByText("euler")).toBeInTheDocument()
  })

  it("sends voting to the arena, where the pairs are like for like", async () => {
    fakeApi({ ...BASELINE_ROUTES })
    renderApp(<ComparePage />)

    const link = await screen.findByRole("link", { name: /go to the arena/i })
    expect(link).toHaveAttribute("href", "/arena")
  })
})
