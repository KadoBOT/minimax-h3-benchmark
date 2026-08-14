import { chromium } from "playwright"
import { mkdir } from "node:fs/promises"
import { fileURLToPath } from "node:url"
import path from "node:path"

const outdir = path.join(fileURLToPath(new URL("../../.shots/mobile-after/", import.meta.url)))
await mkdir(outdir, { recursive: true })

const browser = await chromium.launch()
const context = await browser.newContext({
  viewport: { width: 390, height: 844 },
  deviceScaleFactor: 2,
  isMobile: true,
  hasTouch: true,
  userAgent:
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
})
const page = await context.newPage()

const pages = [
  ["lab", "http://127.0.0.1:5173/"],
  ["runs", "http://127.0.0.1:5173/runs"],
  ["compare", "http://127.0.0.1:5173/compare"],
  ["arena", "http://127.0.0.1:5173/arena"],
  ["insights", "http://127.0.0.1:5173/insights"],
  ["leaderboard", "http://127.0.0.1:5173/leaderboard"],
]

const results = []
for (const [name, url] of pages) {
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 })
  await page.waitForTimeout(1500)
  const metrics = await page.evaluate(() => {
    const doc = document.documentElement
    const body = document.body
    const scrollW = Math.max(doc.scrollWidth, body.scrollWidth)
    const clientW = doc.clientWidth
    return {
      scrollW,
      clientW,
      overflow: scrollW - clientW,
      h1: document.querySelector("h1")?.textContent ?? null,
      hasMenu: Boolean(document.querySelector('[aria-label*="navigation" i]')),
    }
  })
  await page.screenshot({ path: path.join(outdir, `${name}.png`), fullPage: true })
  await page.screenshot({ path: path.join(outdir, `${name}-viewport.png`), fullPage: false })
  results.push({ name, ...metrics })
  console.log(JSON.stringify({ name, ...metrics }))
}

await page.goto("http://127.0.0.1:5173/", { waitUntil: "domcontentloaded" })
await page.waitForTimeout(800)
await page.getByLabel(/open navigation/i).click()
await page.waitForTimeout(400)
await page.screenshot({ path: path.join(outdir, "nav-open.png"), fullPage: false })
await page.getByRole("link", { name: /Runs/i }).first().click()
await page.waitForTimeout(1000)
await page.screenshot({ path: path.join(outdir, "nav-to-runs.png"), fullPage: false })

const stageBtn = page.getByRole("button", { name: /Stage for comparison/i }).first()
if (await stageBtn.count()) {
  await stageBtn.click()
  await page.waitForTimeout(400)
  await page.screenshot({ path: path.join(outdir, "runs-bench.png"), fullPage: false })
}

const desk = await browser.newPage({ viewport: { width: 1440, height: 900 } })
await desk.goto("http://127.0.0.1:5173/", { waitUntil: "domcontentloaded" })
await desk.waitForTimeout(1000)
const deskMetrics = await desk.evaluate(() => ({
  scrollW: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
  clientW: document.documentElement.clientWidth,
}))
await desk.screenshot({ path: path.join(outdir, "lab-desktop.png"), fullPage: false })
console.log(JSON.stringify({ name: "lab-desktop", ...deskMetrics, overflow: deskMetrics.scrollW - deskMetrics.clientW }))
await desk.close()
await browser.close()

const bad = results.filter((r) => r.overflow > 2)
if (bad.length) {
  console.error("OVERFLOW FAIL", JSON.stringify(bad, null, 2))
  process.exit(1)
}
console.log("ALL MOBILE PAGES NO OVERFLOW")
