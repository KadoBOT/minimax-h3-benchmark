const POLL_MS = 1500;

const COLS = [
  { key: "nvfp4|sol_on", quant: "nvfp4", sol: true, label: "nvfp4 · sol on" },
  { key: "nvfp4|sol_off", quant: "nvfp4", sol: false, label: "nvfp4 · sol off" },
  { key: "int8|sol_on", quant: "int8", sol: true, label: "int8 · sol on" },
  { key: "int8|sol_off", quant: "int8", sol: false, label: "int8 · sol off" },
];

/** @type {Map<string, object>} */
const runIndex = new Map();

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
  if (run.sec_per_it == null || run.sec_per_it === undefined) return wall;
  return `${wall} / ${Number(run.sec_per_it).toFixed(2)}s/it`;
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
  const title = run.sec_per_it != null
    ? `${run.id} · ${fmtRunTime(run)}`
    : run.id;
  return `<td class="${classes.join(" ")}" data-run-id="${escapeHtml(run.id)}" title="${escapeHtml(title)}">${content}</td>`;
}

function renderStatus(data) {
  const el = document.getElementById("status-line");
  const cur = data.current;
  const curText = cur
    ? `${cur.phase || "?"} / ${cur.run_id || "?"} / ${cur.stage || "?"}`
    : "idle";
  el.textContent = `suite=${data.status || "?"} · ${curText} · updated ${data.updated_at || "—"}`;
  const best = findFastest(data.phases?.speed?.runs || []);
  document.getElementById("fastest").textContent = best
    ? `Fastest: ${fmtRunTime(best)} (${best.id})`
    : "";
}

function renderSpeedHeatmap(runs) {
  const wrap = document.getElementById("speed-heatmap");
  if (!runs.length) {
    wrap.innerHTML = `<div class="empty-msg">No speed runs yet.</div>`;
    return;
  }

  // Preserve first-seen row order from the run list
  const rowOrder = [];
  const rowSet = new Set();
  const grid = new Map(); // rowLabel -> colKey -> run

  for (const run of runs) {
    const cfg = run.config || {};
    const row = rowLabel(cfg);
    const col = colKey(cfg);
    if (!rowSet.has(row)) {
      rowSet.add(row);
      rowOrder.push(row);
    }
    if (!grid.has(row)) grid.set(row, new Map());
    // Prefer keeping the first match; variants with sol_* only fill sol_on col
    if (!grid.get(row).has(col)) {
      grid.get(row).set(col, run);
    }
  }

  const best = findFastest(runs);
  const bestId = best ? best.id : null;

  let html = "<table><thead><tr><th class=\"row-label\">cache / variant</th>";
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

  wrap.querySelectorAll("td.cell[data-run-id]").forEach((td) => {
    td.addEventListener("click", () => openDetail(td.dataset.runId));
  });
}

function renderQuality(runs) {
  const wrap = document.getElementById("quality-table");
  if (!runs.length) {
    wrap.innerHTML = `<div class="empty-msg">No quality runs yet.</div>`;
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
  if (!runs.length) {
    wrap.innerHTML = `<div class="empty-msg">No scale runs yet.</div>`;
    return;
  }

  // Pivot: rows = mp, cols = duration
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

  let html = "<table><thead><tr><th class=\"row-label\">MP \\ duration</th>";
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
  wrap.querySelectorAll("td.cell[data-run-id]").forEach((td) => {
    td.addEventListener("click", () => openDetail(td.dataset.runId));
  });
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

function renderGallery(allRuns) {
  const done = allRuns
    .filter((r) => r.video_path)
    .sort((a, b) => (b.finished_at || "").localeCompare(a.finished_at || ""));
  const g = document.getElementById("gallery");
  if (!done.length) {
    g.innerHTML = `<div class="empty-msg">No videos yet.</div>`;
    return;
  }
  g.innerHTML = done
    .map(
      (r) => `
    <article class="card" data-run-id="${escapeHtml(r.id)}">
      <video src="/${escapeHtml(r.video_path)}" controls preload="metadata"></video>
      <div class="meta">
        <strong>${escapeHtml(r.id)}</strong><br>
        ${escapeHtml(fmtRunTime(r))} · ${escapeHtml(r.config?.cache || "?")} · ${escapeHtml(r.config?.quant || "?")}
        <div class="chips">${configChips(r.config)}</div>
      </div>
    </article>`
    )
    .join("");
  g.querySelectorAll(".card").forEach((card) => {
    card.addEventListener("click", (e) => {
      if (e.target.tagName === "VIDEO") return;
      openDetail(card.dataset.runId);
    });
  });
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
      ${run.sec_per_it != null ? `· s/it=<span>${Number(run.sec_per_it).toFixed(2)}</span>` : ""}
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
