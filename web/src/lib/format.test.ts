import { describe, expect, it } from "vitest"

import { makeRun } from "@/test/harness"
import {
  ago,
  bytes,
  delta,
  modelStem,
  moment,
  percent,
  plural,
  secPerIt,
  seconds,
  shortHash,
} from "./format"

describe("formatting", () => {
  it("shows an em dash rather than NaN for a missing number", () => {
    for (const format of [secPerIt, seconds, percent, bytes]) {
      expect(format(null)).toBe("—")
      expect(format(undefined)).toBe("—")
    }
    expect(secPerIt(Number.NaN)).toBe("—")
  })

  it("keeps seconds-per-step at two decimals, which is the resolution ComfyUI reports", () => {
    expect(secPerIt(1.2345)).toMatch(/^1\.23/)
    expect(secPerIt(12)).toMatch(/^12\.00/)
  })

  it("switches to minutes once a duration stops being readable in seconds", () => {
    expect(seconds(45.2)).toMatch(/^45\.2/)
    expect(seconds(62)).toMatch(/^1m.02s$/)
    expect(seconds(95)).toMatch(/^1m.35s$/)
    expect(seconds(605)).toMatch(/^10m.05s$/)
  })

  it("signs a delta so the direction reads before the magnitude", () => {
    expect(delta(1.5)).toBe("+1.50")
    expect(delta(-1.5)).toBe("−1.50")
    expect(delta(0)).toBe("±0.00")
    expect(delta(-12.34, 1, "%")).toBe("−12.3%")
  })

  it("trims a model filename to the part that distinguishes it", () => {
    expect(modelStem("minimax_h3_fp8_scaled.safetensors")).toBe("fp8_scaled")
    expect(
      modelStem("minimax-h3/MiniMax_H3_FL2VA_pruned_int8_convrot.safetensors")
    ).toBe("FL2VA_pruned_int8_convrot")
    expect(modelStem("some_other_model.safetensors")).toBe("some_other_model")
    expect(modelStem(null)).toBe("default")
  })

  it("scales bytes to the unit a person would say aloud", () => {
    expect(bytes(512)).toMatch(/^512.B$/)
    expect(bytes(2_400_000)).toMatch(/^2\.3.MB$/)
  })

  it("reads recent times as relative and older ones as a date", () => {
    const now = new Date().toISOString()
    expect(ago(now)).toBe("just now")
    expect(ago(new Date(Date.now() - 5 * 60_000).toISOString())).toBe("5 min ago")
    expect(ago(new Date(Date.now() - 3 * 3_600_000).toISOString())).toBe("3h ago")
    expect(ago(null)).toBe("—")
  })

  it("dates a finished run by when it finished, not when it was queued", () => {
    /**
     * Queueing eight runs at once and reading them back an hour later showed eight identical
     * ages, all measured from the moment the batch was submitted. The number a benchmark is
     * read by has to be the moment the work actually ended.
     */
    const run = makeRun({
      status: "succeeded",
      created_at: "2026-08-08T00:00:00Z",
      started_at: "2026-08-08T00:40:00Z",
      finished_at: "2026-08-08T00:45:00Z",
    })
    expect(moment(run)).toEqual({ at: "2026-08-08T00:45:00Z", verb: "finished" })
  })

  it("dates a run still on the GPU by when it started", () => {
    const run = makeRun({
      status: "running",
      created_at: "2026-08-08T00:00:00Z",
      started_at: "2026-08-08T00:40:00Z",
      finished_at: null,
    })
    expect(moment(run)).toEqual({ at: "2026-08-08T00:40:00Z", verb: "started" })
  })

  it("dates a waiting run by when it was queued, because nothing else has happened yet", () => {
    const run = makeRun({
      status: "queued",
      created_at: "2026-08-08T00:00:00Z",
      started_at: null,
      finished_at: null,
    })
    expect(moment(run)).toEqual({ at: "2026-08-08T00:00:00Z", verb: "queued" })
  })

  it("falls back through the stamps a run does have", () => {
    // Imported runs can be terminal with no finish time recorded.
    const imported = makeRun({
      status: "succeeded",
      created_at: "2026-08-08T00:00:00Z",
      started_at: null,
      finished_at: null,
    })
    expect(moment(imported)).toEqual({ at: "2026-08-08T00:00:00Z", verb: "queued" })
  })

  it("treats a naive timestamp as UTC, the way the API writes them", () => {
    const naive = new Date(Date.now() - 60_000).toISOString().replace("Z", "")
    expect(ago(naive)).toBe("a minute ago")
  })

  it("pluralises without a stray s on one", () => {
    expect(plural(1, "run")).toBe("1 run")
    expect(plural(3, "run")).toBe("3 runs")
    expect(plural(2, "combination")).toBe("2 combinations")
  })

  it("shortens a hash to something a person can compare by eye", () => {
    expect(shortHash("0123456789abcdef")).toBe("012345")
    expect(shortHash("0123456789abcdef", 10)).toBe("0123456789")
    expect(shortHash(null)).toBe("—")
  })
})
