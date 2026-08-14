/**
 * The single place the app talks to the API.
 *
 * Every refusal arrives as the same `Problem` shape, so this throws one error type with the
 * pieces already separated: a short line to show, a longer detail to expand, and a `kind`
 * callers branch on (an unreachable ComfyUI is a banner; a bad field is inline).
 */

import type { Problem } from "./schema"

export type ProblemKind = Problem["kind"]

export class ApiError extends Error {
  readonly status: number
  readonly kind: ProblemKind
  readonly detail: string
  readonly fields: Record<string, string>

  constructor(status: number, problem: Problem) {
    super(problem.error)
    this.name = "ApiError"
    this.status = status
    this.kind = problem.kind ?? "invalid"
    this.detail = problem.detail || problem.error
    this.fields = problem.fields ?? {}
  }

  /** True when retrying later could plausibly succeed without the user changing anything. */
  get transient(): boolean {
    return this.kind === "comfy_unreachable" || this.status >= 500
  }
}

export type Params = Record<string, string | number | boolean | null | undefined | string[]>

export function withParams(path: string, params?: Params): string {
  if (!params) return path
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue
    if (Array.isArray(value)) {
      // FastAPI reads repeated keys as a list; a joined string would arrive as one value.
      for (const item of value) search.append(key, String(item))
    } else {
      search.append(key, String(value))
    }
  }
  const query = search.toString()
  return query ? `${path}?${query}` : path
}

type RequestOptions = {
  method?: string
  body?: unknown
  params?: Params
  signal?: AbortSignal
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, params, signal } = options
  const isForm = body instanceof FormData

  let response: Response
  try {
    response = await fetch(withParams(path, params), {
      method,
      signal,
      headers: body !== undefined && !isForm ? { "Content-Type": "application/json" } : undefined,
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
    })
  } catch (cause) {
    // A dead server produces a TypeError with no useful message; name the real cause.
    throw new ApiError(0, {
      error: "the lab is not answering",
      detail:
        cause instanceof Error && cause.name === "AbortError"
          ? "the request was cancelled"
          : `${method} ${path} could not be sent. Is \`h3lab serve\` still running?`,
      kind: "internal",
    })
  }

  if (response.status === 204) return undefined as T

  const text = await response.text()
  const payload = text ? safeJson(text) : null

  if (!response.ok) {
    throw new ApiError(response.status, asProblem(payload, response, method, path))
  }
  return payload as T
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return { raw: text }
  }
}

function asProblem(payload: unknown, response: Response, method: string, path: string): Problem {
  if (isProblem(payload)) return payload
  return {
    error: `${response.status} from ${method} ${path}`,
    detail: typeof payload === "string" ? payload : response.statusText || "unexpected response",
    kind: response.status === 404 ? "not_found" : "internal",
  }
}

function isProblem(value: unknown): value is Problem {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as Problem).error === "string" &&
    typeof (value as Problem).detail === "string"
  )
}

export const api = {
  get: <T>(path: string, params?: Params, signal?: AbortSignal) =>
    request<T>(path, { params, signal }),
  post: <T>(path: string, body?: unknown, params?: Params) =>
    request<T>(path, { method: "POST", body, params }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: "PUT", body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: "PATCH", body }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
}
