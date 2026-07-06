// Churn ROI frontend logic. Everything downstream of the sliders is recomputed
// here in the browser from the committed OOF scores, no server round trip. The
// charts are built once from metrics.json / shap.json and never touched again.

"use strict";

// Cached formatters reused across every render.
const usd = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", maximumFractionDigits: 0,
});
const pct = new Intl.NumberFormat("en-US", {
  style: "percent", maximumFractionDigits: 0,
});

const PAGE = 10;
const GRID_COSTS = [25, 50, 100];
const GRID_RATES = [0.2, 0.3, 0.4];

// State populated on load.
let N = 0;
let p, v, ev, order;   // Float64Array p, v, ev; Int32Array order
let customers = [];    // raw display objects
let why = [];          // precomputed reason strings, slider-independent
let metrics = null;

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

// Static per-customer reason string, computed once at load.
function buildWhy(c) {
  let risk;
  if (c.p_churn >= 0.7) risk = "Very likely to leave";
  else if (c.p_churn >= 0.4) risk = "Elevated churn risk";
  else risk = "Moderate risk";

  let valPhrase;
  if (c.balance >= 100000) valPhrase = "large deposit balance";
  else if (c.num_products >= 2) valPhrase = "multi-product relationship";
  else valPhrase = "single-product customer";

  const quals = [];
  if (c.geography === "Germany") quals.push("Germany");
  if (c.is_active === 0) quals.push("inactive");

  let s = risk + ", " + valPhrase;
  if (quals.length) s += " (" + quals.join(", ") + ")";
  return s;
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

  renderHeadline(sumEV, selected.length, cap);
  renderLift(cost, rate);
  renderTable(true);
}

function renderHeadline(sumEV, sent, cap) {
  document.getElementById("ev-figure").textContent = usd.format(sumEV);
  document.getElementById("offers-figure").textContent =
    sent.toLocaleString("en-US") + " sent of " + cap.toLocaleString("en-US") + " allowed";

  const callout = document.getElementById("offers-callout");
  if (sent < cap) {
    callout.className = "caption callout-negative";
    callout.textContent =
      "The budget allows " + cap.toLocaleString("en-US") + " offers but only " +
      sent.toLocaleString("en-US") + " clear positive expected value. Spending the rest " +
      "would destroy value, so the engine stops.";
  } else {
    callout.className = "caption";
    callout.textContent = "Every allowed offer clears positive expected value.";
  }
}

function renderLift(cost, rate) {
  const nc = nearest(cost, GRID_COSTS);
  const nr = nearest(rate, GRID_RATES);
  const cell = metrics.decision.sensitivity_grid.find(
    (r) => r.offer_cost === nc && r.offer_success_rate === nr
  );
  const line = document.getElementById("lift-line");
  if (!cell) { line.textContent = ""; return; }

  line.textContent =
    "Backtested at the nearest precomputed scenario (cost " + usd.format(cell.offer_cost) +
    ", " + pct.format(cell.offer_success_rate) + " success, " + usd.format(cell.budget) +
    " budget): EV targeting returned " + usd.format(cell.ev.net_value) + " vs " +
    usd.format(cell.risk.net_value) + " for risk targeting, a lift of " +
    signedUsd(cell.lift_abs) + " (" + signedPct1(cell.lift_pct) + ").";
}

// Build the row HTML for selected[start..end).
function rowsHtml(start, end) {
  let html = "";
  for (let r = start; r < end; r++) {
    const idx = selected[r];
    const c = customers[idx];
    const evVal = ev[idx];
    html +=
      "<tr>" +
      "<td>" + (r + 1) + "</td>" +
      "<td>" + c.id + "</td>" +
      "<td>" + (c.p_churn * 100).toFixed(1) + "%</td>" +
      "<td>" + usd.format(c.value_saved) + "</td>" +
      "<td class=\"" + (evVal >= 0 ? "pos" : "neg") + "\">" + signedUsd(evVal) + "</td>" +
      "<td class=\"why\">" + why[idx] + "</td>" +
      "</tr>";
  }
  return html;
}

// reset=true rebuilds from the top 100; reset=false appends the next page.
function renderTable(reset) {
  const body = document.getElementById("save-body");
  if (reset) {
    shown = Math.min(PAGE, selected.length);
    body.innerHTML = rowsHtml(0, shown);
  } else {
    const next = Math.min(shown + PAGE, selected.length);
    body.insertAdjacentHTML("beforeend", rowsHtml(shown, next));
    shown = next;
  }
  document.getElementById("list-caption").textContent =
    "Showing " + shown.toLocaleString("en-US") + " of " +
    selected.length.toLocaleString("en-US") + " selected.";
  document.getElementById("show-more").hidden = shown >= selected.length;
}

// requestAnimationFrame dirty-flag coalescing. Not a timing debounce, just cheap
// insurance against dense input streams collapsing to one recompute per frame.
let dirty = false;
function markDirty() {
  if (dirty) return;
  dirty = true;
  requestAnimationFrame(() => {
    dirty = false;
    const cost = Number(document.getElementById("cost").value);
    const rate = Number(document.getElementById("rate").value);
    const budget = Number(document.getElementById("budget").value);
    document.getElementById("cost-out").textContent = usd.format(cost);
    document.getElementById("rate-out").textContent = pct.format(rate);
    document.getElementById("budget-out").textContent = usd.format(budget);
    recompute(cost, rate, budget);
  });
}

