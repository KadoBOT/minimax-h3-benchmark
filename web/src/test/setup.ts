/**
 * Test environment.
 *
 * jsdom is missing the handful of browser APIs this app leans on. Each shim below stands in
 * for one of them; none of them change behaviour the tests assert on.
 */

import "@testing-library/jest-dom/vitest"

import { cleanup } from "@testing-library/react"
import { afterEach, beforeEach, vi } from "vitest"

class FakeEventSource {
  static instances: FakeEventSource[] = []

  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  readonly url: string
  closed = false

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  close() {
    this.closed = true
  }

  /**
   * Push an event the way the server would, for tests that assert on live updates.
   *
   * This calls `onmessage` directly, so it cannot tell you whether a real browser would have
   * routed the frame there — a frame the server names goes to a listener of that name and
   * never reaches `onmessage`. That gap once hid a completely dead live layer behind a green
   * suite. The wire format is pinned in `tests/test_contract.py`, and the round trip is
   * checked against a real browser in `scripts/smoke.py`.
   */
  emit(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent)
  }
}

vi.stubGlobal("EventSource", FakeEventSource)

// Base UI measures its popups; jsdom has no layout engine, so these return zeroes rather
// than throwing.
vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
)

if (!window.matchMedia) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }))
}

Element.prototype.scrollIntoView = Element.prototype.scrollIntoView ?? (() => {})
window.HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined)
window.HTMLMediaElement.prototype.pause = vi.fn()

if (!window.localStorage || typeof window.localStorage.clear !== "function") {
  const store = new Map<string, string>()
  const storageShim = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => store.set(key, String(value)),
    removeItem: (key: string) => store.delete(key),
    clear: () => store.clear(),
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    get length() {
      return store.size
    },
  }
  Object.defineProperty(window, "localStorage", { value: storageShim, writable: true, configurable: true })
}

beforeEach(() => {
  FakeEventSource.instances = []
  window.localStorage.clear()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

export { FakeEventSource }
