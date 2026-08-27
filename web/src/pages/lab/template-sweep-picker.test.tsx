import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import type { StudioTemplateCatalog } from "@/lib/studio-runtime"
import { TemplateSweepPicker } from "./template-sweep-picker"

const CATALOG = {
  version: 1,
  managed_keys: ["steps", "upscale_rtx"],
  selector: { label: "Template", placeholder: "Search 3 templates" },
  categories: [
    { id: "essentials", name: "Essentials" },
    { id: "looks", name: "Visual looks" },
    { id: "finishing", name: "Finishing" },
  ],
  templates: [
    {
      id: "essentials/balanced",
      category: "essentials",
      name: "Balanced",
      description: "A general starting point.",
      tradeoff: "Moderate speed.",
      evidence: "curated",
      evidence_ref: null,
      tags: ["general"],
      requirements: [],
      values: { steps: 20, upscale_rtx: false },
    },
    {
      id: "looks/anime-action",
      category: "looks",
      name: "Anime Action",
      description: "Graphic action with fast motion.",
      tradeoff: "Less photographic.",
      evidence: "experimental",
      evidence_ref: null,
      tags: ["anime", "motion"],
      requirements: [],
      values: { steps: 28, upscale_rtx: false },
    },
    {
      id: "finishing/rtx",
      category: "finishing",
      name: "RTX Finish",
      description: "Upscale the final clip.",
      tradeoff: "Uses more VRAM.",
      evidence: "measured",
      evidence_ref: ".h3bench/results/FINDINGS.md#3",
      tags: ["upscale"],
      requirements: [
        {
          kind: "capability",
          key: "upscale_rtx",
          value: true,
          message: "RTX Video Super Resolution must be available.",
        },
      ],
      values: { steps: 20, upscale_rtx: true },
    },
  ],
} satisfies StudioTemplateCatalog

function picker(overrides: Partial<Parameters<typeof TemplateSweepPicker>[0]> = {}) {
  const onChange = vi.fn()
  render(
    <TemplateSweepPicker
      catalog={CATALOG}
      selected={["__current__"]}
      inputs={{}}
      capabilities={{ upscale_rtx: false }}
      onChange={onChange}
      {...overrides}
    />
  )
  return onChange
}

describe("Template sweep picker", () => {
  it("searches names, categories, descriptions, evidence, and tags", async () => {
    picker()
    const user = userEvent.setup()

    expect(screen.getByText("Essentials")).toBeInTheDocument()
    expect(screen.getByText("Visual looks")).toBeInTheDocument()
    await user.type(screen.getByRole("searchbox", { name: /search template axis/i }), "anime motion")

    expect(screen.getByRole("button", { name: /anime action/i })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /balanced/i })).not.toBeInTheDocument()
    expect(screen.getByText("experimental")).toBeInTheDocument()
  })

  it("selects current settings and packaged templates", async () => {
    const onChange = picker()
    const user = userEvent.setup()

    await user.click(screen.getByRole("button", { name: /balanced/i }))
    expect(onChange).toHaveBeenLastCalledWith(["__current__", "essentials/balanced"])

    await user.click(screen.getByRole("button", { name: /current settings/i }))
    expect(onChange).toHaveBeenLastCalledWith([])
  })

  it("disables templates whose requirements are unmet", () => {
    picker()

    const rtx = screen.getByRole("button", { name: /rtx finish/i })
    expect(rtx).toBeDisabled()
    expect(rtx).toHaveTextContent("RTX Video Super Resolution must be available.")
  })
})
