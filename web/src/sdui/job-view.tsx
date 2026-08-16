import type { JobDocument } from "@/api/schema"
import { routes } from "@/api/routes"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"

export type LiveJobProgress = {
  step: number | null
  stepTotal: number | null
  previewSeq: number | null
}

type JobComponent = JobDocument["components"][number]
type JobAction = JobDocument["actions"][number]
type SectionComponent = Extract<JobComponent, { kind: "section" }>

export function SduiJobView({
  document,
  localRunId,
  live,
  diagnostics = [],
  busy = false,
  onCancel,
  onRetryCollection,
}: {
  document: JobDocument
  localRunId: string
  live?: LiveJobProgress | null
  diagnostics?: readonly string[]
  busy?: boolean
  onCancel?: () => void | Promise<void>
  onRetryCollection?: () => void | Promise<void>
}) {
  const safetyIssues = validateLocalTargets(document, localRunId)
  const groups = groupComponents(document.components)
  const unavailable =
    document.availability.state === "available"
      ? null
      : document.availability.reason.detail

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs text-muted-foreground">
        <span>Shared job {document.jobId}</span>
        <span>Schema {document.schemaRevision}</span>
      </div>

      {unavailable ? (
        <p
          role="alert"
          className="rounded border border-crimson-dim/50 bg-crimson/5 p-3 text-sm"
        >
          {unavailable}
        </p>
      ) : null}

      {groups.map((group, index) => (
        <section
          key={group.section?.id ?? `job-group-${index}`}
          aria-labelledby={
            group.section ? `job-section-${group.section.id}` : undefined
          }
          className="space-y-3 rounded-lg border border-rule bg-panel/30 p-3"
        >
          {group.section ? (
            <header>
              <h3
                id={`job-section-${group.section.id}`}
                className="text-sm font-medium text-bone"
              >
                {group.section.title}
              </h3>
              {group.section.description ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  {group.section.description}
                </p>
              ) : null}
            </header>
          ) : null}
          {group.components.map((component) => (
            <JobItem
              key={component.id}
              component={component}
              localRunId={localRunId}
              live={live}
              unsafe={safetyIssues.has(component.id)}
            />
          ))}
        </section>
      ))}

      {document.actions.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {document.actions.map((action) => {
            if (safetyIssues.has(action.id) || action.kind === "delete")
              return null
            const invoke =
              action.kind === "cancel"
                ? onCancel
                : action.kind === "retry_collection"
                  ? onRetryCollection
                  : undefined
            return (
              <Button
                key={action.id}
                type="button"
                variant={action.kind === "cancel" ? "destructive" : "outline"}
                size="sm"
                disabled={busy || !invoke || Boolean(unavailable)}
                onClick={() => void invoke?.()}
              >
                {action.label}
              </Button>
            )
          })}
        </div>
      ) : null}

      {[...diagnostics, ...safetyIssues.values()].length > 0 ? (
        <aside
          role="alert"
          className="rounded border border-signal/30 bg-signal/5 p-3"
        >
          <p className="text-xs font-medium text-bone">
            Shared view diagnostics
          </p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-xs text-muted-foreground">
            {[...diagnostics, ...safetyIssues.values()].map((diagnostic) => (
              <li key={diagnostic}>{diagnostic}</li>
            ))}
          </ul>
        </aside>
      ) : null}
    </div>
  )
}

