import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Route, Routes } from "react-router"
import { beforeEach, describe, expect, it } from "vitest"

import type { JobDocument, RunView } from "@/api/schema"
import { RunPage } from "@/pages/run"
import { JOB_ID, REVISION, jobDocument } from "@/sdui/test-fixtures"
import { BASELINE_ROUTES, fakeApi, makeView, renderApp } from "@/test/harness"

const RUN_ID = "r1"

function sharedRun(overrides: Partial<RunView["run"]> = {}): RunView {
  return makeView({
    run: {
      id: RUN_ID,
      label: "shared H3 benchmark",
      status: "running",
      artifact: undefined,
      metrics: undefined,
      shared_job_id: JOB_ID,
      shared_submission: {
        workflowRevision: REVISION,
        schemaRevision: "h3-v1",
        input: {
          prompt: "Pinned shared prompt",
          steps: 18,
          seed: 42,
        },
      },
      shared_provenance: {
        manifestDigest: `sha256:${"b".repeat(64)}`,
        compiler: { id: "h3", version: "1" },
        catalogRevision: `sha256:${"c".repeat(64)}`,
        inputDigest: `sha256:${"d".repeat(64)}`,
        resolvedSeed: 42,
      },
      ...overrides,
    },
  })
}

function sharedJob(overrides: Partial<JobDocument> = {}): JobDocument {
  return jobDocument({
    components: jobDocument().components.map((component) =>
      component.kind === "preview"
        ? { ...component, src: `/api/runs/${RUN_ID}/shared-preview` }
        : component
    ),
    capabilities: {
      ...jobDocument().capabilities,
      required: [
        ...jobDocument().capabilities.required,
        "action.retry_collection",
      ],
    },
    actions: [
      ...jobDocument().actions.map((action) => ({
        ...action,
        endpoint: `/api/runs/${RUN_ID}/cancel`,
      })),
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

function open(view = sharedRun(), document: unknown = sharedJob()) {
  const api = fakeApi({
    ...BASELINE_ROUTES,
    [`/api/runs/${RUN_ID}`]: view,
    [`/api/runs/${RUN_ID}/shared-view`]: document,
    [`POST /api/runs/${RUN_ID}/cancel`]: {
      ok: true,
      detail: "cancel requested",
    },
    [`POST /api/runs/${RUN_ID}/retry-collection`]: {
      ...view,
      run: { ...view.run, status: "running" },
    },
    [`POST /api/runs/${RUN_ID}/rerun`]: view,
  })
  const rendered = renderApp(
    <Routes>
      <Route path="/runs/:runId" element={<RunPage />} />
    </Routes>,
    { route: `/runs/${RUN_ID}` }
  )
  return { ...api, ...rendered }
}

describe("a shared-service run", () => {
  beforeEach(() => localStorage.clear())

  it("renders the generic job document beside the durable benchmark record", async () => {
    open()
    expect(
      await screen.findByRole("status", { name: "Running" })
    ).toHaveTextContent("Sampling")
    expect(
      screen.getByRole("progressbar", { name: "Sampling" })
    ).toHaveAttribute("aria-valuenow", "50")
    expect(screen.getByText("Pinned shared prompt")).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "Save preset" })
    ).not.toBeInTheDocument()
    expect(screen.getByText(JOB_ID, { exact: false })).toBeInTheDocument()
  })

  it("targets cancel and collection retry through the same-origin local run", async () => {
    const { calls } = open()
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }))
    await userEvent.click(
      screen.getByRole("button", { name: "Retry collection" })
    )

    await waitFor(() => {
      expect(
        calls.some((call) => call.path === `/api/runs/${RUN_ID}/cancel`)
      ).toBe(true)
      expect(
        calls.some(
          (call) => call.path === `/api/runs/${RUN_ID}/retry-collection`
        )
      ).toBe(true)
    })
  })

  it("reruns with a fresh idempotency key while leaving exact input reconstruction to the bridge", async () => {
    let key: string | null = null
    const view = sharedRun()
    fakeApi({
      ...BASELINE_ROUTES,
      [`/api/runs/${RUN_ID}`]: view,
      [`/api/runs/${RUN_ID}/shared-view`]: sharedJob(),
      [`POST /api/runs/${RUN_ID}/rerun`]: (
        _url: URL,
        init: RequestInit | undefined
      ) => {
        key = new Headers(init?.headers).get("Idempotency-Key")
        return view
      },
    })
    renderApp(
      <Routes>
        <Route path="/runs/:runId" element={<RunPage />} />
      </Routes>,
      { route: `/runs/${RUN_ID}` }
    )
    await userEvent.click(
      await screen.findByRole("button", { name: "Run again" })
    )

    await waitFor(() => expect(key).toMatch(/\S+/))
  })

  it("contains an incompatible job document without hiding local benchmark controls", async () => {
    open(sharedRun(), { ...sharedJob(), protocolVersion: "99.0" })

    expect(
      await screen.findByRole("alert", {
        name: /shared job view could not be used/i,
      })
    ).toHaveTextContent(/protocol/i)
    expect(screen.getByRole("heading", { name: "Rating" })).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Run again" })
    ).toBeInTheDocument()
  })

  it("offers local collection recovery without requesting a rerender", async () => {
    const view = sharedRun({
      status: "collection_failed",
      shared_failure_kind: "artifact_import",
    })
    const document = sharedJob({
      components: sharedJob().components.map((component) =>
        component.kind === "status"
          ? {
              ...component,
              state: "collection_failed",
              label: "Collection failed",
              detail: "The render succeeded; importing its video failed.",
            }
          : component
      ),
    })
    const { calls } = open(view, document)
    await userEvent.click(
      await screen.findByRole("button", { name: "Retry collection" })
    )

    await waitFor(() =>
      expect(
        calls.filter(
          (call) => call.path === `/api/runs/${RUN_ID}/retry-collection`
        )
      ).toHaveLength(1)
    )
    expect(
      calls.some((call) => call.path === `/api/runs/${RUN_ID}/rerun`)
    ).toBe(false)
  })
})
