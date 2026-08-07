const POLL_MS = 1500;

const AXIS_PRIORITY = [
  (c) => c.diffusion_model || (c.model_path === "gguf" ? "gguf" : c.quant),
  (c) => (!c.cache_enabled || c.cache === "none" ? "none" : c.cache),
  (c) => (c.model_path === "gguf" ? "gguf" : c.quant),
  (c) => (c.sol_attn ? "sol_on" : "sol_off"),
  (c) => (c.turbo ? "turbo" : "no_turbo"),
  (c) => c.scheduler,
  (c) => c.sampler,
  (c) => String(c.steps),
  (c) => c.cache_preset,
  (c) => c.sol_preset,
];

/** Infer loader path from diffusion model basename (mirrors bench.diffusion_models.infer_loader). */
function inferLoader(filename) {
  const n = String(filename || "")
    .toLowerCase()
    .replace(/-/g, "_");
  // GGUF → GGUF loader; every other model → UNETLoader (NVFP4 node)
  if (n.endsWith(".gguf")) return { model_path: "gguf", quant: "nvfp4" };
  return { model_path: "safetensor", quant: "nvfp4" };
}

function loaderLabel(cfg) {
  if (!cfg) return "—";
  if (cfg.model_path === "gguf") return "GGUF";
  return "UNETLoader";
}

const DEFAULT_FIRST_FRAME =
  "Cyberpunk_outlaw_with_jagged_grin_202605230412.jpeg";
const DEFAULT_ASPECT_RATIO = "16:9 (Widescreen)";
const DEFAULT_PROMPT =
  "The scene animates from the first frame. Steam billows heavily from under " +
  "the car hood. The older man exhales a tired sigh and slumps slightly. The " +
  "overhead light flickers. The younger man tightens his grip on the wrench, " +
  "steps forward, and angrily points it toward the engine while shouting. A " +
  "sudden burst of sparks shoots up from the engine bay, casting a bright " +
  "orange flash across both men's faces as the camera quickly zooms in on the " +
  "younger man.";

const state = {
  config: {
    model_path: "safetensor",
    quant: "nvfp4",
    diffusion_model: "",
    first_frame: DEFAULT_FIRST_FRAME,
    prompt: DEFAULT_PROMPT,
    aspect_ratio: DEFAULT_ASPECT_RATIO,
    turbo: false,
    rife: false,
    upscaler: false,
    clean_vram: false,
    cache_enabled: true,
    cache: "spectrum",
    cache_preset: "moderate",
    sol_attn: true,
    sol_preset: "moderate",
    scheduler: "beta57",
    sampler: "euler",
    steps: 20,
    mp: 0.5,
    duration_s: 5,
    seed: 42,
  },
  options: null,
  busy: false,
  /** @type {Set<string>} Field keys allowed to differ in gallery compare mode */
  galleryVaryAxes: new Set(),
  /** @type {string[]} up to two run ids for 50/50 video compare */
  compareIds: [],
};

/** @type {Map<string, object>} */
const runIndex = new Map();

let lastListKey = "";
let lastHeatmapKey = "";
let lastGalleryKey = "";
let lastScoresKey = "";
let detailRunId = null;
let galleryFiltersWired = false;
let expandedRunId = null;

/**
 * Comparable config dimensions for gallery "allow-vary" filtering.
 * `get` normalizes a RunConfig into a stable string for fingerprinting.
 */
const GALLERY_COMPARE_FIELDS = [
  { key: "scheduler", label: "scheduler", get: (c) => String(c.scheduler ?? "") },
  { key: "sampler", label: "sampler", get: (c) => String(c.sampler ?? "") },
  { key: "steps", label: "steps", get: (c) => String(c.steps ?? "") },
  {
    key: "diffusion_model",
    label: "model",
    get: (c) => String(c.diffusion_model || c.quant || c.model_path || ""),
  },
  { key: "first_frame", label: "first frame", get: (c) => String(c.first_frame ?? "") },
  {
    key: "prompt",
    label: "prompt",
    get: (c) => String(c.prompt ?? "").trim().slice(0, 200),
  },
  {
    key: "aspect_ratio",
    label: "aspect",
    get: (c) => String(c.aspect_ratio ?? ""),
  },
  {
    key: "cache",
    label: "cache",
    get: (c) =>
      !c.cache_enabled || c.cache === "none"
        ? "none"
        : `${c.cache}/${c.cache_preset || "moderate"}`,
  },
  {
    key: "sol",
    label: "sol-attn",
    get: (c) => (c.sol_attn ? `on/${c.sol_preset || "moderate"}` : "off"),
  },
  { key: "turbo", label: "turbo", get: (c) => (c.turbo ? "on" : "off") },
  { key: "rife", label: "rife", get: (c) => (c.rife ? "on" : "off") },
  { key: "upscaler", label: "upscaler", get: (c) => (c.upscaler ? "on" : "off") },
  {
    key: "clean_vram",
    label: "clean VRAM",
    get: (c) => (c.clean_vram ? "on" : "off"),
  },
  { key: "mp", label: "MP", get: (c) => String(c.mp ?? "") },
  { key: "duration_s", label: "duration", get: (c) => String(c.duration_s ?? "") },
  { key: "seed", label: "seed", get: (c) => String(c.seed ?? "") },
  {
    key: "loader",
    label: "loader",
    get: (c) => (c.model_path === "gguf" ? "gguf" : "unet"),
  },
];

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

async function fetchResults() {
  const r = await fetch("/api/results", { cache: "no-store" });
  if (!r.ok) throw new Error("api failed");
  return r.json();
}

async function loadOptions() {
  try {
    const r = await fetch("/api/options", { cache: "no-store" });
    if (!r.ok) throw new Error("options failed");
    state.options = await r.json();
  } catch {
    state.options = {
      schedulers: ["beta", "beta57", "simple"],
      samplers: ["euler", "res_multistep", "er_sde"],
      source: "fallback",
      defaults: {},
    };
  }
  fillSelect("scheduler", state.options.schedulers, state.config.scheduler);
  fillSelect("sampler", state.options.samplers, state.config.sampler);
  const aspects =
    state.options.aspect_ratios && state.options.aspect_ratios.length
      ? state.options.aspect_ratios
      : [
          "1:1 (Square)",
          "2:3 (Portrait Photo)",
          "3:2 (Photo)",
          "3:4 (Portrait Standard)",
          "4:3 (Standard)",
          "9:16 (Portrait Widescreen)",
          "16:9 (Widescreen)",
          "21:9 (Ultrawide)",
        ];
  fillSelect("aspect_ratio", aspects, state.config.aspect_ratio || DEFAULT_ASPECT_RATIO);
  const models = state.options.diffusion_models || [];
  const d = state.options.defaults || {};
  const defaultModel = d.diffusion_model || models[0] || "";
  if (!state.config.diffusion_model || !models.includes(state.config.diffusion_model)) {
    state.config.diffusion_model = defaultModel;
  }
  fillSelect("diffusion_model", models, state.config.diffusion_model);
  applyInferredLoader(state.config.diffusion_model);

  const banner = document.getElementById("options-banner");
  if (state.options.source === "fallback") {
    banner.hidden = false;
  } else {
    banner.hidden = true;
  }
  const hint = document.getElementById("diffusion-hint");
  if (hint) {
    const src = state.options.diffusion_models_source || "?";
    hint.textContent =
      src === "disk"
        ? `Found ${models.length} MiniMax H3 model(s) on disk.`
        : `Using fallback model names (${src}); check DIFFUSION_MODELS_DIR.`;
  }
  // Prefer live defaults when provided
  if (d.scheduler && state.options.schedulers.includes(d.scheduler)) {
    state.config.scheduler = d.scheduler;
  }
  if (d.sampler && state.options.samplers.includes(d.sampler)) {
    state.config.sampler = d.sampler;
  }
  if (d.aspect_ratio) state.config.aspect_ratio = d.aspect_ratio;
  if (d.prompt) state.config.prompt = d.prompt;
  if (d.steps != null) state.config.steps = d.steps;
  if (d.mp != null) state.config.mp = d.mp;
  if (d.duration_s != null) state.config.duration_s = d.duration_s;
  if (d.seed != null) state.config.seed = d.seed;
  if (d.first_frame) state.config.first_frame = d.first_frame;
  else if (!state.config.first_frame) state.config.first_frame = DEFAULT_FIRST_FRAME;
  if (!state.config.prompt) state.config.prompt = DEFAULT_PROMPT;
  if (!state.config.aspect_ratio) state.config.aspect_ratio = DEFAULT_ASPECT_RATIO;
  updateFirstFramePreview(state.config.first_frame);
  formFromState();
}

