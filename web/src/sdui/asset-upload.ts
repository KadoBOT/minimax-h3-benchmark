import type { PublicMediaMetadata } from "@/api/schema"
import { routes } from "@/api/routes"

import { parsePublicMediaMetadata } from "./contracts"

export type AssetUploader = (
  file: File,
  signal: AbortSignal,
  onProgress: (percent: number) => void
) => Promise<PublicMediaMetadata>

export const uploadSharedAsset: AssetUploader = (file, signal, onProgress) =>
  new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open("POST", routes.sharedAssets())
    request.responseType = "json"
    request.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress((event.loaded / event.total) * 100)
      }
    }
    request.onerror = () =>
      reject(new Error("The managed asset upload could not be sent."))
    request.onabort = () =>
      reject(new DOMException("Upload cancelled", "AbortError"))
    request.onload = () => {
      const payload: unknown =
        request.response ??
        (() => {
          try {
            return JSON.parse(request.responseText) as unknown
          } catch {
            return null
          }
        })()
      if (request.status < 200 || request.status >= 300) {
        const problem =
          typeof payload === "object" && payload !== null
            ? (payload as { detail?: unknown; error?: unknown })
            : null
        reject(
          new Error(
            typeof problem?.detail === "string"
              ? problem.detail
              : typeof problem?.error === "string"
                ? problem.error
                : `Upload failed with HTTP ${request.status}.`
          )
        )
        return
      }
      try {
        resolve(parsePublicMediaMetadata(payload))
      } catch (error) {
        reject(error)
      }
    }
    signal.addEventListener("abort", () => request.abort(), { once: true })
    const body = new FormData()
    body.append("file", file)
    request.send(body)
  })
