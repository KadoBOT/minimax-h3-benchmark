/**
 * The filmstrip: six frames pulled from a run's video, with an edge code beneath it.
 *
 * This is the app's signature. Fifty near-identical five-second clips cannot be judged from
 * fifty play buttons, but they can be scanned as contact strips — and because every strip is
 * cut at the same six timecodes, divergence between two runs lands at the same x position.
 * Hovering scrubs: the strip is one wide image, so moving across it moves through the clip.
 *
 * Resting on one does something else. Sweeping across a list is scanning; stopping is asking
 * a question about that run, and the answer to most of them is motion — the judder and warp
 * a benchmark exists to catch, which six still frames cannot show. So a pointer that stays
 * put gets the clip itself.
 *
 * It plays in a floating card rather than inside the strip. A strip is 6:1 by construction,
 * which is the right shape for six frames in a row and the wrong shape for one: a clip played
 * in that box is cropped to a letterbox slice with the subject's head and feet outside it.
 * The card is anchored to the strip and sized by the video's own aspect ratio, so what you
 * are judging is the frame the model actually produced.
 */

import { useEffect, useRef, useState } from "react"

import { PreviewCard } from "@base-ui/react/preview-card"

import { routes } from "@/api/routes"
import type { Run } from "@/api/schema"
import { seconds } from "@/lib/format"
import { cn } from "@/lib/utils"

export const STRIP_TILES = 6

/** Long enough that crossing a list of cards costs nothing, short enough to feel immediate. */
export const PREVIEW_DELAY_MS = 320

type FilmstripProps = {
  run: Run
  /** Frames rendered side by side; a strip is one image, so this only sets the aspect box. */
  className?: string
  /** Scrub with the pointer. Off in dense lists where the pointer is usually just passing. */
  scrub?: boolean
  /** Play the clip when the pointer rests. Off where the video is already on screen. */
  preview?: boolean
  onClick?: () => void
}

function wantsStillness(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  )
}

export function Filmstrip({
  run,
  className,
  scrub = false,
  preview = true,
  onClick,
}: FilmstripProps) {
  const [tile, setTile] = useState<number | null>(null)
  const [playing, setPlaying] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const dwell = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => () => clearTimeout(dwell.current), [])

  const strip = run.artifact?.strip_path
  const poster = run.artifact?.poster_path
  const video = run.artifact?.video_path
  const previewable = preview && Boolean(video)

  const rest = () => {
    clearTimeout(dwell.current)
    setPlaying(false)
  }

  if (!strip && !poster) {
    return <StripPlaceholder run={run} className={className} onClick={onClick} />
  }

  const handleEnter = (event: React.PointerEvent) => {
    if (!previewable || wantsStillness() || event.pointerType === "touch") return
    clearTimeout(dwell.current)
    dwell.current = setTimeout(() => setPlaying(true), PREVIEW_DELAY_MS)
  }

  // Scrubbing and the floating card are no longer rivals for the same box, so both run at
  // once: the strip follows the pointer, the card plays the clip beside it.
  const handleMove = (event: React.PointerEvent) => {
    if (!scrub || !strip || !box.current) return
    const bounds = box.current.getBoundingClientRect()
    const ratio = (event.clientX - bounds.left) / bounds.width
    setTile(Math.min(STRIP_TILES - 1, Math.max(0, Math.floor(ratio * STRIP_TILES))))
  }

  const handleLeave = () => {
    setTile(null)
    rest()
  }

  const { width, height } = run.artifact ?? {}
  const w = width || 16
  const h = height || 9
  const stripAspect = `${STRIP_TILES * w} / ${h}`

  // Showing one frame means widening the image to STRIP_TILES× and sliding it into place.
  const zoomed = tile !== null && strip
  const url = strip ? routes.strip(strip) : routes.poster(poster as string)

  return (
    <>
      <div
        ref={box}
        onPointerEnter={handleEnter}
        onPointerMove={handleMove}
        onPointerLeave={handleLeave}
        onClick={onClick}
        className={cn(
          "bg-ink relative max-w-full min-w-0 overflow-hidden touch-pan-y min-h-[36px] sm:min-h-0",
          onClick && "cursor-pointer",
          className
        )}
        style={{
          ...(!className?.includes("aspect-") ? { aspectRatio: stripAspect } : {}),
        }}
        data-testid="filmstrip"
        data-frame={tile ?? ""}
        data-playing={playing || undefined}
      >
        <img
          src={url}
          alt=""
          loading="lazy"
          decoding="async"
          draggable={false}
          className={cn(
            "h-full origin-left select-none object-cover",
            zoomed ? "transition-none" : "w-full transition-[width] duration-150"
          )}
          style={
            zoomed
              ? { width: `${STRIP_TILES * 100}%`, transform: `translateX(-${(tile / STRIP_TILES) * 100}%)` }
              : undefined
          }
        />
        {strip ? <Perforations /> : null}
      </div>
      {previewable ? <HoverPreview run={run} anchor={box} open={playing} onClose={rest} /> : null}
    </>
  )
}