function updateFirstFramePreview(name) {
  const label = document.getElementById("first-frame-name");
  const img = document.getElementById("first-frame-preview");
  if (label) label.textContent = name ? `Using: ${name}` : "No image selected";
  if (!img) return;
  if (!name) {
    img.hidden = true;
    img.removeAttribute("src");
    return;
  }
  img.src = `/api/input-preview/${encodeURIComponent(name)}?t=${Date.now()}`;
  img.hidden = false;
  img.onerror = () => {
    img.hidden = true;
  };
}

async function onFirstFrameFileChange(ev) {
  const file = ev.target?.files?.[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("image", file, file.name);
  try {
    const r = await fetch("/api/upload-image", { method: "POST", body: fd });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      alert(data.error || "Upload failed");
      return;
    }
    state.config.first_frame = data.first_frame || file.name;
    updateFirstFramePreview(state.config.first_frame);
  } catch (e) {
    alert(`Upload failed: ${e.message || e}`);
  }
}

function applyInferredLoader(filename) {
  if (!filename) return;
  const inf = inferLoader(filename);
  state.config.model_path = inf.model_path;
  state.config.quant = inf.quant;
  state.config.diffusion_model = filename;
  const el = document.getElementById("loader-hint");
  if (el) el.textContent = `Loader: ${loaderLabel(state.config)} · ${filename}`;
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

function fmtSec(s) {
  if (s == null || s === undefined) return "—";
  return `${Number(s).toFixed(1)}s`;
}

/** Sampler s/it (seconds per iteration) if present and sane; else null. */
function samplerSecPerIt(run) {
  if (!run) return null;
  const it = run.sec_per_it;
  if (it == null || it === undefined) return null;
  const n = Number(it);
  // Reject inverted burst junk (e.g. 0.008s/it → 116 it/s) if it slipped into storage
  if (!(n >= 0.05) || !Number.isFinite(n)) return null;
  return n;
}

/** Wall time + Comfy-style s/it (seconds per iteration), e.g. "113.0s · 5.66s/it" */
function fmtRunTime(run) {
  if (!run || run.timed_s == null) return "—";
  const wall = fmtSec(run.timed_s);
  const spi = samplerSecPerIt(run);
  if (spi == null) return wall;
  return `${wall} · ${spi.toFixed(2)}s/it`;
}

function fmtSecPerIt(run) {
  const spi = samplerSecPerIt(run);
  return spi == null ? "—" : `${spi.toFixed(2)}s/it`;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function findFastest(runs) {
  return runs
    .filter((r) => r.status === "done" && r.timed_s != null && !r.excluded)
    .sort((a, b) => a.timed_s - b.timed_s)[0];
}

/** Runs that count for compare / heatmap / scores / fastest (not excluded). */
function includedRuns(runs) {
  return runs.filter((r) => !r.excluded);
}

function configChips(cfg) {
  if (!cfg) return "";
  const bits = [
    cfg.diffusion_model || null,
    cfg.first_frame ? `img:${cfg.first_frame}` : null,
    cfg.aspect_ratio || null,
    cfg.prompt ? `prompt:${String(cfg.prompt).slice(0, 40)}…` : null,
    cfg.model_path === "gguf" ? "gguf" : null,
    cfg.turbo ? "turbo" : null,
    cfg.rife ? "rife" : null,
    cfg.upscaler ? "upscaler" : null,
    cfg.clean_vram ? "clean_vram" : null,
    !cfg.cache_enabled || cfg.cache === "none"
      ? "cache_off"
      : `${cfg.cache}/${cfg.cache_preset || "?"}`,
    cfg.sol_attn ? `sol/${cfg.sol_preset || "?"}` : "sol_off",
    cfg.scheduler,
    cfg.sampler,
    cfg.steps != null ? `${cfg.steps}st` : null,
    cfg.mp != null ? `${cfg.mp}mp` : null,
    cfg.duration_s != null ? `${cfg.duration_s}s` : null,
    cfg.seed != null ? `seed=${cfg.seed}` : null,
    // legacy
    cfg.cache_variant,
    cfg.sol_variant,
  ].filter(Boolean);
  return bits.map((b) => `<span class="chip">${escapeHtml(b)}</span>`).join("");
}

// ---------------------------------------------------------------------------
// Runs index / flatten
// ---------------------------------------------------------------------------

function collectRuns(data) {
  if (data.runs && data.runs.length) return data.runs.slice();
  const out = [];
  for (const phase of ["speed", "quality", "scale", "manual"]) {
    for (const r of data.phases?.[phase]?.runs || []) {
      out.push(r);
    }
  }
  // any other phase keys
  if (data.phases) {
    for (const [k, ph] of Object.entries(data.phases)) {
      if (["speed", "quality", "scale", "manual"].includes(k)) continue;
      for (const r of ph?.runs || []) out.push(r);
    }
  }
  return out;
}

function indexRuns(runs) {
  runIndex.clear();
  for (const r of runs) {
    if (r?.id) runIndex.set(r.id, r);
  }
}

// ---------------------------------------------------------------------------
// Form ↔ state
// ---------------------------------------------------------------------------

function fillSelect(id, values, selected) {
  const el = document.getElementById(id);
  if (!el) return;
  // Must be a real array of strings — iterating a string yields single characters
  // (that was the C/O/M/B/O bug when Comfy returned type "COMBO").
  let list = Array.isArray(values) ? values.filter((v) => typeof v === "string" && v) : [];
  if (!list.length && selected) list = [selected];
  el.innerHTML = "";
  let found = false;
  for (const v of list) {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = v;
    if (v === selected) {
      opt.selected = true;
      found = true;
    }
    el.appendChild(opt);
  }
  if (!found && selected) {
    const opt = document.createElement("option");
    opt.value = selected;
    opt.textContent = selected;
    opt.selected = true;
    el.appendChild(opt);
  }
}

function formFromState() {
  const c = state.config;
  const dm = document.getElementById("diffusion_model");
  if (dm && c.diffusion_model) {
    if (![...dm.options].some((o) => o.value === c.diffusion_model)) {
      const opt = document.createElement("option");
      opt.value = c.diffusion_model;
      opt.textContent = c.diffusion_model;
      dm.appendChild(opt);
    }
    dm.value = c.diffusion_model;
  }
  const mpRadio = document.querySelector(
    `input[name="model_path"][value="${c.model_path}"]`
  );
  if (mpRadio) mpRadio.checked = true;

  const qRadio = document.querySelector(`input[name="quant"][value="${c.quant}"]`);
  if (qRadio) qRadio.checked = true;

  const loaderEl = document.getElementById("loader-hint");
  if (loaderEl) {
    loaderEl.textContent = c.diffusion_model
      ? `Loader: ${loaderLabel(c)} · ${c.diffusion_model}`
      : `Loader: ${loaderLabel(c)}`;
  }

  document.getElementById("toggle-turbo").checked = !!c.turbo;
  document.getElementById("toggle-rife").checked = !!c.rife;
  document.getElementById("toggle-cache").checked = !!c.cache_enabled;
  document.getElementById("toggle-sol").checked = !!c.sol_attn;
  document.getElementById("toggle-upscaler").checked = !!c.upscaler;
  document.getElementById("toggle-clean-vram").checked = !!c.clean_vram;

  const cacheVal = c.cache === "none" ? "spectrum" : c.cache;
  const cacheRadio = document.querySelector(`input[name="cache"][value="${cacheVal}"]`);
  if (cacheRadio) cacheRadio.checked = true;

  document.getElementById("cache_preset").value = c.cache_preset || "moderate";
  document.getElementById("sol_preset").value = c.sol_preset || "moderate";

  const sched = document.getElementById("scheduler");
  if (sched && [...sched.options].some((o) => o.value === c.scheduler)) {
    sched.value = c.scheduler;
  }
  const samp = document.getElementById("sampler");
  if (samp && [...samp.options].some((o) => o.value === c.sampler)) {
    samp.value = c.sampler;
  }

  document.getElementById("steps").value = c.steps;
  document.getElementById("seed").value = c.seed;
  document.getElementById("mp").value = c.mp;
  document.getElementById("duration_s").value = c.duration_s;
  const promptEl = document.getElementById("prompt");
  if (promptEl) promptEl.value = c.prompt || DEFAULT_PROMPT;
  const ar = document.getElementById("aspect_ratio");
  if (ar && c.aspect_ratio) {
    if (![...ar.options].some((o) => o.value === c.aspect_ratio)) {
      const opt = document.createElement("option");
      opt.value = c.aspect_ratio;
      opt.textContent = c.aspect_ratio;
      ar.appendChild(opt);
    }
    ar.value = c.aspect_ratio;
  }
  updateFirstFramePreview(c.first_frame || DEFAULT_FIRST_FRAME);

  syncDisabled();
  updateDuplicateHint();
}

function stateFromForm() {
  const diffusionModel =
    document.getElementById("diffusion_model")?.value ||
    state.config.diffusion_model ||
    "";
  const inferred = diffusionModel
    ? inferLoader(diffusionModel)
    : {
        model_path:
          document.querySelector('input[name="model_path"]:checked')?.value ||
          "safetensor",
        quant:
          document.querySelector('input[name="quant"]:checked')?.value || "nvfp4",
      };
  const cacheEnabled = document.getElementById("toggle-cache").checked;
  const cache =
    document.querySelector('input[name="cache"]:checked')?.value || "spectrum";

  const promptRaw = document.getElementById("prompt")?.value ?? "";
  state.config = {
    model_path: inferred.model_path,
    quant: inferred.quant,
    diffusion_model: diffusionModel,
    first_frame: state.config.first_frame || DEFAULT_FIRST_FRAME,
    prompt: (promptRaw && promptRaw.trim()) || DEFAULT_PROMPT,
    aspect_ratio:
      document.getElementById("aspect_ratio")?.value ||
      state.config.aspect_ratio ||
      DEFAULT_ASPECT_RATIO,
    turbo: document.getElementById("toggle-turbo").checked,
    rife: document.getElementById("toggle-rife").checked,
    upscaler: document.getElementById("toggle-upscaler").checked,
    clean_vram: document.getElementById("toggle-clean-vram").checked,
    cache_enabled: cacheEnabled,
    cache: cacheEnabled ? cache : "none",
    cache_preset: document.getElementById("cache_preset").value || "moderate",
    sol_attn: document.getElementById("toggle-sol").checked,
    sol_preset: document.getElementById("sol_preset").value || "moderate",
    scheduler: document.getElementById("scheduler").value || state.config.scheduler,
    sampler: document.getElementById("sampler").value || state.config.sampler,
    steps: Number(document.getElementById("steps").value) || 20,
    mp: Number(document.getElementById("mp").value) || 0.5,
    duration_s: Number(document.getElementById("duration_s").value) || 5,
    seed: Number(document.getElementById("seed").value) || 42,
  };
  // When cache disabled, keep last cache type for re-enable UX (but send "none")
  if (!cacheEnabled) {
    state.config.cache = "none";
  }
  const loaderEl = document.getElementById("loader-hint");
  if (loaderEl) {
    loaderEl.textContent = diffusionModel
      ? `Loader: ${loaderLabel(state.config)} · ${diffusionModel}`
      : `Loader: ${loaderLabel(state.config)}`;
  }
  updateDuplicateHint();
}

function syncDisabled() {
  const cacheOn = document.getElementById("toggle-cache").checked;
  const solOn = document.getElementById("toggle-sol").checked;

  // model_path / quant are derived from diffusion_model (hidden groups)

  const cacheGroup = document.getElementById("cache-group");
  cacheGroup.classList.toggle("disabled", !cacheOn);
  cacheGroup.querySelectorAll("input, select").forEach((el) => {
    el.disabled = !cacheOn;
  });

  const solGroup = document.getElementById("sol-group");
  solGroup.classList.toggle("disabled", !solOn);
  solGroup.querySelectorAll("select").forEach((el) => {
    el.disabled = !solOn;
  });
}

function syncButtons() {
  const runBtn = document.getElementById("btn-run");
  // Always allow queueing more runs — ComfyUI + our FIFO handle the rest
  runBtn.disabled = false;
  runBtn.classList.toggle("busy", state.busy);
  runBtn.textContent = state.busy ? "Queue another run" : "Run this config";
}

function wireForm() {
  const panel = document.getElementById("run-panel");
  panel.addEventListener("change", (e) => {
    if (e.target && e.target.id === "first_frame_file") {
      onFirstFrameFileChange(e);
      return;
    }
    stateFromForm();
    syncDisabled();
  });
  panel.addEventListener("input", (e) => {
    if (e.target.matches("input[type=number], textarea#prompt")) {
      stateFromForm();
    }
  });
  const ff = document.getElementById("first_frame_file");
  if (ff) {
    ff.addEventListener("change", onFirstFrameFileChange);
  }
}

// ---------------------------------------------------------------------------
// Run / Abort
// ---------------------------------------------------------------------------

async function runConfig() {
  stateFromForm();
  // Payload uses exact RunConfig field names; when cache on use selected cache type
  const payload = { ...state.config };
  if (payload.cache_enabled && payload.cache === "none") {
    payload.cache = "spectrum";
  }

  const r = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const j = await r.json();
      msg = j.error || JSON.stringify(j);
    } catch {
      try {
        msg = await r.text();
      } catch {
        /* ignore */
      }
    }
    alert(msg || "Run failed");
    return;
  }
  // Queued successfully — poll will show status=queued / running
  try {
    const body = await r.json();
    if (body.run_id) {
      // light feedback via status line
      const el = document.getElementById("status-line");
      if (el) {
        el.textContent = `Queued ${body.run_id} (depth ${body.queue_depth ?? "?"})`;
      }
    }
  } catch {
    /* ignore */
  }
  state.busy = true;
  syncButtons();
}

