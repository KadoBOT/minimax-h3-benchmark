import type { GenerationConfig, H3Inputs, Guide } from "@/api/schema"

export function h3Inputs(config: GenerationConfig): H3Inputs {
  const raw: unknown = config.widgets?.guides ?? []
  const guides: unknown = typeof raw === "string" ? JSON.parse(raw) : raw
  return {
    preset: config.preset ?? "speed",
    prompt: config.prompt ?? "",
    width: config.width ?? 1344, height: config.height ?? 768, frames: config.frames ?? 175,
    seed: config.seed ?? 42, ref_image_size: config.ref_image_size ?? "match",
    first_frame: config.first_frame ?? "", last_frame: config.last_frame ?? "",
    references: { images: config.ref_images ?? [], videos: config.ref_videos ?? [], video_audios: config.ref_video_audios ?? [], audios: config.ref_audios ?? [] },
    guides: guides as Guide[],
    final_audio: typeof config.widgets?.final_audio === "string" ? config.widgets.final_audio : "",
    experiment: config.experiment ?? {},
  }
}
