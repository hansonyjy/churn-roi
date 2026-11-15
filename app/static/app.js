// Churn ROI frontend logic. Everything downstream of the sliders is recomputed
// here in the browser from the committed OOF scores, no server round trip. The
// charts are built once from metrics.json / shap.json and never touched again.

"use strict";

// Cached formatters reused across every render.
const usd = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", maximumFractionDigits: 0,
});
const usdCompact = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1,
});
const pct = new Intl.NumberFormat("en-US", {
  style: "percent", maximumFractionDigits: 0,
});
const int = new Intl.NumberFormat("en-US");

const PAGE = 10;
const $ = (id) => document.getElementById(id);

// State populated on load.
let N = 0;
let p, v, ev, order;   // Float64Array p, v, ev; Int32Array order
let customers = [];    // raw display objects
let signals = [];      // precomputed signal chips, slider-independent
let metrics = null;
let grid = [];         // sensitivity grid cells
let gridCosts = [], gridRates = [];

let selected = [];     // current selection, EV descending
let shown = 0;         // rows currently rendered in the table

// Signed currency, e.g. "+$71,489" / "-$1,200".
function signedUsd(x) {
  return (x >= 0 ? "+" : "-") + usd.format(Math.abs(x));
}
function signedPct1(x) {
  return (x >= 0 ? "+" : "") + x.toFixed(1) + "%";
}

// Nearest candidate by absolute difference, ties resolved toward the lower value.
// Candidates are ascending, so the first one achieving the minimum wins the tie.
function nearest(value, candidates) {
  let best = candidates[0];
  let bestDiff = Math.abs(value - best);
  for (let i = 1; i < candidates.length; i++) {
    const d = Math.abs(value - candidates[i]);
    if (d < bestDiff) {
      best = candidates[i];
      bestDiff = d;
    }
  }
  return best;
}

// Static per-customer signal chips, computed once at load.
// Each chip is [label, tone] where tone maps to a CSS modifier.
function buildSignals(c) {
  const out = [];
  if (c.p_churn >= 0.7) out.push(["Very likely to leave", "hot"]);
  else if (c.p_churn >= 0.4) out.push(["Elevated risk", "warm"]);
  else out.push(["Moderate risk", "dim"]);

  if (c.balance >= 100000) out.push(["Large balance", ""]);
  else if (c.num_products >= 2) out.push(["Multi-product", ""]);
  else out.push(["Single product", ""]);

  if (c.geography === "Germany") out.push(["Germany", "dim"]);
  if (c.is_active === 0) out.push(["Inactive", "dim"]);
  return out;
}

function readControls() {
  return {
    cost: Number($("cost").value),
    rate: Number($("rate").value),
    budget: Number($("budget").value),
  };
}

// The core recompute, run on every slider input (coalesced to one per frame).
function recompute(cost, rate, budget) {
  for (let i = 0; i < N; i++) {
    ev[i] = p[i] * v[i] * rate - cost;
  }

  // Stable sort by EV descending. Array.prototype.sort is stable per spec, so
  // ties break by lowest original index, matching the Python stable argsort.
  order.sort((a, b) => ev[b] - ev[a]);

  const cap = Math.min(Math.floor(budget / cost), N);

  selected = [];
  let sumEV = 0;
  for (let k = 0; k < order.length; k++) {
    if (selected.length >= cap) break;
    const idx = order[k];
    if (ev[idx] <= 0) break;   // strict positive-EV stop, matches Python ev > 0
    selected.push(idx);
    sumEV += ev[idx];
  }

  renderKpis(sumEV, selected.length, cap, cost, budget);
  renderBacktest(cost, rate, budget);
  renderTable(true);
}

// ---- Renderers ----

