"""Baseline logistic regression, LightGBM challenger, isotonic calibration,
and out-of-fold scoring for the full customer base.

Every downstream number (metrics, SHAP, decision engine) is computed from the
OOF calibrated probabilities produced here, never from in-fold predictions.
"""

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

try:
    from lightgbm import LGBMClassifier
    CHALLENGER_NAME = "lightgbm"
except ImportError:
    from sklearn.ensemble import HistGradientBoostingClassifier as LGBMClassifier
    CHALLENGER_NAME = "histgradientboosting"

RANDOM_STATE = 42
N_SPLITS = 5


def build_baseline() -> Pipeline:
    """Logistic regression on scaled features, for interpretability."""
    return Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=1000, random_state=RANDOM_STATE)),
    ])


def build_challenger():
    """LightGBM, falling back to HistGradientBoostingClassifier if unavailable."""
    if CHALLENGER_NAME == "lightgbm":
        return LGBMClassifier(random_state=RANDOM_STATE, verbose=-1)
    return LGBMClassifier(random_state=RANDOM_STATE)


def oof_calibrated_predict(X: pd.DataFrame, y: pd.Series, build_estimator) -> np.ndarray:
    """Stratified 5-fold OOF scoring with isotonic calibration.

    For each outer fold, the estimator is fit and calibrated on the other four
    folds only (calibration itself uses an inner CV split within that training
    data), then scores the held-out fold. Every row ends up scored by a model
    that never saw it during fitting or calibration.
    """
    X = X.reset_index(drop=True)
    y = y.reset_index(drop=True)
    oof_proba = np.zeros(len(y))

    skf = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    for train_idx, test_idx in skf.split(X, y):
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train = y.iloc[train_idx]

        estimator = build_estimator()
        calibrated = CalibratedClassifierCV(estimator, method="isotonic", cv=5)
        calibrated.fit(X_train, y_train)

        oof_proba[test_idx] = calibrated.predict_proba(X_test)[:, 1]

    return oof_proba


def fit_plain_challenger(X: pd.DataFrame, y: pd.Series):
    """Uncalibrated LightGBM fit on all data, for SHAP only.

    TreeExplainer does not accept a CalibratedClassifierCV wrapper, so this
    model exists solely to explain feature importance. It is never used for
    scoring or the decision layer, only evaluate.py's SHAP summary.
    """
    model = build_challenger()
    model.fit(X, y)
    return model
