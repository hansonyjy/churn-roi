"""Load churn.csv, validate against the documented schema, and prepare features."""

import pandas as pd

DOCUMENTED_COLUMNS = [
    "RowNumber", "CustomerId", "Surname", "CreditScore", "Geography", "Gender",
    "Age", "Tenure", "Balance", "NumOfProducts", "HasCrCard", "IsActiveMember",
    "EstimatedSalary", "Exited",
]

ID_COLUMNS = ["RowNumber", "CustomerId", "Surname"]
TARGET = "Exited"

EXPECTED_ROWS = 10000
EXPECTED_CHURN_RATE_LOW = 0.19
EXPECTED_CHURN_RATE_HIGH = 0.21


def load_raw(path: str = "data/churn.csv") -> pd.DataFrame:
    df = pd.read_csv(path)

    extra_columns = [c for c in df.columns if c not in DOCUMENTED_COLUMNS]
    if extra_columns:
        # The public Kaggle CSV has variants with extra columns beyond the documented
        # schema, including a "Complain" column that duplicates Exited in ~99.9% of
        # rows (target leakage). Per PROJECT.md, only the documented 14 columns are
        # used as features; anything else is dropped here rather than silently kept.
        df = df[DOCUMENTED_COLUMNS]

    missing_columns = [c for c in DOCUMENTED_COLUMNS if c not in df.columns]
    if missing_columns:
        raise ValueError(f"CSV is missing documented columns: {missing_columns}")

    if len(df) != EXPECTED_ROWS:
        raise ValueError(f"Expected {EXPECTED_ROWS} rows, found {len(df)}")

    if df.isnull().any().any():
        null_cols = df.columns[df.isnull().any()].tolist()
        raise ValueError(f"Unexpected missing values in columns: {null_cols}")

    churn_rate = df[TARGET].mean()
    if not (EXPECTED_CHURN_RATE_LOW <= churn_rate <= EXPECTED_CHURN_RATE_HIGH):
        raise ValueError(f"Churn rate {churn_rate:.3f} outside expected 0.19-0.21 range")

    return df.reset_index(drop=True)


def prepare_features(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Drop identifiers, one-hot Geography, binary-encode Gender. Returns (X, y)."""
    y = df[TARGET].copy()
    X = df.drop(columns=ID_COLUMNS + [TARGET])

    X["Gender"] = (X["Gender"] == "Male").astype(int)
    X = pd.get_dummies(X, columns=["Geography"], prefix="Geography", dtype=int)

    return X, y


def load_dataset(path: str = "data/churn.csv") -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """Returns (X, y, raw_df). raw_df is kept around for the decision layer
    (Balance, NumOfProducts, CustomerId, etc. that aren't model features)."""
    raw_df = load_raw(path)
    X, y = prepare_features(raw_df)
    return X, y, raw_df
