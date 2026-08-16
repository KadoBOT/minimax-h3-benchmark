export const GENERATION_CAPABILITIES = [
  "action.submit",
  "component.asset",
  "component.number",
  "component.seed",
  "component.select",
  "component.text",
  "component.textarea",
  "component.toggle",
] as const

export const JOB_CAPABILITIES = [
  "action.cancel",
  "action.delete",
  "action.retry_collection",
  "component.download",
  "component.log",
  "component.preview",
  "component.progress",
  "component.status",
  "component.video",
] as const

export type GenerationCapability = (typeof GENERATION_CAPABILITIES)[number]
export type JobCapability = (typeof JOB_CAPABILITIES)[number]

const generation = new Set<string>(GENERATION_CAPABILITIES)
const job = new Set<string>(JOB_CAPABILITIES)

export type CapabilityScope = "generation" | "job"

export function supportsCapability(
  scope: CapabilityScope,
  capability: string
): boolean {
  return (scope === "generation" ? generation : job).has(capability)
}

export function capabilityFor(kind: string, action = false): string {
  return `${action ? "action" : "component"}.${kind}`
}
