"""Decision engine: value proxy, expected value, budget-capped selection, backtest, grid.

Incrementality caveat, stated up front: this module targets customers by P(churn),
which is not the same as targeting persuadable customers. True incrementality would
need uplift modeling and treatment data that this dataset does not have. Every
function here assumes an offer saves a would-be churner with probability
offer_success_rate and does nothing for a non-churner. That is a deliberate,
stated simplification, not a claim of causal effect.

All functions are pure and operate on numpy arrays aligned positionally with the
dataset order produced by load_dataset (index-free, numpy in and numpy out), so
they are trivially unit-testable with hand-built arrays.
"""

import numpy as np

DEFAULT_BASE_PRODUCT_VALUE = 120.0   # annual relationship value per product
DEFAULT_MARGIN_RATE = 0.02           # net interest margin on deposits
DEFAULT_OFFER_COST = 50.0
DEFAULT_OFFER_SUCCESS_RATE = 0.3
DEFAULT_BUDGET = 25_000.0
GRID_OFFER_COSTS = (25.0, 50.0, 100.0)
GRID_SUCCESS_RATES = (0.2, 0.3, 0.4)


def _validate_economics(offer_cost: float, offer_success_rate: float) -> None:
    """Shared guardrail for the offer economics used across the engine."""
    # Zero cost makes floor(budget / offer_cost) a division by zero and makes
    # "budget as a cap" meaningless, so a strictly positive cost is required.
    if offer_cost <= 0:
        raise ValueError(f"offer_cost must be > 0, got {offer_cost}")
    if not (0.0 <= offer_success_rate <= 1.0):
        raise ValueError(
            f"offer_success_rate must be in [0, 1], got {offer_success_rate}"
        )


def customer_value(
    num_of_products,
    balance,
    base_product_value: float = DEFAULT_BASE_PRODUCT_VALUE,
    margin_rate: float = DEFAULT_MARGIN_RATE,
) -> np.ndarray:
    """Per-customer relationship value, value_saved_i.

    Computes base_product_value * NumOfProducts + margin_rate * Balance.

    Both defaults are documented, configurable assumptions. base_product_value
    ($120) is the annual relationship value per product held, covering fees,
    interchange, and cross-sell. margin_rate (2%) is the net interest margin on
    deposits. Neither is meant to be exact, both are a reasonable order of
    magnitude for retail banking.

    Takes the two raw columns rather than a dataframe so hand-computed tests need
    no fixture scaffolding.
    """
    if base_product_value < 0:
        raise ValueError(f"base_product_value must be >= 0, got {base_product_value}")
    if margin_rate < 0:
        raise ValueError(f"margin_rate must be >= 0, got {margin_rate}")

    num_of_products = np.asarray(num_of_products, dtype=float)
    balance = np.asarray(balance, dtype=float)

    # The product term exists specifically so the 36.2% of customers with
    # Balance = 0 are not valued at zero by construction. A pure balance proxy
    # would make the EV-over-Risk lift partly an artifact of the proxy.
    return base_product_value * num_of_products + margin_rate * balance


def expected_value(
    p_churn: np.ndarray,
    value_saved: np.ndarray,
    offer_success_rate: float,
    offer_cost: float,
) -> np.ndarray:
    """Expected value of sending an offer to each customer.

    EV_i = P(churn)_i * value_saved_i * offer_success_rate - offer_cost.

    offer_success_rate is the assumed probability the offer converts a would-be
    churner.
    """
    _validate_economics(offer_cost, offer_success_rate)
    p_churn = np.asarray(p_churn, dtype=float)
    value_saved = np.asarray(value_saved, dtype=float)
    return p_churn * value_saved * offer_success_rate - offer_cost


