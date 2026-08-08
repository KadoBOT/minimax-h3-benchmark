/**
 * Read-only screenshots of a running lab, for eyeballing real data.
 *
 * Unlike `smoke.mjs` this changes nothing: no rating, no staging, no queueing. It exists so a
 * live instance holding real runs can be inspected without touching them.
 *
 *   node web/scripts/shots.mjs http://127.0.0.1:8787 [outdir]
 */

import { mkdir } from "node:fs/promises"
import { fileURLToPath } from "node:url"
import { chromium } from "playwright"

const base = process.argv[2]
const outdir = process.argv[3] ?? fileURLToPath(new URL("../../.shots/", import.meta.url))

if (!base) {
  console.error("usage: node scripts/shots.mjs <base-url> [outdir]")
  process.exit(2)
}

const PAGES = [
  ["runs", "/runs"],
  ["lab", "/"],
  ["leaderboard", "/leaderboard"],
  ["insights", "/insights"],
  ["compare", "/compare"],
]

await mkdir(outdir, { recursive: true })
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })

const complaints = []
page.on("console", (message) => {
  if (message.type() === "error") complaints.push(message.text())
})
page.on("pageerror", (error) => complaints.push(error.message))

for (const [name, path] of PAGES) {
  await page.goto(base + path, { waitUntil: "networkidle", timeout: 30_000 })
  await page.waitForTimeout(600)
  await page.screenshot({ path: `${outdir}/${name}.png` })
  console.log(`shot ${name.padEnd(12)} ${path}`)
}

await browser.close()
if (complaints.length) {
  console.error(`\n${complaints.length} console problem(s):`)
  for (const complaint of complaints.slice(0, 20)) console.error(`  - ${complaint}`)
  process.exit(1)
}
console.log("\nno console errors against live data")
