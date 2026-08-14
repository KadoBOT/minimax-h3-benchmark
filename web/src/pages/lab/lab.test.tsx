import { act, fireEvent, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { LabPage } from "@/pages/lab"
import {
  BASELINE_ROUTES,
  CATALOG,
  CONFIG,
  EMPTY_QUEUE,
  fakeApi,
  makeView,
  renderApp,
} from "@/test/harness"
import { FakeEventSource } from "@/test/setup"

const DRY_RUN = {
  ok: true,
  problems: [],
  graph: { nodes: 42, classes: [], missing_links: [], files: [] },
  config_hash: "abcdef1234567890",
  recipe_hash: "fedcba0987654321",
  duplicate_of: null,
}

describe("the lab", () => {
  it("builds a form from the API's own vocabulary rather than a hardcoded list", async () => {
    fakeApi({ ...BASELINE_ROUTES })
    renderApp(<LabPage />)

    // Modes come from `meta.modes`; samplers from the catalog.
    expect(await screen.findByRole("button", { name: "Text" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Frames" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Reference" })).toBeInTheDocument()
  })

  it("checks a config without queueing it, and reports the graph it built", async () => {
    const { calls } = fakeApi({ ...BASELINE_ROUTES, "POST /api/runs/dry-run": DRY_RUN })

    renderApp(<LabPage />)
    await userEvent.click(await screen.findByRole("button", { name: /^check$/i }))

    expect(await screen.findByText(/builds cleanly — 42 nodes/i)).toBeInTheDocument()
    expect(screen.getByText("abcdef12")).toBeInTheDocument()
    expect(calls.some((call) => call.path === "/api/runs")).toBe(false)
  })

  it("names the problems when a config could not build", async () => {
    fakeApi({
      ...BASELINE_ROUTES,
      "POST /api/runs/dry-run": {
        ...DRY_RUN,
        ok: false,
        graph: null,
        problems: ["LoadImage.image points at a file ComfyUI does not have"],
      },
    })

    renderApp(<LabPage />)
    await userEvent.click(await screen.findByRole("button", { name: /^check$/i }))

    expect(
      await screen.findByText(/points at a file ComfyUI does not have/i)
    ).toBeInTheDocument()
  })

  it("points at the earlier run when this exact config has been run before", async () => {
    fakeApi({
      ...BASELINE_ROUTES,
      "POST /api/runs/dry-run": { ...DRY_RUN, duplicate_of: "run7" },
    })

    renderApp(<LabPage />)
    await userEvent.click(await screen.findByRole("button", { name: /^check$/i }))

    const link = await screen.findByRole("link", { name: /open that run/i })
    expect(link).toHaveAttribute("href", "/runs/run7")
  })

  it("queues the config the form is showing", async () => {
    const { calls } = fakeApi({ ...BASELINE_ROUTES, "POST /api/runs": [makeView()] })

    renderApp(<LabPage />)
    const prompt = await screen.findByLabelText(/prompt/i)
    await userEvent.clear(prompt)
    await userEvent.type(prompt, "a kestrel over a motorway")
    await userEvent.click(screen.getByRole("button", { name: /queue run/i }))

    await waitFor(() => {
      const queued = calls.find((call) => call.method === "POST" && call.path === "/api/runs")
      expect(queued).toBeDefined()
      expect((queued?.body as { config: { prompt: string } }).config.prompt).toBe(
        "a kestrel over a motorway"
      )
    })
  })

  it("offers all three frame interpolation choices and queues the one picked", async () => {
    const { calls } = fakeApi({ ...BASELINE_ROUTES, "POST /api/runs": [makeView()] })

    renderApp(<LabPage />)
    expect(await screen.findByRole("button", { name: "Off" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "RIFE" })).toBeInTheDocument()

    await userEvent.click(screen.getByRole("button", { name: "FILM Net" }))
    await userEvent.click(screen.getByRole("button", { name: /queue run/i }))

    await waitFor(() => {
      const queued = calls.find((call) => call.method === "POST" && call.path === "/api/runs")
      expect((queued?.body as { config: { interp: string } }).config.interp).toBe("film")
    })
  })

  it("names what each interpolation choice does to the frame rate", async () => {
    fakeApi({ ...BASELINE_ROUTES })
    renderApp(<LabPage />)
    expect(await screen.findByText(/48/)).toBeInTheDocument()
  })

  // --- the turbo LoRA -------------------------------------------------------

  it("asks which LoRA only once turbo is on", async () => {
    fakeApi({ ...BASELINE_ROUTES })
    renderApp(<LabPage />)

    expect(await screen.findByRole("switch", { name: /turbo/i })).toBeInTheDocument()
    expect(screen.queryByRole("combobox", { name: /turbo lora/i })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole("switch", { name: /turbo/i }))

    expect(await screen.findByRole("combobox", { name: /turbo lora/i })).toHaveTextContent(
      "4step"
    )
  })

  it("queues the LoRA that was picked, not the one the template ships with", async () => {
    const { calls } = fakeApi({ ...BASELINE_ROUTES, "POST /api/runs": [makeView()] })

    renderApp(<LabPage />)
    await userEvent.click(await screen.findByRole("switch", { name: /turbo/i }))
    await userEvent.click(screen.getByRole("combobox", { name: /turbo lora/i }))
    await userEvent.click(await screen.findByRole("option", { name: "8step" }))
    await userEvent.click(screen.getByRole("button", { name: /queue run/i }))

    await waitFor(() => {
      const queued = calls.find((call) => call.method === "POST" && call.path === "/api/runs")
      const config = (queued?.body as { config: Record<string, unknown> })?.config
      expect(config?.turbo_lora).toBe("minimax_h3_turbo_8step.safetensors")
      expect(config?.turbo).toBe(true)
    })
  })

  it("says which schedule the picked LoRA samples at", async () => {
    /** A 4-step LoRA and an 8-step one are not the same experiment, and the form has to say so. */
    fakeApi({ ...BASELINE_ROUTES })
    renderApp(<LabPage />)

    await userEvent.click(await screen.findByRole("switch", { name: /turbo/i }))
    expect(await screen.findByText(/this lora samples at 4 steps/i)).toBeInTheDocument()
    expect(screen.getByRole("spinbutton", { name: /steps/i })).toBeDisabled()

    await userEvent.click(screen.getByRole("combobox", { name: /turbo lora/i }))
    await userEvent.click(await screen.findByRole("option", { name: "8step" }))

    expect(await screen.findByText(/this lora samples at 8 steps/i)).toBeInTheDocument()
  })

  it("shows the schedule in the steps field, and gives the typed count back", async () => {
    /**
     * The number in the box is what anybody reads. Leaving the ignored count on screen while
     * the hint said otherwise made the form claim a 20-step run that would sample at four.
     */
    fakeApi({ ...BASELINE_ROUTES })
    renderApp(<LabPage />)

    const steps = await screen.findByRole("spinbutton", { name: /steps/i })
    // `fireEvent` rather than typing: jsdom refuses a selection range on a number input, so
    // `userEvent` can only ever append to the 20 that is already there.
    fireEvent.change(steps, { target: { value: "28" } })
    expect(steps).toHaveValue(28)

    await userEvent.click(screen.getByRole("switch", { name: /turbo/i }))
    expect(steps).toHaveValue(4)

    await userEvent.click(screen.getByRole("combobox", { name: /turbo lora/i }))
    await userEvent.click(await screen.findByRole("option", { name: "8step" }))
    expect(steps).toHaveValue(8)

    // Turbo off returns the run to the count that was typed, not to the LoRA's.
    await userEvent.click(screen.getByRole("switch", { name: /turbo/i }))
    expect(steps).toHaveValue(28)
    expect(steps).toBeEnabled()
  })

  it("comes back to the lab's own step count when a turbo config had none to give back", async () => {
    /**
     * A stored turbo run carries the schedule its LoRA was distilled for — the server writes it
     * there — so a draft that arrives with turbo on has no memory of a normal step count. Handing
     * back the LoRA's four is how a bench whose normal is twenty quietly starts running at four.
     */
    window.localStorage.setItem(
      "h3lab.draft",
      JSON.stringify({
        ...CONFIG,
        turbo: true,
        turbo_lora: "minimax_h3_turbo_4step.safetensors",
        steps: 4,
      })
    )
    fakeApi({ ...BASELINE_ROUTES })
    renderApp(<LabPage />)

    const steps = await screen.findByRole("spinbutton", { name: /steps/i })
    expect(steps).toHaveValue(4)

    await userEvent.click(screen.getByRole("switch", { name: /turbo/i }))
    expect(steps).toHaveValue(20)
    expect(steps).toBeEnabled()
  })

  it("shows the frame ComfyUI is drawing while a run is in flight", async () => {
    /** A benchmark that takes four minutes a run is a blank panel until something is on it. */
    const active = makeView({ run: { id: "r-live", label: "#9 r2v · 4st", status: "running" } })
    fakeApi({
      ...BASELINE_ROUTES,
      "/api/queue": { ...EMPTY_QUEUE, active_run_id: "r-live", active, queued: [], total: 0 },
    })
    renderApp(<LabPage />)
    await screen.findByText("#9 r2v · 4st")

    // Nothing to show until ComfyUI says it has drawn something.
    expect(screen.queryByRole("img", { name: /preview frame/i })).not.toBeInTheDocument()

    const source = FakeEventSource.instances.at(-1)!
    act(() => {
      source.emit({ seq: 1, kind: "run.started", run_id: "r-live", data: {} })
      source.emit({
        seq: 2,
        kind: "run.progress",
        run_id: "r-live",
        data: { step: 2, step_total: 4, preview_seq: 3, preview_mime: "image/jpeg" },
      })
    })

    const frame = await screen.findByRole("img", { name: /preview frame 3/i })
    expect(frame).toHaveAttribute("src", "/api/runs/r-live/preview?f=3")
  })

  it("plays the preview when the frame is a clip rather than a picture", async () => {
    /**
     * The templates hand the whole clip to the preview node, so a step comes back as a short
     * MP4 of the latent so far. Motion is what a video benchmark is judging; an `img` would
     * show a broken frame and say nothing.
     */
    const active = makeView({ run: { id: "r-live", label: "#9 r2v · 4st", status: "running" } })
    fakeApi({
      ...BASELINE_ROUTES,
      "/api/queue": { ...EMPTY_QUEUE, active_run_id: "r-live", active, queued: [], total: 0 },
    })
    renderApp(<LabPage />)
    await screen.findByText("#9 r2v · 4st")

    const source = FakeEventSource.instances.at(-1)!
    act(() => {
      source.emit({ seq: 1, kind: "run.started", run_id: "r-live", data: {} })
      source.emit({
        seq: 2,
        kind: "run.progress",
        run_id: "r-live",
        data: { step: 1, step_total: 4, preview_seq: 1, preview_mime: "video/mp4" },
      })
    })

    const clip = await screen.findByLabelText(/preview frame 1/i)
    expect(clip.tagName).toBe("VIDEO")
    expect(clip).toHaveAttribute("src", "/api/runs/r-live/preview?f=1")
    expect((clip as HTMLVideoElement).muted).toBe(true)
    expect(clip).toHaveAttribute("loop")
  })

  it("drops a frame it cannot show without giving up on the ones after it", async () => {
    /** A frame can be gone by the time it is asked for; the next one is a fresh chance. */
    const active = makeView({ run: { id: "r-live", label: "#9 r2v · 4st", status: "running" } })
    fakeApi({
      ...BASELINE_ROUTES,
      "/api/queue": { ...EMPTY_QUEUE, active_run_id: "r-live", active, queued: [], total: 0 },
    })
    renderApp(<LabPage />)
    await screen.findByText("#9 r2v · 4st")

    const source = FakeEventSource.instances.at(-1)!
    const progress = (seq: number) => ({
      seq,
      kind: "run.progress" as const,
      run_id: "r-live",
      data: { step: seq, step_total: 4, preview_seq: seq, preview_mime: "image/jpeg" },
    })

    act(() => {
      source.emit({ seq: 0, kind: "run.started", run_id: "r-live", data: {} })
      source.emit(progress(1))
    })
    fireEvent.error(await screen.findByAltText(/preview frame 1/i))
    expect(screen.queryByAltText(/preview frame/i)).not.toBeInTheDocument()

    act(() => {
      source.emit(progress(2))
    })
    expect(await screen.findByAltText(/preview frame 2/i)).toBeInTheDocument()
  })

  it("queues a strength the keyboard moved", async () => {
    const { calls } = fakeApi({ ...BASELINE_ROUTES, "POST /api/runs": [makeView()] })

    renderApp(<LabPage />)
    await userEvent.click(await screen.findByRole("switch", { name: /turbo/i }))

    // By label rather than by role: base-ui reveals the thumb after measuring the track, which
    // never happens in jsdom, and a hidden element has no computed accessible name to match on.
    const strength = await screen.findByLabelText("Turbo strength")
    expect(strength).toHaveAttribute("type", "range")
    expect(strength).toHaveAttribute("aria-valuenow", "1")
    strength.focus()
    await userEvent.keyboard("{ArrowLeft}")
    await userEvent.click(screen.getByRole("button", { name: /queue run/i }))

    await waitFor(() => {
      const queued = calls.find((call) => call.method === "POST" && call.path === "/api/runs")
      const config = (queued?.body as { config: Record<string, number> })?.config
      expect(config?.turbo_lora_strength).toBeLessThan(1)
    })
  })

  it("keeps a LoRA a preset named even when this machine does not have it", async () => {
    fakeApi({ ...BASELINE_ROUTES })
    window.localStorage.setItem(
      "h3lab.draft",
      JSON.stringify({ ...CONFIG, turbo: true, turbo_lora: "borrowed_from_the_other_box.safetensors" })
    )

    renderApp(<LabPage />)
    expect(await screen.findByRole("combobox", { name: /turbo lora/i })).toHaveTextContent(
      "borrowed_from_the_other_box"
    )
  })

  it("offers the turbo LoRA as a sweep axis over the files ComfyUI has", async () => {
    fakeApi({ ...BASELINE_ROUTES })
    renderApp(<LabPage />)

    await userEvent.click(await screen.findByRole("combobox", { name: "Add a sweep axis" }))
    await userEvent.click(await screen.findByRole("option", { name: "Turbo LoRA" }))

    expect(await screen.findByRole("button", { name: "4step" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "8step" })).toBeInTheDocument()
  })

  it("warns that a LoRA sweep with turbo off is one run repeated", async () => {
    fakeApi({ ...BASELINE_ROUTES })
    renderApp(<LabPage />)

    await userEvent.click(await screen.findByRole("combobox", { name: "Add a sweep axis" }))
    await userEvent.click(await screen.findByRole("option", { name: "Turbo LoRA" }))

    expect(await screen.findByText(/turbo is off/i)).toBeInTheDocument()
  })

  // A machine with none of the baseline media in ComfyUI's input folder. There is nothing to
  // pre-fill with, so the gap the mode opens stays open — which is what these two check.
  const NO_DEFAULTS = { ...CATALOG, default_first_frame: "", default_ref_images: [] }

  it("refuses to queue a mode whose required input is missing, and says which", async () => {
    fakeApi({ ...BASELINE_ROUTES, "/api/catalog": NO_DEFAULTS })

    renderApp(<LabPage />)
    await userEvent.click(await screen.findByRole("button", { name: "Frames" }))

    expect(await screen.findByText(/^still needs/i)).toHaveTextContent(/first frame/i)
    expect(screen.getByRole("button", { name: /queue run/i })).toBeDisabled()
  })

  it("will not sweep a base config that is still missing an input", async () => {
    fakeApi({ ...BASELINE_ROUTES, "/api/catalog": NO_DEFAULTS })

    renderApp(<LabPage />)
    await userEvent.click(await screen.findByRole("button", { name: "Frames" }))
    await userEvent.click(screen.getByRole("combobox", { name: "Add a sweep axis" }))
    await userEvent.click(screen.getAllByRole("option")[0])

    // Every run in a matrix inherits the base, so one invalid base is a matrix of failures.
    expect(await screen.findByText(/nothing to sweep until that is set/i)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Preview" })).toBeDisabled()
    expect(screen.getByRole("button", { name: /^Queue \d+ runs?$/ })).toBeDisabled()
  })

  it("starts a frame mode with a frame already picked, and shows it", async () => {
    fakeApi({ ...BASELINE_ROUTES })

    renderApp(<LabPage />)
    await userEvent.click(await screen.findByRole("button", { name: "Frames" }))

    const thumb = await screen.findByTestId("thumb")
    expect(thumb).toHaveAttribute("data-name", "courier.png")
    expect(thumb).toHaveAttribute("src", "/api/media/inputs/courier.png")
    expect(screen.queryByText(/^still needs/i)).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: /queue run/i })).not.toBeDisabled()
  })

  it("starts a reference mode with the whole reference set, each one visible", async () => {
    fakeApi({ ...BASELINE_ROUTES })

    renderApp(<LabPage />)
    await userEvent.click(await screen.findByRole("button", { name: "Reference" }))

    const names = (await screen.findAllByTestId("thumb")).map((node) =>
      node.getAttribute("data-name")
    )
    expect(names).toEqual(["ref-one.png", "ref-two.png"])
  })

  it("does not replace a frame that was chosen by hand", async () => {
    // Switching modes to look at something and switching back must not edit the experiment.
    fakeApi({ ...BASELINE_ROUTES })

    renderApp(<LabPage />)
    await userEvent.click(await screen.findByRole("button", { name: "Frames" }))
    await userEvent.click(screen.getByRole("combobox", { name: "First frame" }))
    await userEvent.click(await screen.findByRole("option", { name: "b.png" }))
    expect(await screen.findByTestId("thumb")).toHaveAttribute("data-name", "b.png")

    await userEvent.click(screen.getByRole("button", { name: "Text" }))
    await userEvent.click(screen.getByRole("button", { name: "Frames" }))

    expect(await screen.findByTestId("thumb")).toHaveAttribute("data-name", "b.png")
  })

  it("says so when a picked file is not in the input folder", async () => {
    /**
     * A stored draft outlives the folder it named. Without this the form shows a plausible
     * filename and a blank space, and the run fails at preflight for a reason the form knew.
     */
    fakeApi({ ...BASELINE_ROUTES })
    window.localStorage.setItem(
      "h3lab.draft",
      JSON.stringify({ ...CONFIG, mode: "flf2v", first_frame: "deleted-yesterday.png" })
    )

    renderApp(<LabPage />)
    const thumb = await screen.findByTestId("thumb")
    fireEvent.error(thumb)

    expect(await screen.findByTestId("thumb-missing")).toHaveTextContent(/not in input/i)
  })

  it("takes the machine's own defaults over the model's empty ones", async () => {
    fakeApi({
      ...BASELINE_ROUTES,
      "/api/catalog": { ...CATALOG, defaults: { mode: "flf2v", first_frame: "a.png" } },
    })

    renderApp(<LabPage />)
    expect(await screen.findByTestId("thumb")).toHaveAttribute("data-name", "a.png")
  })

  it("warns when ComfyUI is unreachable but still lets runs be queued", async () => {
    fakeApi({
      ...BASELINE_ROUTES,
      "/api/catalog": { ...CATALOG, comfy_online: false },
    })

    renderApp(<LabPage />)
    expect(await screen.findByText(/comfyui is not answering/i)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /queue run/i })).not.toBeDisabled()
  })

  it("keeps the draft across a reload", async () => {
    fakeApi({ ...BASELINE_ROUTES })

    const first = renderApp(<LabPage />)
    const prompt = await screen.findByLabelText(/prompt/i)
    await userEvent.clear(prompt)
    await userEvent.type(prompt, "held across a reload")
    await waitFor(() =>
      expect(window.localStorage.getItem("h3lab.draft")).toContain("held across a reload")
    )
    first.unmount()

    renderApp(<LabPage />)
    expect(await screen.findByLabelText(/prompt/i)).toHaveValue("held across a reload")
  })
})
