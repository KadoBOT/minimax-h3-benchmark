/** Page furniture: one header treatment, one loading treatment, one failure treatment. */

import { AlertTriangle, Loader2 } from "lucide-react"

import { ApiError } from "@/api/client"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

export function PageHeader({
  eyebrow,
  title,
  lede,
  children,
}: {
  eyebrow?: string
  title: string
  lede?: string
  children?: React.ReactNode
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow ? <div className="edge-code text-signal mb-1.5">{eyebrow}</div> : null}
        <h1 className="display text-bone text-2xl leading-none lg:text-[1.75rem]">{title}</h1>
        {lede ? <p className="text-muted-foreground mt-2 max-w-prose text-sm">{lede}</p> : null}
      </div>
      {children ? <div className="flex shrink-0 items-center gap-2">{children}</div> : null}
    </header>
  )
}

export function Section({
  title,
  hint,
  children,
  className,
  actions,
}: {
  title: string
  hint?: string
  children: React.ReactNode
  className?: string
  actions?: React.ReactNode
}) {
  return (
    <section className={cn("panel p-4", className)}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-bone text-sm font-semibold tracking-tight">{title}</h2>
          {hint ? <p className="text-muted-foreground mt-0.5 text-xs">{hint}</p> : null}
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-1.5">{actions}</div> : null}
      </div>
      {children}
    </section>
  )
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="text-muted-foreground flex items-center gap-2 py-8 text-sm" role="status">
      <Loader2 className="size-4 animate-spin" />
      {label}
    </div>
  )
}

export function StripSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2.5" aria-hidden>
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="space-y-1.5">
          <Skeleton className="aspect-[32/3] w-full rounded-sm" />
          <Skeleton className="h-2.5 w-48" />
        </div>
      ))}
    </div>
  )
}

/** A failed read, stated as what went wrong and what to do next. */
export function Failure({
  error,
  onRetry,
  what = "load that",
}: {
  error: unknown
  onRetry?: () => void
  what?: string
}) {
  const problem = error instanceof ApiError ? error : null
  const title = problem?.message ?? `Could not ${what}`
  const detail =
    problem?.detail ?? (error instanceof Error ? error.message : "Something unexpected happened.")

  return (
    <div
      role="alert"
      className="border-crimson-dim/50 bg-crimson/5 flex items-start gap-3 rounded-lg border p-4"
    >
      <AlertTriangle className="text-crimson mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="text-bone text-sm font-medium">{title}</div>
        <p className="text-muted-foreground mt-1 text-sm">{detail}</p>
        {problem?.fields && Object.keys(problem.fields).length > 1 ? (
          <ul className="text-muted-foreground mt-2 space-y-0.5 text-xs">
            {Object.entries(problem.fields).map(([field, message]) => (
              <li key={field} className="font-mono">
                {field}: {message}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  )
}

export function Stat({
  label,
  value,
  tone = "bone",
  hint,
}: {
  label: string
  value: React.ReactNode
  tone?: "bone" | "signal" | "mint" | "crimson" | "muted"
  hint?: string
}) {
  const tones = {
    bone: "text-bone",
    signal: "text-signal",
    mint: "text-mint",
    crimson: "text-crimson",
    muted: "text-muted-foreground",
  } as const

  return (
    <div title={hint}>
      <div className="edge-code text-muted-foreground">{label}</div>
      <div className={cn("tabular mt-1 text-lg leading-none font-semibold", tones[tone])}>
        {value}
      </div>
    </div>
  )
}
