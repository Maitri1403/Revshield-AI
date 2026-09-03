"""
Converts structured daily results (risk findings, incidents, customer
behaviour) into short natural-language "fact" documents that get
embedded and stored in the vector store. This is the bridge between the
ML/rules layer (which produces numbers) and the RAG layer (which lets
the LLM retrieve grounded, dated facts instead of hallucinating them).
"""
from __future__ import annotations

from typing import List


def build_daily_documents(upload_date: str, risk_finding: dict, incidents: list[dict], top_anomalies: list[dict]) -> List[str]:
    docs = []

    if risk_finding.get("abnormal"):
        docs.append(
            f"On {upload_date}, payment success rate dropped to "
            f"{risk_finding['current_success_rate']*100:.1f}% from a baseline of "
            f"{risk_finding['baseline_success_rate']*100:.1f}%. "
            f"Estimated revenue at risk: {risk_finding['revenue_at_risk_low']:.0f} to "
            f"{risk_finding['revenue_at_risk_high']:.0f}. "
            f"Failures were concentrated in payment method '{risk_finding.get('top_failure_method')}' "
            f"around hour {risk_finding.get('top_failure_hour')}."
        )
    else:
        docs.append(
            f"On {upload_date}, payment success rate was "
            f"{risk_finding['current_success_rate']*100:.1f}%, in line with the recent baseline "
            f"of {risk_finding['baseline_success_rate']*100:.1f}%. No abnormal failure spike detected."
        )

    for inc in incidents:
        docs.append(
            f"On {upload_date}, incident '{inc['incident_type']}' detected for transaction "
            f"{inc.get('external_id', inc.get('transaction_id'))}: {inc['description']}"
        )

    for a in top_anomalies:
        docs.append(
            f"On {upload_date}, transaction {a.get('external_id')} (amount {a.get('amount')}, "
            f"method {a.get('payment_method')}) was flagged with risk score {a.get('risk_score')}. "
            f"Signals: {', '.join(a.get('signals', [])) or 'statistical outlier'}."
        )

    return docs


def build_recovery_documents(upload_date: str, top_recoveries: list[dict]) -> List[str]:
    docs = []
    for r in top_recoveries:
        docs.append(
            f"On {upload_date}, recovery candidate identified: reason '{r['reason']}', "
            f"customer value {r['customer_value']:.0f}, recovery probability "
            f"{r['recovery_probability']*100:.0f}%. Recommended action: {r['recommended_action']}"
        )
    return docs


def build_offer_outcome_document(discount_percent: float, accepted: bool, customer_value: float) -> str:
    outcome = "was accepted" if accepted else "was declined"
    return (
        f"A {discount_percent:.0f}% recovery offer on a {customer_value:.0f}-value cart {outcome} "
        f"by the customer."
    )
