import { describe, expect, it } from "vitest"

import type { Predicate } from "@/api/schema"

import { matchesPredicate, visible } from "./predicates"

describe("SDUI visibility predicates", () => {
  it.each([
    [
      { field: "mode", operator: "equals", value: "frames" },
      { mode: "frames" },
      true,
    ],
    [{ field: "mode", operator: "equals", value: "1" }, { mode: 1 }, false],
    [
      { field: "mode", operator: "not_equals", value: "frames" },
      { mode: "text" },
      true,
    ],
    [{ field: "steps", operator: "in", value: [4, 8] }, { steps: 8 }, true],
    [{ field: "steps", operator: "in", value: ["8"] }, { steps: 8 }, false],
  ] satisfies [Predicate, Record<string, unknown>, boolean][])(
    "evaluates %o with strict primitive semantics",
    (predicate, values, expected) => {
      expect(matchesPredicate(predicate, values)).toBe(expected)
    }
  )

  it("uses AND semantics and treats no predicates as visible", () => {
    expect(visible(undefined, { mode: "frames" })).toBe(true)
    expect(
      visible(
        [
          { field: "mode", operator: "equals", value: "frames" },
          { field: "grade", operator: "equals", value: true },
        ],
        { mode: "frames", grade: false }
      )
    ).toBe(false)
  })
})
