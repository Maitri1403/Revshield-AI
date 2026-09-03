"""
MODULE: Revenue Recovery scoring.

Recovery probability is a transparent, weighted scoring function rather
than a black-box classifier — with no historical "did this customer
come back after an offer" label data yet, a supervised model would just
be fitting noise. This function is the explicit place to plug in a
trained model (e.g. logistic regression / gradient boosting) once the
merchant has accumulated enough Offer outcome history — see
`train_from_history()` below, which upgrades automatically the moment
there's enough labeled data.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

import numpy as np
from sklearn.linear_model import LogisticRegression


def heuristic_recovery_probability(
    *,
    purchase_count: int,
    avg_order_value: float,
    days_since_event: float,
    risk_score: float,
    reason: str,
) -> float:
    """Explainable 0-1 probability used until we have enough labeled outcomes."""
    score = 0.5

    # Loyal, repeat customers come back more often
    score += min(purchase_count, 10) * 0.02

    # Bigger baskets (relative) show real intent
    if avg_order_value > 0:
        score += 0.05

    # Recency matters a lot — probability decays the longer it's been
    score -= min(days_since_event, 14) * 0.02

    # High-risk transactions are less likely to be "genuine" recoverable intent
    score -= (risk_score / 100) * 0.25

    reason_adjust = {
        "abandoned_cart": 0.10,
        "payment_failure": 0.15,
        "inactive_high_value": -0.05,
    }
    score += reason_adjust.get(reason, 0.0)

    return float(min(max(score, 0.02), 0.97))


def train_from_history(offers: list[dict]) -> Optional[LogisticRegression]:
    """
    offers: list of dicts with keys purchase_count, avg_order_value,
    days_since_event, risk_score, accepted (0/1).
    Returns a fitted model once there are >= 25 labeled offers, else None
    (the caller should keep using the heuristic until then).
    """
    if len(offers) < 25:
        return None

    X = np.array([
        [o["purchase_count"], o["avg_order_value"], o["days_since_event"], o["risk_score"]]
        for o in offers
    ])
    y = np.array([o["accepted"] for o in offers])

    if len(set(y.tolist())) < 2:
        return None  # need both classes to train

    model = LogisticRegression(max_iter=1000)
    model.fit(X, y)
    return model


def optimize_budget(candidates: list[dict], budget: float) -> list[dict]:
    """
    Greedy knapsack by expected-net-benefit-per-rupee-of-cost.
    candidates: list of dicts with keys id, customer_value, recovery_probability, offer_cost
    Returns the same list annotated with priority_rank for the ones selected
    within budget (rank None if not selected).
    """
    scored = []
    for c in candidates:
        expected_gain = c["customer_value"] * c["recovery_probability"] - c["offer_cost"]
        roi = expected_gain / c["offer_cost"] if c["offer_cost"] > 0 else expected_gain
        scored.append({**c, "expected_gain": expected_gain, "roi": roi})

    scored.sort(key=lambda x: x["roi"], reverse=True)

    remaining = budget
    rank = 1
    for c in scored:
        if c["expected_gain"] <= 0:
            c["priority_rank"] = None
            continue
        if c["offer_cost"] <= remaining:
            c["priority_rank"] = rank
            remaining -= c["offer_cost"]
            rank += 1
        else:
            c["priority_rank"] = None

    return scored
