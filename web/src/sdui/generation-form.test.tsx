import { useState } from "react"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import type { GenerationDocument } from "@/api/schema"

import { initialValues, type FormValues } from "./form-state"
import { SduiGenerationForm } from "./generation-form"
import { generationDocument } from "./test-fixtures"

function Harness({
  document,
  onSubmit = () => undefined,
  uploading = false,
  diagnostics = [],
}: {
  document: GenerationDocument
  onSubmit?: Parameters<typeof SduiGenerationForm>[0]["onSubmit"]
  uploading?: boolean
  diagnostics?: string[]
}) {
  const [values, setValues] = useState<FormValues>(() =>
    initialValues(document)
  )
  return (
    <SduiGenerationForm
      document={document}
      values={values}
      onChange={setValues}
      onSubmit={onSubmit}
      uploading={uploading}
      diagnostics={diagnostics}
      renderAsset={(component, ids, onChange) => (
        <button
          type="button"
          aria-label={component.label}
          onClick={() => onChange(["123e4567-e89b-42d3-a456-426614174000"])}
        >
          {ids.length} assets
        </button>
      )}
    />
  )
}

function allControlsDocument(): GenerationDocument {
  const base = generationDocument()
  return {
    ...base,
    title: "Document-owned title",
    capabilities: {
      required: [...base.capabilities.required, "component.text"],
      optional: [],
    },
    components: [
      ...base.components,
      {
        id: "prefix",
        kind: "text",
        binding: "prefix",
        label: "Server filename",
        description: "A label mutated only in the document.",
        required: true,
        defaultValue: "server-default",
        minLength: 2,
        maxLength: 20,
        placeholder: "server placeholder",
      },
    ],
  }
}

describe("the generic generation renderer", () => {
  it("renders every scalar control and all presentation from the document", () => {
    render(<Harness document={allControlsDocument()} />)

    expect(
      screen.getByRole("form", { name: "Document-owned title" })
    ).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Source" })).toBeInTheDocument()
    expect(screen.getByRole("textbox", { name: "Prompt" })).toHaveValue(
      "A lighthouse in rain"
    )
    expect(
      screen.getByRole("textbox", { name: "Server filename" })
    ).toHaveValue("server-default")
    expect(
      screen.getByRole("textbox", { name: "Server filename" })
    ).toHaveAttribute("placeholder", "server placeholder")
    expect(
      screen.getByText("A label mutated only in the document.")
    ).toBeInTheDocument()
    expect(screen.getByRole("spinbutton", { name: "Steps" })).toHaveAttribute(
      "min",
      "1"
    )
    expect(screen.getByRole("spinbutton", { name: "Steps" })).toHaveAttribute(
      "max",
      "200"
    )
    expect(screen.getByRole("combobox", { name: "Mode" })).toHaveValue(
      "string:text_to_video"
    )
    expect(
      screen.getByRole("checkbox", { name: /post grade/i })
    ).not.toBeChecked()
    expect(screen.getByRole("spinbutton", { name: "Seed" })).toHaveValue(42)
    expect(
      screen.getByRole("checkbox", { name: /random each submission/i })
    ).not.toBeChecked()
  })

  it("uses strict generic predicates without discarding hidden values", async () => {
    render(<Harness document={generationDocument()} />)

    expect(
      screen.queryByRole("button", { name: "First frame" })
    ).not.toBeInTheDocument()
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Mode" }),
      "string:first_last_frame"
    )
    await userEvent.click(screen.getByRole("button", { name: "First frame" }))
    expect(
      screen.getByRole("button", { name: "First frame" })
    ).toHaveTextContent("1 assets")

    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Mode" }),
      "string:text_to_video"
    )
    expect(
      screen.queryByRole("button", { name: "First frame" })
    ).not.toBeInTheDocument()

    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Mode" }),
      "string:first_last_frame"
    )
    expect(
      screen.getByRole("button", { name: "First frame" })
    ).toHaveTextContent("1 assets")
  })

  it("supports random/manual seed without changing its document bounds", async () => {
    render(<Harness document={generationDocument()} />)
    const random = screen.getByRole("checkbox", {
      name: /random each submission/i,
    })
    const seed = screen.getByRole("spinbutton", { name: "Seed" })

    await userEvent.click(random)
    expect(seed).toBeDisabled()
    expect(seed).toHaveValue(null)
    await userEvent.click(random)
    expect(seed).toHaveValue(42)
    expect(seed).toHaveAttribute("max", String(Number.MAX_SAFE_INTEGER))
  })

  it("submits the pinned revisions and binding map through the declared safe action", async () => {
    const submit = vi.fn()
    render(<Harness document={generationDocument()} onSubmit={submit} />)

    await userEvent.clear(screen.getByRole("textbox", { name: "Prompt" }))
    await userEvent.type(
      screen.getByRole("textbox", { name: "Prompt" }),
      "A mutated prompt"
    )
    await userEvent.click(screen.getByRole("button", { name: "Queue run" }))

    await waitFor(() =>
      expect(submit).toHaveBeenCalledWith(
        expect.objectContaining({
          workflowRevision: generationDocument().workflowRevision,
          schemaRevision: "h3-v1",
          input: expect.objectContaining({
            prompt: "A mutated prompt",
            seed: 42,
          }),
        }),
        expect.objectContaining({ endpoint: "/api/runs", method: "POST" })
      )
    )
  })

  it("blocks unavailable, uploading, invalid, and unsafe submissions with an announced reason", () => {
    const disabled = generationDocument({
      availability: {
        state: "disabled",
        observedAt: "2026-08-15T08:00:00Z",
        reason: {
          code: "offline",
          detail: "ComfyUI is offline.",
          retryable: true,
        },
      },
    })
    const { rerender } = render(<Harness document={disabled} />)
    expect(screen.getByRole("button", { name: "Queue run" })).toBeDisabled()
    expect(screen.getByRole("status")).toHaveTextContent("ComfyUI is offline.")

    rerender(<Harness document={generationDocument()} uploading />)
    expect(screen.getByRole("status")).toHaveTextContent(/upload/i)

    const unsafe = generationDocument({
      actions: [
        {
          ...generationDocument().actions[0],
          endpoint: "/api/admin",
        },
      ],
    })
    rerender(<Harness document={unsafe} />)
    expect(screen.getByRole("status")).toHaveTextContent(/unsafe/i)
  })

  it("focuses the first document-ordered error and reports optional diagnostics", () => {
    const document = generationDocument()
    const { container } = render(
      <Harness
        document={document}
        diagnostics={["Ignored optional component future"]}
      />
    )
    const prompt = screen.getByRole("textbox", { name: "Prompt" })
    fireEvent.change(prompt, { target: { value: "" } })
    fireEvent.submit(container.querySelector("form") as HTMLFormElement)

    expect(prompt).toHaveFocus()
    expect(screen.getByText("This field is required.")).toBeInTheDocument()
    expect(
      screen.getByText("Ignored optional component future")
    ).toBeInTheDocument()
  })
})
