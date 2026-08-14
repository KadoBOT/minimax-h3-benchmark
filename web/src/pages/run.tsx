/**
 * One run, in full.
 *
 * The video is the point, so it leads. Below it, the three questions asked about every run:
 * how good was it, how much did it cost, and what exactly produced it — the last of which is
 * also the button that makes another one like it.
 */

import { useState } from "react"
import {
  ArrowLeft,
  Copy,
  Download,
  Heart,
  Pin,
  RotateCw,
  Rows3,
  Save,
  Tag as TagIcon,
  Trash2,
  X,
} from "lucide-react"
import { Link, useNavigate, useParams } from "react-router"
import { toast } from "sonner"

import { routes } from "@/api/routes"
import {
  useClearRating,
  useDeleteRun,
  useMeta,
  usePatchRun,
  useRate,
  useRerun,
  useRun,
  useSavePreset,
  useSetBaseline,
} from "@/api/hooks"
import type { RunView } from "@/api/schema"
import { Filmstrip } from "@/components/filmstrip"
import { Failure, PageHeader, Section, Spinner, Stat } from "@/components/page"
import { CriteriaRating, StarRating } from "@/components/stars"
import { StatusChip } from "@/components/status-chip"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { useBench } from "@/lib/bench"
import { display, label as fieldLabel } from "@/lib/config"
import { ago, bytes, elo, moment, seconds, secPerIt, shortHash } from "@/lib/format"

export function RunPage() {
  const { runId } = useParams<{ runId: string }>()
  const query = useRun(runId)
  const meta = useMeta()

  if (query.isLoading) return <Spinner label="Opening the run" />
  if (query.isError || !query.data) {
    return (
      <Failure error={query.error} what="open that run" onRetry={() => query.refetch()} />
    )
  }

  return <RunDetail view={query.data} labels={(field: string) => fieldLabel(meta.data, field)} />
}

