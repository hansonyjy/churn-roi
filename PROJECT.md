# Churn ROI

A churn prediction model wrapped in a decision engine. The model predicts who will leave. The decision layer answers the question a model alone can't: given a fixed retention budget, which customers should we spend on, and what net return should we expect. The headline output is a ranked save list with dollars attached, not an AUC score.

This is a portfolio project. Every reported number must be real, computed on real data without leakage, and defensible in an interview. Do not fabricate metrics or hardcode results.

## Non-Negotiables (Read First)

- **No em-dashes anywhere.** Not in code comments, not in the README, not in UI copy. Use commas, periods, or parentheses.
- **Title Case for headings, never all-caps.**
- **Clean, minimal, editorial-finance aesthetic** for the frontend. Match the look of hansonyjy.github.io: restrained palette, serif or refined sans display type, generous whitespace, understated. It should read like a research note, not a dashboard template. It must also be readable on a phone, because recruiters click portfolio links on phones.
- **Custom frontend, not Streamlit.** FastAPI backend serving a static HTML/CSS/JS frontend.
- **Every metric is real.** Compute on the actual CSV. If a number can't be computed yet, leave a clearly labeled TODO, do not invent it.
- Concise, conversational tone in all writing.

## Decisions Already Made (Do Not Relitigate)

- Dataset: the classic Churn_Modelling.csv at `data/churn.csv`, gitignored.
- Models: logistic regression baseline, LightGBM challenger, isotonic calibration.
- Scoring: out-of-fold calibrated probabilities for the entire customer base (details below).
- Value proxy: base relationship value per product plus a balance margin component (details below).
- Selection rule: budget is a cap, not a quota. Never select negative-EV customers.
- Headline result: a sensitivity grid of EV-over-Risk lift, not a single number.
- Deploy: train locally, commit the JSON artifacts, Render serves static. No training on Render.
- Charts: Chart.js from a CDN. Nothing heavier.

## Dataset (Schema Is Known, Confirm On Load)

Churn_Modelling.csv, 10,000 rows, 14 columns: RowNumber, CustomerId, Surname, CreditScore, Geography, Gender, Age, Tenure, Balance, NumOfProducts, HasCrCard, IsActiveMember, EstimatedSalary, Exited. Target is `Exited` (1 = churned). Class balance is roughly 7,963 stayers to 2,037 churners, about 20 percent churn. Drop RowNumber, CustomerId, Surname from features. No missing values expected, but check.

Known quirks to confirm rather than rediscover, and to use in the SHAP writeup:

- Roughly a third of customers have Balance = 0. This matters for the value proxy (see Phase 2).
- NumOfProducts is nonlinear: customers with 3 or 4 products churn at very high rates, 2 products is the safest group. Tree models catch this, the linear baseline won't, which is a good baseline-vs-challenger talking point.
- Germany churns at roughly twice the rate of France and Spain.
- Age is typically the strongest single driver.

If the actual file deviates from this schema, stop and flag it before building on top.

## Architecture Overview

Training is offline. Serving is static. This keeps the deployed app fast and cheap and is itself an interview talking point.

1. A build step (`python -m src.build`) trains, scores every customer out-of-fold, runs the backtest and sensitivity grid, and writes JSON artifacts into `app/static/data/`.
2. The FastAPI app serves the frontend and those artifacts. No inference on request.
3. The sliders (offer cost, offer success rate, budget) recompute expected value and re-rank the save list entirely client-side in JavaScript from the per-customer calibrated probability and value shipped in the JSON. The demo is instant and the user can say "let me change the assumptions live" in an interview.

## File Structure

```
churn-roi/
├── README.md
├── PROJECT.md
├── requirements.txt
├── .gitignore                    (ignores data/churn.csv, NOT app/static/data/)
├── render.yaml
├── data/
│   └── churn.csv                 (user-provided, gitignored)
├── src/
│   ├── data.py                   load, validate schema, feature prep
│   ├── model.py                  baseline LR, LightGBM, calibration, OOF scoring
│   ├── evaluate.py               metrics, calibration curve, SHAP
│   ├── decision.py               value proxy, EV, budget-capped selection, backtest, sensitivity grid
│   └── build.py                  orchestrates everything, writes artifacts to app/static/data/
├── app/
│   ├── main.py                   FastAPI, serves frontend and artifacts
│   └── static/
│       ├── index.html
│       ├── style.css
│       ├── app.js                sliders, live EV recompute, charts
│       └── data/                 generated artifacts, committed to git
│           ├── scored_customers.json
│           ├── metrics.json
│           └── shap.json
└── tests/
    └── test_decision.py          EV math, budget cap, negative-EV exclusion, backtest sanity
```

## Phase 1: Modeling Core

