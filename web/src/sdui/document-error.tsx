import { useId } from "react"
import { AlertTriangle, RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"

export function DocumentError({
  title = "This shared view is incompatible",
  detail,
  issues = [],
  retrying = false,
  onRetry,
}: {
  title?: string
  detail: string
  issues?: readonly string[]
  retrying?: boolean
  onRetry?: () => void
}) {
  const titleId = useId()
  return (
    <section
      role="alert"
      aria-live="assertive"
      aria-labelledby={titleId}
      className="rounded-lg border border-crimson-dim/60 bg-crimson-dim/10 p-4"
    >
      <div className="flex items-start gap-3">
        <AlertTriangle
          aria-hidden="true"
          className="mt-0.5 size-4 shrink-0 text-crimson"
        />
        <div className="min-w-0 flex-1">
          <h2 id={titleId} className="text-sm font-medium text-bone">
            {title}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">{detail}</p>
          {issues.length > 0 ? (
            <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-muted-foreground">
              {issues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          ) : null}
          {onRetry ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mt-3"
              disabled={retrying}
              onClick={onRetry}
            >
              <RefreshCw
                aria-hidden="true"
                className={retrying ? "animate-spin" : undefined}
              />
              {retrying ? "Trying again" : "Try again"}
            </Button>
          ) : null}
        </div>
      </div>
    </section>
  )
}
