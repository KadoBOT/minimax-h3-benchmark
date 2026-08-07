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
  if (n.endsWith(".gguf")) return { model_path: "gguf", quant: "nvfp4" };
  // INT4Q packs load via standard UNETLoader (not OTUNet) — matches Music Suite.
  if (n.includes("int4q")) return { model_path: "safetensor", quant: "nvfp4" };
  if (["convrot", "mixed", "w8a8"].some((t) => n.includes(t))) {
    return { model_path: "safetensor", quant: "int8" };
  }
  if (n.includes("int8") && !n.includes("nvfp4")) {
    return { model_path: "safetensor", quant: "int8" };
  }
  return { model_path: "safetensor", quant: "nvfp4" };
}

function loaderLabel(cfg) {
  if (!cfg) return "—";
  if (cfg.model_path === "gguf") return "GGUF";
  return cfg.quant === "int8" ? "OTUNet (convrot/int8)" : "UNETLoader";
}

const DEFAULT_FIRST_FRAME =
  "Cyberpunk_outlaw_with_jagged_grin_202605230412.jpeg";

const state = {
  config: {
    model_path: "safetensor",
    quant: "nvfp4",
    diffusion_model: "",
    first_frame: DEFAULT_FIRST_FRAME,
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
};

/** @type {Map<string, object>} */
const runIndex = new Map();

let lastListKey = "";
let lastHeatmapKey = "";
let lastGalleryKey = "";
let detailRunId = null;
let galleryFiltersWired = false;

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
    get: (c) =>
      c.model_path === "gguf" ? "gguf" : `safetensor/${c.quant || "nvfp4"}`,
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
  if (d.steps != null) state.config.steps = d.steps;
  if (d.mp != null) state.config.mp = d.mp;
  if (d.duration_s != null) state.config.duration_s = d.duration_s;
  if (d.seed != null) state.config.seed = d.seed;
  if (d.first_frame) state.config.first_frame = d.first_frame;
  else if (!state.config.first_frame) state.config.first_frame = DEFAULT_FIRST_FRAME;
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
    .filter((r) => r.status === "done" && r.timed_s != null)
    .sort((a, b) => a.timed_s - b.timed_s)[0];
}