function abortRun() {
  fetch("/api/abort", { method: "POST" }).catch(() => {});
}

// ---------------------------------------------------------------------------
// Apply config from a past run
// ---------------------------------------------------------------------------

function applyConfigToPanel(cfg) {
  if (!cfg) return;
  const diffusionModel = cfg.diffusion_model || "";
  const inferred = diffusionModel
    ? inferLoader(diffusionModel)
    : {
        model_path: cfg.model_path || "safetensor",
        quant: cfg.quant || "nvfp4",
      };
  state.config = {
    model_path: inferred.model_path,
    quant: inferred.quant,
    diffusion_model: diffusionModel,
    first_frame: cfg.first_frame || DEFAULT_FIRST_FRAME,
    prompt: (cfg.prompt && String(cfg.prompt).trim()) || DEFAULT_PROMPT,
    aspect_ratio: cfg.aspect_ratio || DEFAULT_ASPECT_RATIO,
    turbo: !!cfg.turbo,
    rife: !!cfg.rife,
    upscaler: !!cfg.upscaler,
    clean_vram: !!cfg.clean_vram,
    cache_enabled:
      cfg.cache_enabled != null
        ? !!cfg.cache_enabled
        : cfg.cache != null && cfg.cache !== "none",
    cache: cfg.cache && cfg.cache !== "none" ? cfg.cache : "spectrum",
    cache_preset: cfg.cache_preset || "moderate",
    sol_attn: cfg.sol_attn != null ? !!cfg.sol_attn : true,
    sol_preset: cfg.sol_preset || "moderate",
    scheduler: cfg.scheduler || state.config.scheduler,
    sampler: cfg.sampler || state.config.sampler,
    steps: cfg.steps != null ? cfg.steps : 20,
    mp: cfg.mp != null ? cfg.mp : 0.5,
    duration_s: cfg.duration_s != null ? cfg.duration_s : 5,
    seed: cfg.seed != null ? cfg.seed : 42,
  };
  // Ensure selects include values
  if (state.options) {
    fillSelect("scheduler", state.options.schedulers, state.config.scheduler);
    fillSelect("sampler", state.options.samplers, state.config.sampler);
    const aspects = state.options.aspect_ratios || [];
    if (aspects.length) {
      fillSelect("aspect_ratio", aspects, state.config.aspect_ratio);
    }
    const models = state.options.diffusion_models || [];
    fillSelect("diffusion_model", models, state.config.diffusion_model);
  }
  formFromState();
}

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------

