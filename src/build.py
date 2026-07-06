"""Single writer of all three frontend artifacts, run as `python -m src.build`.

This is the only script that produces app/static/data/{scored_customers,metrics,shap}.json.
It is fully deterministic (random_state=42 throughout, no timestamps anywhere), so
running it twice against the same CSV yields byte-identical output. The challenger
OOF probabilities are computed exactly once and reused for the metrics, the decision
layer, and the per-customer scored list, so every number on the frontend traces back
to the same set of out-of-fold calibrated scores.
"""

import json
import os

import numpy as np

from src.data import load_dataset
from src.decision import (
    DEFAULT_BASE_PRODUCT_VALUE,
    DEFAULT_BUDGET,
    DEFAULT_MARGIN_RATE,
    DEFAULT_OFFER_COST,
    DEFAULT_OFFER_SUCCESS_RATE,
    GRID_OFFER_COSTS,
    GRID_SUCCESS_RATES,
    customer_value,
    sensitivity_grid,
)
from src.evaluate import (
    classification_metrics,
    pr_curve_points,
    reliability_curve,
    shap_summary,
)
from src.model import (
    CHALLENGER_NAME,
    build_baseline,
    build_challenger,
    fit_plain_challenger,
    oof_calibrated_predict,
)

OUT_DIR = "app/static/data"


