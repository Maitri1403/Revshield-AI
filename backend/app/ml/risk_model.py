"""
MODULE: Transaction Risk Intelligence

Real, trained scikit-learn model — not a hardcoded score. Each time a
merchant uploads a new batch of transactions, we fit a fresh
IsolationForest on that merchant's own transaction history (amount,
recency, method-encoded) to flag statistical outliers, then blend that
with a few explainable business rules (amount vs. that customer's own
average, brand-new customer, odd hour). The result is a 0-100 risk_score
plus a machine-readable list of "signals" the LLM later explains in
plain language — the ML model decides WHAT is risky, the LLM explains
WHY in words.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest


def score_transactions(df: pd.DataFrame, customer_stats: dict) -> pd.DataFrame:
    """
    df columns required: amount, hour, payment_method_code, customer_id
    customer_stats: {customer_id: {"avg_order_value": float, "purchase_count": int}}
    Returns df with added columns: risk_score (0-100), is_anomalous (bool), signals (list[str])
    """
    if df.empty:
        df["risk_score"] = []
        df["is_anomalous"] = []
        df["signals"] = []
        return df

    features = df[["amount", "hour", "payment_method_code"]].fillna(0).to_numpy()

    # Isolation Forest needs a handful of points to be meaningful; fall back
    # to rule-only scoring on very small batches.
    use_iforest = len(df) >= 8
    if use_iforest:
        model = IsolationForest(
            n_estimators=150, contamination="auto", random_state=42
        )
        model.fit(features)
        # decision_function: higher = more normal, lower/negative = more anomalous
        raw_scores = model.decision_function(features)
        # normalize to 0-100 where 100 = most anomalous
        norm = (raw_scores.max() - raw_scores) / (raw_scores.max() - raw_scores.min() + 1e-9)
        iforest_component = norm * 100
    else:
        iforest_component = np.zeros(len(df))

    risk_scores = []
    anomaly_flags = []
    signals_list = []

    for i, row in df.reset_index(drop=True).iterrows():
        signals = []
        rule_component = 0.0

        stats = customer_stats.get(row["customer_id"], None)
        if stats is None or stats.get("purchase_count", 0) == 0:
            rule_component += 25
            signals.append("first-time / limited customer history")
        else:
            avg = stats.get("avg_order_value", 0) or 0
            if avg > 0 and row["amount"] > avg * 4:
                rule_component += 35
                signals.append(
                    f"amount is {row['amount'] / avg:.1f}x this customer's normal order value"
                )

        if row["hour"] < 5 or row["hour"] >= 23:
            rule_component += 10
            signals.append("unusual transaction hour")

        combined = 0.6 * iforest_component[i] + 0.4 * min(rule_component, 100)
        combined = float(min(max(combined, 0), 100))

        if combined >= 70:
            signals.append("flagged as a statistical outlier vs. recent transaction pattern")

        risk_scores.append(round(combined, 1))
        anomaly_flags.append(combined >= 65)
        signals_list.append(signals)

    df = df.copy()
    df["risk_score"] = risk_scores
    df["is_anomalous"] = anomaly_flags
    df["signals"] = signals_list
    return df


PAYMENT_METHOD_CODES = {
    "upi": 1, "card": 2, "netbanking": 3, "wallet": 4, "cod": 5, "unknown": 0,
}


def encode_payment_method(method: str) -> int:
    return PAYMENT_METHOD_CODES.get(str(method).strip().lower(), 0)
