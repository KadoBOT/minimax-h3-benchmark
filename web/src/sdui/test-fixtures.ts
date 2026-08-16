import type { GenerationDocument, JobDocument } from "@/api/schema"

export const REVISION = `sha256:${"a".repeat(64)}`
export const JOB_ID = "123e4567-e89b-42d3-a456-426614174000"

export function generationDocument(
  overrides: Partial<GenerationDocument> = {}
): GenerationDocument {
  return {
    protocolVersion: "1.0",
    documentId: "minimax-h3-generation",
    schemaRevision: "h3-v1",
    workflowId: "minimax-h3-unified",
    workflowRevision: REVISION,
    title: "MiniMax H3",
    description: "Generate a video from server-owned controls.",
    availability: {
      state: "available",
      observedAt: "2026-08-15T08:00:00Z",
    },
    capabilities: {
      required: [
        "component.textarea",
        "component.select",
        "component.number",
        "component.toggle",
        "component.asset",
        "component.seed",
        "action.submit",
      ],
      optional: [],
    },
    kind: "generation",
    components: [
      {
        id: "section.source",
        kind: "section",
        title: "Source",
        description: "Choose how the clip begins.",
      },
      {
        id: "mode",
        kind: "select",
        binding: "mode",
        label: "Mode",
        description: "Select the source family.",
        required: true,
        options: [
          { value: "text_to_video", label: "Text to video" },
          { value: "first_last_frame", label: "First / last frame" },
          { value: "reference_to_video", label: "Reference to video" },
        ],
        defaultValue: "text_to_video",
      },
      {
        id: "prompt",
        kind: "textarea",
        binding: "prompt",
        label: "Prompt",
        description: "Describe the shot.",
        required: true,
        minLength: 1,
        maxLength: 12000,
        rows: 6,
        defaultValue: "A lighthouse in rain",
      },
      {
        id: "steps",
        kind: "number",
        binding: "steps",
        label: "Steps",
        description: "Sampling iterations.",
        required: true,
        minimum: 1,
        maximum: 200,
        step: 1,
        integer: true,
        defaultValue: 20,
      },
      {
        id: "seed",
        kind: "seed",
        binding: "seed",
        label: "Seed",
        description: "Use null for a random seed.",
        required: true,
        allowRandom: true,
        minimum: 0,
        maximum: Number.MAX_SAFE_INTEGER,
        defaultValue: 42,
      },
      {
        id: "post-grade",
        kind: "toggle",
        binding: "postGrade",
        label: "Post grade",
        description: "Apply the finishing grade.",
        required: true,
        defaultValue: false,
      },
      {
        id: "first-frame",
        kind: "asset",
        binding: "firstFrame",
        label: "First frame",
        description: "Upload one starting image.",
        required: true,
        accept: ["image"],
        minimumItems: 1,
        maximumItems: 1,
        visibleWhen: [
          { field: "mode", operator: "equals", value: "first_last_frame" },
        ],
      },
    ],
    actions: [
      {
        id: "submit",
        kind: "submit",
        label: "Queue run",
        endpoint: "/api/runs",
        method: "POST",
      },
    ],
    ...overrides,
  }
}

export function jobDocument(overrides: Partial<JobDocument> = {}): JobDocument {
  return {
    protocolVersion: "1.0",
    documentId: "job-view",
    schemaRevision: "h3-v1",
    workflowId: "minimax-h3-unified",
    workflowRevision: REVISION,
    title: "H3 run",
    availability: {
      state: "available",
      observedAt: "2026-08-15T08:00:00Z",
    },
    capabilities: {
      required: [
        "component.status",
        "component.progress",
        "component.log",
        "component.preview",
        "action.cancel",
      ],
      optional: [],
    },
    kind: "job",
    jobId: JOB_ID,
    components: [
      {
        id: "status",
        kind: "status",
        state: "running",
        label: "Running",
        detail: "Sampling",
      },
      {
        id: "progress",
        kind: "progress",
        value: 0.5,
        label: "Sampling",
        current: 10,
        total: 20,
      },
      {
        id: "log",
        kind: "log",
        entries: [
          {
            sequence: 1,
            at: "2026-08-15T08:00:01Z",
            level: "info",
            message: "Started",
          },
        ],
      },
      {
        id: "preview",
        kind: "preview",
        src: `/api/runs/local-1/shared-preview`,
        mime: "image/jpeg",
        sequence: 7,
      },
    ],
    actions: [
      {
        id: "cancel",
        kind: "cancel",
        label: "Cancel",
        endpoint: "/api/runs/local-1/cancel",
        method: "POST",
      },
    ],
    ...overrides,
  }
}
