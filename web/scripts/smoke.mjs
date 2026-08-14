/**
 * Walk the built app in Chromium and fail on anything a user would notice.
 *
 * Started by `scripts/smoke.py`, which seeds the data and serves the bundle. Every check is
 * a visible-text or DOM assertion on the real page, plus a standing watch on the console,
 * page errors, and failed requests — a page that renders while throwing is not a pass.
 */

import { mkdir, readFile, writeFile } from "node:fs/promises"
import { fileURLToPath } from "node:url"
import { chromium } from "playwright"

const base = process.argv[2]
const headed = process.argv.includes("--headed")
const shots = fileURLToPath(new URL("../../.smoke/shots/", import.meta.url))
const shot = (name) => `${shots}${name}.png`

if (!base) {
  console.error("usage: node scripts/smoke.mjs <base-url> [--headed]")
  process.exit(2)
}

/** Requests we expect to fail: the lab talks to a ComfyUI that is not running. */
const TOLERATED = [/\/api\/catalog/, /\/api\/dry-run/, /favicon/]

const problems = []
const note = (where, what) => problems.push(`${where}: ${what}`)

const TOUR = [
  {
    name: "lab",
    path: "/",
    expect: ["Set up a run", "Queue", "Sweep", "This config"],
    async act(page) {
      // Interpolation has three answers, named by the API rather than by the browser. A
      // segmented control that renders but does not move the selection is the failure to catch.
      const off = page.getByRole("button", { name: "Off", exact: true })
      const film = page.getByRole("button", { name: "FILM Net", exact: true })
      await page.getByRole("button", { name: "RIFE", exact: true }).waitFor({ timeout: 10_000 })
      if ((await off.getAttribute("aria-pressed")) !== "true") {
        throw new Error("interpolation did not start off")
      }
      await film.click()
      if ((await film.getAttribute("aria-pressed")) !== "true") {
        throw new Error("clicking FILM Net did not select it")
      }
      if ((await off.getAttribute("aria-pressed")) !== "false") {
        throw new Error("two interpolators were selected at once")
      }
      await off.click()

      // A frame mode arrives with a frame already chosen, and shows it. The image has to load
      // from the API for real — a broken src is invisible in the DOM but obvious on screen.
      await page.getByRole("button", { name: "First / last frame" }).click()
      const thumb = page.getByTestId("thumb").first()
      await thumb.waitFor({ timeout: 10_000 })
      const drawn = await thumb.evaluate((node) => node.naturalWidth > 0)
      if (!drawn) throw new Error("the picked frame's thumbnail never decoded")

      await page.getByRole("combobox", { name: "Add a sweep axis" }).click()
      await page.getByRole("option").first().click()

      // References have no default here, and a sweep inherits the base config — so it has to
      // refuse rather than queue a matrix where every run fails the same validation.
      const preview = page.getByRole("button", { name: "Preview" })
      await page.getByRole("button", { name: "References" }).click()
      await page.getByText(/still needs/i).first().waitFor({ timeout: 10_000 })
      if (!(await preview.isDisabled())) throw new Error("preview stayed live on an invalid base")

      // Text-only needs nothing extra, so the same matrix must now survive a real round trip.
      await page.getByRole("button", { name: "Text only" }).click()
      await page.getByRole("button", { name: /^Queue \d+ runs?$/ }).waitFor({ timeout: 10_000 })
      await preview.click()
      await page.getByText("Already run", { exact: true }).waitFor({ timeout: 15_000 })
    },
  },
  {
    name: "runs",
    path: "/runs",
    expect: ["Judge the results", "spectrum"],
    // Filtering has to actually cut the list down, not just repaint it.
    async act(page) {
      const cards = page.getByTestId("run-card")
      const before = await cards.count()
      await page.getByRole("textbox", { name: "Search runs" }).fill("lighthouse")
      await page.waitForFunction(
        (was) => document.querySelectorAll('[data-testid="run-card"]').length < was,
        before,
        { timeout: 15_000 }
      )
    },
  },
  { name: "compare", path: "/compare", expect: ["Compare"] },
  {
    name: "arena",
    path: "/arena",
    expect: ["Which one is better?", "Held identical"],
    /**
     * The arena's whole claim is that the pair is comparable and anonymous, so both halves
     * are checked on the real page: two clips that decode, no run label anywhere, and the
     * settings genuinely absent from the document until the disclosure is opened.
     */
    async act(page) {
      const clips = page.locator("article video")
      if ((await clips.count()) !== 2) {
        throw new Error(`expected two clips, found ${await clips.count()}`)
      }
      await page.waitForFunction(
        () =>
          Array.from(document.querySelectorAll("article video")).every(
            (node) => node.readyState >= 2
          ),
        undefined,
        { timeout: 15_000 }
      )

      const reveal = page.getByText(/^Reveal \d+ difference/)
      await reveal.waitFor({ timeout: 10_000 })
      if (await page.getByRole("table").isVisible().catch(() => false)) {
        throw new Error("the settings were on the page before anyone asked for them")
      }
      await reveal.click()
      await page.getByRole("columnheader", { name: "Setting" }).waitFor({ timeout: 10_000 })

      // A real vote through the real endpoint, and a fresh pair on the way back.
      const [response] = await Promise.all([
        page.waitForResponse(
          (item) =>
            item.url().includes("/api/votes") && item.request().method() === "POST",
          { timeout: 20_000 }
        ),
        page.getByRole("button", { name: "This one" }).first().click(),
      ])
      if (response.status() !== 201) throw new Error(`the vote answered ${response.status()}`)
      await page.getByText("Held identical").waitFor({ timeout: 15_000 })
    },
  },
  {
    name: "arena-standings",
    path: "/arena/standings",
    expect: ["What the votes decided", "votes counted"],
    async act(page) {
      // A vote was just cast, so at least one setting must now be ranked and explained.
      await page.getByRole("columnheader", { name: "Elo" }).first().waitFor({ timeout: 15_000 })
      const rows = page.locator("tbody tr")
      if ((await rows.count()) < 2) throw new Error("a ranking needs at least two values")
      await page.getByText(/^Best /).first().waitFor({ timeout: 10_000 })
    },
  },
  { name: "insights", path: "/insights", expect: ["What actually matters"] },
  { name: "insights-axis", path: "/insights/cache", expect: ["Cache"] },
  {
    name: "leaderboard",
    path: "/leaderboard",
    expect: ["What is worth reusing", "The trade-off"],
    // Long run labels used to spill across the score column instead of truncating.
    async act(page) {
      const row = page.locator("article").first()
      const label = await row.locator('a[href^="/runs/"]').last().boundingBox()
      const score = await row.getByText("Score", { exact: true }).boundingBox()
      if (label && score && label.x + label.width > score.x) {
        throw new Error("the run label overlaps the score column")
      }
    },
  },
  { name: "not-found", path: "/nope", expect: ["No such page"] },
]

