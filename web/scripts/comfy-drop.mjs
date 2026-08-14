/**
 * Drop a run's saved still onto ComfyUI's canvas and see what it opens as.
 *
 * This is the reported bug, performed: "I've tried dragging an image on comfyui and the nodes
 * looked like when you drag an API file." Everything else the suite can check is upstream of this
 * gesture — the payload the lab sends, the graph the projection builds, the chunk in the file.
 * Only ComfyUI's own frontend can say what the gesture produces, so it is asked directly.
 *
 *   node scripts/comfy-drop.mjs <png-or-json> [comfy-url]
 *
 * Needs a running ComfyUI. Passes when the canvas ends up holding a positioned, grouped graph
 * rather than the unpositioned column an API prompt import produces.
 */

import { readFileSync } from "node:fs"
import { basename } from "node:path"
import { chromium } from "playwright"

const file = process.argv[2]
const base = process.argv[3] ?? "http://127.0.0.1:8188"
if (!file) {
  console.error("usage: node scripts/comfy-drop.mjs <png-or-json> [comfy-url]")
  process.exit(2)
}

const problems = []
const check = (ok, description) => {
  console.log(`${ok ? "ok  " : "FAIL"}  ${description}`)
  if (!ok) problems.push(description)
}

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })

await page.goto(base, { waitUntil: "domcontentloaded", timeout: 60_000 })
// The frontend builds the canvas and the graph after its own bootstrap, not on DOMContentLoaded.
await page.waitForFunction(() => Boolean(window.app?.graph), undefined, { timeout: 60_000 })
await page.waitForTimeout(2000)

const before = await page.evaluate(() => window.app.graph.nodes.length)

const bytes = [...readFileSync(file)]
const name = basename(file)
const dropped = await page.evaluate(
  async ({ bytes, name }) => {
    const type = name.endsWith(".png") ? "image/png" : "application/json"
    const file = new File([new Uint8Array(bytes)], name, { type })
    const transfer = new DataTransfer()
    transfer.items.add(file)
    const canvas = document.querySelector("canvas")
    for (const kind of ["dragenter", "dragover", "drop"]) {
      canvas.dispatchEvent(
        new DragEvent(kind, { dataTransfer: transfer, bubbles: true, cancelable: true })
      )
    }
    return true
  },
  { bytes, name }
)
check(dropped, `dropped ${name} on the canvas`)

// Loading is asynchronous: the PNG is decoded, the chunk parsed, then the graph replaced.
await page
  .waitForFunction((was) => window.app.graph.nodes.length !== was, before, { timeout: 60_000 })
  .catch(() => {})
await page.waitForTimeout(2000)

const graph = await page.evaluate(() => {
  const nodes = window.app.graph.nodes
  return {
    count: nodes.length,
    groups: (window.app.graph.groups ?? []).map((group) => group.title),
    unplaced: nodes.filter((node) => !node.pos || (node.pos[0] === 0 && node.pos[1] === 0)).length,
    distinctColumns: new Set(nodes.map((node) => Math.round(node.pos[0] / 50))).size,
    titled: nodes.filter((node) => node.title && node.title !== node.type).length,
    types: nodes.map((node) => node.type),
    provenance: window.app.graph.extra?.h3lab ?? null,
  }
})

check(graph.count > 0, `the canvas holds ${graph.count} node(s)`)
check(graph.unplaced === 0, `every node has a real position (${graph.unplaced} at the origin)`)
// An API import stacks everything the frontend lays out itself, and carries no groups at all.
check(graph.distinctColumns > 3, `the nodes are laid out, not stacked (${graph.distinctColumns} columns)`)
check(graph.groups.length > 0, `the groups survived: ${graph.groups.join(" | ") || "none"}`)
check(graph.titled > 0, `${graph.titled} node(s) kept the template's own titles`)
check(Boolean(graph.provenance?.run_id), `the graph names its run: ${graph.provenance?.run_id}`)

const interpolators = graph.types.filter(
  (type) => type.includes("Interpolat") || type.includes("RIFE")
)
console.log(`\n      interpolators on the canvas: ${JSON.stringify(interpolators)}`)
console.log(`      groups: ${JSON.stringify(graph.groups)}`)

// Frame the graph so the screenshot shows it rather than empty grid. The canvas keeps its own
// pan and zoom, and the drop leaves it wherever it was.
await page.evaluate(() => {
  const canvas = window.app.canvas
  const nodes = window.app.graph.nodes
  const xs = nodes.flatMap((node) => [node.pos[0], node.pos[0] + (node.size?.[0] ?? 200)])
  const ys = nodes.flatMap((node) => [node.pos[1], node.pos[1] + (node.size?.[1] ?? 100)])
  const [left, right] = [Math.min(...xs), Math.max(...xs)]
  const [top, bottom] = [Math.min(...ys), Math.max(...ys)]
  const element = canvas.canvas
  canvas.ds.scale = Math.min(
    element.width / (right - left + 300),
    element.height / (bottom - top + 300)
  )
  canvas.ds.offset = [-left + 150, -top + 150]
  canvas.setDirty(true, true)
})
await page.waitForTimeout(1500)
await page.screenshot({ path: `../.smoke/shots/comfy-drop-${name}.png` })
await browser.close()

if (problems.length) {
  console.error(`\n${problems.length} problem(s) — the drop did not open as a workflow`)
  process.exit(1)
}
console.log("\nComfyUI opened it as the workflow it came from, layout and groups included")
