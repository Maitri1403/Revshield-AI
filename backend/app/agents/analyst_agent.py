"""
AGENT 1 — ANALYST AGENT
(covers spec modules 1, 2, 3, 4, 11: Revenue Risk Prediction, Root Cause
Intelligence, Payment State Intelligence, Transaction Risk Intelligence,
Revenue Autopsy)

Job: turn a merchant's raw daily data into (a) ML-scored facts and
(b) grounded natural-language explanations. It never decides what to
DO about a problem — that's the Recovery Agent's job. This agent's
output feeds the dashboard "AI Priorities" and answers "why did revenue
drop" / "what's risky right now" questions.

Pipeline per upload:
  raw transactions -> risk_model (ML) -> incident detection (rules) ->
  forecasting (trend vs. baseline) -> knowledge_builder (facts as text)
  -> vector_store.add_documents (RAG index) -> groq_client (LLM explains
  the grounded facts, does not invent numbers)
"""
from __future__ import annotations

import datetime as dt
import json

from sqlalchemy.orm import Session
from app import models

SYSTEM_PROMPT = """You are the Analyst module inside RevShield AI, a revenue-protection \
platform for online merchants. You are given a set of GROUNDED FACTS produced by the \
platform's own ML models and rules for one merchant. Explain them clearly, in plain \
business language, for a non-technical merchant. Rules:
- Never invent numbers, causes, or events that are not present in the facts given to you.
- If the facts don't fully explain something, say what is the strongest available signal \
and note the uncertainty honestly.
- Be concise and concrete. No generic filler like "in today's fast-paced digital economy."
- When asked for priorities, return short, specific, actionable bullet lines.
"""


def analyze_customer_stats(db: Session, merchant_id: int) -> dict:
    customers = db.query(models.Customer).filter(models.Customer.merchant_id == merchant_id).all()
    return {
        c.id: {"avg_order_value": c.avg_order_value, "purchase_count": c.purchase_count}
        for c in customers
    }


def run_risk_scoring(db: Session, merchant_id: int, upload_date: str) -> pd.DataFrame:
    """Scores every transaction from this upload with the ML risk model and persists scores."""
    txns = (
        db.query(models.Transaction)
        .filter(models.Transaction.merchant_id == merchant_id, models.Transaction.upload_date == upload_date)
        .all()
    )
    if not txns:
        return pd.DataFrame()

    customer_stats = analyze_customer_stats(db, merchant_id)

    rows = []
    for t in txns:
        rows.append({
            "id": t.id,
            "external_id": t.external_id,
            "amount": t.amount,
            "hour": t.timestamp.hour if t.timestamp else 12,
            "payment_method": t.payment_method,
            "payment_method_code": encode_payment_method(t.payment_method),
            "customer_id": t.customer_id,
        })
    df = pd.DataFrame(rows)
    scored = score_transactions(df, customer_stats)

    scored_by_id = {r["id"]: r for r in scored.to_dict(orient="records")}
    for t in txns:
        s = scored_by_id.get(t.id)
        if s:
            t.risk_score = s["risk_score"]
            t.is_anomalous = bool(s["is_anomalous"])
    db.commit()
    return scored


