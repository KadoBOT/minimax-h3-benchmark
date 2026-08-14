/**
 * The 1–10 rating control.
 *
 * Ten segments rather than five stars, because the whole point of the lab is separating clips
 * that are nearly the same — five levels collapse them. Keys 1–9 and 0 set a rating from
 * anywhere in a judging flow, so the mouse is optional.
 */

import { Star } from "lucide-react"

import { useMeta } from "@/api/hooks"
import { cn } from "@/lib/utils"

export const STARS_MAX = 10
export const CRITERION_MAX = 5

export function StarRating({
  value,
  onChange,
  onClear,
  size = "default",
  className,
}: {
  value: number | null | undefined
  onChange: (stars: number) => void
  onClear?: () => void
  size?: "default" | "sm"
  className?: string
}) {
  const current = value ?? 0

  return (
    <div
      className={cn("flex items-center gap-1", className)}
      role="group"
      aria-label="Rating out of ten"
      data-testid="star-rating"
    >
      <div className="flex items-center gap-0.5 sm:gap-[3px]">
        {Array.from({ length: STARS_MAX }, (_, index) => {
          const star = index + 1
          const filled = star <= current
          return (
            <button
              key={star}
              type="button"
              aria-label={`${star} out of ${STARS_MAX}`}
              aria-pressed={filled}
              onClick={() => (star === current && onClear ? onClear() : onChange(star))}
              className={cn(
                "rounded-sm transition-colors focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:outline-none",
                // Wider hit targets on touch; still dense on desktop.
                size === "sm" ? "h-7 w-2.5 sm:h-4 sm:w-2" : "h-8 w-3.5 sm:h-6 sm:w-3",
                filled ? "bg-mint" : "bg-rule hover:bg-mint-dim"
              )}
            />
          )
        })}
      </div>
      <span
        className={cn(
          "tabular ml-1.5 font-mono tracking-tight",
          size === "sm" ? "text-[11px]" : "text-sm",
          value == null ? "text-muted-foreground" : "text-mint"
        )}
      >
        {value ?? "—"}
      </span>
    </div>
  )
}

/** Read-only stars, for lists and tables. */
export function StarsRead({ value, className }: { value: number | null | undefined; className?: string }) {
  return (
    <span
      className={cn(
        "tabular inline-flex items-center gap-1 font-mono text-xs",
        value == null ? "text-muted-foreground" : "text-mint",
        className
      )}
      title={value == null ? "not rated" : `${value} out of ${STARS_MAX}`}
    >
      <Star className="size-3" strokeWidth={2.4} fill={value == null ? "none" : "currentColor"} />
      {value ?? "—"}
    </span>
  )
}

/**
 * The five criteria, each 1–5.
 *
 * Optional by design: stars alone are enough to sort a night's work. The criteria are for the
 * runs where you want to say *why* — and they are what the composite score prefers when present,
 * because "good motion, poor detail" survives a week and "7" does not.
 */
export function CriteriaRating({
  value,
  stars,
  onChange,
  className,
}: {
  value: Record<string, number>
  /** Criteria are stored beside a star rating, so one is needed before they can be saved. */
  stars: number | null | undefined
  onChange: (criteria: Record<string, number>) => void
  className?: string
}) {
  const meta = useMeta()
  const criteria = meta.data?.criteria ?? []
  if (criteria.length === 0) return null

  return (
    <div className={cn("space-y-2", className)}>
      {criteria.map((name) => {
        const label = meta.data?.criterion_labels?.[name] ?? name
        const current = value[name] ?? 0
        return (
          <div key={name} className="flex flex-wrap items-center justify-between gap-2 sm:gap-4">
            <span className="text-muted-foreground text-xs">{label}</span>
            <div className="flex items-center gap-1 sm:gap-[3px]" role="group" aria-label={label}>
              {Array.from({ length: CRITERION_MAX }, (_, index) => {
                const score = index + 1
                const filled = score <= current
                return (
                  <button
                    key={score}
                    type="button"
                    aria-label={`${label}: ${score} of ${CRITERION_MAX}`}
                    aria-pressed={filled}
                    onClick={() => {
                      const next = { ...value }
                      if (score === current) delete next[name]
                      else next[name] = score
                      onChange(next)
                    }}
                    className={cn(
                      "focus-visible:ring-ring/60 h-5 w-5 sm:h-4 sm:w-4 rounded-sm transition-colors focus-visible:ring-2 focus-visible:outline-none",
                      filled ? "bg-mint" : "bg-rule hover:bg-mint-dim"
                    )}
                  />
                )
              })}
            </div>
          </div>
        )
      })}
      {stars == null ? (
        <p className="text-muted-foreground text-xs">
          Criteria are saved with a star rating; setting one here will record a 5 unless you
          give it a different one above.
        </p>
      ) : null}
    </div>
  )
}