/** A page wider than the window means something is refusing to shrink. */
const overflow = (page) =>
  page.evaluate(() => {
    const slack = document.documentElement.scrollWidth - window.innerWidth
    return slack > 1 ? slack : 0
  })

const browser = await chromium.launch({ headless: !headed })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await context.newPage()

page.on("console", (message) => {
  if (message.type() === "error") note("console", message.text())
})
page.on("pageerror", (error) => note("pageerror", error.message))
page.on("requestfailed", (request) => {
  if (!TOLERATED.some((pattern) => pattern.test(request.url()))) {
    note("requestfailed", `${request.url()} ${request.failure()?.errorText ?? ""}`)
  }
})
page.on("response", (response) => {
  const url = response.url()
  if (response.status() >= 400 && !TOLERATED.some((pattern) => pattern.test(url))) {
    note("http", `${response.status()} ${url}`)
  }
})

await mkdir(shots, { recursive: true })

const step = async (name, label, body) => {
  const before = problems.length
  try {
    await body()
  } catch (error) {
    note(name, error.message.split("\n")[0])
  }
  const ok = problems.length === before
  console.log(`${ok ? "ok  " : "FAIL"} ${name.padEnd(14)} ${label}`)
  return ok
}

for (const stop of TOUR) {
  await step(stop.name, stop.path, async () => {
    await page.goto(base + stop.path, { waitUntil: "networkidle", timeout: 30_000 })
    for (const text of stop.expect) {
      await page.getByText(text, { exact: false }).first().waitFor({ timeout: 15_000 })
    }
    if (stop.act) await stop.act(page)
    const slack = await overflow(page)
    if (slack) throw new Error(`page overflows the window by ${slack}px`)
    await page.screenshot({ path: shot(stop.name) })
  })
}

