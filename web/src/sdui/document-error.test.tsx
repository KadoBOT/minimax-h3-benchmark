import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, it, vi } from "vitest"

import { DocumentError } from "./document-error"

it("announces document failures and offers recovery", async () => {
  const retry = vi.fn()
  render(
    <DocumentError
      detail="The server requires a component this browser cannot render."
      issues={["component.future is unsupported"]}
      onRetry={retry}
    />
  )

  expect(screen.getByRole("alert")).toHaveAccessibleName(
    "This shared view is incompatible"
  )
  expect(
    screen.getByText("component.future is unsupported")
  ).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Try again" }))
  expect(retry).toHaveBeenCalledOnce()
})

it("announces pending recovery and prevents duplicate retries", () => {
  render(
    <DocumentError
      detail="Connection lost."
      retrying
      onRetry={() => undefined}
    />
  )
  expect(screen.getByRole("button", { name: "Trying again" })).toBeDisabled()
})