Table stakes, done properly. Clean enough that nobody can poke a hole in it. Not the differentiator.

- `data.py`: load, validate the schema above, drop identifiers, one-hot Geography, binary-encode Gender, no missing-value surprises.
- `model.py`:
  - Baseline: logistic regression on scaled features, for interpretability and the coefficient story.
  - Challenger: LightGBM. Fallback to sklearn HistGradientBoostingClassifier only if LightGBM refuses to install.
  - **Calibration is required.** You cannot multiply an uncalibrated probability by a dollar value and get a real number. Use isotonic calibration (enough data at n=10,000).
  - **Out-of-fold scoring for everything downstream.** Use stratified 5-fold CV: for each fold, fit the calibrated challenger on the other four folds and score the held-out fold. Result: every one of the 10,000 customers has a calibrated P(churn) from a model that never saw them. The save list can then cover the whole customer base with no leakage, and the backtest runs on the same OOF probabilities against true labels. Fixed random_state throughout for reproducibility.
- `evaluate.py`:
  - Report ROC-AUC and PR-AUC computed on the OOF predictions. Lead with PR-AUC because churn is imbalanced and accuracy would mislead. Baseline PR-AUC reference is the churn rate itself, about 0.20, state that.
  - Brier score as the calibration headline number, plus reliability-diagram data for the calibration curve.
  - Confusion matrix at a stated threshold.
  - **SHAP runs on a plain LightGBM fit, not on the calibrated wrapper.** TreeExplainer does not accept CalibratedClassifierCV. Fit one uncalibrated LightGBM on all data purely for the SHAP summary and say so in a comment. Expect the NumOfProducts nonlinearity, the Germany effect, and Age dominance to show up, and write the short "what drives churn" readout around what actually appears.
- Write metrics and curve data to `metrics.json` and `shap.json`.

**Checkpoint: print the real OOF metrics and stop for review before Phase 2.**

## Phase 2: Decision Engine (The Actual Project)

This is where the work lives. Five moves most candidates never make.

**1. Calibrated OOF probabilities feed everything.** The decision layer must never touch raw scores or in-fold predictions.

**2. Customer value, without the degenerate case.** A pure balance proxy fails here: about a third of customers have Balance = 0, so `margin * Balance` values them at zero and EV targeting would ignore them by construction. That would make the EV-over-Risk lift partly an artifact of the proxy and an interviewer could catch it. Instead:

```
value_saved_i = base_product_value * NumOfProducts_i + margin_rate * Balance_i
```

Defaults: `base_product_value = 120` (annual relationship value per product held, covering fees, interchange, cross-sell), `margin_rate = 0.02` (net interest margin on deposits). Both are documented, configurable assumptions stated plainly in the README as simplifications, with one sentence on why each default is a reasonable order of magnitude for retail banking. The point is not the exact numbers, it is that zero-balance multi-product customers still carry real value and the decision layer knows it.

**3. Expected value targeting, not risk targeting.** For each customer:

```
EV_i = P(churn)_i * value_saved_i * offer_success_rate - offer_cost
```

The core insight of the whole project: you do not target the highest-risk customers, you target the highest expected-return customers. A 95 percent risk, low-value customer can be a worse spend than a 60 percent risk, high-value one. Ranking by EV instead of by risk is the point.

**4. Budget as a cap, not a quota.** Given budget B and uniform offer cost c, the maximum number of offers is `floor(B / c)`, but selection stops earlier if EV goes negative. Never spend on a customer whose expected return is below zero, even with budget left over. Under-spending a budget because the remaining options destroy value is itself a finding, and the frontend should surface it ("budget allows 400 offers, only 312 are worth sending"). This one rule is a strong interview moment.

**5. Honest incrementality caveat, in code comments and README.** Targeting by P(churn) is not the same as targeting persuadable customers. True incrementality needs uplift modeling and treatment data this dataset does not have. The backtest assumes an offer saves a would-be churner with probability `offer_success_rate` and does nothing for non-churners, a stated simplification. Say this explicitly rather than overclaiming. It signals real understanding of causal inference and lands better than pretending.

**The backtest.** On the full base with OOF probabilities and true `Exited` labels, compare three strategies at the same budget:

- **Random:** eligible-count customers at random, mean over 100 seeds.
- **Risk:** top customers by P(churn) up to the offer cap.
- **EV:** EV-ranked selection with the negative-EV stop.

Realized net value of a strategy:

```
NetValue = sum over selected customers of [ (Exited_i == 1 ? value_saved_i * offer_success_rate : 0) - offer_cost ]
```

You pay `offer_cost` for every offer sent, and you recover value only from customers who truly would have churned, discounted by `offer_success_rate`. Document that interpretation.