function configChips(cfg) {
  if (!cfg) return "";
  const bits = [
    cfg.diffusion_model || null,
    cfg.first_frame ? `img:${cfg.first_frame}` : null,
    cfg.model_path,
    cfg.model_path === "gguf" ? null : cfg.quant,
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
  updateFirstFramePreview(c.first_frame || DEFAULT_FIRST_FRAME);

  syncDisabled();
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

  state.config = {
    model_path: inferred.model_path,
    quant: inferred.quant,
    diffusion_model: diffusionModel,
    first_frame: state.config.first_frame || DEFAULT_FIRST_FRAME,
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
  runBtn.disabled = state.busy;
  runBtn.classList.toggle("busy", state.busy);
  runBtn.textContent = state.busy ? "Running…" : "Run this config";
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
    if (e.target.matches("input[type=number]")) {
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
  if (r.status === 409) {
    alert("Busy — wait for current run");
    return;
  }
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
  const sorted = runs.slice().sort((a, b) => {
    const fa = a.finished_at || a.started_at || "";
    const fb = b.finished_at || b.started_at || "";
    if (fa !== fb) return fb.localeCompare(fa);
    return String(b.id || "").localeCompare(String(a.id || ""));
  });

  const key = sorted
    .map(
      (r) =>
        `${r.id}:${r.status}:${r.timed_s}:${r.sec_per_it}:${r.video_path || ""}`
    )
    .join("|");
  if (key === lastListKey && wrap.dataset.ready === "1") return;
  lastListKey = key;

  if (!sorted.length) {
    wrap.innerHTML = `<div class="empty-msg">No runs yet. Configure the panel and click Run.</div>`;
    wrap.dataset.ready = "1";
    return;
  }

  let html = `<div class="table-wrap"><table class="list-table"><thead><tr>
    <th class="row-label">id</th>
    <th>status</th>
    <th>wall</th>
    <th>s/it</th>
    <th>config</th>
    <th>video</th>
    <th></th>
  </tr></thead><tbody>`;

  for (const r of sorted) {
    const cfg = r.config || {};
    const vid = r.video_path
      ? `<a href="/${escapeHtml(r.video_path)}" target="_blank" rel="noopener">video</a>`
      : "—";
    const wall = r.timed_s != null ? fmtSec(r.timed_s) : "—";
    html += `<tr class="clickable" data-run-id="${escapeHtml(r.id)}">
      <td class="row-label">${escapeHtml(r.id)}</td>
      <td><span class="chip ${escapeHtml(r.status || "queued")}">${escapeHtml(r.status || "queued")}</span></td>
      <td>${escapeHtml(wall)}</td>
      <td title="seconds per sampler step (same unit as Comfy tqdm)">${escapeHtml(fmtSecPerIt(r))}</td>
      <td class="chips-cell"><div class="chips">${configChips(cfg)}</div></td>
      <td>${vid}</td>
      <td><button type="button" class="compact apply-btn" data-apply="${escapeHtml(r.id)}">Apply</button></td>
    </tr>`;
  }
  html += "</tbody></table></div>";
  wrap.innerHTML = html;
  wrap.dataset.ready = "1";

  wrap.querySelectorAll("tr[data-run-id]").forEach((tr) => {
    tr.addEventListener("click", (e) => {
      if (e.target.closest("a, button")) return;
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
  const done = runs.filter((r) => r.status === "done" && r.timed_s != null);
  const key = runs
    .map((r) => `${r.id}:${r.status}:${r.timed_s}`)
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
  meta.innerHTML = `
        <strong>${escapeHtml(r.id)}</strong><br>
        ${escapeHtml(fmtRunTime(r))}
        ${varyBits}
        <div class="chips">${configChips(r.config)}</div>`;
}

function makeGalleryCard(r) {
  const article = document.createElement("article");
  article.className = "card";
  article.dataset.runId = r.id;

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
    openDetail(article.dataset.runId);
  });
  return article;
}

function renderGallery(allRuns) {
  wireGalleryFilters();
  const done = allRuns
    .filter((r) => r.video_path)
    .sort((a, b) => (b.finished_at || "").localeCompare(a.finished_at || ""));
  const g = document.getElementById("gallery");
  const statusEl = document.getElementById("gallery-filter-status");
  const varyKeys = state.galleryVaryAxes;
  const varyKey = [...varyKeys].sort().join(",");
  const { groups, status } = galleryCompareGroups(done, varyKeys);
  if (statusEl) statusEl.textContent = status;

  const flatIds = groups.flatMap((gr) => gr.runs.map((r) => r.id));
  const structureKey = `${varyKey}||${groups
    .map((gr) => gr.fixedKey + ":" + gr.runs.map((r) => `${r.id}:${r.video_path}`).join(","))
    .join(";")}`;
  const metaKey = groups
    .flatMap((gr) => gr.runs)
    .map((r) => `${r.id}:${r.timed_s}:${r.sec_per_it}`)
    .join("|");

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
  body.innerHTML = `
    <h3>${escapeHtml(run.id)}</h3>
    <div class="kv">
      phase=<span>${escapeHtml(run.phase || "?")}</span>
      · status=<span>${escapeHtml(run.status || "?")}</span>
      · timed=<span>${escapeHtml(run.timed_s != null ? fmtSec(run.timed_s) : "—")}</span>
      · s/it=<span>${escapeHtml(fmtSecPerIt(run))}</span>
      ${run.warmup_s != null ? `· warmup=<span>${fmtSec(run.warmup_s)}</span> (legacy)` : ""}
      ${run.graph_cache_cleared != null ? `· graph_clear=<span>${run.graph_cache_cleared}</span>` : ""}
      ${run.sampler_cached != null ? `· sampler_cached=<span>${run.sampler_cached}</span>` : ""}
    </div>
    <div class="chips">${configChips(cfg)}</div>
    ${video}
    ${run.error ? `<p class="kv" style="color:var(--fail)">error: <span>${escapeHtml(run.error)}</span></p>` : ""}
    <pre>${escapeHtml(JSON.stringify(run, null, 2))}</pre>
  `;
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
