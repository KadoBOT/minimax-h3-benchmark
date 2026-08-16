import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import type { SharedSweepRequest, SweepPreview } from "@/api/schema"

import { initialValues } from "./form-state"
import { SduiSweepBuilder } from "./sweep-builder"
import { generationDocument } from "./test-fixtures"

const preview: SweepPreview = {
  count: 4,
  combinations: 2,
  repeats: 2,
  new_count: 3,
  duplicate_count: 1,
  items: [],
}

describe("the shared sweep builder", () => {
  it("authors typed select axes and uses the server preview for queue counts", async () => {
    const document = generationDocument()
    const onPreview = vi.fn<(request: SharedSweepRequest) => Promise<SweepPreview>>()
    onPreview.mockResolvedValue(preview)
    const onRun = vi.fn<(request: SharedSweepRequest) => Promise<void>>()
    onRun.mockResolvedValue(undefined)

    render(
      <SduiSweepBuilder
        document={document}
        values={initialValues(document)}
        onPreview={onPreview}
        onRun={onRun}
      />
    )

    await userEvent.click(screen.getByRole("button", { name: "Add axis" }))
    expect(
      screen.getByRole("button", { name: "Text to video" })
    ).toHaveAttribute("aria-pressed", "true")
    expect(
      screen.getByRole("button", { name: "First / last frame" })
    ).toHaveAttribute("aria-pressed", "true")
    expect(
      screen.queryByPlaceholderText("Comma-separated values")
    ).not.toBeInTheDocument()

    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Sweep repeats" }),
      "2"
    )
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Seed strategy" }),
      "increment"
    )
    await userEvent.click(screen.getByRole("button", { name: "Preview sweep" }))

    await waitFor(() => expect(onPreview).toHaveBeenCalledTimes(1))
    expect(onPreview.mock.calls[0]?.[0]).toMatchObject({
      axes: [
        {
          binding: "mode",
          values: ["text_to_video", "first_last_frame"],
        },
      ],
      repeats: 2,
      seed_strategy: "increment",
      skip_duplicates: true,
    })
    expect(screen.getByText("2 combinations")).toBeInTheDocument()
    expect(screen.getByText("3 new")).toBeInTheDocument()
    expect(screen.getByText("1 already run")).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Queue 3 new runs" })
    ).toBeEnabled()
    await userEvent.click(
      screen.getByRole("button", { name: "Queue 3 new runs" })
    )
    await waitFor(() => expect(onRun).toHaveBeenCalledTimes(1))
    expect(onRun).toHaveBeenCalledWith(onPreview.mock.calls[0]?.[0])
  })

  it("renders bounded numeric and boolean values instead of raw text", async () => {
    const document = generationDocument()
    render(
      <SduiSweepBuilder
        document={document}
        values={initialValues(document)}
        onPreview={async () => preview}
        onRun={async () => undefined}
      />
    )
    await userEvent.click(screen.getByRole("button", { name: "Add axis" }))
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Sweep axis 1" }),
      "steps"
    )

    expect(
      screen.getByRole("spinbutton", { name: "Add Steps value" })
    ).toHaveAttribute("min", "1")
    expect(
      screen.getByRole("spinbutton", { name: "Add Steps value" })
    ).toHaveAttribute("max", "200")
    await userEvent.type(
      screen.getByRole("spinbutton", { name: "Add Steps value" }),
      "500"
    )
    expect(screen.getByRole("button", { name: "Add value" })).toBeDisabled()

    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Sweep axis 1" }),
      "postGrade"
    )
    expect(screen.getByRole("button", { name: "Enabled" })).toHaveAttribute(
      "aria-pressed",
      "true"
    )
    expect(screen.getByRole("button", { name: "Disabled" })).toHaveAttribute(
      "aria-pressed",
      "true"
    )
  })

  it("warns when an axis is irrelevant for some generated combinations", async () => {
    const base = generationDocument()
    const document = generationDocument({
      components: base.components.map((component) =>
        component.kind === "number" && component.binding === "steps"
          ? {
              ...component,
              visibleWhen: [
                {
                  field: "mode",
                  operator: "equals" as const,
                  value: "text_to_video",
                },
              ],
            }
          : component
      ),
    })

    render(
      <SduiSweepBuilder
        document={document}
        values={initialValues(document)}
        onPreview={async () => preview}
        onRun={async () => undefined}
      />
    )
    await userEvent.click(screen.getByRole("button", { name: "Add axis" }))
    await userEvent.click(screen.getByRole("button", { name: "Add axis" }))

    expect(screen.getByRole("alert")).toHaveTextContent(
      /steps is conditionally unavailable/i
    )
    expect(
      screen.getByRole("button", { name: "Preview sweep" })
    ).toBeDisabled()
  })
})