function JobItem({
  component,
  localRunId,
  live,
  unsafe,
}: {
  component: Exclude<JobComponent, SectionComponent>
  localRunId: string
  live?: LiveJobProgress | null
  unsafe: boolean
}) {
  if (unsafe) return null
  switch (component.kind) {
    case "status":
      return (
        <div
          role="status"
          aria-label={component.label}
          aria-live="polite"
          className="flex items-start justify-between gap-3 rounded border border-rule p-3"
        >
          <span className="text-sm font-medium text-bone">
            {component.label}
          </span>
          {component.detail ? (
            <span className="text-right text-xs text-muted-foreground">
              {component.detail}
            </span>
          ) : null}
        </div>
      )
    case "progress": {
      const current =
        live?.step != null && live.stepTotal != null
          ? live.step
          : (component.current ?? null)
      const total =
        live?.step != null && live.stepTotal != null
          ? live.stepTotal
          : (component.total ?? null)
      const value =
        current != null && total != null && total > 0
          ? current / total
          : component.value
      const percent = Math.round(Math.min(1, Math.max(0, value)) * 100)
      const label = component.label ?? "Job progress"
      return (
        <div className="space-y-1.5">
          <div className="flex justify-between gap-2 text-xs text-muted-foreground">
            <span>{label}</span>
            <span>
              {current != null && total != null
                ? `${current} / ${total}`
                : `${percent}%`}
            </span>
          </div>
          <Progress
            aria-label={label}
            aria-valuenow={percent}
            aria-valuemin={0}
            aria-valuemax={100}
            value={percent}
          />
        </div>
      )
    }
    case "log":
      return (
        <ol
          role="log"
          aria-label="Job log"
          aria-live="polite"
          className="max-h-48 space-y-1 overflow-auto rounded bg-ink/50 p-2 font-mono text-xs"
        >
          {component.entries.length === 0 ? (
            <li className="text-muted-foreground">No log entries yet.</li>
          ) : (
            component.entries.map((entry) => (
              <li
                key={entry.sequence}
                className={entry.level === "error" ? "text-crimson" : ""}
              >
                <time dateTime={entry.at}>
                  {new Date(entry.at).toLocaleTimeString()}
                </time>{" "}
                <span className="uppercase">[{entry.level}]</span>{" "}
                {entry.message}
              </li>
            ))
          )}
        </ol>
      )
    case "preview": {
      const sequence = live?.previewSeq ?? component.sequence
      const source =
        sequence === component.sequence
          ? component.src
          : `${routes.sharedJobPreview(localRunId)}?sequence=${sequence}`
      return component.mime.startsWith("video/") ? (
        <video
          key={sequence}
          src={source}
          aria-label={`Job preview ${sequence}`}
          autoPlay
          loop
          muted
          playsInline
          className="max-h-72 w-full rounded bg-ink object-contain"
        />
      ) : (
        <img
          key={sequence}
          src={source}
          alt={`Job preview ${sequence}`}
          className="max-h-72 w-full rounded bg-ink object-contain"
        />
      )
    }
    case "video":
      return (
        <video
          src={component.src}
          poster={component.poster ?? undefined}
          aria-label="Generated video"
          controls
          loop
          playsInline
          className="max-h-[65vh] w-full rounded bg-ink object-contain"
        />
      )
    case "download":
      return (
        <a
          href={component.href}
          download={component.filename}
          className="inline-flex text-sm text-signal underline underline-offset-4"
        >
          {component.label}
        </a>
      )
  }
}

function validateLocalTargets(
  document: JobDocument,
  runId: string
): Map<string, string> {
  const issues = new Map<string, string>()
  for (const component of document.components) {
    if (
      component.kind === "preview" &&
      component.src !== routes.sharedJobPreview(runId)
    ) {
      issues.set(
        component.id,
        `${component.id} targets a different local run and was hidden.`
      )
    }
    if (
      component.kind === "video" &&
      component.src !== routes.sharedJobVideo(runId)
    ) {
      issues.set(
        component.id,
        `${component.id} targets a different local run and was hidden.`
      )
    }
    if (
      component.kind === "download" &&
      component.href !== routes.sharedJobVideo(runId)
    ) {
      issues.set(
        component.id,
        `${component.id} targets a different local run and was hidden.`
      )
    }
  }
  for (const action of document.actions) {
    const expected = expectedActionEndpoint(action, runId)
    if (!expected || action.endpoint !== expected) {
      issues.set(
        action.id,
        `${action.id} targets a different local run and was hidden.`
      )
    }
  }
  return issues
}

function expectedActionEndpoint(
  action: JobAction,
  runId: string
): string | null {
  if (action.kind === "cancel") return routes.runCancel(runId)
  if (action.kind === "retry_collection")
    return routes.runRetryCollection(runId)
  return null
}

function groupComponents(components: JobComponent[]) {
  const groups: {
    section: SectionComponent | null
    components: Exclude<JobComponent, SectionComponent>[]
  }[] = []
  let current = {
    section: null as SectionComponent | null,
    components: [] as Exclude<JobComponent, SectionComponent>[],
  }
  for (const component of components) {
    if (component.kind === "section") {
      if (current.section || current.components.length) groups.push(current)
      current = { section: component, components: [] }
    } else {
      current.components.push(component)
    }
  }
  if (current.section || current.components.length) groups.push(current)
  return groups
}