def detect_payment_state_incidents(db: Session, merchant_id: int, upload_date: str) -> list[models.Incident]:
    """
    MODULE 8/9 — Payment State Intelligence + the "debited but not confirmed"
    scenario: any transaction whose status is exactly that gets a tracked
    incident so the merchant (and, in the UI, the customer) sees a clear
    "don't pay again" state instead of silence.
    """
    txns = (
        db.query(models.Transaction)
        .filter(
            models.Transaction.merchant_id == merchant_id,
            models.Transaction.upload_date == upload_date,
            models.Transaction.status.in_(["debited_not_confirmed", "suspicious"]),
        )
        .all()
    )

    created = []
    for t in txns:
        existing = (
            db.query(models.Incident)
            .filter(models.Incident.transaction_id == t.id, models.Incident.status == "open")
            .first()
        )
        if existing:
            continue

        if t.status == "debited_not_confirmed":
            desc = (
                f"Transaction {t.external_id}: customer's payment of {t.amount:.0f} "
                f"({t.payment_method}) was debited but merchant confirmation is still missing. "
                f"Customer should not be asked to pay again until this is verified."
            )
            itype = "debited_not_confirmed"
        else:
            desc = (
                f"Transaction {t.external_id}: flagged suspicious, amount {t.amount:.0f} "
                f"via {t.payment_method}, risk score {t.risk_score:.0f}. Recommend manual review "
                f"before fulfillment."
            )
            itype = "high_risk"

        inc = models.Incident(
            merchant_id=merchant_id, transaction_id=t.id, incident_type=itype,
            description=desc, status="open",
        )
        db.add(inc)
        created.append(inc)
    db.commit()
    return created


def compute_daily_revenue_stats(db: Session, merchant_id: int, upload_date: str) -> dict:
    txns = (
        db.query(models.Transaction)
        .filter(models.Transaction.merchant_id == merchant_id, models.Transaction.upload_date == upload_date)
        .all()
    )
    if not txns:
        return {"success_rate": 0, "revenue": 0, "failed_amount": 0, "failure_by_method": {}, "failure_by_hour": {}}

    success = [t for t in txns if t.status == "success"]
    failed = [t for t in txns if t.status in ("failed", "debited_not_confirmed")]

    failure_by_method: dict[str, int] = {}
    failure_by_hour: dict[str, int] = {}
    for t in failed:
        failure_by_method[t.payment_method] = failure_by_method.get(t.payment_method, 0) + 1
        hour = str(t.timestamp.hour) if t.timestamp else "unknown"
        failure_by_hour[hour] = failure_by_hour.get(hour, 0) + 1

    return {
        "success_rate": len(success) / len(txns) if txns else 0,
        "revenue": sum(t.amount for t in success),
        "failed_amount": sum(t.amount for t in failed),
        "failure_by_method": failure_by_method,
        "failure_by_hour": failure_by_hour,
    }


def get_recent_history(db: Session, merchant_id: int, exclude_date: str, limit: int = 14) -> list[dict]:
    uploads = (
        db.query(models.DailyUpload)
        .filter(models.DailyUpload.merchant_id == merchant_id, models.DailyUpload.upload_date != exclude_date)
        .order_by(models.DailyUpload.upload_date.desc())
        .limit(limit)
        .all()
    )
    history = []
    for u in reversed(uploads):
        try:
            summary = json.loads(u.summary_json)
            if "success_rate" in summary:
                history.append(summary)
        except Exception:
            continue
    return history