def main():
    X, y, raw_df = load_dataset("data/churn.csv")
    print(f"Loaded {len(raw_df)} rows, churn rate {y.mean():.4f} "
          f"({int(y.sum())} churned / {len(y)} total), challenger backend {CHALLENGER_NAME}")

    # Score both models out of fold. The challenger scores are computed once here
    # and reused for metrics, the decision layer, and the per-customer save list.
    print("Scoring baseline (logistic regression) OOF...")
    baseline_oof = oof_calibrated_predict(X, y, build_baseline)
    print("Scoring challenger (LightGBM) OOF...")
    challenger_oof = oof_calibrated_predict(X, y, build_challenger)

    baseline_metrics = classification_metrics(y, baseline_oof)
    challenger_metrics = classification_metrics(y, challenger_oof)

    reliability = reliability_curve(y, challenger_oof)
    pr_curve = pr_curve_points(y, challenger_oof)

    # SHAP runs on a plain uncalibrated LightGBM, per evaluate.py's contract.
    print("Fitting plain LightGBM and computing SHAP summary...")
    plain = fit_plain_challenger(X, y)
    shap_result = shap_summary(plain, X)

    # Decision layer, all from the challenger OOF scores.
    value_saved = customer_value(raw_df["NumOfProducts"], raw_df["Balance"])
    exited = raw_df["Exited"].to_numpy()

    print("Running sensitivity grid backtest...")
    grid = sensitivity_grid(challenger_oof, value_saved, exited, budget=DEFAULT_BUDGET)

    # The default-scenario backtest is the grid cell at cost 50, success 30%,
    # pulled from the grid list rather than recomputed separately.
    backtest_default = next(
        r for r in grid
        if r["offer_cost"] == DEFAULT_OFFER_COST
        and r["offer_success_rate"] == DEFAULT_OFFER_SUCCESS_RATE
    )
    lift_pcts = [r["lift_pct"] for r in grid]

    # Assemble the three artifacts.
    scored = {
        "meta": {
            "n_customers": len(raw_df),
            "base_product_value": DEFAULT_BASE_PRODUCT_VALUE,
            "margin_rate": DEFAULT_MARGIN_RATE,
            "defaults": {
                "offer_cost": DEFAULT_OFFER_COST,
                "offer_success_rate": DEFAULT_OFFER_SUCCESS_RATE,
                "budget": DEFAULT_BUDGET,
            },
        },
        "customers": [
            {
                "id": int(raw_df["CustomerId"].iat[i]),
                "p_churn": round(float(challenger_oof[i]), 4),
                "value_saved": round(float(value_saved[i]), 2),
                "age": int(raw_df["Age"].iat[i]),
                "geography": str(raw_df["Geography"].iat[i]),
                "num_products": int(raw_df["NumOfProducts"].iat[i]),
                "balance": int(round(float(raw_df["Balance"].iat[i]))),
                "is_active": int(raw_df["IsActiveMember"].iat[i]),
            }
            for i in range(len(raw_df))
        ],
    }

    metrics_out = {
        "challenger_name": CHALLENGER_NAME,
        "n_customers": len(y),
        "churn_rate": float(y.mean()),
        "baseline": baseline_metrics,
        "challenger": challenger_metrics,
        "reliability_curve": reliability,
        "pr_curve": pr_curve,
        "decision": {
            "assumptions": {
                "base_product_value": DEFAULT_BASE_PRODUCT_VALUE,
                "margin_rate": DEFAULT_MARGIN_RATE,
            },
            "defaults": {
                "offer_cost": DEFAULT_OFFER_COST,
                "offer_success_rate": DEFAULT_OFFER_SUCCESS_RATE,
                "budget": DEFAULT_BUDGET,
            },
            "backtest_default": backtest_default,
            "grid_budget": DEFAULT_BUDGET,
            "grid_offer_costs": list(GRID_OFFER_COSTS),
            "grid_success_rates": list(GRID_SUCCESS_RATES),
            "sensitivity_grid": grid,
            "lift_pct_range": [min(lift_pcts), max(lift_pcts)],
        },
    }

    # Sanity asserts before writing anything to disk.
    customers = scored["customers"]
    assert len(customers) == 10000, f"expected 10000 customers, got {len(customers)}"
    assert all(0.0 <= c["p_churn"] <= 1.0 for c in customers), \
        "some p_churn outside [0, 1]"
    assert float(value_saved.min()) >= 120.0, \
        f"value_saved min {value_saved.min()} < 120 (a customer holds < 1 product?)"
    assert len(grid) == 9, f"expected 9 grid cells, got {len(grid)}"
    assert all(r["lift_pct"] is not None for r in grid), \
        "a grid cell has a null lift_pct (Risk baseline was exactly zero)"
    assert backtest_default["ev"]["net_value"] > backtest_default["random"]["net_value_mean"], \
        "EV net value did not beat Random at the default scenario"
    roc = challenger_metrics["roc_auc"]
    brier = challenger_metrics["brier_score"]
    assert 0.84 < roc < 0.88, f"challenger ROC-AUC {roc} outside regression guard 0.84-0.88"
    assert 0.09 < brier < 0.12, f"challenger Brier {brier} outside regression guard 0.09-0.12"

    os.makedirs(OUT_DIR, exist_ok=True)
    # scored_customers.json is ~1MB, so it is minified. The two small config-like
    # artifacts stay indented for human readability.
    with open(os.path.join(OUT_DIR, "scored_customers.json"), "w") as f:
        json.dump(scored, f, separators=(",", ":"))
    with open(os.path.join(OUT_DIR, "metrics.json"), "w") as f:
        json.dump(metrics_out, f, indent=2)
    with open(os.path.join(OUT_DIR, "shap.json"), "w") as f:
        json.dump(shap_result, f, indent=2)

    # Human-readable summary.
    bd = backtest_default
    print("\n=== Build Summary ===")
    print(f"  Challenger OOF: ROC-AUC {roc:.3f}, PR-AUC {challenger_metrics['pr_auc']:.3f} "
          f"(baseline {challenger_metrics['pr_auc_baseline']:.3f}), Brier {brier:.3f}")
    print(f"  Baseline LR:    ROC-AUC {baseline_metrics['roc_auc']:.3f}, "
          f"PR-AUC {baseline_metrics['pr_auc']:.3f}, Brier {baseline_metrics['brier_score']:.3f}")
    print(f"\n  Default scenario (budget ${bd['budget']:,.0f}, cost ${bd['offer_cost']:,.0f}, "
          f"success {bd['offer_success_rate']:.0%}):")
    print(f"    Random ${bd['random']['net_value_mean']:,.0f} "
          f"+/- ${bd['random']['net_value_std']:,.0f}")
    print(f"    Risk   ${bd['risk']['net_value']:,.0f}")
    print(f"    EV     ${bd['ev']['net_value']:,.0f}")
    print(f"    Lift   ${bd['lift_abs']:+,.0f} ({bd['lift_pct']:+.1f}%)")
    print(f"    Offers sent {bd['ev']['n_selected']} of {bd['offers_allowed']} allowed "
          f"out of {len(customers)} customers")
    print(f"\n  Grid lift range across 9 cells: "
          f"{min(lift_pcts):+.1f}% to {max(lift_pcts):+.1f}%")
    print(f"\nWrote scored_customers.json, metrics.json, shap.json to {OUT_DIR}/")


if __name__ == "__main__":
    main()
