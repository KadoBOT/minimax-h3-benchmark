import { beforeEach, describe, expect, it } from "vitest"

import {
  applyPreset,
  deletePreset,
  loadDraft,
  listPresets,
  saveDraft,
  savePreset,
  sweepComponents,
} from "./authoring"
import { initialValues } from "./form-state"
import { generationDocument } from "./test-fixtures"

describe("shared SDUI authoring state", () => {
  beforeEach(() => localStorage.clear())

  it("persists drafts by workflow and safely merges a new revision", () => {
    const previous = generationDocument()
    saveDraft(previous, { ...initialValues(previous), prompt: "Saved draft" })

    const next = generationDocument({ schemaRevision: "h3-v2" })
    const loaded = loadDraft(next)
    expect(loaded.values.prompt).toBe("Saved draft")
    expect(loaded.diagnostics.join(" ")).toMatch(/h3-v1.*h3-v2/i)
  })

  it("stores pinned raw presets and applies them through the same merge", () => {
    const document = generationDocument()
    const preset = savePreset("Rain study", document, {
      ...initialValues(document),
      steps: 28,
    })
    expect(listPresets()).toHaveLength(1)
    expect(applyPreset(preset, document).values.steps).toBe(28)

    deletePreset(preset.id)
    expect(listPresets()).toEqual([])
  })

  it("offers only generic numeric, select, and toggle axes", () => {
    expect(
      sweepComponents(
        generationDocument(),
        initialValues(generationDocument())
      ).map((item) => item.binding)
    ).toEqual(["mode", "steps", "postGrade"])
  })

})
