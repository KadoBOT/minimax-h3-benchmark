import { fireEvent, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { LabPage } from "@/pages/lab"
import { BASELINE_ROUTES, CATALOG, CONFIG, fakeApi, makeView, renderApp } from "@/test/harness"

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