// ---- Charts, built once ----

const SERIES = "#177A53";
const HAIRLINE = "#E4DFD5";
const REF_GRAY = "#A8A297";
const TICK = "#6E6A61";

function baseOptions(extra) {
  const o = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: {
        grid: { color: HAIRLINE, borderDash: [] },
        ticks: { color: TICK, font: { size: 12 } },
      },
      y: {
        grid: { color: HAIRLINE, borderDash: [] },
        ticks: { color: TICK, font: { size: 12 } },
      },
    },
  };
  return Object.assign(o, extra || {});
}

function buildCharts() {
  // Calibration curve.
  const rc = metrics.reliability_curve;
  const calPoints = rc.mean_predicted_value.map((x, i) => ({ x, y: rc.fraction_of_positives[i] }));
  new Chart(document.getElementById("calibration-chart"), {
    type: "scatter",
    data: {
      datasets: [
        {
          data: calPoints,
          showLine: true,
          borderColor: SERIES,
          backgroundColor: SERIES,
          borderWidth: 2,
          pointRadius: 4,
          pointBorderColor: "#FAF7F2",
          pointBorderWidth: 2,
        },
        {
          data: [{ x: 0, y: 0 }, { x: 1, y: 1 }],
          showLine: true,
          borderColor: REF_GRAY,
          borderWidth: 1,
          borderDash: [4, 4],
          pointRadius: 0,
        },
      ],
    },
    options: baseOptions({
      plugins: { legend: { display: false } },
      scales: {
        x: { min: 0, max: 1, title: { display: true, text: "Predicted probability", color: TICK },
             grid: { color: HAIRLINE }, ticks: { color: TICK, font: { size: 12 } } },
        y: { min: 0, max: 1, title: { display: true, text: "Observed churn rate", color: TICK },
             grid: { color: HAIRLINE }, ticks: { color: TICK, font: { size: 12 } } },
      },
      interaction: { mode: "nearest", intersect: true },
    }),
  });

  // PR curve.
  const pr = metrics.pr_curve;
  const prPoints = pr.recall.map((x, i) => ({ x, y: pr.precision[i] }));
  const noSkill = metrics.churn_rate;
  new Chart(document.getElementById("pr-chart"), {
    type: "scatter",
    data: {
      datasets: [
        {
          data: prPoints,
          showLine: true,
          borderColor: SERIES,
          backgroundColor: SERIES,
          borderWidth: 2,
          pointRadius: 0,
        },
        {
          data: [{ x: 0, y: noSkill }, { x: 1, y: noSkill }],
          showLine: true,
          borderColor: REF_GRAY,
          borderWidth: 1,
          borderDash: [4, 4],
          pointRadius: 0,
        },
      ],
    },
    options: baseOptions({
      scales: {
        x: { min: 0, max: 1, title: { display: true, text: "Recall", color: TICK },
             grid: { color: HAIRLINE }, ticks: { color: TICK, font: { size: 12 } } },
        y: { min: 0, max: 1, title: { display: true, text: "Precision", color: TICK },
             grid: { color: HAIRLINE }, ticks: { color: TICK, font: { size: 12 } } },
      },
    }),
  });

  // SHAP horizontal bar, top 10.
  fetch("data/shap.json").then((r) => r.json()).then((shap) => {
    const top = shap.feature_importance.slice(0, 10);
    new Chart(document.getElementById("shap-chart"), {
      type: "bar",
      data: {
        labels: top.map((d) => d.feature),
        datasets: [{
          data: top.map((d) => d.mean_abs_shap),
          backgroundColor: SERIES,
          maxBarThickness: 20,
          borderRadius: 4,
        }],
      },
      options: baseOptions({
        indexAxis: "y",
        scales: {
          x: { title: { display: true, text: "Mean |SHAP Value|", color: TICK },
               grid: { color: HAIRLINE }, ticks: { color: TICK, font: { size: 12 } } },
          y: { grid: { color: HAIRLINE }, ticks: { color: TICK, font: { size: 12 } } },
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

  p = new Float64Array(N);
  v = new Float64Array(N);
  ev = new Float64Array(N);
  order = new Int32Array(N);
  why = new Array(N);
  for (let i = 0; i < N; i++) {
    p[i] = customers[i].p_churn;
    v[i] = customers[i].value_saved;
    order[i] = i;
    why[i] = buildWhy(customers[i]);
  }

  // Wire controls.
  ["cost", "rate", "budget"].forEach((id) => {
    document.getElementById(id).addEventListener("input", markDirty);
  });
  document.getElementById("show-more").addEventListener("click", () => renderTable(false));

  // Fill the performance panel text from the real metrics.
  const ch = metrics.challenger, base = metrics.baseline;
  document.getElementById("perf-line").textContent =
    "PR-AUC " + ch.pr_auc.toFixed(3) + " against a " + ch.pr_auc_baseline.toFixed(3) +
    " no-skill baseline. ROC-AUC " + ch.roc_auc.toFixed(3) + ". Brier " + ch.brier_score.toFixed(3) + ".";
  document.getElementById("perf-baseline").textContent =
    "Logistic regression baseline: PR-AUC " + base.pr_auc.toFixed(3) + ".";

  buildCharts();

  // Initial render at the default assumptions.
  const cost = Number(document.getElementById("cost").value);
  const rate = Number(document.getElementById("rate").value);
  const budget = Number(document.getElementById("budget").value);
  recompute(cost, rate, budget);
});
