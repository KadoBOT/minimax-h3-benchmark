/**
 * Exercise the built shared-SDUI UI in Chromium with only same-origin API routes mocked.
 *
 * This is intentionally below component tests and above a live ComfyUI render: Vite serves the
 * production bundle, Chromium performs real fetch/XHR/media/download behavior, and the route
 * fixture implements the same local BFF paths a browser sees in production.
 */
import { existsSync } from "node:fs"
import { mkdtemp, mkdir, readFile, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { spawn, spawnSync } from "node:child_process"
import { once } from "node:events"
import { createServer } from "node:net"

import { chromium } from "playwright"

const REVISION = `sha256:${"a".repeat(64)}`
const ASSET_ID = "123e4567-e89b-42d3-a456-426614174000"
const JOB_ID = "223e4567-e89b-42d3-a456-426614174001"
const RUN_ID = "local-1"
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
  "base64"
)

const temp = await mkdtemp(join(tmpdir(), "h3lab-shared-browser-"))
const videoPath = join(temp, "result.mp4")
const ffmpeg = spawnSync(
  "ffmpeg",
  [
    "-y",
    "-v",
    "error",
    "-f",
    "lavfi",
    "-i",
    "color=c=black:size=64x64:rate=12:duration=1",
    "-pix_fmt",
    "yuv420p",
    videoPath,
  ],
  { encoding: "utf8" }
)
if (ffmpeg.status !== 0) {
  throw new Error(
    `ffmpeg could not create the browser fixture: ${ffmpeg.stderr}`
  )
}
const VIDEO = await readFile(videoPath)
const port = await freePort()
const base = `http://127.0.0.1:${port}`
const server = spawn(
  process.execPath,
  [
    join(process.cwd(), "node_modules", "vite", "bin", "vite.js"),
    "preview",
    "--host",
    "127.0.0.1",
    "--port",
    String(port),
  ],
  { stdio: ["ignore", "pipe", "pipe"] }
)

let serverOutput = ""
server.stdout.on("data", (chunk) => {
  serverOutput += String(chunk)
})
server.stderr.on("data", (chunk) => {
  serverOutput += String(chunk)
})

const problems = []
const requests = []
let generationState = "available"
let createdSubmission = null
let createdKey = null

