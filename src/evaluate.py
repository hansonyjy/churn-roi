"""Metrics, calibration curve, and SHAP summary computed on OOF predictions.

PR-AUC leads over ROC-AUC because churn is imbalanced (~20% positive rate);
a model that predicts the majority class everywhere still gets a deceptively
high ROC-AUC-adjacent read, whereas PR-AUC is judged against the churn rate
itself as the no-skill baseline.
"""

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    roc_auc_score,
)
from sklearn.calibration import calibration_curve


def classification_metrics(y_true: np.ndarray, y_proba: np.ndarray, threshold: float = 0.5) -> dict:
    y_true = np.asarray(y_true)
    y_proba = np.asarray(y_proba)
    y_pred = (y_proba >= threshold).astype(int)

    tn, fp, fn, tp = confusion_matrix(y_true, y_pred).ravel()
    churn_rate = float(y_true.mean())

    return {
        "roc_auc": float(roc_auc_score(y_true, y_proba)),
        "pr_auc": float(average_precision_score(y_true, y_proba)),
        "pr_auc_baseline": churn_rate,
        "brier_score": float(brier_score_loss(y_true, y_proba)),
        "threshold": threshold,
        "confusion_matrix": {
            "true_negative": int(tn),
            "false_positive": int(fp),
            "false_negative": int(fn),
            "true_positive": int(tp),
        },
        "churn_rate": churn_rate,
        "n": len(y_true),
    }


def reliability_curve(y_true: np.ndarray, y_proba: np.ndarray, n_bins: int = 10) -> dict:
    fraction_of_positives, mean_predicted_value = calibration_curve(
        y_true, y_proba, n_bins=n_bins, strategy="quantile"
    )
    return {
        "mean_predicted_value": [float(v) for v in mean_predicted_value],
        "fraction_of_positives": [float(v) for v in fraction_of_positives],
    }


def pr_curve_points(y_true: np.ndarray, y_proba: np.ndarray) -> dict:
    from sklearn.metrics import precision_recall_curve

    precision, recall, _ = precision_recall_curve(y_true, y_proba)
    # Downsample for a lightweight frontend chart; keep endpoints.
    step = max(1, len(precision) // 200)
    return {
        "precision": [float(v) for v in precision[::step]],
        "recall": [float(v) for v in recall[::step]],
    }


def shap_summary(model, X: pd.DataFrame, max_display: int = 15) -> dict:
    """Mean |SHAP value| per feature from a plain (uncalibrated) LightGBM fit.

    Only for the "what drives churn" readout, not used for scoring.
    """
    import shap

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X)

    # Binary classifiers: some SHAP/model combinations return a list of two
    # arrays (per class); we want the positive (churn) class contribution.
    if isinstance(shap_values, list):
        shap_values = shap_values[1]
    elif shap_values.ndim == 3:
        shap_values = shap_values[:, :, 1]

    mean_abs = np.abs(shap_values).mean(axis=0)
    order = np.argsort(mean_abs)[::-1][:max_display]

    features = X.columns.tolist()
    return {
        "feature_importance": [
            {"feature": features[i], "mean_abs_shap": float(mean_abs[i])}
            for i in order
        ],
    }