def run_full_analysis(db: Session, merchant_id: int, upload_date: str) -> dict:
    """
    Full Analyst Agent pipeline for one day's upload. Called automatically
    right after CSV ingestion (see routers/data.py), and also re-runnable
    on demand for the Revenue Autopsy feature.
    """
    scored = run_risk_scoring(db, merchant_id, upload_date)
    incidents = detect_payment_state_incidents(db, merchant_id, upload_date)
    today_stats = compute_daily_revenue_stats(db, merchant_id, upload_date)
    history = get_recent_history(db, merchant_id, exclude_date=upload_date)
    risk_finding = detect_revenue_risk(today_stats, history)

    top_anomalies = []
    if not scored.empty:
        anomalous = scored[scored["is_anomalous"]].sort_values("risk_score", ascending=False).head(5)
        top_anomalies = anomalous.to_dict(orient="records")

    incident_dicts = [
        {
            "incident_type": i.incident_type,
            "description": i.description,
            "transaction_id": i.transaction_id,
            "external_id": next(
                (t.external_id for t in db.query(models.Transaction).filter(models.Transaction.id == i.transaction_id)),
                None,
            ),
        }
        for i in incidents
    ]

    # Index today's facts into the RAG store — this is the "daily training"
    docs = build_daily_documents(upload_date, risk_finding, incident_dicts, top_anomalies)
    vector_store.add_documents(merchant_id, docs, metadatas=[{"date": upload_date, "type": "analysis"} for _ in docs])

    # Persist the summary so tomorrow's baseline includes today
    upload_row = (
        db.query(models.DailyUpload)
        .filter(models.DailyUpload.merchant_id == merchant_id, models.DailyUpload.upload_date == upload_date)
        .first()
    )
    if upload_row:
        merged = {**today_stats, **{"date": upload_date}}
        upload_row.summary_json = json.dumps(merged)
        db.commit()

    facts_for_llm = {
        "risk_finding": risk_finding,
        "today_stats": {k: v for k, v in today_stats.items() if k != "failure_by_hour"},
        "incidents": [i["description"] for i in incident_dicts][:8],
        "top_anomalies": [
            {"external_id": a.get("external_id"), "amount": a.get("amount"), "risk_score": a.get("risk_score")}
            for a in top_anomalies
        ],
    }

    priorities = generate_ai_priorities(facts_for_llm)

    # Persist priorities + risk finding alongside the stats already saved above
    if upload_row:
        try:
            merged = json.loads(upload_row.summary_json)
        except Exception:
            merged = {}
        merged["ai_priorities"] = priorities
        merged["revenue_at_risk_low"] = risk_finding.get("revenue_at_risk_low", 0)
        merged["revenue_at_risk_high"] = risk_finding.get("revenue_at_risk_high", 0)
        upload_row.summary_json = json.dumps(merged, default=str)
        db.commit()

    return {
        "risk_finding": risk_finding,
        "incidents_created": len(incidents),
        "anomalies_detected": len(top_anomalies),
        "ai_priorities": priorities,
    }


def generate_ai_priorities(facts: dict) -> list[str]:
    user_prompt = (
        "Here are today's grounded facts from the platform:\n\n"
        f"{json.dumps(facts, indent=2, default=str)}\n\n"
        "Return 3-5 short priority lines for the merchant dashboard, most urgent first. "
        "Each line under 15 words. Prefix each with one emoji: 🔴 for urgent/negative, "
        "🟡 for worth attention, 🟢 for a positive/opportunity signal. "
        "Output ONLY the lines, one per line, nothing else."
    )
    try:
        raw = chat(SYSTEM_PROMPT, user_prompt, temperature=0.2, max_tokens=250)
        lines = [l.strip("- ").strip() for l in raw.split("\n") if l.strip()]
        return lines[:5]
    except Exception as e:
        return [f"⚠️ AI explanation unavailable ({e})"]


def revenue_autopsy(db: Session, merchant_id: int, upload_date: str) -> str:
    """MODULE 11 — Revenue Autopsy: 'why did revenue drop yesterday/today?'"""
    today_stats = compute_daily_revenue_stats(db, merchant_id, upload_date)
    history = get_recent_history(db, merchant_id, exclude_date=upload_date)
    risk_finding = detect_revenue_risk(today_stats, history)

    retrieved = vector_store.query(
        merchant_id, f"revenue drop root cause {upload_date}", top_k=6
    )

    user_prompt = (
        f"Grounded structured facts:\n{json.dumps(risk_finding, indent=2, default=str)}\n\n"
        f"Relevant historical facts retrieved from the merchant's data:\n"
        + "\n".join(f"- {d}" for d in retrieved) + "\n\n"
        "Write a short root-cause explanation (3-5 sentences) for the merchant: what changed, "
        "the strongest contributing signal, and whether this looks like a one-off or a trend. "
        "Only use the facts given above."
    )
    try:
        return chat(SYSTEM_PROMPT, user_prompt, temperature=0.2, max_tokens=350)
    except Exception as e:
        return f"AI explanation unavailable: {e}"