function renderKpis(sumEV, sent, cap, cost, budget) {
  const spend = sent * cost;
  const under = sent < cap;

  $("ev-figure").textContent = usd.format(sumEV);

  $("offers-sent").textContent = int.format(sent);
  $("offers-cap").textContent = " / " + int.format(cap);
  const om = $("offers-meter");
  om.style.width = (cap ? (sent / cap) * 100 : 0) + "%";
  om.classList.toggle("is-under", under);
  const of = $("offers-foot");
  of.textContent = under
    ? int.format(cap - sent) + " allowed offers refused."
    : "Every allowed offer clears positive EV.";
  of.classList.toggle("is-warn", under);

  $("spend-figure").textContent = usd.format(spend);
  const sm = $("spend-meter");
  sm.style.width = Math.min(100, (spend / budget) * 100) + "%";
  sm.classList.toggle("is-under", under);
  $("spend-foot").textContent =
    pct.format(spend / budget) + " of " + usd.format(budget) + (under ? ", rest held back." : ".");

  $("roi-figure").textContent = (spend > 0 ? sumEV / spend : 0).toFixed(1) + "x";
  $("roi-foot").textContent = sent
    ? usd.format(sumEV / sent) + " expected net value per offer."
    : "No offer clears positive EV.";

  const callout = $("offers-callout");
  if (under) {
    $("offers-callout-body").textContent =
      "The budget allows " + int.format(cap) + " offers, but only " + int.format(sent) +
      " clear positive expected value. Spending the remaining " + usd.format(budget - spend) +
      " would destroy value, so the engine stops.";
    callout.hidden = false;
  } else {
    callout.hidden = true;
  }
}

