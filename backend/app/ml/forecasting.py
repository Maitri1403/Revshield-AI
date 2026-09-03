"""
MODULE: Revenue Risk Prediction / trend detection.

Lightweight statistical baseline: compares today's payment-success rate,
revenue and failure mix against a rolling historical baseline built from
this merchant's own past DailyUpload summaries. This is intentionally a
lean, explainable statistical model (not a deep forecaster) — accurate
enough to flag "this is abnormal" and cheap enough to run on every
upload; swap in a proper time-series model (Prophet / ARIMA) once a
merchant has months of daily history.
"""
from __future__ import annotations


def detect_revenue_risk(today: dict, history: list[dict]) -> dict:
    """
    today: {"success_rate": float, "revenue": float, "failed_amount": float,
            "failure_by_method": {method: count}, "failure_by_hour": {hour: count}}
    history: list of the same shape from prior days (most recent last)
    Returns a structured finding dict the Analyst Agent will pass to the LLM.
    """
    if not history:
        return {
            "abnormal": False,
            "baseline_success_rate": today["success_rate"],
            "current_success_rate": today["success_rate"],
            "revenue_at_risk_low": 0.0,
            "revenue_at_risk_high": 0.0,
            "top_failure_method": None,
            "top_failure_hour": None,
        }

    baseline_success = sum(h["success_rate"] for h in history) / len(history)
    baseline_revenue = sum(h["revenue"] for h in history) / len(history)

    drop = baseline_success - today["success_rate"]
    abnormal = drop >= 0.08  # 8+ point drop in success rate is flagged

    revenue_at_risk_low = 0.0
    revenue_at_risk_high = 0.0
    if abnormal and baseline_revenue > 0:
        implied_loss_rate = drop
        revenue_at_risk_low = round(baseline_revenue * implied_loss_rate * 0.8, 2)
        revenue_at_risk_high = round(baseline_revenue * implied_loss_rate * 1.3, 2)

    failure_by_method = today.get("failure_by_method", {}) or {}
    failure_by_hour = today.get("failure_by_hour", {}) or {}

    top_method = max(failure_by_method, key=failure_by_method.get) if failure_by_method else None
    top_hour = max(failure_by_hour, key=failure_by_hour.get) if failure_by_hour else None

    return {
        "abnormal": abnormal,
        "baseline_success_rate": round(baseline_success, 4),
        "current_success_rate": round(today["success_rate"], 4),
        "revenue_at_risk_low": revenue_at_risk_low,
        "revenue_at_risk_high": revenue_at_risk_high,
        "top_failure_method": top_method,
        "top_failure_hour": top_hour,
    }
