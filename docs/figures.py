"""Generate the README's SVG figures from the committed metrics.json, so the
numbers in the pictures can never drift from the numbers in the data.

Run after `python -m src.build`:  python docs/figures.py
Standard library only."""

import json
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)
m = json.load(open(f"{ROOT}/app/static/data/metrics.json"))
d = m["decision"]

PAPER, SURF, SURF2 = "#f6f5f0", "#fdfdfb", "#eeede6"
INK, INK2, MUTED, LINE = "#14261f", "#3f4f48", "#6b7771", "#dcdcd3"
ACC, ACC_INK, AMBER = "#0f8f62", "#0b6e4b", "#f2b632"
SANS = "Archivo, -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

def usd(x):
    return ("-" if x < 0 else "") + "$" + f"{abs(round(x)):,}"

def k(x):
    return ("+" if x >= 0 else "-") + "$" + (f"{abs(x)/1000:.1f}K" if abs(x) < 100000 else f"{abs(x)/1000:.0f}K")

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# ---------------- Sensitivity grid ----------------
grid = d["sensitivity_grid"]
costs, rates = d["grid_offer_costs"], d["grid_success_rates"]
lifts = [c["lift_pct"] for c in grid]
lo, hi = min(lifts), max(lifts)
cell = lambda c, r: next(g for g in grid if g["offer_cost"] == c and g["offer_success_rate"] == r)
b = d["backtest_default"]

W, H = 1200, 560
s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="t d">']
alt = "; ".join(f"cost ${int(c['offer_cost'])} at {int(c['offer_success_rate']*100)}% success: +{c['lift_pct']:.1f}% ({k(c['lift_abs'])})" for c in grid)
s.append(f'<title id="t">EV targeting beat risk targeting in all 9 scenarios</title><desc id="d">Lift of EV targeting over risk targeting at a ${int(d["grid_budget"]):,} budget. {alt}. At the default scenario EV returned {usd(b["ev"]["net_value"])}, risk {usd(b["risk"]["net_value"])}, random {usd(b["random"]["net_value_mean"])}.</desc>')
s.append(f'<rect width="{W}" height="{H}" rx="18" fill="{PAPER}"/>')
s.append(f'<text x="48" y="64" font-family="{MONO}" font-size="15" fill="{ACC_INK}">Backtest · out-of-fold predictions against true labels · ${int(d["grid_budget"]):,} budget</text>')
s.append(f'<text x="48" y="106" font-family="{SANS}" font-size="34" font-weight="800" letter-spacing="-1" fill="{INK}">EV targeting beat risk targeting in all 9 scenarios</text>')

# Heat grid, left
gx, gy, cw, ch, gap = 150, 176, 168, 98, 10
s.append(f'<text x="{gx - 104}" y="{gy - 22}" font-family="{MONO}" font-size="13" fill="{MUTED}">Offer cost</text>')
s.append(f'<text x="{gx + (cw * 3 + gap * 2) / 2}" y="{gy - 46}" text-anchor="middle" font-family="{MONO}" font-size="13" fill="{MUTED}">Offer success rate</text>')
for j, r in enumerate(rates):
    s.append(f'<text x="{gx + j * (cw + gap) + cw / 2}" y="{gy - 16}" text-anchor="middle" font-family="{MONO}" font-size="15" fill="{INK2}">{int(r * 100)}%</text>')