// The run detail page needs a real id, so it is reached the way a user reaches it.
await step("run", "/runs/:id (followed from the list)", async () => {
  await page.goto(base + "/runs", { waitUntil: "networkidle" })
  // Queued and failed runs show a placeholder, so pick one that actually rendered something.
  await page
    .locator('[data-testid="run-card"]:has([data-testid="filmstrip"]) a[href^="/runs/"]')
    .first()
    .click()
  await page.getByText("The config that made it").waitFor({ timeout: 15_000 })
  await page.getByText("What it cost").waitFor({ timeout: 5_000 })
  if (!/\/runs\/[A-Za-z0-9]+/.test(page.url())) throw new Error(`url stayed at ${page.url()}`)
  const strip = page.locator("img[src*='/media/strips/']").first()
  if ((await strip.count()) === 0) throw new Error("no filmstrip image rendered")
  await page.screenshot({ path: shot("run") })
})

/**
 * The workflow download, taken the way a user takes it.
 *
 * jsdom can say the anchor has the right href. Only a browser can say the click produces a file,
 * and the file is the entire feature: an editor graph, positioned, holding the interpolator this
 * run actually used — not the API prompt, which opens as a heap of boxes.
 */
await step("workflow", "downloaded a run's graph and read it", async () => {
  const listed = await page.request.get(base + "/api/runs?limit=50")
  const body = await listed.json()
  const runs = (body.items ?? body).map((item) => item.run ?? item)
  const film = runs.find((run) => run.config.interp === "film")
  if (!film) throw new Error("no interpolated run was seeded")

  await page.goto(`${base}/runs/${film.id}`, { waitUntil: "networkidle" })
  const link = page.getByRole("link", { name: /download workflow/i })
  const [download] = await Promise.all([page.waitForEvent("download"), link.click()])

  if (download.suggestedFilename() !== `h3lab-${film.id}.json`) {
    throw new Error(`the file is named ${download.suggestedFilename()}`)
  }
  const saved = `${shots}workflow-${film.id}.json`
  await download.saveAs(saved)
  const workflow = JSON.parse(await readFile(saved, "utf8"))

  if (!Array.isArray(workflow.nodes) || !Array.isArray(workflow.links)) {
    throw new Error("the download is not an editor workflow")
  }
  const unplaced = workflow.nodes.filter((node) => !Array.isArray(node.pos))
  if (unplaced.length) {
    throw new Error(`${unplaced.length} node(s) have no position`)
  }
  const types = new Set(workflow.nodes.map((node) => node.type))
  if (!types.has("FrameInterpolate")) throw new Error("the film run's graph has no interpolator")
  if (types.has("RIFEInterpolation")) throw new Error("the graph kept an interpolator it did not use")
  if (workflow.extra?.h3lab?.run_id !== film.id) {
    throw new Error("the graph does not name the run it came from")
  }
  await page.screenshot({ path: shot("run-workflow") })
})

// Staging on one page and comparing on another is the flow the Bench tray exists for.
await step("bench", "staged two runs, compared them", async () => {
  await page.goto(base + "/runs", { waitUntil: "networkidle" })
  // Two runs that produced something, so the comparison has media on both sides.
  const finished = page.locator('[data-testid="run-card"]:has([data-testid="filmstrip"])')
  for (const index of [0, 1]) {
    await finished.nth(index).getByRole("button", { name: "Stage for comparison" }).click()
  }
  await page.goto(base + "/compare", { waitUntil: "networkidle" })
  await page.getByText("What differs").waitFor({ timeout: 15_000 })
  if ((await page.locator("img[src*='/media/']").count()) < 2) {
    throw new Error("compared two finished runs but only one preview rendered")
  }
  await page.screenshot({ path: shot("compare-staged") })
})

