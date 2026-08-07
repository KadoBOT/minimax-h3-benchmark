const POLL_MS = 1500;

const AXIS_PRIORITY = [
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

const state = {
  config: {
    model_path: "safetensor",
    quant: "nvfp4",
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
};

/** @type {Map<string, object>} */
const runIndex = new Map();

let lastListKey = "";
let lastHeatmapKey = "";
let lastGalleryKey = "";
let detailRunId = null;

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
  const banner = document.getElementById("options-banner");
  if (state.options.source === "fallback") {
    banner.hidden = false;
  } else {
    banner.hidden = true;
  }
  // Prefer live defaults when provided
  const d = state.options.defaults || {};
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
  formFromState();
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

function fmtSec(s) {
  if (s == null || s === undefined) return "—";
  return `${Number(s).toFixed(1)}s`;
}

/** Wall time + ComfyUI s/it, e.g. "120.0s / 6.54s/it" */
function fmtRunTime(run) {
  if (!run || run.timed_s == null) return "—";
  const wall = fmtSec(run.timed_s);
  const it = run.sec_per_it;
  if (it == null || it === undefined || !(Number(it) >= 0.05)) return wall;
  return `${wall} / ${Number(it).toFixed(2)}s/it`;
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
  const list = values && values.length ? values : [selected].filter(Boolean);
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
  const mpRadio = document.querySelector(
    `input[name="model_path"][value="${c.model_path}"]`
  );
  if (mpRadio) mpRadio.checked = true;

  const qRadio = document.querySelector(`input[name="quant"][value="${c.quant}"]`);
  if (qRadio) qRadio.checked = true;

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

  syncDisabled();
}

function stateFromForm() {
  const modelPath =
    document.querySelector('input[name="model_path"]:checked')?.value || "safetensor";
  const quant =
    document.querySelector('input[name="quant"]:checked')?.value || "nvfp4";
  const cacheEnabled = document.getElementById("toggle-cache").checked;
  const cache =
    document.querySelector('input[name="cache"]:checked')?.value || "spectrum";

  state.config = {
    model_path: modelPath,
    quant,
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
}

function syncDisabled() {
  const modelPath =
    document.querySelector('input[name="model_path"]:checked')?.value || "safetensor";
  const cacheOn = document.getElementById("toggle-cache").checked;
  const solOn = document.getElementById("toggle-sol").checked;

  const quantGroup = document.getElementById("quant-group");
  quantGroup.classList.toggle("disabled", modelPath === "gguf");
  quantGroup.querySelectorAll("input").forEach((el) => {
    el.disabled = modelPath === "gguf";
  });

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
  panel.addEventListener("change", () => {
    stateFromForm();
    syncDisabled();
  });
  panel.addEventListener("input", (e) => {
    if (e.target.matches("input[type=number]")) {
      stateFromForm();
    }
  });
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
  state.config = {
    model_path: cfg.model_path || "safetensor",
    quant: cfg.quant || "nvfp4",
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
    <th>time</th>
    <th>config</th>
    <th>video</th>
    <th></th>
  </tr></thead><tbody>`;

  for (const r of sorted) {
    const cfg = r.config || {};
    const vid = r.video_path
      ? `<a href="/${escapeHtml(r.video_path)}" target="_blank" rel="noopener">video</a>`
      : "—";
    html += `<tr class="clickable" data-run-id="${escapeHtml(r.id)}">
      <td class="row-label">${escapeHtml(r.id)}</td>
      <td><span class="chip ${escapeHtml(r.status || "queued")}">${escapeHtml(r.status || "queued")}</span></td>
      <td>${escapeHtml(fmtRunTime(r))}</td>
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
// ---------------------------------------------------------------------------

function renderGallery(allRuns) {
  const done = allRuns
    .filter((r) => r.video_path)
    .sort((a, b) => (b.finished_at || "").localeCompare(a.finished_at || ""));
  const g = document.getElementById("gallery");

  const key = done
    .map((r) => `${r.id}:${r.video_path}:${r.timed_s}:${r.sec_per_it}`)
    .join("|");
  const structureKey = done.map((r) => `${r.id}:${r.video_path}`).join("|");

  if (!done.length) {
    if (g.dataset.structureKey !== "empty") {
      g.innerHTML = `<div class="empty-msg">No videos yet.</div>`;
      g.dataset.structureKey = "empty";
      lastGalleryKey = "";
    }
    return;
  }

  if (g.dataset.structureKey !== structureKey) {
    g.innerHTML = "";
    g.dataset.structureKey = structureKey;
    for (const r of done) {
      g.appendChild(makeGalleryCard(r));
    }
    lastGalleryKey = key;
    return;
  }

  if (key === lastGalleryKey) return;
  lastGalleryKey = key;
  for (const r of done) {
    const card = [...g.querySelectorAll(".card")].find((el) => el.dataset.runId === r.id);
    if (!card) continue;
    const meta = card.querySelector(".meta");
    if (!meta) continue;
    meta.innerHTML = `
        <strong>${escapeHtml(r.id)}</strong><br>
        ${escapeHtml(fmtRunTime(r))} · ${escapeHtml(r.config?.cache || "?")} · ${escapeHtml(r.config?.quant || r.config?.model_path || "?")}
        <div class="chips">${configChips(r.config)}</div>`;
  }
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
  meta.innerHTML = `
        <strong>${escapeHtml(r.id)}</strong><br>
        ${escapeHtml(fmtRunTime(r))} · ${escapeHtml(r.config?.cache || "?")} · ${escapeHtml(r.config?.quant || r.config?.model_path || "?")}
        <div class="chips">${configChips(r.config)}</div>`;

  article.appendChild(video);
  article.appendChild(meta);
  article.addEventListener("click", (e) => {
    if (e.target.tagName === "VIDEO") return;
    openDetail(article.dataset.runId);
  });
  return article;
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
      · timed=<span>${escapeHtml(fmtRunTime(run))}</span>
      · warmup=<span>${fmtSec(run.warmup_s)}</span>
      ${
        run.sec_per_it != null && Number(run.sec_per_it) >= 0.05
          ? `· s/it=<span>${Number(run.sec_per_it).toFixed(2)}</span>`
          : ""
      }
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
