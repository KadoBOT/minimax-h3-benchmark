/**
 * The facts a person reads about a run: what it cost, and the config that made it.
 *
 * Shared by the run page and the strip hover card so the peek matches the open page.
 */

import type { GenerationConfig } from "@/api/schema"
import { display } from "@/lib/config"
import { cn } from "@/lib/utils"

function isEmptyList(value: unknown): boolean {
  return Array.isArray(value) && value.length === 0
}

function configEntries(config: GenerationConfig): [string, unknown][] {
  const rows: [string, unknown][] = []
  for (const [field, value] of Object.entries(config)) {
    if (field === "widgets" && value && typeof value === "object" && !Array.isArray(value)) {
      for (const [name, item] of Object.entries(value as Record<string, unknown>)) {
        if (item !== null && item !== "" && !isEmptyList(item)) rows.push([name, item])
      }
      continue
    }
    if (value !== null && value !== "" && !isEmptyList(value)) rows.push([field, value])
  }
  return rows
}

export function RunConfigList({
  config,
  labels,
  compact = false,
}: {
  config: GenerationConfig
  labels: (field: string) => string
  compact?: boolean
}) {
  return (
    <dl className={cn("grid gap-x-6 gap-y-2", compact ? "grid-cols-1" : "grid-cols-1 sm:grid-cols-2")}>
      {configEntries(config).map(([field, value]) => (
        <div key={field} className="flex items-baseline justify-between gap-2 sm:gap-3 text-sm">
          <dt className="text-muted-foreground truncate shrink-0 max-w-[55%]">{labels(field)}</dt>
          <dd className="text-bone truncate text-right font-mono text-xs">{display(value)}</dd>
        </div>
      ))}
    </dl>
  )
}