function RunDetail({ view, labels }: { view: RunView; labels: (field: string) => string }) {
  const { run } = view
  const navigate = useNavigate()
  const bench = useBench()
  const rate = useRate()
  const clearRating = useClearRating()
  const patch = usePatchRun()
  const rerun = useRerun()
  const remove = useDeleteRun()
  const savePreset = useSavePreset()
  const baseline = useSetBaseline()

  const [notes, setNotes] = useState(run.notes ?? "")
  const [tag, setTag] = useState("")
  const [presetName, setPresetName] = useState(run.label)

  const staged = bench.has(run.id)
  const dirty = notes !== (run.notes ?? "")
  const stamp = moment(run)

  return (
    <>
      <PageHeader eyebrow={`${stamp.verb} ${ago(stamp.at)}`} title={run.label}>
        <Button variant="ghost" size="sm" onClick={() => navigate(-1)}>
          <ArrowLeft data-icon="inline-start" className="size-3.5" />
          Back
        </Button>
        <Button
          variant={staged ? "secondary" : "outline"}
          size="sm"
          onClick={() => bench.toggle(run.id)}
        >
          <Rows3 data-icon="inline-start" className="size-3.5" />
          {staged ? "On the bench" : "Stage"}
        </Button>
        <Button size="sm" onClick={() => rerun.mutate({ id: run.id })}>
          <RotateCw data-icon="inline-start" className="size-3.5" />
          Run again
        </Button>
      </PageHeader>

      <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_23rem]">
        <div className="min-w-0 space-y-4">
          <div className="panel overflow-hidden p-0">
            {run.artifact?.video_path ? (
              <video
                key={run.artifact.video_path}
                src={routes.video(run.artifact.video_path)}
                poster={
                  run.artifact.poster_path ? routes.poster(run.artifact.poster_path) : undefined
                }
                controls
                loop
                playsInline
                className="bg-ink max-h-[55vh] sm:max-h-[65vh] w-full object-contain mx-auto"
                style={{
                  aspectRatio:
                    run.artifact?.width && run.artifact?.height
                      ? `${run.artifact.width} / ${run.artifact.height}`
                      : "16 / 9",
                }}
              />
            ) : (
              <div className="text-muted-foreground flex aspect-video items-center justify-center text-sm">
                {run.status === "failed" ? "This run produced nothing." : "No video yet."}
              </div>
            )}
            {run.artifact?.video_path ? (
              // The player is directly above; the strip's job here is scrubbing, not replaying.
              <Filmstrip run={run} scrub preview={false} className="border-rule border-t min-h-[44px] sm:min-h-0" />
            ) : null}
          </div>

          {run.error ? (
            <div className="border-crimson-dim/50 bg-crimson/5 rounded-lg border p-4">
              <div className="text-crimson mb-1 text-sm font-medium">It failed</div>
              <p className="text-muted-foreground font-mono text-xs break-words whitespace-pre-wrap">
                {run.error}
              </p>
            </div>
          ) : null}

          <Section title="Rating" hint="Stars are the fast judgement; the criteria are the argument.">
            <div className="flex flex-wrap items-center gap-4">
              <StarRating
                value={view.stars}
                onChange={(stars) => rate.mutate({ id: run.id, stars })}
                onClear={() => clearRating.mutate(run.id)}
              />
              {view.stars != null ? (
                <Button variant="ghost" size="sm" onClick={() => clearRating.mutate(run.id)}>
                  Clear
                </Button>
              ) : null}
            </div>
            <CriteriaRating
              value={view.criteria ?? {}}
              stars={view.stars}
              onChange={(criteria) =>
                rate.mutate({ id: run.id, stars: view.stars ?? 5, criteria })
              }
              className="mt-4"
            />
          </Section>

          <Section
            title="The config that made it"
            hint="The workflow download is the same settings as a graph ComfyUI opens."
          >
            <dl className="grid gap-x-6 gap-y-2 grid-cols-1 sm:grid-cols-2">
              {Object.entries(run.config)
                .filter(([, value]) => value !== null && value !== "" && !isEmptyList(value))
                .map(([field, value]) => (
                  <div key={field} className="flex items-baseline justify-between gap-2 sm:gap-3 text-sm">
                    <dt className="text-muted-foreground truncate shrink-0 max-w-[55%]">{labels(field)}</dt>
                    <dd className="text-bone truncate text-right font-mono text-xs">
                      {display(value)}
                    </dd>
                  </div>
                ))}
            </dl>
            <div className="border-rule mt-4 flex flex-wrap items-center gap-2 border-t pt-3">
              <Input
                value={presetName}
                onChange={(event) => setPresetName(event.target.value)}
                placeholder="save this config as…"
                className="w-full sm:w-auto sm:min-w-40 flex-1"
              />
              <Button
                variant="outline"
                size="sm"
                disabled={!presetName.trim()}
                onClick={() => savePreset.mutate({ name: presetName.trim(), run_id: run.id })}
              >
                <Save data-icon="inline-start" className="size-3.5" />
                Save preset
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  void navigator.clipboard?.writeText(JSON.stringify(run.config, null, 2))
                  toast.success("Config copied as JSON")
                }}
              >
                <Copy data-icon="inline-start" className="size-3.5" />
                Copy JSON
              </Button>
              <Button
                variant="ghost"
                size="sm"
                render={
                  // A plain anchor, not a router Link: the file is served by the API, and a
                  // client-side navigation would try to route to it.
                  <a href={routes.runWorkflow(run.id)} download>
                    <Download data-icon="inline-start" className="size-3.5" />
                    Download workflow
                  </a>
                }
              />
            </div>
          </Section>
        </div>

        <div className="space-y-4">
          <Section title="What it cost">
            <div className="grid grid-cols-2 gap-3 sm:gap-4">
              <Stat label="Seconds / step" value={secPerIt(run.metrics?.sec_per_it)} tone="signal" />
              <Stat label="Wall clock" value={seconds(run.metrics?.wall_s)} />
              <Stat
                label="Steps"
                value={run.metrics?.steps ?? run.config.steps ?? "—"}
                tone="muted"
              />
              <Stat
                label="Elo"
                value={elo(view.elo)}
                hint={view.elo_games ? `${view.elo_games} comparisons` : "never compared"}
              />
              {run.artifact?.width && run.artifact.height ? (
                <Stat
                  label="Frame"
                  value={`${run.artifact.width}×${run.artifact.height}`}
                  tone="muted"
                />
              ) : null}
              {run.artifact?.frame_count ? (
                <Stat
                  label="Frames"
                  value={run.artifact.frame_count}
                  tone="muted"
                  hint={run.artifact.fps ? `${run.artifact.fps} fps` : undefined}
                />
              ) : null}
              {run.artifact?.size_bytes ? (
                <Stat label="Size" value={bytes(run.artifact.size_bytes)} tone="muted" />
              ) : null}
              {run.metrics?.cache_cleared ? (
                <Stat label="VRAM" value="cleared first" tone="muted" />
              ) : null}
            </div>
            <div className="border-rule mt-4 flex flex-wrap items-center justify-between gap-2 border-t pt-3">
              <StatusChip run={run} showRate={false} />
              <span className="edge-code text-muted-foreground text-xs">
                cfg {shortHash(run.config_hash)} · rcp {shortHash(run.recipe_hash)}
              </span>
            </div>
          </Section>

          <Section title="Keep or lose it">
            <div className="flex flex-wrap gap-1.5">
              <Button
                variant={run.favourite ? "secondary" : "outline"}
                size="sm"
                onClick={() => patch.mutate({ id: run.id, favourite: !run.favourite })}
              >
                <Heart
                  data-icon="inline-start"
                  className="size-3.5"
                  fill={run.favourite ? "currentColor" : "none"}
                />
                Favourite
              </Button>
              <Button variant="outline" size="sm" onClick={() => baseline.mutate(run.id)}>
                <Pin data-icon="inline-start" className="size-3.5" />
                Pin as baseline
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => patch.mutate({ id: run.id, archived: !run.archived })}
              >
                {run.archived ? "Unarchive" : "Archive"}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="text-crimson hover:text-crimson"
                onClick={() => {
                  remove.mutate(run.id, { onSuccess: () => navigate("/runs") })
                }}
              >
                <Trash2 data-icon="inline-start" className="size-3.5" />
                Delete
              </Button>
            </div>
          </Section>

          <Section title="Tags" hint="How you find this again in three weeks.">
            <div className="mb-2 flex flex-wrap gap-1.5">
              {(run.tags ?? []).map((name) => (
                <span
                  key={name}
                  className="border-rule text-bone inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 font-mono text-xs"
                >
                  {name}
                  <button
                    aria-label={`Remove tag ${name}`}
                    onClick={() =>
                      patch.mutate({
                        id: run.id,
                        tags: (run.tags ?? []).filter((item) => item !== name),
                      })
                    }
                    className="text-muted-foreground hover:text-crimson"
                  >
                    <X className="size-3" />
                  </button>
                </span>
              ))}
              {(run.tags ?? []).length === 0 ? (
                <span className="text-muted-foreground text-xs">No tags yet.</span>
              ) : null}
            </div>
            <form
              className="flex gap-1.5"
              onSubmit={(event) => {
                event.preventDefault()
                const name = tag.trim()
                if (!name) return
                patch.mutate({ id: run.id, tags: [...new Set([...(run.tags ?? []), name])] })
                setTag("")
              }}
            >
              <Input
                value={tag}
                onChange={(event) => setTag(event.target.value)}
                placeholder="add a tag"
                className="flex-1"
              />
              <Button type="submit" variant="outline" size="icon" aria-label="Add tag">
                <TagIcon className="size-3.5" />
              </Button>
            </form>
          </Section>

          <Section title="Notes" hint="What you noticed. Searchable from the runs list.">
            <Textarea
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              rows={4}
              placeholder="Hands melt on the second beat; motion is otherwise clean."
              className="text-[13px]"
            />
            {dirty ? (
              <div className="mt-2 flex gap-1.5">
                <Button size="sm" onClick={() => patch.mutate({ id: run.id, notes })}>
                  Save note
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setNotes(run.notes ?? "")}>
                  Discard
                </Button>
              </div>
            ) : null}
          </Section>

          {run.config.prompt ? (
            <Section title="Prompt">
              <p className="text-muted-foreground font-mono text-xs leading-relaxed whitespace-pre-wrap">
                {run.config.prompt}
              </p>
            </Section>
          ) : null}

          <p className="text-muted-foreground text-center text-xs">
            <Link to={`/runs?query=${encodeURIComponent(run.recipe_hash.slice(0, 8))}`} className="hover:text-bone">
              Find the other runs of this recipe
            </Link>
          </p>
        </div>
      </div>
    </>
  )
}

function isEmptyList(value: unknown): boolean {
  return Array.isArray(value) && value.length === 0
}