**The headline result is a sensitivity grid, not one number.** Compute the EV-over-Risk lift (absolute dollars and percent) across a small grid of assumptions, for example offer cost in {25, 50, 100} crossed with success rate in {0.2, 0.3, 0.4} at a fixed budget. Report the full grid in `metrics.json` and the README. The resume bullet quotes the grid honestly, for example "EV-based targeting outperformed risk-based targeting by X to Y percent across a range of offer economics." A range is more defensible than a cherry-picked point, and if some cells show small or negative lift, that is a finding to explain (when offers are cheap and customers are homogeneous in value, risk and EV converge), not a failure to hide.

`decision.py` exposes clean, unit-testable functions: `customer_value(...)`, `expected_value(...)`, `select_under_budget(...)`, `backtest(...)`, `sensitivity_grid(...)`. `tests/test_decision.py` checks the EV formula on hand-computed cases, confirms selection never exceeds the budget, confirms no selected customer has negative EV, and confirms EV beats Random on the real data at default assumptions (a sanity floor computed live, never hardcoded).

**Checkpoint: print the real backtest and grid results and stop for review before Phase 3.**

## Phase 3: Frontend and Deploy

**Frontend (`app/static/`).** Editorial-finance research-note aesthetic matching hansonyjy.github.io, readable on mobile. Sections:

- A short header framing the tool as a retention allocation decision, not a churn score.
- **Three controls:** offer cost, offer success rate, total budget. Sliders or clean numeric inputs with sensible ranges and formatted values.
- **The headline block:** projected net return at current settings, offers sent versus offers the budget allows (surfacing the negative-EV stop), and the EV-over-Risk lift at the nearest grid point.
- **The save list:** selected customers ranked by EV, updating live. Show P(churn), customer value, EV, and a one-line reason they made the cut. Recompute entirely in `app.js` from `scored_customers.json`, no server round trip. With 10,000 rows and simple arithmetic this is instant, render the top slice and virtualize or paginate the rest.
- **A performance panel** so rigor is visible, not just claimed: calibration curve, PR curve, SHAP feature summary, Brier score. Chart.js from CDN, keep it minimal.

Keep the JavaScript readable and dependency-light. Ship only the fields the frontend needs per customer (an anonymized id, P(churn), value components, and the few display features), not the full feature rows.

**Backend (`app/main.py`).** FastAPI serves the static frontend and artifacts. No inference endpoint. Minimal.

**Deploy.** Train locally, commit the three JSON artifacts, and let Render serve them statically. The CSV is gitignored so Render cannot train, and free-tier build minutes should not be spent on it anyway. `render.yaml` with a plain uvicorn start command, matching the Starbucks app pattern. Note in the README that Render free tier spins down when idle, so the first hit after a quiet period takes about a minute, worth knowing before a live interview demo (open the link five minutes early).

**README.** Doubles as the portfolio writeup. Include: one-line pitch, the core insight (EV over risk, budget as cap), an architecture diagram (offline training to static serving to client-side recompute), the sensitivity grid with the honest range, how to run locally, the value and incrementality assumptions stated plainly, and a short "what this demonstrates" section (supervised ML, calibration, out-of-fold rigor, decision economics, honest causal reasoning).

## Deliverables Checklist

- [ ] Phase 1: OOF calibrated scoring for all 10,000 customers, real metrics, SHAP readout
- [ ] Phase 2: value proxy without the zero-balance degeneracy, EV engine, budget-cap selection with negative-EV stop, three-way backtest, sensitivity grid
- [ ] Phase 3: custom editorial frontend with live sliders and the offers-sent-vs-allowed readout, performance panel, Render config
- [ ] README as portfolio writeup with architecture diagram and honest caveats
- [ ] Tests passing on decision math, budget cap, and negative-EV exclusion
- [ ] A suggested resume bullet and a short portfolio blurb, both quoting the real grid range

## Suggested Order Of Work

1. `data.py`, confirm schema and class balance match the numbers above.
2. Baseline LR, LightGBM, isotonic calibration, OOF scoring. Print real OOF metrics. **Stop for review.**
3. `evaluate.py` with PR-AUC leading, Brier score, calibration curve, SHAP on the plain LightGBM.
4. `decision.py`: value proxy, EV, capped selection, backtest, sensitivity grid. Print the real grid. **Stop for review.**
5. Tests on the decision math.
6. `build.py` emitting the three artifacts.
7. Frontend wired to the artifacts, sliders recomputing live, mobile check.
8. Render config, README, resume and portfolio copy.

The two stop-for-review checkpoints are where a wrong turn is expensive: a calibration mistake or a backtest bug would undermine the "every number is real" pitch, so those get human eyes before anything is built on top of them.
