import { useState } from "react"
import { api } from "@/api/client"
import { routes } from "@/api/routes"
import type { Upload } from "@/api/schema"
import type { Draft } from "@/lib/config"
import "./studio-host.css"
import { ExperimentPanel } from "./experiment-panel"

type StudioHostProps = { draft: Draft; onChange: (patch: Partial<Draft>) => void }
const referenceFields = ["ref_images", "ref_videos", "ref_video_audios", "ref_audios"] as const

export function StudioHost({ draft, onChange }: StudioHostProps) {
  const [error, setError] = useState("")
  const [uploaded, setUploaded] = useState("")
  return <div className="studio-runtime-frame" style={{ padding: 20, display: "grid", gap: 12 }}>
    <label>Starting recipe <select value={draft.preset ?? "speed"} onChange={e => onChange({ preset: e.target.value as Draft["preset"] })}>
      <option value="speed">Speed</option><option value="quality">Quality</option><option value="quality_pece">Quality PECE</option><option value="motion">Motion / De-rope</option>
    </select></label>
    {draft.preset === "motion" && <p>For fast action or visible smearing: Quality plus De-rope. Preserves original audio; about 2.4 times the Quality runtime in the reviewed test.</p>}
    <label>Prompt<textarea rows={8} value={draft.prompt ?? ""} onChange={e => onChange({ prompt: e.target.value })} /></label>
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(100px, 1fr))", gap: 12 }}>
      {(["width", "height", "frames", "seed"] as const).map(key => <label key={key}>{key}<input type="number" value={draft[key] ?? ({ width: 1344, height: 768, frames: 175, seed: 42 }[key])} onChange={e => onChange({ [key]: Number(e.target.value) })} /></label>)}
    </div>
    <p>24 fps. Native frame grid: 5, 22, 39, …, 175. Production baseline: 1344 × 768.</p>
    <label>Target MP ({((draft.width ?? 1344) * (draft.height ?? 768) / 1_000_000).toFixed(3)} MP actual)
      <input type="number" step="0.1" min="0.01" defaultValue={1} onBlur={e => {
        const pixels = Number(e.target.value) * 1_000_000
        if (pixels > 0) { const ratio = (draft.width ?? 1344) / (draft.height ?? 768); onChange({ width: Math.max(32, Math.round(Math.sqrt(pixels * ratio) / 32) * 32), height: Math.max(32, Math.round(Math.sqrt(pixels / ratio) / 32) * 32) }) }
      }} />
    </label>
    <ExperimentPanel draft={draft} onChange={onChange} />
    {(["first_frame", "last_frame"] as const).map(key => <label key={key}>{key}<input value={draft[key] ?? ""} onChange={e => onChange({ [key]: e.target.value })} /></label>)}
    {referenceFields.map(key => <label key={key}>{key} — one uploaded filename per line<textarea rows={2} value={(draft[key] ?? []).join("\n")} onChange={e => onChange({ [key]: e.target.value ? e.target.value.split("\n") : [] })} /></label>)}
    <label>Reference image size<select value={draft.ref_image_size ?? "match"} onChange={e => onChange({ ref_image_size: e.target.value as "match" | "max" })}><option value="match">Match output</option><option value="max">Maximum</option></select></label>
    <label>Final audio<input value={typeof draft.widgets?.final_audio === "string" ? draft.widgets.final_audio : ""} onChange={e => onChange({ widgets: { ...draft.widgets, final_audio: e.target.value } })} /></label>
    <label>Timed guides — JSON array, with frame and image/video/audio filenames<textarea key={JSON.stringify(draft.widgets?.guides)} rows={4} defaultValue={typeof draft.widgets?.guides === "string" ? draft.widgets.guides : JSON.stringify(draft.widgets?.guides ?? [])} onBlur={e => {
      try { const guides: unknown = JSON.parse(e.target.value); if (!Array.isArray(guides)) throw new Error("Guides must be an array"); onChange({ widgets: { ...draft.widgets, guides } }); setError("") }
      catch (cause) { setError(String(cause)) }
    }} /></label>
    <label>Upload media<input type="file" multiple onChange={async e => {
      try { const names: string[] = []; for (const file of Array.from(e.target.files ?? [])) { const body = new FormData(); body.append("file", file); names.push((await api.post<Upload>(routes.uploads(), body)).name) } setUploaded(names.join("\n")); setError("") }
      catch (cause) { setError(String(cause)) }
    }} /></label>
    {uploaded && <pre>{uploaded}</pre>}{error && <p role="alert">{error}</p>}
  </div>
}
