import { useQuery } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { Draft } from "@/lib/config"

type Scalar = string | number | boolean
type Spec = { kind: string; options: string[]; step?: number }
type ExperimentOptions = {
  defaults: Record<string, Scalar>
  options: Record<string, string[]>
  nodes: { id: string; name: string; inputs: Record<string, Scalar>; specs: Record<string, Spec> }[]
}
type Lora = { name: string; strength: number }
type Props = { draft: Draft; onChange: (patch: Partial<Draft>) => void }

const labels: Record<string, string> = {
  diffusion_model: "Diffusion weights", weight_dtype: "Weight dtype", sampler: "Primary sampler",
  scheduler: "Scheduler", steps: "Steps", denoise: "Denoise", shift_video: "Video sigma shift",
  shift_audio: "Audio sigma shift", ffn_chunks: "FFN chunks", bridge_alpha: "Semantic bridge strength",
  refine_enabled: "Refinement pass", refine_sampler: "Refinement sampler", refine_sigmas: "Refinement sigmas",
  video_vae: "Video VAE", audio_vae: "Audio VAE", text_encoder: "Text encoder",
}

function ValueInput({ id, value, options = [], onChange }: {
  id: string; value: Scalar; options?: string[]; onChange: (value: Scalar) => void
}) {
  if (typeof value === "boolean") return <input id={id} type="checkbox" checked={value} onChange={e => onChange(e.target.checked)} />
  return <>
    <input id={id} list={options.length ? `${id}-choices` : undefined} type={typeof value === "number" ? "number" : "text"}
      step="any" value={value} onChange={e => onChange(typeof value === "number" ? Number(e.target.value) : e.target.value)} />
    {!!options.length && <datalist id={`${id}-choices`}>{options.map(option => <option key={option} value={option} />)}</datalist>}
  </>
}

export function ExperimentPanel({ draft, onChange }: Props) {
  const preset = draft.preset ?? "speed"
  const query = useQuery({ queryKey: ["experiment-options", preset],
    queryFn: () => api.get<ExperimentOptions>("/api/studio/experiment", { preset }), staleTime: 60_000 })
  const experiment = draft.experiment ?? {}
  const patch = (key: string, value: unknown) => onChange({ experiment: { ...experiment, [key]: value } })
  const reset = (key: string) => { const next = { ...experiment }; delete next[key]; onChange({ experiment: next }) }
  const loras = (experiment.loras ?? []) as Lora[]
  const nodeInputs = (experiment.node_inputs ?? {}) as Record<string, Record<string, Scalar>>
  if (query.isError) return <p role="alert">Could not load installed experiment controls: {String(query.error)}</p>
  if (!query.data) return <p>Loading installed weights and sampler controls…</p>
  const { defaults, options, nodes } = query.data
  const common = ["diffusion_model", "weight_dtype", "sampler", "scheduler", "steps", "denoise", "shift_video", "shift_audio", "ffn_chunks", "bridge_alpha", "refine_enabled"]
  const refining = experiment.refine_enabled ?? defaults.refine_enabled
  if (refining) common.push("refine_sampler", "refine_sigmas")
  return <section className="experiment-panel">
    <div className="experiment-heading"><h3>Experiment controls</h3><button type="button" onClick={() => onChange({ experiment: {} })}>Reset to recipe</button></div>
    <p>Edit and save the selected preset's native graph in ComfyUI to change the recipe. New runs read those saved changes. Overrides here are saved with the run and used when checking, queuing and sweeping.</p>
    <div className="experiment-grid">{common.filter(key => key in defaults || key in experiment).map(key => <label key={key} htmlFor={`exp-${key}`}>{labels[key]}
      <ValueInput id={`exp-${key}`} value={(experiment[key] ?? defaults[key] ?? "0.15,0.075,0") as Scalar} options={options[key]}
        onChange={value => patch(key, value)} />
      {key in experiment && <button type="button" onClick={() => reset(key)}>Use recipe value</button>}
    </label>)}</div>
    <h4>LoRAs</h4>
    <p>Applied in order before attention and sampling. Steps remain independently editable.</p>
    {loras.map((lora, index) => <div className="lora-row" key={index}>
      <label>LoRA {index + 1}<ValueInput id={`lora-${index}`} value={lora.name} options={options.loras}
        onChange={name => patch("loras", loras.map((entry, i) => i === index ? { ...entry, name } : entry))} /></label>
      <label>Strength<input aria-label={`LoRA ${index + 1} strength`} type="number" step="0.05" value={lora.strength}
        onChange={e => patch("loras", loras.map((entry, i) => i === index ? { ...entry, strength: Number(e.target.value) } : entry))} /></label>
      <button type="button" onClick={() => patch("loras", loras.filter((_, i) => i !== index))}>Remove</button>
    </div>)}
    <button type="button" onClick={() => patch("loras", [...loras, { name: options.loras?.[0] ?? "", strength: 1 }])}>Add LoRA</button>
    <details><summary>Encoders and VAEs</summary><div className="experiment-grid">{["text_encoder", "video_vae", "audio_vae"].map(key => <label key={key}>{labels[key]}
      <ValueInput id={`exp-${key}`} value={(experiment[key] ?? defaults[key]) as Scalar} options={options[key]} onChange={value => patch(key, value)} />
      {key in experiment && <button type="button" onClick={() => reset(key)}>Use recipe value</button>}
    </label>)}</div></details>
    <details><summary>Advanced node inputs</summary>
      <p>Inspect and override the recipe's individual controls, including VSA/SLA attention. These overrides are applied last.</p>
      {nodes.map(node => <details key={node.id}><summary>{node.name} · {node.id}</summary><div className="experiment-grid">
        {Object.entries(node.inputs).map(([field, original]) => <label key={field}>{field}
          <ValueInput id={`node-${node.id}-${field}`} value={nodeInputs[node.id]?.[field] ?? original} options={node.specs[field]?.options}
            onChange={value => patch("node_inputs", { ...nodeInputs, [node.id]: { ...nodeInputs[node.id], [field]: value } })} />
        </label>)}
      </div>{nodeInputs[node.id] && <button type="button" onClick={() => {
        const next = { ...nodeInputs }; delete next[node.id]; patch("node_inputs", next)
      }}>Reset this node</button>}</details>)}
    </details>
  </section>
}