/**
 * The live layer, checked the only way it can be: a change made outside the page.
 *
 * This shipped broken and neither suite noticed. The server named every SSE frame after its
 * kind, which routes it to a listener of that name rather than to `onmessage` — so the socket
 * opened, stayed open, reported no errors, and delivered nothing. Only a real browser reading
 * a real stream can tell the difference, which is why the assertion lives here.
 */
await step("live", "the page moved without being reloaded", async () => {
  await page.goto(base + "/runs", { waitUntil: "networkidle" })
  const before = await page.getByTestId("run-card").count()

  const created = await page.request.post(base + "/api/runs", {
    data: { config: { mode: "t2v", prompt: "queued from outside the page" }, count: 1 },
  })
  if (!created.ok()) throw new Error(`could not queue a run: ${created.status()}`)
  const id = (await created.json())[0].run.id

  await page.waitForFunction(
    (was) => document.querySelectorAll('[data-testid="run-card"]').length > was,
    before,
    { timeout: 15_000 }
  )
  // The run the server just made, on a page nobody reloaded.
  await page.locator(`[data-run-id="${id}"]`).waitFor({ timeout: 15_000 })
})

/**
 * Resting on a strip opens the clip in a floating card. jsdom can assert the element appears
 * and that it is portalled out of the 6:1 strip; only a browser can say whether autoplay
 * policy let it start and whether the card actually landed on screen.
 */
await step("hover", "a rested pointer played the clip", async () => {
  await page.goto(base + "/runs", { waitUntil: "networkidle" })
  const strip = page
    .locator('[data-testid="run-card"] [data-testid="filmstrip"]:has(img[src*="/media/strips/"])')
    .first()

  await strip.hover()
  const video = page.getByTestId("hover-preview")
  await video.waitFor({ timeout: 10_000 })

  // Muted autoplay is allowed without a gesture; if that ever changes, the clip sits at zero.
  await page.waitForFunction(
    () => {
      const node = document.querySelector('[data-testid="hover-preview"]')
      return node instanceof HTMLVideoElement && node.currentTime > 0 && !node.paused
    },
    undefined,
    { timeout: 10_000 }
  )

  // The whole point of floating it: a shape you can judge, fully on screen.
  const card = await page.getByTestId("hover-card").boundingBox()
  const view = page.viewportSize()
  if (!card) throw new Error("the preview card has no box")
  if (card.width < 240 || card.height < 160) {
    throw new Error(`the preview card is ${card.width}×${card.height}, too small to judge`)
  }
  if (card.x < 0 || card.y < 0 || card.x + card.width > view.width || card.y + card.height > view.height) {
    throw new Error(`the preview card sits outside the viewport at ${card.x},${card.y}`)
  }
  await page.screenshot({ path: shot("hover-preview") })

  // Moving away has to give the decoder back, not leave a video playing off-screen.
  await page.getByRole("heading", { name: /Judge the results/i }).hover()
  await video.waitFor({ state: "detached", timeout: 10_000 })
})

/**
 * The turbo LoRA, driven the way it is meant to be used: pick one, watch the schedule follow it,
 * then sweep the axis.
 *
 * A distilled LoRA is trained for a fixed step count, so switching LoRAs silently changes the
 * sampling. The count is computed on the server and shipped in the catalog, which means only a
 * real page against a real API can show that the two agree — and the field is disabled, so the
 * number on screen is the only place the run's true schedule is visible before it is queued.
 */
