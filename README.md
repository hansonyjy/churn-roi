# Churn ROI

A churn model wrapped in a decision engine: given a fixed retention budget, who is worth saving, and what net return should we expect.

## The Core Insight

You do not target the highest-risk customers, you target the highest expected-return customers. A 95 percent risk, low-value customer can be a worse spend than a 60 percent risk, high-value one. Ranking by expected value instead of by raw churn probability is the whole point.

The budget is a cap, not a quota. Given a budget and a uniform offer cost, the most offers you can send is `floor(budget / cost)`, but selection stops earlier the moment expected value goes negative. You never send a negative-EV offer, even with money left over. Under-spending a budget because the remaining options destroy value is itself a finding, not a bug.

## Headline Results

EV-over-Risk lift at a $25,000 budget, across a 3x3 grid of offer economics (dollars and percent, computed on the real data):

| Offer cost | 20% success | 30% success | 40% success |
| ---------- | ----------- | ----------- | ----------- |
| $25 | +$65,334 (+20.9%) | +$98,001 (+20.4%) | +$130,668 (+20.1%) |
| $50 | +$47,659 (+27.3%) | +$71,489 (+26.0%) | +$95,319 (+25.4%) |
| $100 | +$35,065 (+40.7%) | +$52,598 (+37.1%) | +$70,130 (+35.5%) |

EV-based targeting beat risk-based targeting by 20 to 41 percent across the grid at a $25,000 budget.

At the default scenario (budget $25,000, offer cost $50, 30% success rate), EV targeting returned $346,314 in realized net value against $274,825 for risk targeting, a lift of +$71,489 (+26.0%). Random targeting returned only $35,809 (mean over 100 seeds). The budget allowed 500 offers out of 10,000 customers and all 500 cleared positive expected value at these assumptions. As offers get more expensive the negative-EV stop binds sooner and the EV advantage over naive risk targeting widens, which is why the $100 column shows the largest percentage lift.

## Architecture

```
churn.csv
   -> python -m src.build   (train, calibrate, OOF score, backtest)
   -> 3 JSON artifacts committed to git
   -> FastAPI serves static files on Render
   -> sliders recompute EV, ranking, and the budget stop in the browser
```

Training is offline and serving is static. The three artifacts are committed to git and the FastAPI process only hands out files, so there is no model inference on request: the deploy is fast, cheap, and cannot fall over under load.

## Model Notes

Every customer gets a calibrated P(churn) from a model that never saw them. Stratified 5-fold cross-validation fits an isotonically calibrated LightGBM on four folds and scores the held-out fifth, so the save list can cover the whole base with no leakage and the backtest runs on the same out-of-fold probabilities against the true labels. Calibration is not optional here: you cannot multiply an uncalibrated probability by a dollar value and get a real number.

The challenger reaches PR-AUC 0.699 against a 0.204 no-skill baseline (the churn rate itself), ROC-AUC 0.861, and a Brier score of 0.103. The logistic regression baseline manages only PR-AUC 0.464. The tree model wins largely because NumOfProducts is sharply nonlinear and a linear model cannot represent it.

SHAP on a plain LightGBM fit confirms the known quirks: Age is the strongest single driver, NumOfProducts is next and nonlinear (2 products is safest at 7.6% churn, 3 products churns at 82.7%, 4 products at 100%), Germany churns at roughly twice the rate of France and Spain, and about a third of customers hold a zero balance.

## Assumptions, Stated Plainly

The value of saving a customer is a proxy:

```
value_saved = 120 * num_products + 0.02 * balance
```

The $120 per product is an annual relationship value order of magnitude for retail banking (fees, interchange, cross-sell). The 2% is a net interest margin on deposits. Neither is meant to be exact, both are reasonable orders of magnitude and both are documented, configurable assumptions. The per-product term matters: a pure balance proxy would degenerate on the roughly 36% of customers who hold a zero balance, valuing them at zero, so EV targeting would ignore them by construction and the measured lift would be partly an artifact of the proxy.

Incrementality caveat: this targets customers by churn probability, not by persuadability. True incrementality would need uplift modeling and treatment data this dataset does not have. The backtest assumes an offer saves a would-be churner with probability `offer_success_rate` and does nothing for a non-churner. That is a stated simplification, not a claim of causal effect.

## Run It Locally

1. Get `Churn_Modelling.csv` (the classic Kaggle churn dataset) and save it to `data/churn.csv`. This file is gitignored.
2. `pip install -r requirements.txt`
3. `python -m src.build` to train, score, backtest, and write the three JSON artifacts into `app/static/data/`.
4. `uvicorn app.main:app --reload` and open http://localhost:8000.
5. `pytest` to run the decision-math tests.

## Deployment

Deployed on the Render free tier. The build installs only `fastapi` and `uvicorn[standard]`, not the full requirements: the training dependencies are never imported at serve time because the artifacts are already committed, and the CSV is gitignored so Render could not train anyway. This keeps free-tier build minutes low.

The free tier spins down when idle, so the first hit after a quiet period takes about a minute to wake up. Open the link roughly five minutes before a live demo.

## What This Demonstrates

Supervised ML on imbalanced data, probability calibration, out-of-fold rigor with no leakage, decision economics under a budget constraint, and honest causal reasoning about what a churn score can and cannot claim.

## Resume Bullet and Portfolio Blurb

**Resume bullet:**

> Built a churn retention decision engine (calibrated LightGBM, out-of-fold scoring, expected-value budget allocation with a negative-EV stop). EV-based targeting beat risk-based targeting by 20 to 41 percent in backtests across a 3x3 grid of offer economics on 10,000 customers, deployed as an instant client-side what-if tool (FastAPI, vanilla JS, Render).

**Portfolio blurb:**

> The model predicts who will leave, the decision layer decides who is worth saving under a fixed retention budget. Ranking customers by expected value rather than raw risk beat naive risk targeting by 20 to 41 percent across a grid of offer economics on 10,000 customers. A live-slider demo recomputes the ranking, the budget stop, and the projected return in the browser, so you can change the assumptions on the spot.