try {
  await waitForServer(base)
  const systemChrome = process.env.CHROME_BIN ?? "/usr/bin/google-chrome"
  const browser = await chromium.launch({
    headless: !process.argv.includes("--headed"),
    executablePath: existsSync(systemChrome) ? systemChrome : undefined,
  })
  try {
    const context = await browser.newContext({
      viewport: { width: 1365, height: 900 },
      acceptDownloads: true,
    })
    const page = await context.newPage()
    page.on("console", (message) => {
      if (message.type() === "error")
        problems.push(`console: ${message.text()}`)
    })
    page.on("pageerror", (error) =>
      problems.push(`pageerror: ${error.message}`)
    )
    page.on("requestfailed", (request) => {
      if (!request.url().includes("/api/events")) {
        problems.push(`requestfailed: ${request.method()} ${request.url()}`)
      }
    })

    await page.route("**/api/**", async (route) => {
      const request = route.request()
      const url = new URL(request.url())
      const key = `${request.method()} ${url.pathname}`
      requests.push(key)

      if (url.pathname === "/api/events") {
        await route.fulfill({
          status: 200,
          contentType: "text/event-stream",
          body: "",
        })
        return
      }
      if (key === "GET /api/status") {
        await json(route, {
          worker_alive: true,
          paused: false,
          active_run_id: null,
          queued: 0,
          comfy_url: "shared service",
          counts: { running: 1 },
          total_runs: 1,
          votes: 0,
          rated: 0,
          event_seq: 0,
          criteria: ["motion", "detail"],
        })
        return
      }
      if (key === "GET /api/queue") {
        await json(route, {
          paused: false,
          worker_alive: true,
          active_run_id: null,
          active: null,
          queued: [],
          total: 0,
        })
        return
      }
      if (key === "GET /api/meta") {
        await json(route, meta())
        return
      }
      if (key === "GET /api/shared/generation") {
        if (generationState === "malformed") {
          await json(route, {
            ...generationDocument(),
            protocolVersion: "99.0",
          })
        } else if (generationState === "disabled") {
          await json(route, generationDocument(true))
        } else {
          await json(route, generationDocument())
        }
        return
      }
      if (key === "POST /api/shared/assets") {
        await json(route, {
          id: ASSET_ID,
          kind: "asset",
          mediaKind: "image",
          mime: "image/png",
          size: PNG.length,
          digest: `sha256:${"b".repeat(64)}`,
          filename: "frame.png",
          contentUrl: `/api/shared/assets/${ASSET_ID}/content`,
        })
        return
      }
      if (key === `GET /api/shared/assets/${ASSET_ID}/content`) {
        await route.fulfill({
          status: 200,
          contentType: "image/png",
          body: PNG,
        })
        return
      }
      if (key === "POST /api/runs") {
        createdSubmission = JSON.parse(request.postData() ?? "{}")
        createdKey = await request.headerValue("idempotency-key")
        await json(route, [runView()])
        return
      }
      if (key === `GET /api/runs/${RUN_ID}`) {
        await json(route, runView())
        return
      }
      if (key === `GET /api/runs/${RUN_ID}/shared-view`) {
        await json(route, jobDocument())
        return
      }
      if (key === `POST /api/runs/${RUN_ID}/cancel`) {
        await json(route, { ok: true, detail: "cancel requested" })
        return
      }
      if (key === `POST /api/runs/${RUN_ID}/retry-collection`) {
        await json(route, runView())
        return
      }
      if (key === `POST /api/runs/${RUN_ID}/rerun`) {
        if (!(await request.headerValue("idempotency-key"))) {
          await json(
            route,
            { error: "missing idempotency key", detail: "missing key" },
            400
          )
          return
        }
        await json(route, runView())
        return
      }
      if (
        key === `GET /api/runs/${RUN_ID}/shared-preview` ||
        key === `GET /api/runs/${RUN_ID}/preview`
      ) {
        await route.fulfill({
          status: 200,
          contentType: "image/png",
          body: PNG,
        })
        return
      }
      if (key === `GET /api/runs/${RUN_ID}/shared-video`) {
        await route.fulfill({
          status: 200,
          headers: {
            "Content-Type": "video/mp4",
            "Content-Length": String(VIDEO.length),
            "Accept-Ranges": "bytes",
            "Content-Disposition": 'inline; filename="result.mp4"',
          },
          body: VIDEO,
        })
        return
      }
      if (key === `GET /api/runs/${RUN_ID}/workflow`) {
        await json(route, { kind: "shared-job-receipt", runId: RUN_ID })
        return
      }
      if (url.pathname.startsWith("/api/runs")) {
        await json(route, {
          items: [runView()],
          total: 1,
          limit: 60,
          offset: 0,
        })
        return
      }
      if (
        [
          "/api/presets",
          "/api/tags",
          "/api/recipes",
          "/api/insights/axes",
        ].includes(url.pathname)
      ) {
        await json(route, [])
        return
      }
      await json(
        route,
        {
          error: "unmocked route",
          detail: `${request.method()} ${url.pathname}`,
        },
        404
      )
    })

    await page.goto(base, { waitUntil: "networkidle" })
    await page.getByRole("heading", { name: "Browser SDUI fixture" }).waitFor()
    await page
      .getByLabel("Source strategy")
      .selectOption({ label: "Start from a frame" })
    await page.getByLabel("Upload Opening frame").setInputFiles({
      name: "frame.png",
      mimeType: "image/png",
      buffer: PNG,
    })
    await page.getByRole("img", { name: "frame.png" }).waitFor()
    await page
      .getByRole("textbox", { name: "Creative direction" })
      .fill("Browser lifecycle")
    await page.getByRole("button", { name: "Start shared render" }).click()
    await page.waitForFunction(
      () => document.activeElement?.getAttribute("tabindex") === "-1"
    )

    assert(createdKey, "generation did not send an idempotency key")
    assert(
      createdSubmission?.workflowRevision === REVISION,
      "workflow revision was not pinned"
    )
    assert(
      createdSubmission?.input?.openingFrame?.[0] === ASSET_ID,
      "submission did not contain the uploaded opaque asset id"
    )
    assert(
      createdSubmission?.input?.prompt === "Browser lifecycle",
      "submission did not contain the visible prompt"
    )

    await page.goto(`${base}/runs/${RUN_ID}`, { waitUntil: "networkidle" })
    await page.getByRole("status", { name: "Rendering" }).waitFor()
    assert(
      (await page
        .getByRole("progressbar", { name: "Denoising" })
        .getAttribute("aria-valuenow")) === "50",
      "job progress did not render at 50 percent"
    )
    await page
      .getByRole("log", { name: "Job log" })
      .getByText("Sampler started")
      .waitFor()
    await page.getByLabel("Generated video").waitFor()
    await page.getByRole("button", { name: "Cancel shared render" }).click()
    await page.getByRole("button", { name: "Retry video collection" }).click()
    await page.getByRole("button", { name: "Run again" }).click()

    const downloadLink = page.getByRole("link", {
      name: "Download generated video",
    })
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      downloadLink.click(),
    ])
    assert(
      download.suggestedFilename() === "result.mp4",
      "download filename was not preserved"
    )
    assert(
      requests.includes(`POST /api/runs/${RUN_ID}/cancel`),
      "cancel did not use the local same-origin route"
    )
    assert(
      requests.includes(`POST /api/runs/${RUN_ID}/retry-collection`),
      "collection retry did not use the local same-origin route"
    )

    await page.setViewportSize({ width: 390, height: 844 })
    await page.reload({ waitUntil: "networkidle" })
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth
    )
    assert(
      overflow <= 1,
      `shared run page overflowed mobile viewport by ${overflow}px`
    )

    generationState = "malformed"
    await page.goto(base)
    await page.reload({ waitUntil: "networkidle" })
    await page
      .getByRole("alert", { name: /generation document could not be used/i })
      .waitFor()
    assert(
      (await page
        .getByRole("button", { name: "Start shared render" })
        .count()) === 0,
      "malformed generation document left submission enabled"
    )

    generationState = "disabled"
    await page.reload({ waitUntil: "networkidle" })
    await page
      .getByText("The render service is intentionally unavailable.")
      .waitFor()
    assert(
      await page
        .getByRole("button", { name: "Start shared render" })
        .isDisabled(),
      "disabled availability left submission enabled"
    )

    const shots = join(process.cwd(), "..", ".smoke", "shots")
    await mkdir(shots, { recursive: true })
    await page.screenshot({
      path: join(shots, "shared-sdui.png"),
      fullPage: true,
    })

    if (problems.length) throw new Error(problems.join("\n"))
    console.log("ok   shared SDUI production-browser lifecycle")
  } finally {
    await browser.close()
  }
} finally {
  if (server.exitCode === null) {
    server.kill("SIGTERM")
    await once(server, "exit")
  }
  await rm(temp, { recursive: true, force: true })
}