await step("turbo-lora", "picked a LoRA, swept the axis", async () => {
  await page.goto(base, { waitUntil: "networkidle" })
  const turbo = page.getByRole("switch", { name: /^Turbo/ })
  await turbo.waitFor({ timeout: 15_000 })
  await turbo.click()

  const picker = page.getByRole("combobox", { name: "Turbo LoRA" })
  await picker.waitFor({ timeout: 10_000 })
  await page.getByText("4-step schedule").waitFor({ timeout: 10_000 })

  await picker.click()
  const options = page.getByRole("option")
  await options.first().waitFor({ timeout: 10_000 })
  const count = await options.count()
  if (count < 2) throw new Error(`the picker offers ${count} LoRA(s), so there is no choice`)
  const names = await options.allInnerTexts()
  if (names.some((name) => /\.safetensors/.test(name))) {
    throw new Error(`the options are raw filenames: ${names[0]}`)
  }
  // The 8-step file, chosen by what it reads as rather than by its position in the list.
  const eight = names.findIndex((name) => /8step/i.test(name))
  if (eight < 0) throw new Error(`no 8-step LoRA among ${names.join(", ")}`)
  await options.nth(eight).click()

  // The schedule moved with the pick, and the steps field shows it while refusing edits.
  await page.getByText("8-step schedule").waitFor({ timeout: 10_000 })
  const steps = page.getByRole("spinbutton", { name: "Steps" })
  if (await steps.isEnabled()) throw new Error("a turbo run let its step count be edited")
  if ((await steps.inputValue()) !== "8") {
    throw new Error(`the steps field reads ${await steps.inputValue()}, not the LoRA's 8`)
  }

  // Strength is the second half of the axis, and it is a slider with no text input.
  const strength = page.getByRole("slider", { name: "Turbo strength" })
  await strength.focus()
  await page.keyboard.press("ArrowLeft")
  await page.getByText(/0\.9\d ×/).waitFor({ timeout: 10_000 })

  await picker.scrollIntoViewIfNeeded()
  await page.screenshot({ path: shot("turbo-lora") })

  // Sweeping it is the point: a matrix of LoRAs, priced by the server.
  await page.getByRole("combobox", { name: "Add a sweep axis" }).click()
  await page.getByRole("option", { name: /Turbo LoRA/ }).click()
  const queue = page.getByRole("button", { name: /^Queue \d+ runs?$/ })
  await queue.waitFor({ timeout: 10_000 })
  const [priced] = await Promise.all([
    page.waitForResponse(
      (item) => item.url().includes("/api/sweeps/preview") && item.request().method() === "POST",
      { timeout: 20_000 }
    ),
    page.getByRole("button", { name: "Preview" }).click(),
  ])
  if (priced.status() !== 200) throw new Error(`the preview answered ${priced.status()}`)
  const body = await priced.json()
  const loras = new Set(body.items.map((item) => item.config.turbo_lora))
  if (loras.size < 2) throw new Error("the swept matrix names one LoRA")
  if (!body.items.every((item) => item.config.turbo_lora_strength < 1)) {
    throw new Error("the matrix dropped the strength the form was set to")
  }
  await page.screenshot({ path: shot("turbo-lora-sweep") })
})

// Rating from the list is the single most repeated action in the product.
await step("rate", "rated a run and saw it stick", async () => {
  await page.goto(base + "/runs", { waitUntil: "networkidle" })
  const card = page.getByTestId("run-card").first()
  const runId = await card.getAttribute("data-run-id")
  await card.getByRole("button", { name: "9 out of 10" }).click()
  await page.waitForResponse(
    (response) =>
      response.url().includes(`/api/runs/${runId}/rating`) && response.request().method() === "PUT",
    { timeout: 15_000 }
  )
  await page.reload({ waitUntil: "networkidle" })
  const again = page.locator(`[data-run-id="${runId}"]`).first()
  await again
    .getByRole("button", { name: "9 out of 10", pressed: true })
    .waitFor({ timeout: 15_000 })
})

await writeFile(`${shots}problems.txt`, problems.join("\n"), "utf8")
await browser.close()

if (problems.length) {
  console.error(`\n${problems.length} problem(s):`)
  for (const problem of problems.slice(0, 40)) console.error(`  - ${problem}`)
  process.exit(1)
}
console.log("\nsmoke passed: every page rendered and responded, console clean")