function renderStatus(data, runs) {
  const el = document.getElementById("status-line");
  const cur = data.current;
  let curText = "idle";
  if (cur) {
    const bits = [cur.phase || "?", cur.run_id || "?", cur.stage || "?"];
    if (cur.detail) bits.push(cur.detail);
    else if (cur.node_label) bits.push(cur.node_label);
    curText = bits.join(" / ");
  }
  el.textContent = `suite=${data.status || "?"} · ${curText} · updated ${data.updated_at || "—"}`;

  const best = findFastest(runs);
  document.getElementById("fastest").textContent = best
    ? `Fastest: ${fmtRunTime(best)} (${best.id})`
    : "";

  const busy = data.status === "running" || !!data.current;
  if (state.busy !== busy) {
    state.busy = busy;
    syncButtons();
  } else {
    state.busy = busy;
    syncButtons();
  }
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

function wireTabs() {
  document.querySelectorAll(".tabs [data-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      document.querySelectorAll(".tabs [data-tab]").forEach((b) => {
        b.classList.toggle("active", b === btn);
        b.setAttribute("aria-selected", b === btn ? "true" : "false");
      });
      document.querySelectorAll(".tab-panel").forEach((sec) => {
        sec.hidden = sec.id !== `tab-${tab}`;
      });
    });
  });
}

// ---------------------------------------------------------------------------
// List view
// ---------------------------------------------------------------------------

function renderList(runs) {
  const wrap = document.getElementById("tab-list");
  const excludedCount = runs.filter((r) => r.excluded).length;
  // Excluded runs are not shown anywhere in the UI
  const sorted = includedRuns(runs).slice().sort((a, b) => {
    const fa = a.finished_at || a.started_at || "";
    const fb = b.finished_at || b.started_at || "";
    if (fa !== fb) return fb.localeCompare(fa);
    return String(b.id || "").localeCompare(String(a.id || ""));
  });

  const key = sorted
    .map(
      (r) =>
        `${r.id}:${r.status}:${r.timed_s}:${r.sec_per_it}:${r.video_path || ""}:${r.rating ?? ""}:${expandedRunId || ""}`
    )
    .join("|") + `|ex:${excludedCount}`;
  if (key === lastListKey && wrap.dataset.ready === "1") return;
  lastListKey = key;

  if (!sorted.length) {
    wrap.innerHTML = `<div class="empty-msg">${
      excludedCount
        ? `No visible runs (${excludedCount} excluded).`
        : "No runs yet. Configure the panel and click Run."
    }</div>`;
    wrap.dataset.ready = "1";
    return;
  }

  let html = "";
  if (excludedCount) {
    html += `<p class="muted field-hint">${excludedCount} excluded run(s) hidden from all views.</p>`;
  }
  html += `<div class="table-wrap"><table class="list-table"><thead><tr>
    <th class="row-label">id</th>
    <th>status</th>
    <th>wall</th>
    <th>s/it</th>
    <th>rating</th>
    <th>config</th>
    <th>video</th>
    <th></th>
  </tr></thead><tbody>`;

  for (const r of sorted) {
    const cfg = r.config || {};
    const vid = r.video_path
      ? `<button type="button" class="linkish video-expand-btn" data-expand="${escapeHtml(r.id)}">video</button>`
      : "—";
    const wall = r.timed_s != null ? fmtSec(r.timed_s) : "—";
    const ratingOpts = ['<option value="">—</option>']
      .concat(
        Array.from({ length: 10 }, (_, i) => {
          const v = i + 1;
          const sel = r.rating === v ? " selected" : "";
          return `<option value="${v}"${sel}>${v}</option>`;
        })
      )
      .join("");
    html += `<tr class="clickable" data-run-id="${escapeHtml(r.id)}">
      <td class="row-label">${escapeHtml(r.id)}</td>
      <td><span class="chip ${escapeHtml(r.status || "queued")}">${escapeHtml(r.status || "queued")}</span></td>
      <td>${escapeHtml(wall)}</td>
      <td title="seconds per sampler step (same unit as Comfy tqdm)">${escapeHtml(fmtSecPerIt(r))}</td>
      <td><select class="rating-select" data-rate="${escapeHtml(r.id)}" title="Quality 1–10">${ratingOpts}</select></td>
      <td class="chips-cell"><div class="chips">${configChips(cfg)}</div></td>
      <td>${vid}</td>
      <td class="row-actions">
        <button type="button" class="compact apply-btn" data-apply="${escapeHtml(r.id)}">Apply</button>
        <button type="button" class="compact danger" data-exclude="${escapeHtml(r.id)}" title="Hide this run from all views">Exclude</button>
      </td>
    </tr>`;
    if (expandedRunId === r.id && r.video_path) {
      html += `<tr class="video-expand-row"><td colspan="8">
        <div class="inline-video-wrap">
          <video src="/${escapeHtml(r.video_path)}" controls autoplay playsinline></video>
          <button type="button" class="compact" data-collapse="${escapeHtml(r.id)}">Collapse</button>
        </div>
      </td></tr>`;
    }
  }
  html += "</tbody></table></div>";
  wrap.innerHTML = html;
  wrap.dataset.ready = "1";

  wrap.querySelectorAll("tr[data-run-id]").forEach((tr) => {
    tr.addEventListener("click", (e) => {
      if (e.target.closest("a, button, select")) return;
      openDetail(tr.dataset.runId);
    });
  });
  wrap.querySelectorAll("[data-apply]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const run = runIndex.get(btn.dataset.apply);
      if (run) applyConfigToPanel(run.config);
    });
  });
  wrap.querySelectorAll("[data-exclude]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      submitExclude(btn.dataset.exclude, true);
    });
  });
  wrap.querySelectorAll("[data-expand]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const id = btn.dataset.expand;
      expandedRunId = expandedRunId === id ? null : id;
      lastListKey = "";
      renderList([...runIndex.values()]);
    });
  });
  wrap.querySelectorAll("[data-collapse]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      expandedRunId = null;
      lastListKey = "";
      renderList([...runIndex.values()]);
    });
  });
  wrap.querySelectorAll("select[data-rate]").forEach((sel) => {
    sel.addEventListener("change", (e) => {
      e.stopPropagation();
      submitRating(sel.dataset.rate, sel.value === "" ? null : Number(sel.value));
    });
    sel.addEventListener("click", (e) => e.stopPropagation());
  });
}

async function submitExclude(runId, excluded) {
  try {
    const r = await fetch("/api/exclude", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId, excluded: !!excluded }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      alert(err.error || "Failed to update exclude");
      return;
    }
    const run = runIndex.get(runId);
    if (run) run.excluded = !!excluded;
    // Drop from compare slots if excluded
    if (excluded) {
      state.compareIds = state.compareIds.filter((id) => id !== runId);
      syncCompareToolbar();
    }
    lastListKey = "";
    lastScoresKey = "";
    lastHeatmapKey = "";
    lastGalleryKey = "";
    const g = document.getElementById("gallery");
    if (g) g.dataset.structureKey = "";
    const runs = [...runIndex.values()];
    renderList(runs);
    renderHeatmap(runs);
    renderGallery(runs);
    renderScores(runs);
  } catch (e) {
    alert(String(e.message || e));
  }
}

async function submitRating(runId, rating) {
  try {
    const r = await fetch("/api/rate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId, rating }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      alert(err.error || "Failed to save rating");
      return;
    }
    const run = runIndex.get(runId);
    if (run) run.rating = rating;
    lastListKey = "";
    lastScoresKey = "";
    lastGalleryKey = "";
    const g = document.getElementById("gallery");
    if (g) g.dataset.structureKey = "";
    renderScores([...runIndex.values()]);
  } catch (e) {
    alert(String(e.message || e));
  }
}

function openVideoExpand(runId) {
  const run = runIndex.get(runId);
  const dlg = document.getElementById("video-expand");
  const body = document.getElementById("video-expand-body");
  const title = document.getElementById("video-expand-title");
  if (!run || !run.video_path) return;
  title.textContent = run.id;
  body.innerHTML = `<video src="/${escapeHtml(run.video_path)}" controls autoplay playsinline></video>`;
  dlg.showModal();
}

// ---------------------------------------------------------------------------
// Smart heatmap
// ---------------------------------------------------------------------------

