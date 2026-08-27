/** Number and time formatting, in one place so a value never appears two ways. */

const NBSP = "\u00a0"

export function secPerIt(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—"
  return `${value.toFixed(2)}${NBSP}s/it`
}

export function seconds(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—"
  if (value < 60) return `${value.toFixed(1)}${NBSP}s`
  const minutes = Math.floor(value / 60)
  const rest = Math.round(value % 60)
  return `${minutes}m${NBSP}${String(rest).padStart(2, "0")}s`
}

export function stars(value: number | null | undefined): string {
  return value == null ? "—" : `${value.toFixed(1)}`
}

export function elo(value: number | null | undefined): string {
  return value == null ? "—" : Math.round(value).toString()
}

export function percent(value: number | null | undefined, digits = 0): string {
  if (value == null || !Number.isFinite(value)) return "—"
  return `${(value * 100).toFixed(digits)}%`
}

/** A signed delta, so the direction reads before the magnitude. */
export function delta(value: number | null | undefined, digits = 2, suffix = ""): string {
  if (value == null || !Number.isFinite(value)) return "—"
  const sign = value > 0 ? "+" : value < 0 ? "−" : "±"
  return `${sign}${Math.abs(value).toFixed(digits)}${suffix}`
}

export function bytes(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—"
  if (value < 1024) return `${value}${NBSP}B`
  const units = ["KB", "MB", "GB"]
  let size = value / 1024
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return `${size.toFixed(size < 10 ? 1 : 0)}${NBSP}${units[unit]}`
}

/** Short relative time. Absolute dates are noise when everything happened tonight. */
export function ago(iso: string | null | undefined): string {
  if (!iso) return "—"
  const then = Date.parse(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`)
  if (Number.isNaN(then)) return "—"
  const seconds = Math.max(0, (Date.now() - then) / 1000)
  if (seconds < 45) return "just now"
  if (seconds < 90) return "a minute ago"
  const minutes = seconds / 60
  if (minutes < 60) return `${Math.round(minutes)} min ago`
  const hours = minutes / 60
  if (hours < 24) return `${Math.round(hours)}h ago`
  const days = hours / 24
  if (days < 7) return `${Math.round(days)}d ago`
  return new Date(then).toLocaleDateString(undefined, { month: "short", day: "numeric" })
}

/** The exact moment, for a tooltip. Relative time answers "recently", not "when". */
export function exact(iso: string | null | undefined): string {
  if (!iso) return "unknown"
  const then = Date.parse(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`)
  return Number.isNaN(then) ? "unknown" : new Date(then).toLocaleString()
}

/**
 * The moment a run should be dated by, and the word for it.
 *
 * A whole sweep is created in the same millisecond, so dating runs by their creation gives a
 * page of identical ages that say only when you pressed the button. What a benchmark is read
 * by is when the work ended — and for anything still in flight, the most recent thing that
 * actually happened to it.
 */
export function moment(run: {
  created_at: string
  started_at?: string | null
  finished_at?: string | null
}): { at: string | null; verb: "finished" | "started" | "queued" } {
  if (run.finished_at) return { at: run.finished_at, verb: "finished" }
  if (run.started_at) return { at: run.started_at, verb: "started" }
  return { at: run.created_at ?? null, verb: "queued" }
}

export function shortHash(hash: string | null | undefined, length = 6): string {
  return hash ? hash.slice(0, length) : "—"
}

/** Trim a model filename to the part that distinguishes it. */
export function modelStem(filename: string | null | undefined): string {
  if (!filename) return "default"
  let stem = (filename.replaceAll("\\", "/").split("/").at(-1) ?? filename).replace(/\.[^.]+$/, "")
  for (const noise of ["minimax_h3_", "minimax-h3-", "minimax_"]) {
    if (stem.toLowerCase().startsWith(noise)) {
      stem = stem.slice(noise.length)
      break
    }
  }
  return stem || "default"
}

/**
 * A turbo LoRA in the few characters that tell it apart from the others.
 *
 * Mirrors `lora_stem` in `h3lab/domain/config.py`, which is what the run labels and the arena
 * standings use — a LoRA has to read the same in the picker as in the row it produced.
 */
export function loraStem(filename: string | null | undefined): string {
  const stem = modelStem(filename)
  for (const noise of ["turbo_", "turbo-"]) {
    if (stem.toLowerCase().startsWith(noise)) return stem.slice(noise.length) || "default"
  }
  return stem
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`
}
