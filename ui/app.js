const POLL_MS = 1500;

const COLS = [
  { key: "nvfp4|sol_on", quant: "nvfp4", sol: true, label: "nvfp4 · sol on" },
  { key: "nvfp4|sol_off", quant: "nvfp4", sol: false, label: "nvfp4 · sol off" },
  { key: "int8|sol_on", quant: "int8", sol: true, label: "int8 · sol on" },
  { key: "int8|sol_off", quant: "int8", sol: false, label: "int8 · sol off" },
];

/** @type {Map<string, object>} */
const runIndex = new Map();

/** Skip full table re-renders when nothing meaningful changed */
let lastSpeedKey = "";
let lastQualityKey = "";
let lastScaleKey = "";
let lastGalleryKey = "";

async function fetchResults() {
  const r = await fetch("/api/results", { cache: "no-store" });
  if (!r.ok) throw new Error("api failed");
  return r.json();
}

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

function rowLabel(cfg) {
  if (!cfg) return "?";
  if (cfg.cache_variant) return cfg.cache_variant;
  if (cfg.sol_variant) return cfg.sol_variant;
  return cfg.cache || "?";
}

function colKey(cfg) {
  const sol = cfg.sol_attn ? "sol_on" : "sol_off";
  return `${cfg.quant}|${sol}`;
}

function findFastest(runs) {
  return runs
    .filter((r) => r.status === "done" && r.timed_s != null)
    .sort((a, b) => a.timed_s - b.timed_s)[0];
}

