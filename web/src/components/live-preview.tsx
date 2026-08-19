/**
 * What ComfyUI is drawing, while it is drawing it.
 *
 * The URL carries the frame count so each one is a fetch of its own rather than a cache hit,
 * and a frame that cannot be shown takes itself off screen rather than leaving a broken picture
 * behind. The templates hand the whole clip to the preview node, so a frame is usually a short
 * video of the latent rather than a still.
 */

import { useState } from "react"

import { routes } from "@/api/routes"
import { cn } from "@/lib/utils"

export function LivePreview({
  runId,
  seq,
  mime,
  className,
}: {
  runId: string
  seq: number
  mime: string | null
  className?: string
}) {
  const [failed, setFailed] = useState<number | null>(null)
  if (failed === seq) return null

  const source = `${routes.runPreview(runId)}?f=${seq}`
  const label = `Preview frame ${seq} of the run in flight`

  return (
    <div className={cn("bg-ink/60 overflow-hidden", className)}>
      {mime?.startsWith("video/") ? (
        <video
          src={source}
          aria-label={label}
          className="max-h-[inherit] w-full object-contain"
          autoPlay
          loop
          muted
          playsInline
          onError={() => setFailed(seq)}
        />
      ) : (
        <img
          src={source}
          alt={label}
          className="max-h-[inherit] w-full object-contain"
          onError={() => setFailed(seq)}
        />
      )}
    </div>
  )
}
