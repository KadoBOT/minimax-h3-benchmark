import type { Predicate } from "@/api/schema"

export function matchesPredicate(
  predicate: Predicate,
  values: Readonly<Record<string, unknown>>
): boolean {
  const current = values[predicate.field]
  switch (predicate.operator) {
    case "equals":
      return current === predicate.value
    case "not_equals":
      return current !== predicate.value
    case "in":
      return Array.isArray(predicate.value)
        ? predicate.value.some((candidate) => candidate === current)
        : false
  }
}

export function visible(
  predicates: readonly Predicate[] | null | undefined,
  values: Readonly<Record<string, unknown>>
): boolean {
  return (predicates ?? []).every((predicate) =>
    matchesPredicate(predicate, values)
  )
}
