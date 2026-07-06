"""Tests for the decision engine: value proxy, EV math, budget cap, backtest."""

import json
from pathlib import Path

import numpy as np
import pytest

from src.decision import (
    backtest,
    customer_value,
    expected_value,
    realized_net_value,
    select_under_budget,
)


# --- Synthetic, hand-computed cases ---------------------------------------

def test_customer_value_hand_computed():
    val = customer_value([2, 1], [50000, 0])
    assert val[0] == pytest.approx(1240.0)   # 120*2 + 0.02*50000
    assert val[1] == pytest.approx(120.0)     # 120*1 + 0.02*0


def test_customer_value_zero_balance_not_zero():
    val = customer_value([3], [0])
    assert val[0] == pytest.approx(360.0)
    assert val[0] > 0


def test_expected_value_hand_computed():
    ev1 = expected_value(np.array([0.5]), np.array([1000.0]), 0.3, 50.0)
    assert ev1[0] == pytest.approx(100.0)     # 0.5*1000*0.3 - 50
    ev2 = expected_value(np.array([0.1]), np.array([200.0]), 0.2, 50.0)
    assert ev2[0] == pytest.approx(-46.0)     # 0.1*200*0.2 - 50


def test_selection_never_exceeds_budget():
    ev = np.array([10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0])
    selected = select_under_budget(ev, budget=100.0, offer_cost=30.0)
    assert len(selected) == 3                  # floor(100/30) = 3
    assert list(selected) == [0, 1, 2]         # top-3 EVs descending

    for budget, cost in [(100.0, 30.0), (250.0, 40.0), (55.0, 10.0), (1000.0, 30.0)]:
        sel = select_under_budget(ev, budget=budget, offer_cost=cost)
        assert len(sel) * cost <= budget


def test_no_negative_ev_selected():
    ev = np.array([5.0, 3.0, 0.0, -1.0, -10.0])
    selected = select_under_budget(ev, budget=1_000_000.0, offer_cost=10.0)
    assert len(selected) == 2                   # excludes 0.0 and negatives
    assert list(selected) == [0, 1]


def test_selection_ordering_and_tie_determinism():
    ev = np.array([2.0, 5.0, 5.0, 1.0])
    selected = select_under_budget(ev, budget=1_000_000.0, offer_cost=1.0)
    assert list(selected) == [1, 2, 0, 3]       # stable, lower index first on ties
    again = select_under_budget(ev, budget=1_000_000.0, offer_cost=1.0)
    assert list(selected) == list(again)


def test_zero_and_small_budget():
    ev = np.array([5.0, 3.0, 1.0])
    assert len(select_under_budget(ev, budget=0.0, offer_cost=30.0)) == 0
    assert len(select_under_budget(ev, budget=29.0, offer_cost=30.0)) == 0


def test_invalid_economics_raise():
    ev = np.array([1.0, 2.0])
    with pytest.raises(ValueError):
        select_under_budget(ev, budget=100.0, offer_cost=0.0)
    with pytest.raises(ValueError):
        select_under_budget(ev, budget=100.0, offer_cost=-5.0)
    with pytest.raises(ValueError):
        expected_value(np.array([0.5]), np.array([100.0]), offer_success_rate=1.5, offer_cost=50.0)


def test_realized_net_value_hand_computed():
    selected = np.array([0, 1, 2])
    exited = np.array([1, 0, 1])
    values = np.array([1000.0, 500.0, 200.0])
    net = realized_net_value(selected, exited, values, offer_success_rate=0.3, offer_cost=50.0)
    # 1000*0.3 + 0 + 200*0.3 - 50*3 = 300 + 60 - 150
    assert net == pytest.approx(210.0)


def test_realized_net_value_empty_selection():
    net = realized_net_value(np.array([], dtype=int), np.array([1, 0]),
                             np.array([100.0, 50.0]), 0.3, 50.0)
    assert net == 0.0


def test_backtest_structure_and_counts():
    rng = np.random.default_rng(0)
    n = 50
    p_churn = rng.uniform(0, 1, n)
    value_saved = rng.uniform(100, 2000, n)
    exited = rng.integers(0, 2, n)
    result = backtest(p_churn, value_saved, exited, budget=500.0,
                      offer_cost=50.0, offer_success_rate=0.3)

    offers_allowed = result["offers_allowed"]
    assert result["random"]["n_selected"] == offers_allowed
    assert result["risk"]["n_selected"] == offers_allowed
    assert result["ev"]["n_selected"] <= offers_allowed

    for key in ["budget", "offer_cost", "offer_success_rate", "offers_allowed",
                "random", "risk", "ev", "lift_abs", "lift_pct"]:
        assert key in result
    # JSON-serializable end to end.
    json.dumps(result)


# --- Real-data sanity floor -----------------------------------------------

@pytest.fixture(scope="module")
def real_backtest():
    from src.data import load_dataset
    from src.model import build_challenger, oof_calibrated_predict

    X, y, raw_df = load_dataset("data/churn.csv")
    p_churn = oof_calibrated_predict(X, y, build_challenger)
    value_saved = customer_value(raw_df["NumOfProducts"], raw_df["Balance"])
    exited = raw_df["Exited"].to_numpy()
    return backtest(p_churn, value_saved, exited, budget=25_000.0,
                    offer_cost=50.0, offer_success_rate=0.3,
                    n_random_seeds=100, random_state=42)


@pytest.mark.skipif(
    not Path("data/churn.csv").exists(),
    reason="data/churn.csv is gitignored and not present",
)
def test_ev_beats_random_on_real_data(real_backtest):
    assert real_backtest["ev"]["net_value"] > real_backtest["random"]["net_value_mean"]