function inferAxes(runs) {
  const done = runs.filter((r) => r.status === "done" && r.timed_s != null);
  const varying = [];
  for (const fn of AXIS_PRIORITY) {
    const vals = new Set(done.map((r) => fn(r.config || {})));
    if (vals.size >= 2) varying.push(fn);
    if (varying.length === 2) break;
  }
  return varying;
}

function axisLabel(fn, cfg) {
  return String(fn(cfg || {}));
}

function renderHeatmap(runs) {
  const wrap = document.getElementById("tab-heatmap");
  const done = includedRuns(runs).filter(
    (r) => r.status === "done" && r.timed_s != null
  );
  const key = runs
    .map((r) => `${r.id}:${r.status}:${r.timed_s}:${r.excluded ? 1 : 0}`)
    .join("|");
  if (key === lastHeatmapKey && wrap.dataset.ready === "1") return;
  lastHeatmapKey = key;

  if (!done.length) {
    wrap.innerHTML = `<div class="empty-msg">Need at least one completed timed run for heatmap.</div>`;
    wrap.dataset.ready = "1";
    return;
  }

  const axes = inferAxes(runs);
  const best = findFastest(runs);
  const bestId = best ? best.id : null;

  if (axes.length === 0) {
    // All same config — single column list of best
    let html = `<div class="table-wrap"><table><thead><tr>
      <th class="row-label">run</th><th>timed</th>
    </tr></thead><tbody>`;
    for (const r of done.sort((a, b) => a.timed_s - b.timed_s)) {
      const classes = ["cell", "done"];
      if (r.id === bestId) classes.push("best");
      html += `<tr>
        <td class="row-label">${escapeHtml(r.id)}</td>
        <td class="${classes.join(" ")}" data-run-id="${escapeHtml(r.id)}">${escapeHtml(fmtRunTime(r))}</td>
      </tr>`;
    }
    html += "</tbody></table></div>";
    wrap.innerHTML = html;
    wrap.dataset.ready = "1";
    bindCellClicks(wrap);
    return;
  }

  if (axes.length === 1) {
    const rowFn = axes[0];
    const rows = [];
    const rowSet = new Set();
    const grid = new Map(); // row -> best run
    for (const r of done) {
      const row = axisLabel(rowFn, r.config);
      if (!rowSet.has(row)) {
        rowSet.add(row);
        rows.push(row);
      }
      const prev = grid.get(row);
      if (!prev || r.timed_s < prev.timed_s) grid.set(row, r);
    }
    rows.sort();
    let html = `<div class="heatmap-meta muted">Axes: ${escapeHtml(describeAxis(rowFn))}</div>`;
    html += `<div class="table-wrap"><table><thead><tr>
      <th class="row-label">${escapeHtml(describeAxis(rowFn))}</th><th>best timed</th>
    </tr></thead><tbody>`;
    for (const row of rows) {
      const run = grid.get(row);
      html += `<tr><td class="row-label">${escapeHtml(row)}</td>${cellHtml(run, bestId)}</tr>`;
    }
    html += "</tbody></table></div>";
    wrap.innerHTML = html;
    wrap.dataset.ready = "1";
    bindCellClicks(wrap);
    return;
  }

  // 2 axes
  const [rowFn, colFn] = axes;
  const rows = [];
  const cols = [];
  const rowSet = new Set();
  const colSet = new Set();
  const grid = new Map(); // `${row}|${col}` -> best run

  for (const r of done) {
    const row = axisLabel(rowFn, r.config);
    const col = axisLabel(colFn, r.config);
    if (!rowSet.has(row)) {
      rowSet.add(row);
      rows.push(row);
    }
    if (!colSet.has(col)) {
      colSet.add(col);
      cols.push(col);
    }
    const k = `${row}|${col}`;
    const prev = grid.get(k);
    if (!prev || r.timed_s < prev.timed_s) grid.set(k, r);
  }
  rows.sort();
  cols.sort();

  let html = `<div class="heatmap-meta muted">Axes: ${escapeHtml(describeAxis(rowFn))} × ${escapeHtml(describeAxis(colFn))} (best timed_s per cell)</div>`;
  html += `<div class="table-wrap"><table><thead><tr><th class="row-label"></th>`;
  for (const c of cols) {
    html += `<th>${escapeHtml(c)}</th>`;
  }
  html += "</tr></thead><tbody>";
  for (const row of rows) {
    html += `<tr><td class="row-label">${escapeHtml(row)}</td>`;
    for (const col of cols) {
      html += cellHtml(grid.get(`${row}|${col}`), bestId);
    }
    html += "</tr>";
  }
  html += "</tbody></table></div>";
  wrap.innerHTML = html;
  wrap.dataset.ready = "1";
  bindCellClicks(wrap);
}

function describeAxis(fn) {
  // Identify by sampling a probe config
  const probes = [
    [{ cache_enabled: true, cache: "spectrum" }, { cache_enabled: true, cache: "easy" }, "cache"],
    [{ model_path: "gguf" }, { model_path: "safetensor", quant: "nvfp4" }, "model/quant"],
    [{ sol_attn: true }, { sol_attn: false }, "sol"],
    [{ turbo: true }, { turbo: false }, "turbo"],
    [{ scheduler: "a" }, { scheduler: "b" }, "scheduler"],
    [{ sampler: "a" }, { sampler: "b" }, "sampler"],
    [{ steps: 1 }, { steps: 2 }, "steps"],
    [{ cache_preset: "a" }, { cache_preset: "b" }, "cache_preset"],
    [{ sol_preset: "a" }, { sol_preset: "b" }, "sol_preset"],
  ];
  for (const [a, b, name] of probes) {
    if (fn(a) !== fn(b)) return name;
  }
  return "axis";
}

function cellHtml(run, bestId) {
  if (!run) {
    return `<td class="cell empty">—</td>`;
  }
  const classes = ["cell", run.status || "queued"];
  if (run.id === bestId) classes.push("best");
  let content;
  if (run.status === "done" && run.timed_s != null) {
    content = fmtRunTime(run);
  } else {
    content = `<span class="chip ${escapeHtml(run.status || "queued")}">${escapeHtml(run.status || "queued")}</span>`;
  }
  const title =
    run.sec_per_it != null && Number(run.sec_per_it) >= 0.05
      ? `${run.id} · ${fmtRunTime(run)}`
      : run.id;
  return `<td class="${classes.join(" ")}" data-run-id="${escapeHtml(run.id)}" title="${escapeHtml(title)}">${content}</td>`;
}

function bindCellClicks(wrap) {
  wrap.querySelectorAll("td.cell[data-run-id]").forEach((td) => {
    td.addEventListener("click", () => openDetail(td.dataset.runId));
  });
}

// ---------------------------------------------------------------------------
// Gallery (incremental — never rewrite <video> for existing cards)
// Compare filter: selected axes may differ; everything else must match.
// ---------------------------------------------------------------------------

function fieldValue(field, cfg) {
  return field.get(cfg || {});
}

/** Full config fingerprint (all compare fields) for duplicate detection. */
function fullConfigFingerprint(cfg) {
  return GALLERY_COMPARE_FIELDS.map(
    (f) => `${f.key}=${fieldValue(f, cfg || {})}`
  ).join("|");
}

/**
 * Non-excluded runs that already used the same settings as *cfg*.
 * Prefers completed runs; also flags queued/timing duplicates.
 */
function findMatchingRuns(cfg, allRuns) {
  const fp = fullConfigFingerprint(cfg);
  const matches = includedRuns(allRuns || [...runIndex.values()]).filter(
    (r) => fullConfigFingerprint(r.config || {}) === fp
  );
  return matches;
}

function updateDuplicateHint() {
  const el = document.getElementById("dup-config-hint");
  if (!el) return;
  const matches = findMatchingRuns(state.config);
  if (!matches.length) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  const done = matches.filter((r) => r.status === "done");
  const pending = matches.filter((r) =>
    ["queued", "warmup", "timing"].includes(r.status)
  );
  const ids = matches
    .slice(0, 4)
    .map((r) => r.id)
    .join(", ");
  const more = matches.length > 4 ? ` (+${matches.length - 4} more)` : "";
  let msg = "";
  if (done.length && pending.length) {
    msg = `Info: this exact setup was already run (${done.length} done, ${pending.length} in queue/running). Examples: ${ids}${more}. You can still queue another.`;
  } else if (done.length) {
    msg = `Info: this exact setup was already benchmarked (${done.length} run${done.length === 1 ? "" : "s"}). Examples: ${ids}${more}. You can still queue another.`;
  } else {
    msg = `Info: this exact setup is already queued or running (${pending.length}). Examples: ${ids}${more}.`;
  }
  el.textContent = msg;
  el.hidden = false;
}

