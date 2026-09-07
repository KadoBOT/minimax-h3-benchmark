import { h3Inputs } from "@/lib/h3-inputs"
import { useState } from "react"
import { useRunSweep, useSweepPreview } from "@/api/hooks"
import type { GenerationConfig, Meta, SweepRequest } from "@/api/schema"
import { Section } from "@/components/page"
import { Button } from "@/components/ui/button"

type Props = { base: GenerationConfig; meta: Meta | undefined; catalog: unknown; missing?: string[] }
export function SweepBuilder({ base, meta, missing = [] }: Props) {
  const [axes, setAxes] = useState([{ field: "preset", text: '["speed", "quality", "quality_pece"]' }])
  const [repeats, setRepeats] = useState(1)
  const preview = useSweepPreview()
  const start = useRunSweep()
  let error = ""
  let count = repeats
  const parsed = axes.map(axis => {
    try {
      const values: unknown = JSON.parse(axis.text)
      if (!Array.isArray(values) || !values.length) throw new Error("Enter a nonempty JSON array")
      count *= values.length
      return { field: axis.field, values }
    } catch { error = `Invalid values for ${axis.field}`; return { field: axis.field, values: [] } }
  })
  const request: SweepRequest = { base: h3Inputs(base), axes: parsed, repeats, seed_strategy: "increment", skip_duplicates: true }
  const change = (index: number, patch: Partial<typeof axes[number]>) => setAxes(axes.map((axis, i) => i === index ? { ...axis, ...patch } : axis))
  const fields = meta?.axes ?? []
  return <Section title="Sweep configurations" hint="Vary weights, sampling, LoRAs or any experiment parameter. All combinations keep the same shot inputs and seed sequence.">
    <div className="grid gap-3">
      {axes.map((axis, index) => <div className="flex flex-wrap items-center gap-3" key={index}>
        <label>Parameter <select className="border p-2" value={axis.field} onChange={e => change(index, { field: e.target.value })}>
          {fields.map(field => <option key={field.field} value={field.field}>{field.label}</option>)}
        </select></label>
        <label className="grow">Values (JSON array) <input className="w-full border p-2 font-mono" value={axis.text} onChange={e => change(index, { text: e.target.value })} /></label>
        <Button variant="outline" onClick={() => setAxes(axes.filter((_, i) => i !== index))}>Remove</Button>
      </div>)}
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" onClick={() => setAxes([...axes, { field: "experiment.steps", text: "[4, 8]" }])}>Add parameter</Button>
        <label>Repeats <input className="w-16 border p-1" type="number" min={1} max={32} value={repeats} onChange={e => setRepeats(Number(e.target.value))} /></label>
        <Button disabled={!!error || !!missing.length || preview.isPending} variant="outline" onClick={() => preview.mutate(request)}>Preview</Button>
        <Button disabled={!!error || !!missing.length || start.isPending} onClick={() => start.mutate(request)}>Queue {count} runs</Button>
      </div>
    </div>
    {error && <p role="alert">{error}</p>}
    {preview.data && <p className="mt-3 text-sm">{preview.data.new_count} new runs; {preview.data.duplicate_count} duplicates skipped.</p>}
  </Section>
}
