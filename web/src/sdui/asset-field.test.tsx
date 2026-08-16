import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, it, vi } from "vitest"

import type { AssetComponent, PublicMediaMetadata } from "@/api/schema"

import { AssetField, type AssetUploader } from "./asset-field"

const FIRST_ID = "123e4567-e89b-42d3-a456-426614174000"
const SECOND_ID = "223e4567-e89b-42d3-a456-426614174001"

const component: AssetComponent = {
  id: "references",
  kind: "asset",
  binding: "references",
  label: "Reference media",
  description: "Upload source material.",
  required: true,
  accept: ["image", "video", "audio"],
  minimumItems: 1,
  maximumItems: 2,
}

function metadata(
  id: string,
  mediaKind: "image" | "video" | "audio",
  filename: string
): PublicMediaMetadata {
  return {
    id,
    kind: "asset",
    mediaKind,
    mime: `${mediaKind}/${mediaKind === "image" ? "png" : mediaKind === "video" ? "mp4" : "mpeg"}`,
    size: 12,
    digest: `sha256:${"a".repeat(64)}`,
    filename,
    contentUrl: `/api/shared/assets/${id}/content`,
  }
}

it("derives browser accept families and enforces document cardinality", async () => {
  const change = vi.fn()
  const upload: AssetUploader = vi
    .fn()
    .mockResolvedValueOnce(metadata(FIRST_ID, "image", "frame.png"))
    .mockResolvedValueOnce(metadata(SECOND_ID, "video", "clip.mp4"))
  render(
    <AssetField
      component={component}
      ids={[]}
      onChange={change}
      upload={upload}
    />
  )

  const picker = screen.getByLabelText("Upload Reference media")
  expect(picker).toHaveAttribute("accept", "image/*,video/*,audio/*")
  expect(picker).toHaveAttribute("multiple")

  await userEvent.upload(picker, [
    new File(["frame"], "frame.png", { type: "image/png" }),
    new File(["video"], "clip.mp4", { type: "video/mp4" }),
    new File(["extra"], "extra.mp3", { type: "audio/mpeg" }),
  ])

  await waitFor(() =>
    expect(change).toHaveBeenLastCalledWith([FIRST_ID, SECOND_ID])
  )
  expect(upload).toHaveBeenCalledTimes(2)
  expect(screen.getByRole("img", { name: "frame.png" })).toHaveAttribute(
    "src",
    `/api/shared/assets/${FIRST_ID}/content`
  )
  expect(screen.getByText("2 of 2 assets")).toBeInTheDocument()
  expect(picker).toBeDisabled()
})

it("reports upload progress and allows removal without deleting managed media", async () => {
  let finish: ((value: PublicMediaMetadata) => void) | undefined
  const upload: AssetUploader = (_file, _signal, progress) => {
    progress(35)
    return new Promise<PublicMediaMetadata>((resolve) => {
      finish = resolve
    })
  }
  const change = vi.fn()
  render(
    <AssetField
      component={component}
      ids={[]}
      onChange={change}
      upload={upload}
    />
  )

  await userEvent.upload(
    screen.getByLabelText("Upload Reference media"),
    new File(["frame"], "frame.png", { type: "image/png" })
  )
  expect(
    await screen.findByRole("progressbar", { name: "Uploading frame.png" })
  ).toHaveAttribute("aria-valuenow", "35")

  finish?.(metadata(FIRST_ID, "image", "frame.png"))
  await screen.findByRole("img", { name: "frame.png" })
  await userEvent.click(
    screen.getByRole("button", { name: "Remove frame.png" })
  )
  expect(change).toHaveBeenLastCalledWith([])
  expect(screen.queryByText("frame.png")).not.toBeInTheDocument()
})

it("announces upload failures and cancels pending work on removal", async () => {
  const aborts: AbortSignal[] = []
  const upload: AssetUploader = vi.fn((_file, signal) => {
    aborts.push(signal)
    return Promise.reject(new Error("upload refused"))
  })
  render(
    <AssetField
      component={component}
      ids={[]}
      onChange={() => undefined}
      upload={upload}
    />
  )

  await userEvent.upload(
    screen.getByLabelText("Upload Reference media"),
    new File(["bad"], "bad.png", { type: "image/png" })
  )
  expect(await screen.findByRole("alert")).toHaveTextContent("upload refused")
  await userEvent.click(screen.getByRole("button", { name: "Remove bad.png" }))
  expect(aborts[0]?.aborted).toBe(true)
})

it("refuses an unsafe returned preview URL and never accepts its opaque id", async () => {
  const change = vi.fn()
  const upload: AssetUploader = vi.fn().mockResolvedValue({
    ...metadata(FIRST_ID, "image", "frame.png"),
    contentUrl: "https://shared.internal/assets/secret",
  })
  render(
    <AssetField
      component={component}
      ids={[]}
      onChange={change}
      upload={upload}
    />
  )

  await userEvent.upload(
    screen.getByLabelText("Upload Reference media"),
    new File(["frame"], "frame.png", { type: "image/png" })
  )
  expect(await screen.findByRole("alert")).toHaveTextContent(
    /unsafe|safe same-origin/i
  )
  expect(change).not.toHaveBeenCalled()
})