function fixedFingerprint(cfg, varyKeys) {
  const parts = [];
  for (const f of GALLERY_COMPARE_FIELDS) {
    if (varyKeys.has(f.key)) continue;
    parts.push(`${f.key}=${fieldValue(f, cfg)}`);
  }
  return parts.join("|");
}

function varySignature(cfg, varyKeys) {
  const parts = [];
  for (const f of GALLERY_COMPARE_FIELDS) {
    if (!varyKeys.has(f.key)) continue;
    parts.push(`${f.key}=${fieldValue(f, cfg)}`);
  }
  return parts.join("|");
}

/**
 * Group runs that share all non-vary settings. Only groups with 2+ runs
 * (true comparison sets) are returned when any vary axis is selected.
 * @returns {{ groups: { fixedKey: string, fixedLabel: string, runs: object[] }[], status: string }}
 */
function galleryCompareGroups(doneRuns, varyKeys) {
  if (!varyKeys.size) {
    return {
      groups: [
        {
          fixedKey: "all",
          fixedLabel: "",
          runs: doneRuns.slice(),
        },
      ],
      status: `${doneRuns.length} video(s) · no compare filter (showing all)`,
    };
  }

  /** @type {Map<string, object[]>} */
  const buckets = new Map();
  for (const r of doneRuns) {
    const k = fixedFingerprint(r.config || {}, varyKeys);
    if (!buckets.has(k)) buckets.set(k, []);
    buckets.get(k).push(r);
  }

  const axisLabels = GALLERY_COMPARE_FIELDS.filter((f) => varyKeys.has(f.key)).map(
    (f) => f.label
  );
  const groups = [];
  for (const [fixedKey, runs] of buckets) {
    if (runs.length < 2) continue;
    // Must actually differ on at least one allowed axis (otherwise not interesting)
    const sigs = new Set(runs.map((r) => varySignature(r.config || {}, varyKeys)));
    if (sigs.size < 2) continue;

    const fixedLabel = GALLERY_COMPARE_FIELDS.filter((f) => !varyKeys.has(f.key))
      .map((f) => `${f.label}=${fieldValue(f, runs[0].config || {})}`)
      .join(" · ");

    runs.sort((a, b) => {
      // Order by vary signature then time
      const sa = varySignature(a.config || {}, varyKeys);
      const sb = varySignature(b.config || {}, varyKeys);
      if (sa !== sb) return sa.localeCompare(sb);
      return (a.timed_s ?? 1e12) - (b.timed_s ?? 1e12);
    });

    groups.push({ fixedKey, fixedLabel, runs });
  }

  groups.sort((a, b) => b.runs.length - a.runs.length);

  const nRuns = groups.reduce((s, g) => s + g.runs.length, 0);
  const status = groups.length
    ? `${nRuns} video(s) in ${groups.length} set(s) · only ${axisLabels.join(" + ")} differ`
    : `No sets where only ${axisLabels.join(" + ")} differ (need 2+ matching runs)`;

  return { groups, status };
}

function wireGalleryFilters() {
  if (galleryFiltersWired) return;
  const host = document.getElementById("gallery-vary-axes");
  if (!host) return;
  galleryFiltersWired = true;
  host.innerHTML = "";
  for (const f of GALLERY_COMPARE_FIELDS) {
    const label = document.createElement("label");
    label.className = "toggle-chip";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = f.key;
    input.dataset.varyKey = f.key;
    input.checked = state.galleryVaryAxes.has(f.key);
    input.addEventListener("change", () => {
      if (input.checked) state.galleryVaryAxes.add(f.key);
      else state.galleryVaryAxes.delete(f.key);
      // Force full gallery rebuild with new filter
      const g = document.getElementById("gallery");
      if (g) g.dataset.structureKey = "";
      lastGalleryKey = "";
      // Re-render from last known runs via a soft tick path
      const runs = [...runIndex.values()];
      renderGallery(runs);
    });
    const span = document.createElement("span");
    span.textContent = f.label;
    label.appendChild(input);
    label.appendChild(span);
    host.appendChild(label);
  }
}

function updateGalleryCardMeta(card, r) {
  const meta = card.querySelector(".meta");
  if (!meta) return;
  const vary = state.galleryVaryAxes;
  let varyBits = "";
  if (vary.size) {
    const parts = GALLERY_COMPARE_FIELDS.filter((f) => vary.has(f.key)).map(
      (f) => `${f.label}=${fieldValue(f, r.config || {})}`
    );
    varyBits = `<div class="chips">${parts
      .map((p) => `<span class="chip">${escapeHtml(p)}</span>`)
      .join("")}</div>`;
  }
  const inCompare = state.compareIds.includes(r.id);
  const slot = state.compareIds[0] === r.id ? "A" : state.compareIds[1] === r.id ? "B" : "";
  const ratingOpts = ['<option value="">rate —</option>']
    .concat(
      Array.from({ length: 10 }, (_, i) => {
        const v = i + 1;
        const sel = r.rating === v ? " selected" : "";
        return `<option value="${v}"${sel}>${v}</option>`;
      })
    )
    .join("");
  meta.innerHTML = `
        <strong>${escapeHtml(r.id)}</strong>
        ${slot ? `<span class="chip compare-mark">Compare ${slot}</span>` : ""}
        <br>
        ${escapeHtml(fmtRunTime(r))}
        ${r.rating != null ? ` · ★${r.rating}` : ""}
        ${varyBits}
        <div class="chips">${configChips(r.config)}</div>
        <div class="card-actions">
          <select class="rating-select" data-rate="${escapeHtml(r.id)}">${ratingOpts}</select>
          <button type="button" class="compact ${inCompare ? "primary" : ""}" data-compare-toggle="${escapeHtml(r.id)}">
            ${inCompare ? "Unpick" : "Pick compare"}
          </button>
          <button type="button" class="compact danger" data-exclude="${escapeHtml(r.id)}" data-excluded="0">Exclude</button>
        </div>`;
  meta.querySelectorAll("select[data-rate]").forEach((sel) => {
    sel.addEventListener("change", (e) => {
      e.stopPropagation();
      submitRating(sel.dataset.rate, sel.value === "" ? null : Number(sel.value));
    });
    sel.addEventListener("click", (e) => e.stopPropagation());
  });
  meta.querySelectorAll("[data-compare-toggle]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleComparePick(btn.dataset.compareToggle);
    });
  });
  meta.querySelectorAll("[data-exclude]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      submitExclude(btn.dataset.exclude, true);
    });
  });
}

function makeGalleryCard(r) {
  const article = document.createElement("article");
  article.className = "card";
  article.dataset.runId = r.id;
  if (state.compareIds.includes(r.id)) article.classList.add("compare-picked");

  const video = document.createElement("video");
  video.controls = true;
  video.preload = "metadata";
  video.src = `/${r.video_path}`;
  video.dataset.src = r.video_path;

  const meta = document.createElement("div");
  meta.className = "meta";
  article.appendChild(video);
  article.appendChild(meta);
  updateGalleryCardMeta(article, r);
  article.addEventListener("click", (e) => {
    if (e.target.tagName === "VIDEO") return;
    if (e.target.closest("button, select")) return;
    openDetail(article.dataset.runId);
  });
  return article;
}

function toggleComparePick(runId) {
  const idx = state.compareIds.indexOf(runId);
  if (idx >= 0) {
    state.compareIds.splice(idx, 1);
  } else {
    if (state.compareIds.length >= 2) {
      state.compareIds.shift();
    }
    state.compareIds.push(runId);
  }
  syncCompareToolbar();
  const g = document.getElementById("gallery");
  if (g) g.dataset.structureKey = "";
  lastGalleryKey = "";
  renderGallery([...runIndex.values()]);
}

function syncCompareToolbar() {
  const a = state.compareIds[0];
  const b = state.compareIds[1];
  const elA = document.getElementById("compare-slot-a");
  const elB = document.getElementById("compare-slot-b");
  const play = document.getElementById("btn-compare-play");
  if (elA) elA.textContent = a ? `A: ${a}` : "A: —";
  if (elB) elB.textContent = b ? `B: ${b}` : "B: —";
  if (play) play.disabled = !(a && b);
}