function renderBacktest(cost, rate, budget) {
  const nc = nearest(cost, gridCosts);
  const nr = nearest(rate, gridRates);
  const cell = grid.find((r) => r.offer_cost === nc && r.offer_success_rate === nr);
  if (!cell) return;

  const exact = nc === cost && Math.abs(nr - rate) < 1e-9 && budget === cell.budget;
  $("scenario-tag").textContent =
    (exact ? "" : "Nearest: ") + usd.format(cell.offer_cost) + " · " + pct.format(cell.offer_success_rate) + " success";

  const evN = cell.ev.net_value;
  const riskN = cell.risk.net_value;
  const randN = cell.random.net_value_mean;
  const max = Math.max(evN, riskN, randN, 1);
  $("bar-ev").style.width = (evN / max) * 100 + "%";
  $("bar-risk").style.width = (riskN / max) * 100 + "%";
  $("bar-random").style.width = (Math.max(randN, 0) / max) * 100 + "%";
  $("bar-ev-val").textContent = usd.format(evN);
  $("bar-risk-val").textContent = usd.format(riskN);
  $("bar-random-val").textContent = usd.format(randN);

  const line = $("lift-line");
  line.innerHTML =
    "EV targeting returned <strong>" + signedUsd(cell.lift_abs) + " (" + signedPct1(cell.lift_pct) +
    ")</strong> more than risk targeting, with " + int.format(cell.offers_allowed) +
    " offers allowed at a " + usd.format(cell.budget) + " budget.";

  document.querySelectorAll(".heat-cell").forEach((btn) => {
    const on = Number(btn.dataset.cost) === nc && Number(btn.dataset.rate) === nr;
    btn.classList.toggle("is-active", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  });
}

function buildHeatTable() {
  const lifts = grid.map((c) => c.lift_pct);
  const lo = Math.min(...lifts), hi = Math.max(...lifts);

  const headRow = document.querySelector("#heat-table thead tr");
  gridRates.forEach((r) => {
    const th = document.createElement("th");
    th.scope = "col";
    th.className = "mono";
    th.textContent = pct.format(r);
    th.title = "Offer success rate";
    headRow.appendChild(th);
  });

  const body = document.querySelector("#heat-table tbody");
  let html = "";
  gridCosts.forEach((c) => {
    html += "<tr><th scope=\"row\">" + usd.format(c) + "</th>";
    gridRates.forEach((r) => {
      const cell = grid.find((g) => g.offer_cost === c && g.offer_success_rate === r);
      const t = hi > lo ? (cell.lift_pct - lo) / (hi - lo) : 0.5;
      const alpha = (0.08 + t * 0.42).toFixed(3);
      html +=
        "<td><button type=\"button\" class=\"heat-cell\" data-cost=\"" + c + "\" data-rate=\"" + r + "\"" +
        " style=\"background: rgba(" + ACCENT_RGB + ", " + alpha + ")\"" +
        " aria-label=\"Load scenario: cost " + usd.format(c) + ", " + pct.format(r) + " success, lift " +
        signedPct1(cell.lift_pct) + "\">" +
        "<span class=\"pct\">" + signedPct1(cell.lift_pct) + "</span>" +
        "<span class=\"abs\">" + (cell.lift_abs >= 0 ? "+" : "-") + usdCompact.format(Math.abs(cell.lift_abs)) + "</span>" +
        "</button></td>";
    });
    html += "</tr>";
  });
  body.innerHTML = html;

  body.addEventListener("click", (e) => {
    const btn = e.target.closest(".heat-cell");
    if (!btn) return;
    setControls(Number(btn.dataset.cost), Number(btn.dataset.rate), metrics.decision.grid_budget);
  });
}

// Build the row HTML for selected[start..end).
function rowsHtml(start, end) {
  let html = "";
  for (let r = start; r < end; r++) {
    const idx = selected[r];
    const c = customers[idx];
    const evVal = ev[idx];
    const pc = c.p_churn * 100;
    let chips = "";
    for (const [label, tone] of signals[idx]) {
      chips += "<span class=\"sig" + (tone ? " sig-" + tone : "") + "\">" + label + "</span>";
    }
    html +=
      "<tr>" +
      "<td class=\"rank num\">" + (r + 1) + "</td>" +
      "<td class=\"cid\">" + c.id + "</td>" +
      "<td class=\"prob-td\"><div class=\"prob\"><span class=\"prob-bar" + (pc >= 70 ? " is-high" : "") + "\"><span style=\"width:" +
        pc.toFixed(1) + "%\"></span></span><span class=\"prob-val\">" + pc.toFixed(1) + "%</span></div></td>" +
      "<td class=\"num val\" data-label=\"Value \">" + usd.format(c.value_saved) + "</td>" +
      "<td class=\"num ev " + (evVal >= 0 ? "pos" : "neg") + "\">" + signedUsd(evVal) + "</td>" +
      "<td class=\"sig-td\"><div class=\"signals\">" + chips + "</div></td>" +
      "</tr>";
  }
  return html;
}

// reset=true rebuilds from the top; reset=false appends the next page.
function renderTable(reset) {
  const body = $("save-body");
  if (reset) {
    shown = Math.min(PAGE, selected.length);
    body.innerHTML = selected.length
      ? rowsHtml(0, shown)
      : "<tr class=\"empty-row\"><td colspan=\"6\">No customer clears positive expected value at these assumptions. Try a cheaper offer or a higher success rate.</td></tr>";
  } else {
    const next = Math.min(shown + PAGE, selected.length);
    body.insertAdjacentHTML("beforeend", rowsHtml(shown, next));
    shown = next;
  }
  $("list-caption").textContent =
    "Showing " + int.format(shown) + " of " + int.format(selected.length) + " selected";
  $("window-path").textContent =
    "save_list.csv · " + int.format(selected.length) + " rows · ranked by expected value";
  $("show-more").hidden = shown >= selected.length;
  $("export-csv").disabled = selected.length === 0;
}

function exportCsv() {
  const head = ["rank", "customer_id", "p_churn", "value_saved", "expected_value",
    "geography", "num_products", "balance", "is_active", "signals"];
  const lines = [head.join(",")];
  selected.forEach((idx, r) => {
    const c = customers[idx];
    lines.push([
      r + 1, c.id, c.p_churn, c.value_saved, ev[idx].toFixed(2),
      c.geography, c.num_products, c.balance, c.is_active,
      "\"" + signals[idx].map((s) => s[0]).join("; ") + "\"",
    ].join(","));
  });
  const { cost, rate, budget } = readControls();
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "save_list_cost" + cost + "_rate" + Math.round(rate * 100) + "_budget" + budget + ".csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function renderMetrics() {
  const ch = metrics.challenger, base = metrics.baseline;
  $("m-prauc").textContent = ch.pr_auc.toFixed(3);
  $("m-prauc-sub").innerHTML =
    "<span class=\"up\">" + (ch.pr_auc / ch.pr_auc_baseline).toFixed(1) + "x</span> no-skill · LR " + base.pr_auc.toFixed(3);
  $("m-roc").textContent = ch.roc_auc.toFixed(3);
  $("m-roc-sub").textContent = "Logistic regression " + base.roc_auc.toFixed(3);
  $("m-brier").textContent = ch.brier_score.toFixed(3);
  $("m-brier-sub").textContent = "Lower is better · LR " + base.brier_score.toFixed(3);
  $("m-rate").textContent = (metrics.churn_rate * 100).toFixed(1) + "%";
  $("pr-caption").textContent =
    "The dashed line is the " + metrics.churn_rate.toFixed(3) + " no-skill baseline, the churn rate itself.";
}

// Keep the filled part of each range track in sync with its value.
function paintSlider(el) {
  const min = Number(el.min), max = Number(el.max), val = Number(el.value);
  el.style.setProperty("--fill", ((val - min) / (max - min)) * 100 + "%");
}

function setControls(cost, rate, budget) {
  $("cost").value = cost;
  $("rate").value = rate;
  $("budget").value = budget;
  markDirty();
}

// requestAnimationFrame dirty-flag coalescing. Not a timing debounce, just cheap
// insurance against dense input streams collapsing to one recompute per frame.
let dirty = false;
function markDirty() {
  if (dirty) return;
  dirty = true;
  requestAnimationFrame(() => {
    dirty = false;
    applyControls();
  });
}

// Read the sliders and render everything. Called directly on boot so the first
// paint does not wait on rAF, which browsers pause in background tabs.
function applyControls() {
  const { cost, rate, budget } = readControls();
  ["cost", "rate", "budget"].forEach((id) => paintSlider($(id)));
  $("cost-out").textContent = usd.format(cost);
  $("rate-out").textContent = pct.format(rate);
  $("budget-out").textContent = usd.format(budget);
  $("f-cost").textContent = usd.format(cost);
  $("f-rate").textContent = rate.toFixed(2);
  recompute(cost, rate, budget);
}

// Highlight the top-nav link for the section in view.
function initScrollSpy() {
  // The active section is the last one whose top has crossed 35% of the
  // viewport, which stays correct for long sections that span the whole screen.
  const links = [...document.querySelectorAll(".topnav a")];
  const sections = links.map((a) => $(a.getAttribute("href").slice(1)));
  let ticking = false;
  const update = () => {
    ticking = false;
    const line = window.innerHeight * 0.35;
    let active = -1;
    sections.forEach((s, i) => { if (s && s.getBoundingClientRect().top <= line) active = i; });
    if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) {
      active = sections.length - 1;
    }
    links.forEach((a, i) => a.classList.toggle("is-active", i === active));
  };
  window.addEventListener("scroll", () => {
    if (!ticking) { ticking = true; requestAnimationFrame(update); }
  }, { passive: true });
  update();
}