function runsFingerprint(runs, fields) {
  return runs
    .map((r) => fields.map((f) => r[f] ?? r.config?.[f] ?? "").join(":"))
    .join("|");
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

function renderStatus(data) {
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
  const best = findFastest(data.phases?.speed?.runs || []);
  document.getElementById("fastest").textContent = best
    ? `Fastest: ${fmtRunTime(best)} (${best.id})`
    : "";
}

function bindCellClicks(wrap) {
  wrap.querySelectorAll("td.cell[data-run-id]").forEach((td) => {
    td.addEventListener("click", () => openDetail(td.dataset.runId));
  });
}

function renderSpeedHeatmap(runs) {
  const wrap = document.getElementById("speed-heatmap");
  const key = runsFingerprint(runs, ["id", "status", "timed_s", "sec_per_it"]);
  if (key === lastSpeedKey && wrap.dataset.ready === "1") return;
  lastSpeedKey = key;

  if (!runs.length) {
    wrap.innerHTML = `<div class="empty-msg">No speed runs yet.</div>`;
    wrap.dataset.ready = "1";
    return;
  }

  const rowOrder = [];
  const rowSet = new Set();
  const grid = new Map();

  for (const run of runs) {
    const cfg = run.config || {};
    const row = rowLabel(cfg);
    const col = colKey(cfg);
    if (!rowSet.has(row)) {
      rowSet.add(row);
      rowOrder.push(row);
    }
    if (!grid.has(row)) grid.set(row, new Map());
    if (!grid.get(row).has(col)) {
      grid.get(row).set(col, run);
    }
  }

  const best = findFastest(runs);
  const bestId = best ? best.id : null;

  let html = '<table><thead><tr><th class="row-label">cache / variant</th>';
  for (const c of COLS) {
    html += `<th>${escapeHtml(c.label)}</th>`;
  }
  html += "</tr></thead><tbody>";

  for (const row of rowOrder) {
    html += `<tr><td class="row-label">${escapeHtml(row)}</td>`;
    const cols = grid.get(row) || new Map();
    for (const c of COLS) {
      html += cellHtml(cols.get(c.key), bestId);
    }
    html += "</tr>";
  }
  html += "</tbody></table>";
  wrap.innerHTML = html;
  wrap.dataset.ready = "1";
  bindCellClicks(wrap);
}

function renderQuality(runs) {
  const wrap = document.getElementById("quality-table");
  const key = runsFingerprint(runs, [
    "id",
    "status",
    "timed_s",
    "sec_per_it",
    "scheduler",
    "sampler",
    "steps",
  ]);
  if (key === lastQualityKey && wrap.dataset.ready === "1") return;
  lastQualityKey = key;

  if (!runs.length) {
    wrap.innerHTML = `<div class="empty-msg">No quality runs yet.</div>`;
    wrap.dataset.ready = "1";
    return;
  }
  let html = `<table><thead><tr>
    <th class="row-label">id</th>
    <th>status</th>
    <th>scheduler</th>
    <th>sampler</th>
    <th>steps</th>
    <th>time</th>
    <th>video</th>
  </tr></thead><tbody>`;
  for (const r of runs) {
    const cfg = r.config || {};
    const vid = r.video_path
      ? `<a href="/${escapeHtml(r.video_path)}" target="_blank" rel="noopener">video</a>`
      : "—";
    html += `<tr class="clickable" data-run-id="${escapeHtml(r.id)}">
      <td class="row-label">${escapeHtml(r.id)}</td>
      <td><span class="chip ${escapeHtml(r.status || "queued")}">${escapeHtml(r.status || "queued")}</span></td>
      <td>${escapeHtml(cfg.scheduler ?? "—")}</td>
      <td>${escapeHtml(cfg.sampler ?? "—")}</td>
      <td>${escapeHtml(cfg.steps ?? "—")}</td>
      <td>${escapeHtml(fmtRunTime(r))}</td>
      <td>${vid}</td>
    </tr>`;
  }
  html += "</tbody></table>";
  wrap.innerHTML = html;
  wrap.dataset.ready = "1";
  wrap.querySelectorAll("tr[data-run-id]").forEach((tr) => {
    tr.style.cursor = "pointer";
    tr.addEventListener("click", (e) => {
      if (e.target.closest("a")) return;
      openDetail(tr.dataset.runId);
    });
  });
}

function renderScale(runs) {
  const wrap = document.getElementById("scale-table");
  const key = runsFingerprint(runs, ["id", "status", "timed_s", "sec_per_it", "mp", "duration_s"]);
  if (key === lastScaleKey && wrap.dataset.ready === "1") return;
  lastScaleKey = key;

  if (!runs.length) {
    wrap.innerHTML = `<div class="empty-msg">No scale runs yet.</div>`;
    wrap.dataset.ready = "1";
    return;
  }

  const mps = [];
  const durs = [];
  const mpSet = new Set();
  const durSet = new Set();
  const grid = new Map();

  for (const r of runs) {
    const cfg = r.config || {};
    const mp = cfg.mp;
    const dur = cfg.duration_s;
    if (!mpSet.has(mp)) {
      mpSet.add(mp);
      mps.push(mp);
    }
    if (!durSet.has(dur)) {
      durSet.add(dur);
      durs.push(dur);
    }
    grid.set(`${mp}|${dur}`, r);
  }
  mps.sort((a, b) => a - b);
  durs.sort((a, b) => a - b);

  const best = findFastest(runs);
  const bestId = best ? best.id : null;

  let html = '<table><thead><tr><th class="row-label">MP \\ duration</th>';
  for (const d of durs) {
    html += `<th>${escapeHtml(d)}s</th>`;
  }
  html += "</tr></thead><tbody>";
  for (const mp of mps) {
    html += `<tr><td class="row-label">${escapeHtml(mp)} MP</td>`;
    for (const d of durs) {
      html += cellHtml(grid.get(`${mp}|${d}`), bestId);
    }
    html += "</tr>";
  }
  html += "</tbody></table>";
  wrap.innerHTML = html;
  wrap.dataset.ready = "1";
  bindCellClicks(wrap);
}

function configChips(cfg) {
  if (!cfg) return "";
  const bits = [
    cfg.cache,
    cfg.cache_variant,
    cfg.quant,
    cfg.sol_attn ? "sol_on" : "sol_off",
    cfg.sol_variant,
    cfg.scheduler,
    cfg.sampler,
    cfg.steps != null ? `${cfg.steps}st` : null,
    cfg.mp != null ? `${cfg.mp}mp` : null,
    cfg.duration_s != null ? `${cfg.duration_s}s` : null,
  ].filter(Boolean);
  return bits.map((b) => `<span class="chip">${escapeHtml(b)}</span>`).join("");
}

/**
 * Incremental gallery update: never rewrite <video> for existing cards.
 * Full innerHTML on every poll was restarting playback (spinner).
 */
function renderGallery(allRuns) {
  const done = allRuns
    .filter((r) => r.video_path)
    .sort((a, b) => (b.finished_at || "").localeCompare(a.finished_at || ""));
  const g = document.getElementById("gallery");

  const key = done
    .map((r) => `${r.id}:${r.video_path}:${r.timed_s}:${r.sec_per_it}`)
    .join("|");
  // Even when key changes for meta (timed_s), keep videos; only structural set change
  // needs full rebuild of card list order/add/remove.
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
    // Structural change: rebuild, but only when membership/order of videos changes
    g.innerHTML = "";
    g.dataset.structureKey = structureKey;
    for (const r of done) {
      g.appendChild(makeGalleryCard(r));
    }
    lastGalleryKey = key;
    return;
  }

  // Same videos: update meta text only (no video reload)
  if (key === lastGalleryKey) return;
  lastGalleryKey = key;
  for (const r of done) {
    const card = [...g.querySelectorAll(".card")].find((el) => el.dataset.runId === r.id);
    if (!card) continue;
    const meta = card.querySelector(".meta");
    if (!meta) continue;
    meta.innerHTML = `
        <strong>${escapeHtml(r.id)}</strong><br>
        ${escapeHtml(fmtRunTime(r))} · ${escapeHtml(r.config?.cache || "?")} · ${escapeHtml(r.config?.quant || "?")}
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
  // Cache-bust only once on create so poll doesn't reload
  video.src = `/${r.video_path}`;
  video.dataset.src = r.video_path;

  const meta = document.createElement("div");
  meta.className = "meta";
  meta.innerHTML = `
        <strong>${escapeHtml(r.id)}</strong><br>
        ${escapeHtml(fmtRunTime(r))} · ${escapeHtml(r.config?.cache || "?")} · ${escapeHtml(r.config?.quant || "?")}
        <div class="chips">${configChips(r.config)}</div>`;

  article.appendChild(video);
  article.appendChild(meta);
  article.addEventListener("click", (e) => {
    if (e.target.tagName === "VIDEO") return;
    openDetail(article.dataset.runId);
  });
  return article;
}

function openDetail(runId) {
  const run = runIndex.get(runId);
  const body = document.getElementById("detail-body");
  if (!run) {
    body.innerHTML = `<p class="muted">Run ${escapeHtml(runId)} not found.</p>`;
    document.getElementById("detail").showModal();
    return;
  }
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

function indexRuns(data) {
  runIndex.clear();
  for (const phase of ["speed", "quality", "scale"]) {
    for (const r of data.phases?.[phase]?.runs || []) {
      runIndex.set(r.id, r);
    }
  }
}

async function tick() {
  try {
    const data = await fetchResults();
    indexRuns(data);
    renderStatus(data);
    const speed = data.phases?.speed?.runs || [];
    const quality = data.phases?.quality?.runs || [];
    const scale = data.phases?.scale?.runs || [];
    renderSpeedHeatmap(speed);
    renderQuality(quality);
    renderScale(scale);
    renderGallery([...speed, ...quality, ...scale]);
  } catch (e) {
    document.getElementById("status-line").textContent =
      `Waiting for results… (${e.message})`;
  }
}

tick();
setInterval(tick, POLL_MS);