/** Sequential A→B compare state (no dual-sync — avoids seek loops). */
const compareSeq = {
  active: null, // "a" | "b" | null
  onEndedA: null,
  onEndedB: null,
};

function compareVideos() {
  return {
    a: document.getElementById("compare-video-a"),
    b: document.getElementById("compare-video-b"),
    paneA: document.getElementById("compare-pane-a"),
    paneB: document.getElementById("compare-pane-b"),
    status: document.getElementById("compare-seq-status"),
  };
}

function setCompareActivePane(which) {
  const { paneA, paneB } = compareVideos();
  if (paneA) paneA.classList.toggle("playing", which === "a");
  if (paneB) paneB.classList.toggle("playing", which === "b");
}

function setCompareStatus(text) {
  const { status } = compareVideos();
  if (status) status.textContent = text || "";
}

function detachCompareEndedHandlers() {
  const { a, b } = compareVideos();
  if (a && compareSeq.onEndedA) {
    a.removeEventListener("ended", compareSeq.onEndedA);
  }
  if (b && compareSeq.onEndedB) {
    b.removeEventListener("ended", compareSeq.onEndedB);
  }
  compareSeq.onEndedA = null;
  compareSeq.onEndedB = null;
}

function stopComparePlayback() {
  const { a, b } = compareVideos();
  if (a) {
    a.pause();
  }
  if (b) {
    b.pause();
  }
  compareSeq.active = null;
  setCompareActivePane(null);
}

function resetCompareVideosToStart() {
  const { a, b } = compareVideos();
  if (a) {
    try {
      a.pause();
      a.currentTime = 0;
    } catch {
      /* ignore */
    }
  }
  if (b) {
    try {
      b.pause();
      b.currentTime = 0;
    } catch {
      /* ignore */
    }
  }
}

function playCompareSequence() {
  const { a, b } = compareVideos();
  if (!a || !b || !a.src || !b.src) return;

  detachCompareEndedHandlers();
  stopComparePlayback();
  resetCompareVideosToStart();

  compareSeq.onEndedA = () => {
    if (compareSeq.active !== "a") return;
    a.pause();
    try {
      b.currentTime = 0;
    } catch {
      /* ignore */
    }
    compareSeq.active = "b";
    setCompareActivePane("b");
    setCompareStatus("Playing B…");
    b.play().catch(() => setCompareStatus("Could not play B"));
  };
  compareSeq.onEndedB = () => {
    if (compareSeq.active !== "b") return;
    b.pause();
    compareSeq.active = null;
    setCompareActivePane(null);
    setCompareStatus("Done — click Play A → B to watch again");
  };

  a.addEventListener("ended", compareSeq.onEndedA);
  b.addEventListener("ended", compareSeq.onEndedB);

  compareSeq.active = "a";
  setCompareActivePane("a");
  setCompareStatus("Playing A…");
  a.play().catch(() => setCompareStatus("Could not play A"));
}

function pauseCompareSequence() {
  const { a, b } = compareVideos();
  if (a) a.pause();
  if (b) b.pause();
  if (compareSeq.active) {
    setCompareStatus(
      `Paused on ${compareSeq.active.toUpperCase()} — click Play A → B to restart, or use Pause then play that pane’s native control if needed`
    );
  }
}

function wireCompareControls() {
  const play = document.getElementById("btn-compare-play");
  const clear = document.getElementById("btn-compare-clear");
  const seqBtn = document.getElementById("btn-compare-seq");
  const pauseBtn = document.getElementById("btn-compare-pause");
  if (play) {
    play.addEventListener("click", () => openCompareDialog());
  }
  if (clear) {
    clear.addEventListener("click", () => {
      state.compareIds = [];
      syncCompareToolbar();
      const g = document.getElementById("gallery");
      if (g) g.dataset.structureKey = "";
      lastGalleryKey = "";
      renderGallery([...runIndex.values()]);
    });
  }
  if (seqBtn) {
    seqBtn.addEventListener("click", () => playCompareSequence());
  }
  if (pauseBtn) {
    pauseBtn.addEventListener("click", () => pauseCompareSequence());
  }
  const dlg = document.getElementById("compare-dialog");
  if (dlg) {
    dlg.addEventListener("close", () => {
      detachCompareEndedHandlers();
      stopComparePlayback();
      const { a, b } = compareVideos();
      if (a) {
        a.removeAttribute("src");
        a.load();
      }
      if (b) {
        b.removeAttribute("src");
        b.load();
      }
      setCompareStatus("");
      setCompareActivePane(null);
    });
  }
  syncCompareToolbar();
}

function openCompareDialog() {
  const aId = state.compareIds[0];
  const bId = state.compareIds[1];
  const ra = runIndex.get(aId);
  const rb = runIndex.get(bId);
  if (!ra?.video_path || !rb?.video_path) {
    alert("Pick two runs that have videos.");
    return;
  }
  const { a, b } = compareVideos();
  const la = document.getElementById("compare-label-a");
  const lb = document.getElementById("compare-label-b");
  if (la) la.textContent = `A · ${aId}${ra.rating != null ? ` · ★${ra.rating}` : ""}`;
  if (lb) lb.textContent = `B · ${bId}${rb.rating != null ? ` · ★${rb.rating}` : ""}`;

  detachCompareEndedHandlers();
  stopComparePlayback();

  // Bust cache slightly so re-open always reloads cleanly
  const bust = `t=${Date.now()}`;
  a.src = `/${ra.video_path}?${bust}`;
  b.src = `/${rb.video_path}?${bust}`;
  a.load();
  b.load();

  document.getElementById("compare-dialog").showModal();
  setCompareStatus("Ready — click Play A → B");
  // Auto-start sequence once both can play
  const tryStart = () => {
    if (a.readyState >= 2 && b.readyState >= 2) {
      playCompareSequence();
      return;
    }
    setTimeout(tryStart, 100);
  };
  tryStart();
}

function renderGallery(allRuns) {
  wireGalleryFilters();
  const done = includedRuns(allRuns)
    .filter((r) => r.video_path)
    .sort((a, b) => (b.finished_at || "").localeCompare(a.finished_at || ""));
  const g = document.getElementById("gallery");
  const statusEl = document.getElementById("gallery-filter-status");
  const varyKeys = state.galleryVaryAxes;
  const varyKey = [...varyKeys].sort().join(",");
  const { groups, status } = galleryCompareGroups(done, varyKeys);
  if (statusEl) statusEl.textContent = status;

  const flatIds = groups.flatMap((gr) => gr.runs.map((r) => r.id));
  const compareKey = state.compareIds.join(",");
  const structureKey = `${varyKey}||${compareKey}||${groups
    .map((gr) => gr.fixedKey + ":" + gr.runs.map((r) => `${r.id}:${r.video_path}`).join(","))
    .join(";")}`;
  const metaKey = groups
    .flatMap((gr) => gr.runs)
    .map((r) => `${r.id}:${r.timed_s}:${r.sec_per_it}:${r.rating ?? ""}`)
    .join("|") + `|c:${compareKey}`;

  if (!done.length) {
    if (g.dataset.structureKey !== "empty") {
      g.innerHTML = `<div class="empty-msg">No videos yet.</div>`;
      g.dataset.structureKey = "empty";
      lastGalleryKey = "";
    }
    return;
  }

  if (!flatIds.length && varyKeys.size) {
    if (g.dataset.structureKey !== "filtered-empty") {
      g.innerHTML = `<div class="empty-msg">${escapeHtml(status)}</div>`;
      g.dataset.structureKey = "filtered-empty";
      lastGalleryKey = "";
    }
    return;
  }

  if (g.dataset.structureKey !== structureKey) {
    g.innerHTML = "";
    g.dataset.structureKey = structureKey;

    if (!varyKeys.size) {
      // Flat grid — all videos
      for (const r of groups[0].runs) {
        g.appendChild(makeGalleryCard(r));
      }
    } else {
      for (const gr of groups) {
        const section = document.createElement("div");
        section.className = "gallery-group";
        const header = document.createElement("div");
        header.className = "gallery-group-header";
        header.innerHTML = `<span class="title">Matched set (${gr.runs.length})</span>
          <span class="muted field-hint">${escapeHtml(gr.fixedLabel)}</span>`;
        const grid = document.createElement("div");
        grid.className = "gallery";
        for (const r of gr.runs) {
          grid.appendChild(makeGalleryCard(r));
        }
        section.appendChild(header);
        section.appendChild(grid);
        g.appendChild(section);
      }
    }
    lastGalleryKey = metaKey;
    return;
  }

  if (metaKey === lastGalleryKey) return;
  lastGalleryKey = metaKey;
  // Same structure: update meta only (preserve <video>)
  const cards = [...g.querySelectorAll(".card")];
  for (const r of groups.flatMap((gr) => gr.runs)) {
    const card = cards.find((el) => el.dataset.runId === r.id);
    if (card) updateGalleryCardMeta(card, r);
  }
}