/**
 * The clip, floating beside the strip it belongs to.
 *
 * Anchored rather than inline: the strip is 6:1 and the video is not, and the whole point of
 * the preview is seeing the frame as it was generated. Base UI does the portalling and the
 * flipping so a card near the bottom of a long list opens upward instead of off-screen.
 *
 * Nothing here takes the pointer. The card can land under the cursor after a flip, and a card
 * that captured hover would pull the pointer off its own anchor, close, reopen, and flicker.
 */
function HoverPreview({
  run,
  anchor,
  open,
  onClose,
}: {
  run: Run
  anchor: React.RefObject<HTMLDivElement | null>
  open: boolean
  onClose: () => void
}) {
  const { video_path: video, poster_path: poster, width, height, fps, frame_count } = run.artifact ?? {}
  if (!video) return null

  const duration = fps && frame_count ? frame_count / fps : null

  return (
    <PreviewCard.Root open={open} onOpenChange={(next) => !next && onClose()}>
      <PreviewCard.Portal>
        <PreviewCard.Positioner
          anchor={anchor}
          side="top"
          sideOffset={10}
          collisionPadding={16}
          className="pointer-events-none z-50"
        >
          <PreviewCard.Popup
            data-testid="hover-card"
            className="border-rule bg-panel w-[30rem] max-w-[85vw] overflow-hidden rounded-lg border shadow-2xl"
          >
            <video
              key={video}
              src={routes.video(video)}
              poster={poster ? routes.poster(poster) : undefined}
              autoPlay
              loop
              muted
              playsInline
              preload="none"
              data-testid="hover-preview"
              className="bg-ink block w-full"
              style={{ aspectRatio: width && height ? `${width} / ${height}` : "16 / 9" }}
            />
            <div className="edge-code text-muted-foreground flex items-center gap-2.5 px-2.5 py-1.5">
              <span className="text-bone/70 truncate tracking-[0.14em]">{run.label}</span>
              <span className="ml-auto shrink-0">
                {width && height ? `${width}×${height}` : "—"}
                {duration ? ` · ${seconds(duration)}` : ""}
              </span>
            </div>
          </PreviewCard.Popup>
        </PreviewCard.Positioner>
      </PreviewCard.Portal>
    </PreviewCard.Root>
  )
}

/** Frame dividers, drawn as a repeating gradient so there is no element per frame. */
function Perforations() {
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-0"
      style={{
        backgroundImage: `repeating-linear-gradient(to right, transparent, transparent calc(${100 / STRIP_TILES}% - 1px), rgba(16,14,12,.85) calc(${100 / STRIP_TILES}% - 1px), rgba(16,14,12,.85) ${100 / STRIP_TILES}%)`,
      }}
    />
  )
}

const ERROR_LIMIT = 120

/** Cut at a space and mark the cut, so a clipped reason never reads as the whole reason. */
function shorten(text: string | null | undefined): string {
  const clean = (text ?? "").trim()
  if (clean.length <= ERROR_LIMIT) return clean
  const head = clean.slice(0, ERROR_LIMIT)
  const space = head.lastIndexOf(" ")
  return `${(space > ERROR_LIMIT / 2 ? head.slice(0, space) : head).trimEnd()}…`
}

function StripPlaceholder({
  run,
  className,
  onClick,
}: {
  run: Run
  className?: string
  onClick?: () => void
}) {
  const message =
    run.status === "failed"
      ? shorten(run.error?.split("\n")[0]) || "failed"
      : run.status === "running"
        ? "rendering"
        : run.status === "queued"
          ? "queued"
          : "no preview"

  const { width, height } = run.artifact ?? {}
  const w = width || 16
  const h = height || 9
  const stripAspect = `${STRIP_TILES * w} / ${h}`

  return (
    <div
      onClick={onClick}
      data-testid="filmstrip-placeholder"
      className={cn(
        "border-rule/60 bg-panel/60 flex items-center justify-center border border-dashed",
        run.status === "failed" && "border-crimson-dim/60",
        onClick && "cursor-pointer",
        className
      )}
      style={!className?.includes("aspect-") ? { aspectRatio: stripAspect } : undefined}
    >
      <span
        className={cn(
          "edge-code px-2 text-center",
          run.status === "failed" ? "text-crimson" : "text-muted-foreground"
        )}
      >
        {message}
      </span>
    </div>
  )
}
