# Churn ROI

A customer with a 95 percent chance of leaving can be the wrong customer to save. If they are worth little, the retention offer costs more than it recovers, while a 60 percent risk, high-value customer down the list is a clearly positive bet. This project takes a calibrated churn model and wraps it in the layer most churn projects skip: an expected-value decision engine that decides, under a fixed budget, who is actually worth spending on and what net return to expect.

**Live demo:** [churn-roi.onrender.com](https://churn-roi.onrender.com) (free tier, first load after idle takes about a minute)
**Code:** [github.com/hansonyjy/churn-roi](https://github.com/hansonyjy/churn-roi)

## The Headline Result

Most portfolio projects quote one flattering number. The honest version is a range, so the headline here is a sensitivity grid: EV-based targeting versus risk-based targeting at a $25,000 budget, across a 3x3 grid of offer economics, computed on real out-of-fold predictions against true labels.

| Offer cost | 20% success | 30% success | 40% success |
| ---------- | ----------- | ----------- | ----------- |
| $25 | +$65,334 (+20.9%) | +$98,001 (+20.4%) | +$130,668 (+20.1%) |
| $50 | +$47,659 (+27.3%) | +$71,489 (+26.0%) | +$95,319 (+25.4%) |
| $100 | +$35,065 (+40.7%) | +$52,598 (+37.1%) | +$70,130 (+35.5%) |

EV targeting beat risk targeting by 20 to 41 percent across every cell. The pattern in the grid is itself a finding: as offers get more expensive, the negative-EV stop binds sooner and the EV advantage widens, which is why the $100 row shows the largest percentage lift.

At the default scenario (offer cost $50, 30% success rate), EV targeting returned $346,314 in realized net value against $274,825 for risk targeting and $35,809 for random targeting (mean over 100 seeds).

## The Two Rules That Do the Work

**Rank by expected value, not risk.** For each customer, `EV = P(churn) * value_saved * success_rate - offer_cost`. Sorting the save list by EV instead of raw churn probability is the entire edge over a standard churn model, and it is where all of the lift in the grid comes from.

**The budget is a cap, not a quota.** Selection stops the moment expected value goes negative, even with money left over, because a negative-EV offer destroys value no matter how much budget remains. This rule binds hard in practice: at a $10 offer cost and a $100,000 budget, the budget allows offers to all 10,000 customers, but the engine sends only 6,984 and refuses the other 3,016 because their expected return is below zero. Under-spending a budget is a finding, not a bug, and the demo surfaces it live.

## How It Works

```
churn.csv
   -> python -m src.build   (train, calibrate, OOF score, backtest)
   -> 3 JSON artifacts committed to git
   -> FastAPI serves static files on Render
   -> sliders recompute EV, ranking, and the budget stop in the browser
```

Training is offline, serving is static. The FastAPI process only hands out files, so there is no inference on request and the deploy is fast, cheap, and cannot fall over under load. The sliders (offer cost, success rate, budget) re-rank all 10,000 customers client-side, so changing the assumptions is instant.

## Model Notes

Every customer gets a calibrated P(churn) from a model that never saw them: stratified 5-fold cross-validation fits an isotonically calibrated LightGBM on four folds and scores the held-out fifth. The save list covers the whole base with no leakage, and the backtest runs on the same out-of-fold probabilities against true labels. Calibration is not optional here, because you cannot multiply an uncalibrated probability by a dollar value and get a real number.

The calibrated LightGBM reaches PR-AUC 0.699 against a 0.204 no-skill baseline (the churn rate itself), ROC-AUC 0.861, and a Brier score of 0.103. The logistic regression baseline manages PR-AUC 0.464. The tree model wins largely because NumOfProducts is sharply nonlinear: 2 products is the safest group at 7.6% churn, 3 products churns at 82.7%, and 4 products at 100%, a shape no linear model can represent. SHAP on a plain LightGBM fit confirms the rest of the story: Age is the strongest single driver, and Germany churns at roughly twice the rate of France and Spain.

## Assumptions, Stated Plainly

The value of saving a customer is a proxy:

```
value_saved = 120 * num_products + 0.02 * balance
```

The $120 per product is an annual relationship value order of magnitude for retail banking (fees, interchange, cross-sell); the 2% is a net interest margin on deposits. Both are documented, configurable, and meant as reasonable orders of magnitude, not exact figures. The per-product term is load-bearing: about 36% of customers hold a zero balance, so a pure balance proxy would value them at zero, EV targeting would ignore them by construction, and the measured lift would be partly an artifact of the proxy.

Incrementality caveat: this targets by churn probability, not persuadability. True incrementality needs uplift modeling and treatment data this dataset does not have. The backtest assumes an offer saves a would-be churner with probability `offer_success_rate` and does nothing for a non-churner, a stated simplification, not a claim of causal effect.

## Run It Locally

1. Get `Churn_Modelling.csv` (the classic Kaggle churn dataset) and save it to `data/churn.csv`. This file is gitignored.
2. `pip install -r requirements.txt`
3. `python -m src.build` to train, score, backtest, and write the three JSON artifacts into `app/static/data/`.
4. `uvicorn app.main:app --reload` and open http://localhost:8000.
5. `pytest` to run the decision-math tests.

## Deployment

Deployed on the Render free tier. The build installs only `fastapi` and `uvicorn[standard]`: the artifacts are already committed and the CSV is gitignored, so nothing trains at deploy time and free-tier build minutes stay low. The free tier spins down when idle, so the first hit after a quiet period takes about a minute. Open the link five minutes before a live demo.

## What This Demonstrates

Supervised ML on imbalanced data, probability calibration, out-of-fold rigor with no leakage, decision economics under a budget constraint, and honest causal reasoning about what a churn score can and cannot claim.

## Resume Bullet and Portfolio Blurb

**Resume bullet:**

> Built a churn retention decision engine (calibrated LightGBM, out-of-fold scoring, expected-value budget allocation with a negative-EV stop). EV-based targeting beat risk-based targeting by 20 to 41 percent in backtests across a 3x3 grid of offer economics on 10,000 customers, deployed as an instant client-side what-if tool (FastAPI, vanilla JS, Render).

**Portfolio blurb:**

> The model predicts who will leave; the decision layer decides who is worth saving under a fixed retention budget. Ranking customers by expected value rather than raw risk beat naive risk targeting by 20 to 41 percent across a grid of offer economics on 10,000 customers. A live-slider demo recomputes the ranking, the budget stop, and the projected return in the browser, so you can change the assumptions on the spot.
