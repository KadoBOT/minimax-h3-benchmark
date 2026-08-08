/**
 * The numeric ranges the config form offers.
 *
 * A control may offer less than the API accepts — nobody needs a 60 second benchmark clip —
 * but never more, or the form hands over a value the API rejects with a 422 the user cannot
 * act on. `tests/test_contract.py` checks each range against the OpenAPI schema, which is
 * how a megapixel slider that started below the accepted floor was caught.
 */
export const LIMITS = {
  steps: { min: 1, max: 200, step: 1 },
  mp: { min: 0.1, max: 2, step: 0.05 },
  duration_s: { min: 1, max: 15, step: 0.5 },
} as const

export type LimitField = keyof typeof LIMITS