for i, c in enumerate(costs):
    y = gy + i * (ch + gap)
    s.append(f'<text x="{gx - 104}" y="{y + ch / 2 + 6}" font-family="{MONO}" font-size="16" fill="{INK2}">${int(c)}</text>')
    for j, r in enumerate(rates):
        g = cell(c, r)
        t = (g["lift_pct"] - lo) / (hi - lo)
        x = gx + j * (cw + gap)
        default = c == b["offer_cost"] and r == b["offer_success_rate"]
        s.append(f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="12" fill="{ACC}" fill-opacity="{0.10 + t * 0.48:.3f}"' + (f' stroke="{INK}" stroke-width="2.5"' if default else '') + '/>')
        s.append(f'<text x="{x + cw / 2}" y="{y + 50}" text-anchor="middle" font-family="{SANS}" font-size="27" font-weight="800" letter-spacing="-0.5" fill="{INK}">+{g["lift_pct"]:.1f}%</text>')
        s.append(f'<text x="{x + cw / 2}" y="{y + 76}" text-anchor="middle" font-family="{MONO}" font-size="14" fill="{INK2}">{k(g["lift_abs"])}</text>')
s.append(f'<text x="{gx - 104}" y="{H - 40}" font-family="{SANS}" font-size="15" fill="{MUTED}">Pricier offers make the negative-EV stop bind sooner, so the advantage widens. Outlined: the default scenario.</text>')

# Strategy bars, right
bx, by, bw = 760, 176, 392
s.append(f'<rect x="{bx - 28}" y="{by - 40}" width="{bw + 56}" height="330" rx="14" fill="{SURF}" stroke="{LINE}"/>')
s.append(f'<text x="{bx}" y="{by - 8}" font-family="{SANS}" font-size="17" font-weight="700" fill="{INK}">Net value at the default scenario</text>')
s.append(f'<text x="{bx}" y="{by + 16}" font-family="{MONO}" font-size="13" fill="{MUTED}">${int(b["offer_cost"])} offer · {int(b["offer_success_rate"] * 100)}% success · {b["offers_allowed"]} offers</text>')
rows = [("EV targeting", b["ev"]["net_value"], ACC), ("Risk targeting", b["risk"]["net_value"], INK), ("Random, mean of 100 seeds", b["random"]["net_value_mean"], "#a3aaa6")]
mx = max(v for _, v, _ in rows)
for n, (name, val, col) in enumerate(rows):
    y = by + 58 + n * 66
    s.append(f'<text x="{bx}" y="{y}" font-family="{SANS}" font-size="16" fill="{INK}">{name}</text>')
    s.append(f'<text x="{bx + bw}" y="{y}" text-anchor="end" font-family="{MONO}" font-size="16" font-weight="600" fill="{INK}">{usd(val)}</text>')
    s.append(f'<rect x="{bx}" y="{y + 12}" width="{bw}" height="14" rx="7" fill="{SURF2}"/>')
    s.append(f'<rect x="{bx}" y="{y + 12}" width="{max(val, 0) / mx * bw:.1f}" height="14" rx="7" fill="{col}"/>')
s.append(f'<text x="{bx}" y="{by + 270}" font-family="{SANS}" font-size="16" fill="{INK2}">EV over risk: <tspan font-weight="700" fill="{ACC_INK}">+{usd(b["lift_abs"])} (+{b["lift_pct"]:.1f}%)</tspan></text>')
s.append('</svg>')
open(f"{ROOT}/docs/img/sensitivity.svg", "w").write("\n".join(s))

# ---------------- Architecture ----------------
W, H = 1200, 470
a = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="at ad">']
a.append('<title id="at">Architecture: offline training, static serving, in-browser decisions</title>')
a.append('<desc id="ad">Offline: churn.csv goes into python -m src.build, which runs 5-fold out-of-fold calibrated LightGBM scoring, the backtest and the sensitivity grid, and writes three JSON artifacts committed to git. Online: FastAPI on Render only serves static files. In the browser, the sliders recompute EV for all 10,000 customers, rank by EV, and stop at the budget cap or when EV reaches zero, producing the save list.</desc>')
a.append(f'<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{INK2}"/></marker></defs>')
a.append(f'<rect width="{W}" height="{H}" rx="18" fill="{PAPER}"/>')
# zones
a.append(f'<rect x="32" y="56" width="540" height="382" rx="14" fill="none" stroke="{LINE}" stroke-dasharray="6 6"/>')
a.append(f'<text x="56" y="44" font-family="{MONO}" font-size="14" fill="{MUTED}">Offline, once, on a laptop</text>')
a.append(f'<rect x="604" y="56" width="564" height="382" rx="14" fill="none" stroke="{ACC}" stroke-opacity="0.45" stroke-dasharray="6 6"/>')
a.append(f'<text x="628" y="44" font-family="{MONO}" font-size="14" fill="{ACC_INK}">Online, every visit</text>')

def box(x, y, w, h, title, lines, kind="plain"):
    fill, stroke, tcol, lcol = {"plain": (SURF, LINE, INK, INK2), "dark": (INK, INK, PAPER, "#b7c4be"), "accent": ("#e3f1ea", ACC, ACC_INK, INK2)}[kind]
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{stroke}"/>',
           f'<text x="{x + 18}" y="{y + 32}" font-family="{SANS}" font-size="18" font-weight="700" fill="{tcol}">{esc(title)}</text>']
    for n, ln in enumerate(lines):
        out.append(f'<text x="{x + 18}" y="{y + 58 + n * 22}" font-family="{MONO}" font-size="13" fill="{lcol}">{esc(ln)}</text>')
    return out

a += box(56, 84, 220, 96, "churn.csv", ["10,000 customers", "gitignored, never deployed"])
a += box(56, 222, 492, 142, "python -m src.build", ["5-fold out-of-fold scoring", "isotonic-calibrated LightGBM", "backtest: EV vs risk vs random", "3x3 sensitivity grid, SHAP"], "dark")
a += box(316, 84, 232, 96, "3 JSON artifacts", ["scored_customers.json", "metrics.json, shap.json"])
a.append(f'<text x="56" y="414" font-family="{SANS}" font-size="14" fill="{MUTED}">Training never runs on the server. The artifacts are committed to git.</text>')

a += box(628, 84, 250, 96, "FastAPI on Render", ["static files + gzip", "no inference endpoint"])
a += box(628, 222, 516, 186, "Your browser, on every slider move", [
    "EV = P(churn) × value × success − cost",
    "for all 10,000 customers",
    "rank by EV, not by risk",
    "stop at the budget cap or EV ≤ 0",
    "→ save list, KPIs, backtest grid"], "accent")
a += box(910, 84, 234, 96, "Commit to main", ["Render auto-deploys", "/api/health for uptime"])

arrows = [((166, 180), (166, 222)), ((420, 222), (420, 180)), ((548, 132), (628, 132)), ((753, 180), (753, 222)), ((910, 132), (878, 132))]
for (x1, y1), (x2, y2) in arrows:
    a.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2 - (4 if y2 > y1 else -4) if x1 == x2 else y2}" stroke="{INK2}" stroke-width="2" marker-end="url(#ar)"/>')
a.append('</svg>')
open(f"{ROOT}/docs/img/architecture.svg", "w").write("\n".join(a))
print("ok")
