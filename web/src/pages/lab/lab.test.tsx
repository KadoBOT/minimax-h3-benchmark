import { act, fireEvent, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it } from "vitest"

import { LabPage } from "@/pages/lab"
import { generationDocument } from "@/sdui/test-fixtures"
import {
  BASELINE_ROUTES,
  EMPTY_QUEUE,
  fakeApi,
  makeView,
  renderApp,
} from "@/test/harness"
import { FakeEventSource } from "@/test/setup"

const GENERATION_PATH = "/api/shared/generation"

describe("the shared SDUI lab", () => {
  beforeEach(() => localStorage.clear())

  it("renders the server's labels, options, defaults, and visibility rules", async () => {
    const document = generationDocument({
      title: "Server-owned H3 form",
      components: generationDocument().components.map((component) =>
        component.kind === "select" && component.binding === "mode"
          ? {
              ...component,
              label: "Source strategy",
              options: [
                { value: "words", label: "Only words" },
                { value: "frame", label: "Start frame" },
              ],
              defaultValue: "words",
            }
          : component.kind === "asset"
            ? {
                ...component,
                visibleWhen: [
                  { field: "mode", operator: "equals", value: "frame" },
                ],
              }
            : component
      ),
    })
    fakeApi({ ...BASELINE_ROUTES, [GENERATION_PATH]: document })

    renderApp(<LabPage />)

    expect(
      await screen.findByRole("heading", { name: "Server-owned H3 form" })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("combobox", { name: "Source strategy" })
    ).toHaveTextContent("Only words")
    expect(
      screen.queryByLabelText("Upload First frame")
    ).not.toBeInTheDocument()
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Source strategy" }),
      screen.getByRole("option", { name: "Start frame" })
    )
    expect(screen.getByLabelText("Upload First frame")).toBeInTheDocument()
    expect(screen.queryByLabelText(/diffusion model/i)).not.toBeInTheDocument()
  })

  it("submits the exact pinned raw binding map with an idempotency key", async () => {
    let key: string | null = null
    const { calls } = fakeApi({
      ...BASELINE_ROUTES,
      [GENERATION_PATH]: generationDocument(),
      "POST /api/runs": (_url: URL, init: RequestInit | undefined) => {
        key = new Headers(init?.headers).get("Idempotency-Key")
        return [makeView()]
      },
    })
    renderApp(<LabPage />)

    const prompt = await screen.findByRole("textbox", { name: "Prompt" })
    await userEvent.clear(prompt)
    await userEvent.type(prompt, "A paper boat in a storm")
    await userEvent.click(screen.getByRole("button", { name: "Queue run" }))

    await waitFor(() =>
      expect(calls.filter((call) => call.path === "/api/runs")).toHaveLength(1)
    )
    const request = calls.find((call) => call.path === "/api/runs")
    expect(request?.body).toMatchObject({
      workflowRevision: generationDocument().workflowRevision,
      schemaRevision: "h3-v1",
      input: {
        mode: "text_to_video",
        prompt: "A paper boat in a storm",
        steps: 20,
        seed: 42,
        postGrade: false,
        firstFrame: [],
      },
    })
    expect(key).toMatch(/\S+/)
  })

  it("queues multiple copies with distinct idempotency keys", async () => {
    const keys: string[] = []
    const { calls } = fakeApi({
      ...BASELINE_ROUTES,
      [GENERATION_PATH]: generationDocument(),
      "POST /api/runs": (_url: URL, init: RequestInit | undefined) => {
        keys.push(new Headers(init?.headers).get("Idempotency-Key") ?? "")
        return [makeView()]
      },
    })
    renderApp(<LabPage />)

    const copies = await screen.findByRole("spinbutton", { name: "Run copies" })
    await userEvent.clear(copies)
    await userEvent.type(copies, "3")
    await userEvent.click(screen.getByRole("button", { name: "Queue run" }))

    await waitFor(() =>
      expect(calls.filter((call) => call.path === "/api/runs")).toHaveLength(3)
    )
    expect(new Set(keys).size).toBe(3)
  })

  it("shows server availability and refuses submission while disabled", async () => {
    fakeApi({
      ...BASELINE_ROUTES,
      [GENERATION_PATH]: generationDocument({
        availability: {
          state: "disabled",
          observedAt: "2026-08-15T08:00:00Z",
          reason: {
            code: "comfy_unreachable",
            detail: "ComfyUI is not answering; generation is disabled.",
            retryable: true,
          },
        },
      }),
    })
    renderApp(<LabPage />)

    expect(
      await screen.findByText(/comfyui is not answering/i)
    ).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Queue run" })).toBeDisabled()
  })

  it("projects upstream field errors back onto their bound controls", async () => {
    fakeApi({
      ...BASELINE_ROUTES,
      [GENERATION_PATH]: generationDocument(),
      "POST /api/runs": new Response(
        JSON.stringify({
          error: "Input rejected",
          detail: "Fix the prompt.",
          kind: "invalid",
          fields: {
            prompt: "The prompt was rejected by the workflow package.",
          },
        }),
        { status: 422, headers: { "Content-Type": "application/json" } }
      ),
    })
    renderApp(<LabPage />)

    await userEvent.click(
      await screen.findByRole("button", { name: "Queue run" })
    )
    expect(await screen.findByText(/prompt was rejected/i)).toBeInTheDocument()
    expect(screen.getByRole("textbox", { name: "Prompt" })).toHaveAttribute(
      "aria-invalid",
      "true"
    )
  })

  it("fails closed on a malformed or unsupported document", async () => {
    fakeApi({
      ...BASELINE_ROUTES,
      [GENERATION_PATH]: {
        ...generationDocument(),
        protocolVersion: "99.0",
      },
    })
    renderApp(<LabPage />)

    expect(
      await screen.findByRole("alert", {
        name: /generation document could not be used/i,
      })
    ).toHaveTextContent(/protocol/i)
    expect(
      screen.queryByRole("button", { name: "Queue run" })
    ).not.toBeInTheDocument()
  })

  it("restores a draft after the page is remounted", async () => {
    fakeApi({ ...BASELINE_ROUTES, [GENERATION_PATH]: generationDocument() })
    const first = renderApp(<LabPage />)
    const prompt = await screen.findByRole("textbox", { name: "Prompt" })
    await userEvent.clear(prompt)
    await userEvent.type(prompt, "A durable browser draft")
    await waitFor(() =>
      expect(
        Object.values(localStorage).some((value) =>
          value.includes("A durable browser draft")
        )
      ).toBe(true)
    )
    first.unmount()

    renderApp(<LabPage />)
    expect(await screen.findByRole("textbox", { name: "Prompt" })).toHaveValue(
      "A durable browser draft"
    )
  })

  it("saves and reapplies a pinned raw preset", async () => {
    fakeApi({ ...BASELINE_ROUTES, [GENERATION_PATH]: generationDocument() })
    renderApp(<LabPage />)
    const prompt = await screen.findByRole("textbox", { name: "Prompt" })
    await userEvent.clear(prompt)
    await userEvent.type(prompt, "Preset prompt")
    await userEvent.type(
      screen.getByRole("textbox", { name: "New preset name" }),
      "Rain"
    )
    await userEvent.click(screen.getByRole("button", { name: "Save" }))

    await userEvent.clear(prompt)
    await userEvent.type(prompt, "Temporary prompt")
    await userEvent.click(screen.getByRole("button", { name: "Apply" }))
    expect(prompt).toHaveValue("Preset prompt")
  })

  it("previews and queues one server-expanded typed sweep", async () => {
    const keys: string[] = []
    const bodies: unknown[] = []
    fakeApi({
      ...BASELINE_ROUTES,
      [GENERATION_PATH]: generationDocument(),
      "POST /api/sweeps/preview": {
        count: 4,
        combinations: 2,
        repeats: 2,
        new_count: 4,
        duplicate_count: 0,
        items: [],
      },
      "POST /api/sweeps": (_url: URL, init: RequestInit | undefined) => {
        keys.push(new Headers(init?.headers).get("Idempotency-Key") ?? "")
        bodies.push(JSON.parse(String(init?.body)))
        return [makeView()]
      },
    })
    renderApp(<LabPage />)
    await screen.findByRole("textbox", { name: "Prompt" })

    await userEvent.click(screen.getByRole("button", { name: "Add axis" }))
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Sweep axis 1" }),
      "steps"
    )
    await userEvent.click(
      screen.getByRole("button", { name: "Remove Steps value 20" })
    )
    await userEvent.click(
      screen.getByRole("button", { name: "Remove Steps value 21" })
    )
    const value = screen.getByRole("spinbutton", {
      name: "Add Steps value",
    })
    await userEvent.type(value, "12")
    await userEvent.click(screen.getByRole("button", { name: "Add value" }))
    await userEvent.type(value, "18")
    await userEvent.click(screen.getByRole("button", { name: "Add value" }))
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Sweep repeats" }),
      "2"
    )
    await userEvent.click(screen.getByRole("button", { name: "Preview sweep" }))
    await userEvent.click(
      await screen.findByRole("button", { name: "Queue 4 new runs" })
    )

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toMatchObject({
      axes: [{ binding: "steps", values: [12, 18] }],
      repeats: 2,
      skip_duplicates: true,
    })
    expect(keys[0]).toMatch(/\S+/)
  })

  it("keeps the existing queue and transient preview workflow", async () => {
    const active = makeView({
      run: {
        id: "active",
        seq: 9,
        label: "shared H3 run",
        status: "running",
        artifact: undefined,
        metrics: undefined,
      },
    })
    fakeApi({
      ...BASELINE_ROUTES,
      [GENERATION_PATH]: generationDocument(),
      "/api/queue": {
        ...EMPTY_QUEUE,
        active_run_id: active.run.id,
        active,
        total: 1,
      },
    })
    renderApp(<LabPage />)
    await screen.findByText("shared H3 run")

    act(() => {
      FakeEventSource.instances.at(-1)?.emit({
        seq: 20,
        kind: "run.progress",
        run_id: "active",
        at: new Date().toISOString(),
        data: { preview_seq: 3, preview_mime: "video/mp4" },
      })
    })
    const preview = await screen.findByLabelText(/preview frame 3/i)
    expect(preview.tagName).toBe("VIDEO")
    fireEvent.error(preview)
    expect(screen.queryByLabelText(/preview frame 3/i)).not.toBeInTheDocument()
  })
})