def select_under_budget(
    ev: np.ndarray,
    budget: float,
    offer_cost: float,
) -> np.ndarray:
    """Positional indices into ev to make offers to, EV descending.

    Returns a 1-D integer array (not a boolean mask) so the ranking is preserved
    for the save-list use case and the result indexes cleanly into other aligned
    arrays.
    """
    # Reuse the shared guard for offer_cost > 0 (dummy valid success rate).
    _validate_economics(offer_cost, 0.5)
    if budget < 0:
        raise ValueError(f"budget must be >= 0, got {budget}")

    ev = np.asarray(ev, dtype=float)

    cap = int(budget // offer_cost)
    cap = min(cap, len(ev))
    if cap == 0:
        return np.array([], dtype=int)

    # Stable sort on the negated array ranks by EV descending and breaks ties
    # deterministically by lowest original index. Isotonic calibration can
    # produce stepwise-constant probabilities, so ties are realistic here.
    order = np.argsort(-ev, kind="stable")

    # Budget is a cap, not a quota: truncate to at most floor(budget / cost).
    order = order[:cap]

    # Strict > 0 negative-EV stop. An EV of exactly zero ties up budget and
    # capacity for zero expected return, so it is excluded. Selection can stop
    # before the cap but never exceed it.
    order = order[ev[order] > 0]
    return order


def realized_net_value(
    selected: np.ndarray,
    exited: np.ndarray,
    value_saved: np.ndarray,
    offer_success_rate: float,
    offer_cost: float,
) -> float:
    """Realized net value of a selection against true Exited labels.

    You pay offer_cost for every offer sent and recover value only from customers
    who truly would have churned, discounted by offer_success_rate. The offer is
    assumed to save a would-be churner with probability offer_success_rate and to
    do nothing for a non-churner. No uplift or treatment data exists in this
    dataset to do better, so this is a stated simplification.
    """
    selected = np.asarray(selected, dtype=int)
    if len(selected) == 0:
        return 0.0
    exited = np.asarray(exited, dtype=float)
    value_saved = np.asarray(value_saved, dtype=float)
    saved = np.sum(exited[selected] * value_saved[selected] * offer_success_rate)
    return float(saved - offer_cost * len(selected))


def backtest(
    p_churn: np.ndarray,
    value_saved: np.ndarray,
    exited: np.ndarray,
    budget: float,
    offer_cost: float,
    offer_success_rate: float,
    n_random_seeds: int = 100,
    random_state: int = 42,
) -> dict:
    """Compare Random, Risk, and EV targeting at a fixed budget.

    Returns a JSON-serializable dict of realized net values, selection counts,
    and the EV-over-Risk lift in dollars and percent.
    """
    _validate_economics(offer_cost, offer_success_rate)
    p_churn = np.asarray(p_churn, dtype=float)
    value_saved = np.asarray(value_saved, dtype=float)
    exited = np.asarray(exited, dtype=float)

    n = len(p_churn)
    cap = min(int(budget // offer_cost), n)

    # Random strategy: cap customers drawn uniformly at random, averaged over
    # many seeds so a single lucky or unlucky draw does not define the baseline.
    if cap == 0:
        random_mean = 0.0
        random_std = 0.0
    else:
        random_values = np.empty(n_random_seeds, dtype=float)
        for seed_i in range(n_random_seeds):
            rng = np.random.default_rng(random_state + seed_i)
            picks = rng.choice(n, size=cap, replace=False)
            random_values[seed_i] = realized_net_value(
                picks, exited, value_saved, offer_success_rate, offer_cost
            )
        random_mean = float(np.mean(random_values))
        random_std = float(np.std(random_values))

    # Risk strategy: top cap by P(churn) descending, with NO negative-EV stop.
    # This is intentional. Risk is the naive "call the riskiest customers"
    # comparator being argued against; adding the EV stop here would smuggle EV
    # logic into the baseline.
    risk_selected = np.argsort(-p_churn, kind="stable")[:cap]
    risk_net = realized_net_value(
        risk_selected, exited, value_saved, offer_success_rate, offer_cost
    )

    # EV strategy: EV-ranked selection with the negative-EV stop.
    ev = expected_value(p_churn, value_saved, offer_success_rate, offer_cost)
    ev_selected = select_under_budget(ev, budget, offer_cost)
    ev_net = realized_net_value(
        ev_selected, exited, value_saved, offer_success_rate, offer_cost
    )

    lift_abs = ev_net - risk_net
    # abs() in the denominator because Risk's realized net value can legitimately
    # be negative. A signed denominator would flip the sign of the lift
    # nonsensically (a bigger positive lift over a negative baseline would read
    # as negative). None when the baseline is exactly zero to avoid dividing by 0.
    lift_pct = None if risk_net == 0 else lift_abs / abs(risk_net) * 100

    return {
        "budget": float(budget),
        "offer_cost": float(offer_cost),
        "offer_success_rate": float(offer_success_rate),
        "offers_allowed": int(cap),
        "random": {
            "net_value_mean": random_mean,
            "net_value_std": random_std,
            "n_selected": int(cap),
        },
        "risk": {
            "net_value": risk_net,
            "n_selected": int(len(risk_selected)),
        },
        "ev": {
            "net_value": ev_net,
            "n_selected": int(len(ev_selected)),
        },
        "lift_abs": float(lift_abs),
        "lift_pct": None if lift_pct is None else float(lift_pct),
    }


def sensitivity_grid(
    p_churn: np.ndarray,
    value_saved: np.ndarray,
    exited: np.ndarray,
    budget: float = DEFAULT_BUDGET,
    offer_costs=GRID_OFFER_COSTS,
    success_rates=GRID_SUCCESS_RATES,
    n_random_seeds: int = 100,
    random_state: int = 42,
) -> list:
    """Run backtest across offer_cost x success_rate at a fixed budget.

    value_saved is passed in once because it does not depend on offer economics.
    Returns a flat list of backtest result dicts (each already carries its own
    cost, rate, lifts, and counts), directly JSON-serializable.
    """
    results = []
    for offer_cost in offer_costs:
        for offer_success_rate in success_rates:
            _validate_economics(offer_cost, offer_success_rate)
            results.append(
                backtest(
                    p_churn,
                    value_saved,
                    exited,
                    budget=budget,
                    offer_cost=offer_cost,
                    offer_success_rate=offer_success_rate,
                    n_random_seeds=n_random_seeds,
                    random_state=random_state,
                )
            )
    return results