function generationDocument(disabled = false) {
  return {
    protocolVersion: "1.0",
    documentId: "browser-shared-generation",
    schemaRevision: "browser-v1",
    workflowId: "minimax-h3-unified",
    workflowRevision: REVISION,
    title: "Browser SDUI fixture",
    description:
      "Controls and labels originate in the shared service document.",
    availability: disabled
      ? {
          state: "disabled",
          observedAt: new Date().toISOString(),
          reason: {
            code: "maintenance",
            detail: "The render service is intentionally unavailable.",
            retryable: true,
          },
        }
      : { state: "available", observedAt: new Date().toISOString() },
    capabilities: {
      required: [
        "component.select",
        "component.textarea",
        "component.number",
        "component.seed",
        "component.toggle",
        "component.asset",
        "action.submit",
      ],
      optional: [],
    },
    kind: "generation",
    components: [
      { id: "source", kind: "section", title: "Source" },
      {
        id: "source-strategy",
        kind: "select",
        binding: "mode",
        label: "Source strategy",
        required: true,
        options: [
          { value: "text", label: "Text only" },
          { value: "frame", label: "Start from a frame" },
        ],
        defaultValue: "text",
      },
      {
        id: "prompt",
        kind: "textarea",
        binding: "prompt",
        label: "Creative direction",
        required: true,
        minLength: 1,
        maxLength: 2000,
        defaultValue: "A lighthouse in rain",
      },
      {
        id: "steps",
        kind: "number",
        binding: "steps",
        label: "Iteration budget",
        required: true,
        minimum: 1,
        maximum: 100,
        integer: true,
        defaultValue: 20,
      },
      {
        id: "seed",
        kind: "seed",
        binding: "seed",
        label: "Random seed",
        required: true,
        allowRandom: true,
        minimum: 0,
        maximum: Number.MAX_SAFE_INTEGER,
        defaultValue: 42,
      },
      {
        id: "grade",
        kind: "toggle",
        binding: "grade",
        label: "Finishing grade",
        required: true,
        defaultValue: false,
      },
      {
        id: "opening-frame",
        kind: "asset",
        binding: "openingFrame",
        label: "Opening frame",
        required: true,
        accept: ["image"],
        minimumItems: 1,
        maximumItems: 1,
        visibleWhen: [{ field: "mode", operator: "equals", value: "frame" }],
      },
    ],
    actions: [
      {
        id: "submit",
        kind: "submit",
        label: "Start shared render",
        endpoint: "/api/runs",
        method: "POST",
      },
    ],
  }
}

