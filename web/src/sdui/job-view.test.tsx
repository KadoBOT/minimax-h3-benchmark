import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, it, vi } from "vitest"

import type { JobDocument } from "@/api/schema"

import { SduiJobView } from "./job-view"
import { JOB_ID, jobDocument } from "./test-fixtures"

const RUN_ID = "local-1"

function fullDocument(overrides: Partial<JobDocument> = {}): JobDocument {
  return jobDocument({
    capabilities: {
      required: [
        "component.section",
        "component.status",
        "component.progress",
        "component.log",
        "component.preview",
        "component.video",
        "component.download",
        "action.cancel",
        "action.retry_collection",
      ].filter((item) => item !== "component.section"),
      optional: [],
    },
    components: [
      { id: "section.live", kind: "section", title: "Live job" },
      ...jobDocument().components,
      {
        id: "video",
        kind: "video",
        src: `/api/runs/${RUN_ID}/shared-video`,
        mime: "video/mp4",
      },
      {
        id: "download",
        kind: "download",
        href: `/api/runs/${RUN_ID}/shared-video`,
        filename: "result.mp4",
        label: "Download result",
      },
    ],
    actions: [
      ...jobDocument().actions,
      {
        id: "retry",
        kind: "retry_collection",
        label: "Retry collection",
        endpoint: `/api/runs/${RUN_ID}/retry-collection`,
        method: "POST",
      },
    ],
    ...overrides,
  })
}

it("renders every required job component accessibly", () => {
  render(<SduiJobView document={fullDocument()} localRunId={RUN_ID} />)

  expect(screen.getByRole("status", { name: "Running" })).toHaveTextContent(
    "Sampling"
  )
  expect(screen.getByRole("progressbar", { name: "Sampling" })).toHaveAttribute(
    "aria-valuenow",
    "50"
  )
  expect(screen.getByRole("log", { name: "Job log" })).toHaveTextContent(
    "Started"
  )
  expect(screen.getByRole("img", { name: "Job preview 7" })).toHaveAttribute(
    "src",
    `/api/runs/${RUN_ID}/shared-preview`
  )
  expect(screen.getByLabelText("Generated video")).toHaveAttribute(
    "src",
    `/api/runs/${RUN_ID}/shared-video`
  )
  expect(screen.getByRole("link", { name: "Download result" })).toHaveAttribute(
    "download",
    "result.mp4"
  )
})

it("overlays translated live progress without changing document structure", () => {
  render(
    <SduiJobView
      document={fullDocument()}
      localRunId={RUN_ID}
      live={{ step: 18, stepTotal: 20, previewSeq: 9 }}
    />
  )
  expect(screen.getByRole("progressbar", { name: "Sampling" })).toHaveAttribute(
    "aria-valuenow",
    "90"
  )
  expect(screen.getByText("18 / 20")).toBeInTheDocument()
  expect(screen.getByRole("img", { name: "Job preview 9" })).toHaveAttribute(
    "src",
    `/api/runs/${RUN_ID}/shared-preview?sequence=9`
  )
})

it("dispatches only same-origin actions bound to this local run", async () => {
  const cancel = vi.fn()
  const retry = vi.fn()
  render(
    <SduiJobView
      document={fullDocument()}
      localRunId={RUN_ID}
      onCancel={cancel}
      onRetryCollection={retry}
    />
  )

  await userEvent.click(screen.getByRole("button", { name: "Cancel" }))
  await userEvent.click(
    screen.getByRole("button", { name: "Retry collection" })
  )
  expect(cancel).toHaveBeenCalledOnce()
  expect(retry).toHaveBeenCalledOnce()
})

it("fails closed when media or actions point at a different run", () => {
  const document = fullDocument({
    components: fullDocument().components.map((component) =>
      component.kind === "video"
        ? { ...component, src: "/api/runs/other/shared-video" }
        : component.kind === "download"
          ? { ...component, href: "/api/runs/other/shared-video" }
          : component
    ),
    actions: fullDocument().actions.map((action) => ({
      ...action,
      endpoint:
        action.kind === "cancel"
          ? "/api/runs/other/cancel"
          : "/api/runs/other/retry-collection",
    })),
  })
  render(<SduiJobView document={document} localRunId={RUN_ID} />)

  expect(screen.queryByLabelText("Generated video")).not.toBeInTheDocument()
  expect(
    screen.queryByRole("link", { name: "Download result" })
  ).not.toBeInTheDocument()
  expect(
    screen.queryByRole("button", { name: "Cancel" })
  ).not.toBeInTheDocument()
  expect(screen.getByRole("alert")).toHaveTextContent(/different local run/i)
})

it("keeps the shared job identity visible for support diagnostics", () => {
  render(<SduiJobView document={fullDocument()} localRunId={RUN_ID} />)
  expect(screen.getByText(new RegExp(JOB_ID))).toBeInTheDocument()
})
