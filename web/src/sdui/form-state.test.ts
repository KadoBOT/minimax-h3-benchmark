import { describe, expect, it } from "vitest"

import type { GenerationDocument } from "@/api/schema"

import {
  initialValues,
  mergeValues,
  submissionInput,
  validateValues,
  type FormValues,
} from "./form-state"
import { generationDocument } from "./test-fixtures"

describe("SDUI form state", () => {
  it("derives typed defaults from component kinds", () => {
    const base = generationDocument()
    const document: GenerationDocument = {
      ...base,
      capabilities: {
        ...base.capabilities,
        required: [...base.capabilities.required, "component.text"],
      },
      components: [
        ...base.components,
        {
          id: "prefix",
          kind: "text",
          binding: "prefix",
          label: "Prefix",
          required: false,
          defaultValue: "clip",
        },
      ],
    }

    expect(initialValues(document)).toEqual({
      mode: "text_to_video",
      prompt: "A lighthouse in rain",
      steps: 20,
      seed: 42,
      postGrade: false,
      firstFrame: [],
      prefix: "clip",
    })
  })

  it("validates strict primitive types and every generic constraint", () => {
    const document = generationDocument()
    const invalid: FormValues = {
      ...initialValues(document),
      mode: "missing",
      prompt: "",
      steps: 20.5,
      seed: Number.MAX_SAFE_INTEGER + 1,
      postGrade: "false",
      firstFrame: [],
    }
    const result = validateValues(document, invalid)

    expect(result.errors).toMatchObject({
      mode: expect.stringMatching(/option/i),
      prompt: expect.stringMatching(/required/i),
      steps: expect.stringMatching(/integer/i),
      seed: expect.stringMatching(/maximum|safe integer/i),
      postGrade: expect.stringMatching(/boolean/i),
    })
    expect(result.firstError).toEqual({ binding: "mode", componentId: "mode" })
  })

  it("retains hidden values while suppressing hidden required errors", () => {
    const document = generationDocument()
    const hidden = {
      ...initialValues(document),
      mode: "text_to_video",
      firstFrame: [],
    }
    expect(validateValues(document, hidden).errors.firstFrame).toBeUndefined()

    const visible = { ...hidden, mode: "first_last_frame" }
    expect(validateValues(document, visible).errors.firstFrame).toMatch(
      /at least 1/i
    )

    const retained = {
      ...hidden,
      firstFrame: ["123e4567-e89b-42d3-a456-426614174000"],
    }
    expect(submissionInput(document, retained).firstFrame).toEqual(
      retained.firstFrame
    )
  })

  it("merges a new document revision by binding and compatible type", () => {
    const previous = generationDocument()
    const values = {
      ...initialValues(previous),
      prompt: "Keep this draft",
      steps: 33,
    }
    const next: GenerationDocument = {
      ...previous,
      schemaRevision: "h3-v2",
      components: previous.components
        .filter(
          (component) =>
            !("binding" in component) || component.binding !== "postGrade"
        )
        .map((component) =>
          "binding" in component && component.binding === "steps"
            ? {
                id: "steps",
                kind: "text" as const,
                binding: "steps",
                label: "Steps as text",
                required: true,
                defaultValue: "twenty",
              }
            : component
        ),
      capabilities: {
        required: [
          ...previous.capabilities.required.filter(
            (capability) =>
              capability !== "component.number" &&
              capability !== "component.toggle"
          ),
          "component.text",
        ],
        optional: [],
      },
    }

    const merged = mergeValues(previous, values, next)
    expect(merged.values.prompt).toBe("Keep this draft")
    expect(merged.values.steps).toBe("twenty")
    expect(merged.diagnostics).toEqual(
      expect.arrayContaining([
        expect.stringMatching(/steps.*type changed/i),
        expect.stringMatching(/postGrade.*removed/i),
        expect.stringMatching(/h3-v1.*h3-v2/i),
      ])
    )
  })

  it("rejects malformed asset arrays and disabled select options", () => {
    const base = generationDocument()
    const document: GenerationDocument = {
      ...base,
      components: base.components.map((component) =>
        component.kind === "select" && component.binding === "mode"
          ? {
              ...component,
              options: component.options.map((option) =>
                option.value === "first_last_frame"
                  ? { ...option, disabled: true }
                  : option
              ),
            }
          : component
      ),
    }

    expect(
      validateValues(document, {
        ...initialValues(document),
        mode: "first_last_frame",
        firstFrame: ["not-an-opaque-id", 7] as unknown as string[],
      }).errors
    ).toMatchObject({
      mode: expect.stringMatching(/disabled/i),
      firstFrame: expect.stringMatching(/opaque asset ids/i),
    })
  })
})
