/**
 * The strip scans, the floating card inspects.
 *
 * Sweeping a pointer across a list and resting it on one card are different intents, and the
 * strip answers both: moving scrubs the six frames, staying still opens the clip beside it.
 * Motion is the thing a video benchmark is actually judging, and a contact sheet cannot show
 * it — nor can a 6:1 box, which is why the clip does not play inside the strip.
 */

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { Filmstrip, PREVIEW_DELAY_MS } from "@/components/filmstrip"
import { makeRun } from "@/test/harness"

const WITH_VIDEO = makeRun({
  status: "succeeded",
  artifact: {
    video_path: "R1.mp4",
    poster_path: "R1.png",
    strip_path: "R1-strip.png",
    width: 848,
    height: 480,
    fps: 24,
    frame_count: 120,
    size_bytes: 1024,
  },
})

// The setup file installs matchMedia once for the whole file, so a test that changes it has
// to put it back — otherwise every later test in here silently runs as reduced-motion, and
// the ones asserting "no video" would pass for the wrong reason.
const realMatchMedia = window.matchMedia

afterEach(() => {
  vi.useRealTimers()
  vi.stubGlobal("matchMedia", realMatchMedia)
})

function hover(element: HTMLElement) {
  fireEvent.pointerEnter(element)
}

/**
 * Advance past the dwell and let React render the result.
 *
 * Without the `act`, a synchronous "there is no video" assertion passes even when one is a
 * flush away — which quietly made four of these tests assert nothing at all.
 */
async function waitOutTheDwell(multiple = 1) {
  await act(async () => {
    vi.advanceTimersByTime(PREVIEW_DELAY_MS * multiple)
  })
}

describe("the filmstrip preview", () => {
  it("plays the clip once the pointer rests on it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(<Filmstrip run={WITH_VIDEO} />)

    hover(screen.getByTestId("filmstrip"))
    expect(screen.queryByTestId("hover-preview")).not.toBeInTheDocument()

    await waitOutTheDwell()
    const video = screen.getByTestId("hover-preview")
    expect(video).toHaveAttribute("src", "/api/media/videos/R1.mp4")
    expect(video).toHaveAttribute("loop")
    // Fifty cards autoplaying with sound is not a feature anybody wants.
    expect((video as HTMLVideoElement).muted).toBe(true)
  })

  it("opens the clip beside the strip rather than inside it", async () => {
    /**
     * The strip is 6:1 because that is the shape of six frames in a row. Playing a clip in
     * that box crops it to a letterbox slice, which is the complaint this replaced: a card
     * "very long and narrow, not good for displaying the previews".
     */
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(<Filmstrip run={WITH_VIDEO} />)
    const strip = screen.getByTestId("filmstrip")

    hover(strip)
    await waitOutTheDwell()

    const video = screen.getByTestId("hover-preview")
    expect(strip).not.toContainElement(video)
    // Sized by the video's own frame, not by the box it was scanned in.
    expect(video.style.aspectRatio).toBe("848 / 480")
  })

  it("names the run it is previewing, since the card floats over its neighbours", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(<Filmstrip run={WITH_VIDEO} />)

    hover(screen.getByTestId("filmstrip"))
    await waitOutTheDwell()

    const card = screen.getByTestId("hover-card")
    expect(card).toHaveTextContent(WITH_VIDEO.label)
    expect(card).toHaveTextContent("848×480")
    expect(card).toHaveTextContent("5.0")
  })

  it("does not load a video for a pointer that is only passing through", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(<Filmstrip run={WITH_VIDEO} />)
    const strip = screen.getByTestId("filmstrip")

    hover(strip)
    fireEvent.pointerLeave(strip)
    await waitOutTheDwell(4)

    expect(screen.queryByTestId("hover-preview")).not.toBeInTheDocument()
  })

  it("drops the clip again when the pointer leaves, rather than leaving it decoding", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(<Filmstrip run={WITH_VIDEO} />)
    const strip = screen.getByTestId("filmstrip")

    hover(strip)
    await waitOutTheDwell()
    expect(screen.getByTestId("hover-preview")).toBeInTheDocument()

    fireEvent.pointerLeave(strip)
    await waitFor(() => expect(screen.queryByTestId("hover-preview")).not.toBeInTheDocument())
  })

  it("has nothing to play for a run that produced no video", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const queued = makeRun({ status: "queued", artifact: {} })
    render(<Filmstrip run={queued} />)

    hover(screen.getByTestId("filmstrip-placeholder"))
    await waitOutTheDwell(4)

    expect(screen.queryByTestId("hover-preview")).not.toBeInTheDocument()
  })

  it("stays still for someone who asked for less motion", async () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("prefers-reduced-motion"),
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }))
    vi.useFakeTimers({ shouldAdvanceTime: true })

    render(<Filmstrip run={WITH_VIDEO} />)
    hover(screen.getByTestId("filmstrip"))
    await waitOutTheDwell(4)

    expect(screen.queryByTestId("hover-preview")).not.toBeInTheDocument()
  })

  it("can be turned off where a preview would be noise", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(<Filmstrip run={WITH_VIDEO} preview={false} />)

    hover(screen.getByTestId("filmstrip"))
    await waitOutTheDwell(4)

    expect(screen.queryByTestId("hover-preview")).not.toBeInTheDocument()
  })
})
