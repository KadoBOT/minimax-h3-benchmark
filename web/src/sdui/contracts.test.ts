import { describe, expect, it } from "vitest"

import {
  isSafeApiPath,
  parseGenerationDocument,
  parseJobDocument,
  SduiContractError,
} from "./contracts"
import { generationDocument, jobDocument } from "./test-fixtures"

describe("SDUI document validation", () => {
  it("accepts the pinned generation and job vocabularies", () => {
    expect(parseGenerationDocument(generationDocument()).document.title).toBe(
      "MiniMax H3"
    )
    expect(parseJobDocument(jobDocument()).document.jobId).toBe(
      "123e4567-e89b-42d3-a456-426614174000"
    )
  })

  it.each([
    ["protocol", { protocolVersion: "2.0" }],
    ["workflow revision", { workflowRevision: "latest" }],
    ["schema revision", { schemaRevision: "../next" }],
  ])("rejects a malformed %s", (_name, override) => {
    expect(() =>
      parseGenerationDocument({ ...generationDocument(), ...override })
    ).toThrow(SduiContractError)
  })

  it("rejects duplicate ids and bindings", () => {
    const document = generationDocument()
    const duplicateId = {
      ...document,
      actions: [{ ...document.actions[0], id: document.components[0]?.id }],
    }
    expect(() => parseGenerationDocument(duplicateId)).toThrow(
      /ids must be unique/i
    )

    const duplicateBinding = {
      ...document,
      components: [
        ...document.components,
        {
          ...document.components[2],
          id: "prompt-copy",
        },
      ],
    }
    expect(() => parseGenerationDocument(duplicateBinding)).toThrow(
      /bindings must be unique/i
    )
  })

  it("rejects malformed and dangling predicates", () => {
    const document = generationDocument()
    const firstFrame = document.components.at(-1)
    expect(() =>
      parseGenerationDocument({
        ...document,
        components: [
          ...document.components.slice(0, -1),
          {
            ...firstFrame,
            visibleWhen: [{ field: "missing", operator: "equals", value: "x" }],
          },
        ],
      })
    ).toThrow(/unknown binding/i)

    expect(() =>
      parseGenerationDocument({
        ...document,
        components: [
          ...document.components.slice(0, -1),
          {
            ...firstFrame,
            visibleWhen: [{ field: "mode", operator: "in", value: [] }],
          },
        ],
      })
    ).toThrow(/must not be empty/i)
  })

  it("blocks unknown required capabilities and required items", () => {
    const document = generationDocument()
    expect(() =>
      parseGenerationDocument({
        ...document,
        capabilities: {
          ...document.capabilities,
          required: [...document.capabilities.required, "component.future"],
        },
      })
    ).toThrow(/unsupported.*component\.future/i)

    expect(() =>
      parseGenerationDocument({
        ...document,
        components: [
          ...document.components,
          { id: "future", kind: "future", optional: false },
        ],
      })
    ).toThrow(/unsupported required component future/i)
  })

  it("omits unknown optional capabilities and items with diagnostics", () => {
    const document = generationDocument()
    const parsed = parseGenerationDocument({
      ...document,
      capabilities: {
        ...document.capabilities,
        optional: ["component.future"],
      },
      components: [
        ...document.components,
        { id: "future", kind: "future", optional: true },
      ],
    })

    expect(parsed.document.components).toHaveLength(document.components.length)
    expect(parsed.diagnostics).toEqual([
      "Ignored unsupported optional capability component.future",
      "Ignored unsupported optional component future",
    ])
  })

  it("rejects undeclared component capabilities and overlapping declarations", () => {
    const document = generationDocument()
    expect(() =>
      parseGenerationDocument({
        ...document,
        capabilities: {
          required: document.capabilities.required.filter(
            (capability) => capability !== "component.number"
          ),
          optional: [],
        },
      })
    ).toThrow(/missing declared capability component\.number/i)

    expect(() =>
      parseGenerationDocument({
        ...document,
        capabilities: {
          required: document.capabilities.required,
          optional: ["component.number"],
        },
      })
    ).toThrow(/cannot be both required and optional/i)
  })

  it.each([
    "https://shared.internal/v1/jobs",
    "//shared.internal/v1/jobs",
    "/v1/jobs",
    "/api/../admin",
    "/api/%2e%2e/admin",
    String.raw`/api/runs\..\admin`,
  ])("rejects the unsafe browser path %s", (path) => {
    expect(isSafeApiPath(path)).toBe(false)
  })

  it("rejects unsafe component and action paths", () => {
    const generation = generationDocument()
    expect(() =>
      parseGenerationDocument({
        ...generation,
        actions: [
          {
            ...generation.actions[0],
            endpoint: "https://shared.internal/jobs",
          },
        ],
      })
    ).toThrow(/same-origin/i)

    const job = jobDocument()
    expect(() =>
      parseJobDocument({
        ...job,
        components: job.components.map((component) =>
          component.kind === "preview"
            ? { ...component, src: "//shared.internal/preview" }
            : component
        ),
      })
    ).toThrow(/same-origin/i)
  })
})