// ---------------------------------------------------------------------------
// Scores tab — average rating by setting value
// ---------------------------------------------------------------------------

function renderScores(runs) {
  const wrap = document.getElementById("tab-scores");
  if (!wrap) return;
  const rated = includedRuns(runs).filter(
    (r) => r.rating != null && Number(r.rating) >= 1 && Number(r.rating) <= 10
  );
  const key =
    rated.map((r) => `${r.id}:${r.rating}`).sort().join("|") +
    "|" +
    runs.filter((r) => r.excluded).map((r) => r.id).join(",");
  if (key === lastScoresKey && wrap.dataset.ready === "1") return;
  lastScoresKey = key;

  if (!rated.length) {
    wrap.innerHTML = `<div class="empty-msg">
      No ratings yet. Rate runs 1–10 in the List or Gallery tabs.
      This board averages scores per setting value (e.g. which scheduler tends higher)
      so you can see what lifts or hurts quality — not a rating of a single knob alone.
    </div>`;
    wrap.dataset.ready = "1";
    return;
  }

  // For each dimension, average rating by discrete value
  let html = `<p class="muted field-hint">
    Based on <strong>${rated.length}</strong> rated run(s).
    Each table shows mean ★ for that setting’s values across runs (other settings still vary).
  </p>`;

  for (const field of GALLERY_COMPARE_FIELDS) {
    /** @type {Map<string, number[]>} */
    const buckets = new Map();
    for (const r of rated) {
      const v = fieldValue(field, r.config || {}) || "(empty)";
      if (!buckets.has(v)) buckets.set(v, []);
      buckets.get(v).push(Number(r.rating));
    }
    if (buckets.size === 0) continue;
    const rows = [...buckets.entries()]
      .map(([val, scores]) => {
        const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
        return { val, avg, n: scores.length, min: Math.min(...scores), max: Math.max(...scores) };
      })
      .sort((a, b) => b.avg - a.avg || b.n - a.n);

    const globalAvg =
      rated.reduce((s, r) => s + Number(r.rating), 0) / rated.length;

    html += `<section class="score-block">
      <h3 class="score-dim">${escapeHtml(field.label)}</h3>
      <div class="table-wrap"><table class="list-table score-table">
        <thead><tr>
          <th>value</th><th>avg ★</th><th>n</th><th>min</th><th>max</th><th>vs mean</th>
        </tr></thead><tbody>`;
    for (const row of rows) {
      const delta = row.avg - globalAvg;
      const deltaStr = (delta >= 0 ? "+" : "") + delta.toFixed(2);
      const cls = delta > 0.15 ? "score-up" : delta < -0.15 ? "score-down" : "";
      html += `<tr>
        <td class="row-label">${escapeHtml(row.val)}</td>
        <td><strong>${row.avg.toFixed(2)}</strong></td>
        <td>${row.n}</td>
        <td>${row.min}</td>
        <td>${row.max}</td>
        <td class="${cls}">${deltaStr}</td>
      </tr>`;
    }
    html += `</tbody></table></div></section>`;
  }

  wrap.innerHTML = html;
  wrap.dataset.ready = "1";
}

// ---------------------------------------------------------------------------
// Detail dialog
// ---------------------------------------------------------------------------

function openDetail(runId) {
  const run = runIndex.get(runId);
  detailRunId = runId;
  const body = document.getElementById("detail-body");
  const applyBtn = document.getElementById("btn-apply-config");
  if (!run) {
    body.innerHTML = `<p class="muted">Run ${escapeHtml(runId)} not found.</p>`;
    applyBtn.hidden = true;
    document.getElementById("detail").showModal();
    return;
  }
  applyBtn.hidden = false;
  const cfg = run.config || {};
  const video = run.video_path
    ? `<video src="/${escapeHtml(run.video_path)}" controls preload="metadata"></video>`
    : `<p class="muted">No video yet.</p>`;
  const ratingOpts = ['<option value="">—</option>']
    .concat(
      Array.from({ length: 10 }, (_, i) => {
        const v = i + 1;
        const sel = run.rating === v ? " selected" : "";
        return `<option value="${v}"${sel}>${v}</option>`;
      })
    )
    .join("");
  if (run.excluded) {
    // Excluded runs are not shown in the UI; close if opened somehow
    body.innerHTML = `<p class="muted">This run is excluded and hidden from the UI.</p>`;
    applyBtn.hidden = true;
    document.getElementById("detail").showModal();
    return;
  }
  body.innerHTML = `
    <h3>${escapeHtml(run.id)}</h3>
    <div class="kv">
      phase=<span>${escapeHtml(run.phase || "?")}</span>
      · status=<span>${escapeHtml(run.status || "?")}</span>
      · timed=<span>${escapeHtml(run.timed_s != null ? fmtSec(run.timed_s) : "—")}</span>
      · s/it=<span>${escapeHtml(fmtSecPerIt(run))}</span>
      · rating=
      <select id="detail-rating" class="rating-select">${ratingOpts}</select>
      ${run.warmup_s != null ? `· warmup=<span>${fmtSec(run.warmup_s)}</span> (legacy)` : ""}
      ${run.graph_cache_cleared != null ? `· graph_clear=<span>${run.graph_cache_cleared}</span>` : ""}
      ${run.sampler_cached != null ? `· sampler_cached=<span>${run.sampler_cached}</span>` : ""}
    </div>
    <div class="chips">${configChips(cfg)}</div>
    <p class="card-actions">
      <button type="button" id="detail-exclude" class="compact danger">Exclude from results</button>
    </p>
    ${video}
    ${run.error ? `<p class="kv" style="color:var(--fail)">error: <span>${escapeHtml(run.error)}</span></p>` : ""}
    <pre>${escapeHtml(JSON.stringify(run, null, 2))}</pre>
  `;
  const rateSel = document.getElementById("detail-rating");
  if (rateSel) {
    rateSel.addEventListener("change", () => {
      submitRating(run.id, rateSel.value === "" ? null : Number(rateSel.value));
    });
  }
  const exBtn = document.getElementById("detail-exclude");
  if (exBtn) {
    exBtn.addEventListener("click", () => {
      submitExclude(run.id, true).then(() => {
        document.getElementById("detail").close();
      });
    });
  }
  document.getElementById("detail").showModal();
}

// ---------------------------------------------------------------------------
// Poll loop
// ---------------------------------------------------------------------------

async function tick() {
  try {
    const data = await fetchResults();
    const runs = collectRuns(data);
    indexRuns(runs);
    renderStatus(data, runs);
    renderList(runs);
    renderHeatmap(runs);
    renderGallery(runs);
    renderScores(runs);
    updateDuplicateHint();
  } catch (e) {
    document.getElementById("status-line").textContent =
      `Waiting for results… (${e.message})`;
  }
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

function boot() {
  wireForm();
  wireTabs();
  wireGalleryFilters();
  wireCompareControls();
  formFromState();
  syncButtons();

  document.getElementById("btn-run").addEventListener("click", () => {
    runConfig().catch((e) => alert(e.message || String(e)));
  });
  document.getElementById("btn-abort").addEventListener("click", abortRun);
  document.getElementById("btn-abort-header").addEventListener("click", abortRun);
  document.getElementById("btn-apply-config").addEventListener("click", () => {
    const run = detailRunId ? runIndex.get(detailRunId) : null;
    if (run) {
      applyConfigToPanel(run.config);
      document.getElementById("detail").close();
    }
  });

  loadOptions()
    .then(() => tick())
    .catch(() => tick());
  setInterval(tick, POLL_MS);
}

boot();