// ---- Charts, built once ----

// Colors come from the CSS tokens in style.css, so the palette lives in one place.
let INK, ACCENT, ACCENT_RGB, SURFACE, GRID, REF, TICK;
function readTheme() {
  const css = getComputedStyle(document.documentElement);
  const tok = (name) => css.getPropertyValue(name).trim();
  const inkRgb = tok("--ink-rgb");
  ACCENT_RGB = tok("--accent-rgb");
  INK = "rgb(" + inkRgb + ")";
  ACCENT = "rgb(" + ACCENT_RGB + ")";
  SURFACE = tok("--surface");
  GRID = "rgba(" + inkRgb + ", 0.08)";
  REF = "rgba(" + inkRgb + ", 0.38)";
  TICK = "rgba(" + inkRgb + ", 0.58)";
}

function axis(title, extra) {
  return Object.assign({
    grid: { color: GRID, drawTicks: false },
    border: { display: false },
    ticks: { color: TICK, font: { size: 11 }, padding: 8 },
    title: title ? { display: true, text: title, color: TICK, font: { size: 11 } } : undefined,
  }, extra || {});
}

function baseOptions(extra) {
  return Object.assign({
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 700, easing: "easeOutQuart" },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: INK,
        titleFont: { family: "IBM Plex Mono", size: 11 },
        bodyFont: { family: "IBM Plex Mono", size: 12 },
        padding: 10,
        cornerRadius: 8,
        displayColors: false,
      },
    },
  }, extra || {});
}