function jobDocument() {
  return {
    protocolVersion: "1.0",
    documentId: `browser-job-${JOB_ID}`,
    schemaRevision: "browser-v1",
    workflowId: "minimax-h3-unified",
    workflowRevision: REVISION,
    kind: "job",
    jobId: JOB_ID,
    title: "Browser shared job",
    availability: { state: "available", observedAt: new Date().toISOString() },
    capabilities: {
      required: [
        "component.status",
        "component.progress",
        "component.log",
        "component.preview",
        "component.video",
        "component.download",
        "action.cancel",
        "action.retry_collection",
      ],
      optional: [],
    },
    components: [
      { id: "live", kind: "section", title: "Live output" },
      {
        id: "status",
        kind: "status",
        state: "running",
        label: "Rendering",
        detail: "Sampling",
      },
      {
        id: "progress",
        kind: "progress",
        value: 0.5,
        label: "Denoising",
        current: 10,
        total: 20,
      },
      {
        id: "log",
        kind: "log",
        entries: [
          {
            sequence: 1,
            at: new Date().toISOString(),
            level: "info",
            message: "Sampler started",
          },
        ],
      },
      {
        id: "preview",
        kind: "preview",
        src: `/api/runs/${RUN_ID}/shared-preview`,
        mime: "image/png",
        sequence: 1,
      },
      {
        id: "video",
        kind: "video",
        src: `/api/runs/${RUN_ID}/shared-video`,
        mime: "video/mp4",
      },
      {
        id: "download",
        kind: "download",
        href: `/api/runs/${RUN_ID}/shared-video`,
        filename: "result.mp4",
        label: "Download generated video",
      },
    ],
    actions: [
      {
        id: "cancel",
        kind: "cancel",
        label: "Cancel shared render",
        endpoint: `/api/runs/${RUN_ID}/cancel`,
        method: "POST",
      },
      {
        id: "retry",
        kind: "retry_collection",
        label: "Retry video collection",
        endpoint: `/api/runs/${RUN_ID}/retry-collection`,
        method: "POST",
      },
    ],
  }
}

function runView() {
  return {
    run: {
      id: RUN_ID,
      seq: 1,
      label: "browser shared benchmark",
      status: "running",
      config: { mode: "t2v", prompt: "Browser lifecycle", steps: 20, seed: 42 },
      config_hash: "browser-config",
      recipe_hash: "browser-recipe",
      shared_submission: createdSubmission ?? {
        workflowRevision: REVISION,
        schemaRevision: "browser-v1",
        input: { prompt: "Browser lifecycle", steps: 20, seed: 42 },
      },
      shared_job_id: JOB_ID,
      shared_provenance: {
        manifestDigest: `sha256:${"c".repeat(64)}`,
        compiler: { id: "minimax-h3", version: "1" },
        catalogRevision: `sha256:${"d".repeat(64)}`,
        inputDigest: `sha256:${"e".repeat(64)}`,
        resolvedSeed: 42,
      },
      shared_event_cursor: 3,
      error: null,
      favourite: false,
      archived: false,
      notes: "",
      tags: [],
      created_at: new Date().toISOString(),
      started_at: new Date().toISOString(),
      finished_at: null,
    },
    stars: null,
    criteria: {},
    elo: null,
    elo_games: 0,
    score: null,
    rank: null,
    duplicate_of: null,
    is_baseline: false,
  }
}

function meta() {
  return {
    axes: [],
    criteria: ["motion", "detail"],
    criterion_labels: { motion: "Motion", detail: "Detail" },
    stars: { min: 1, max: 10 },
    seed_strategies: ["fixed"],
    field_labels: { prompt: "Prompt", steps: "Steps", seed: "Seed" },
    modes: [],
    mode_needs: {},
    defaults: {},
    limits: {},
  }
}

async function json(route, body, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  })
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function freePort() {
  return new Promise((resolve, reject) => {
    const probe = createServer()
    probe.once("error", reject)
    probe.listen(0, "127.0.0.1", () => {
      const address = probe.address()
      const selected =
        typeof address === "object" && address ? address.port : null
      probe.close((error) => (error ? reject(error) : resolve(selected)))
    })
  })
}

async function waitForServer(url) {
  const deadline = Date.now() + 30_000
  while (Date.now() < deadline) {
    if (server.exitCode !== null) {
      throw new Error(`Vite preview exited before startup:\n${serverOutput}`)
    }
    try {
      const response = await fetch(url)
      if (response.ok) return
    } catch {
      // Keep waiting while Vite binds its socket.
    }
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new Error(`Vite preview did not start:\n${serverOutput}`)
}