function buildCharts() {
  Chart.defaults.font.family = "'IBM Plex Mono', ui-monospace, monospace";
  Chart.defaults.color = TICK;

  // Calibration curve.
  const rc = metrics.reliability_curve;
  const calPoints = rc.mean_predicted_value.map((x, i) => ({ x, y: rc.fraction_of_positives[i] }));
  new Chart($("calibration-chart"), {
    type: "scatter",
    data: {
      datasets: [
        {
          data: calPoints,
          showLine: true,
          borderColor: ACCENT,
          backgroundColor: ACCENT,
          borderWidth: 2.5,
          pointRadius: 4.5,
          pointHoverRadius: 6,
          pointBorderColor: SURFACE,
          pointBorderWidth: 2,
        },
        {
          data: [{ x: 0, y: 0 }, { x: 1, y: 1 }],
          showLine: true,
          borderColor: REF,
          borderWidth: 1.25,
          borderDash: [4, 4],
          pointRadius: 0,
        },
      ],
    },
    options: baseOptions({
      scales: {
        x: axis("Predicted probability", { min: 0, max: 1 }),
        y: axis("Observed churn rate", { min: 0, max: 1 }),
      },
      interaction: { mode: "nearest", intersect: true },
    }),
  });

  // PR curve.
  const pr = metrics.pr_curve;
  const prPoints = pr.recall.map((x, i) => ({ x, y: pr.precision[i] }));
  const noSkill = metrics.churn_rate;
  new Chart($("pr-chart"), {
    type: "scatter",
    data: {
      datasets: [
        {
          data: prPoints,
          showLine: true,
          borderColor: ACCENT,
          backgroundColor: "rgba(" + ACCENT_RGB + ", 0.08)",
          fill: "origin",
          borderWidth: 2.5,
          pointRadius: 0,
        },
        {
          data: [{ x: 0, y: noSkill }, { x: 1, y: noSkill }],
          showLine: true,
          borderColor: REF,
          borderWidth: 1.25,
          borderDash: [4, 4],
          pointRadius: 0,
        },
      ],
    },
    options: baseOptions({
      scales: {
        x: axis("Recall", { min: 0, max: 1 }),
        y: axis("Precision", { min: 0, max: 1 }),
      },
    }),
  });

  // SHAP horizontal bar, top 10. The two dominant drivers carry the accent.
  fetch("data/shap.json").then((r) => r.json()).then((shap) => {
    const top = shap.feature_importance.slice(0, 10);
    new Chart($("shap-chart"), {
      type: "bar",
      data: {
        labels: top.map((d) => d.feature),
        datasets: [{
          data: top.map((d) => d.mean_abs_shap),
          backgroundColor: top.map((_, i) => (i < 2 ? ACCENT : INK)),
          maxBarThickness: 18,
          borderRadius: 999,
          borderSkipped: false,
        }],
      },
      options: baseOptions({
        indexAxis: "y",
        scales: {
          x: axis("Mean |SHAP value|"),
          y: axis(null, { grid: { display: false }, ticks: { color: INK, font: { size: 12 }, padding: 8 } }),
        },
      }),
    });
  });
}

// ---- Boot ----

Promise.all([
  fetch("data/scored_customers.json").then((r) => r.json()),
  fetch("data/metrics.json").then((r) => r.json()),
]).then(([scored, m]) => {
  metrics = m;
  customers = scored.customers;
  N = customers.length;

  grid = metrics.decision.sensitivity_grid;
  gridCosts = metrics.decision.grid_offer_costs;
  gridRates = metrics.decision.grid_success_rates;

  p = new Float64Array(N);
  v = new Float64Array(N);
  ev = new Float64Array(N);
  order = new Int32Array(N);
  signals = new Array(N);
  for (let i = 0; i < N; i++) {
    p[i] = customers[i].p_churn;
    v[i] = customers[i].value_saved;
    order[i] = i;
    signals[i] = buildSignals(customers[i]);
  }

  // Wire controls.
  ["cost", "rate", "budget"].forEach((id) => {
    $(id).addEventListener("input", markDirty);
  });
  $("show-more").addEventListener("click", () => renderTable(false));
  $("export-csv").addEventListener("click", exportCsv);
  const d = metrics.decision.defaults;
  $("reset").addEventListener("click", () => setControls(d.offer_cost, d.offer_success_rate, d.budget));

  readTheme();
  $("grid-budget").textContent = usd.format(metrics.decision.grid_budget);
  renderMetrics();
  buildHeatTable();
  buildCharts();
  initScrollSpy();

  document.body.classList.remove("is-loading");
  $("status-text").textContent = "Model live · " + int.format(N) + " scored";

  // Initial render at the default assumptions.
  applyControls();
}).catch(() => {
  $("status-text").textContent = "Failed to load scores";
});
