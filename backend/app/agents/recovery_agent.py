"""
AGENT 2 — RECOVERY AGENT
(covers spec modules 5, 6, 7, 8, 9, 10: Revenue Recovery Engine, Offer
Recommendation, Approval Workflow, Recovery Budget Optimizer, What-if
Simulator, Merchant AI Assistant / "Ask RevShield")

Job: decide WHO to try to win back and HOW, propose it, and never touch
money without merchant approval (human-in-the-loop). It reads facts the
Analyst Agent produced (via the same RAG store) plus customer/order data
to find recovery candidates, scores + ranks them under a budget
constraint, and drafts merchant-approvable offer text with the LLM.
"""
from __future__ import annotations

import datetime as dt
import json

from sqlalchemy.orm import Session

from app import models
from app.ml.recovery_model import heuristic_recovery_probability, optimize_budget
from app.rag import vector_store
from app.rag.knowledge_builder import build_recovery_documents, build_offer_outcome_document
from app.agents.groq_client import chat, chat_with_history

SYSTEM_PROMPT = """You are the Recovery module inside RevShield AI, a revenue-protection \
platform for online merchants. You draft short, honest, non-pushy customer-facing offer \
messages and merchant-facing recommendations, grounded only in the facts given to you. \
Never guarantee outcomes ("will definitely buy") — describe probabilities and reasoning \
plainly. Keep customer-facing messages under 30 words and friendly, not salesy."""

ASSISTANT_SYSTEM_PROMPT = """You are "Ask RevShield", the merchant assistant inside RevShield \
AI. Merchants ask you about their business risk, revenue, incidents and recovery status. \
Answer ONLY from the grounded facts / retrieved context you are given for this merchant. \
If you don't have enough information to answer, say so plainly and suggest what data would \
help. Be concise, concrete, and business-toned. Never invent numbers."""


def find_recovery_candidates(db: Session, merchant_id: int, upload_date: str) -> list[dict]:
    candidates = []

    # 1) Abandoned orders from this upload
    abandoned = (
        db.query(models.Order)
        .filter(models.Order.merchant_id == merchant_id, models.Order.upload_date == upload_date, models.Order.status == "abandoned")
        .all()
    )
    for o in abandoned:
        customer = db.query(models.Customer).get(o.customer_id) if o.customer_id else None
        candidates.append(_build_candidate(o.customer_id, customer, "abandoned_cart", o.amount, order_id=o.id, risk_score=0))

    # 2) Failed / debited-not-confirmed transactions from this upload (excluding suspicious/high risk — those go through review, not offers)
    failed_txns = (
        db.query(models.Transaction)
        .filter(
            models.Transaction.merchant_id == merchant_id,
            models.Transaction.upload_date == upload_date,
            models.Transaction.status.in_(["failed", "debited_not_confirmed"]),
        )
        .all()
    )
    for t in failed_txns:
        customer = db.query(models.Customer).get(t.customer_id) if t.customer_id else None
        candidates.append(_build_candidate(t.customer_id, customer, "payment_failure", t.amount, risk_score=t.risk_score))

    # 3) Inactive high-value customers (no purchase in 21+ days, above-median spend)
    all_customers = db.query(models.Customer).filter(models.Customer.merchant_id == merchant_id).all()
    if all_customers:
        spends = sorted(c.total_spent for c in all_customers)
        median_spend = spends[len(spends) // 2] if spends else 0
        for c in all_customers:
            if c.last_purchase_date and c.total_spent >= median_spend and c.total_spent > 0:
                days_inactive = (dt.datetime.utcnow() - c.last_purchase_date).days
                if days_inactive >= 21:
                    candidates.append(
                        _build_candidate(c.id, c, "inactive_high_value", c.avg_order_value or c.total_spent * 0.2, risk_score=0)
                    )

    return candidates


def _build_candidate(customer_id, customer, reason, value, order_id=None, risk_score=0.0) -> dict:
    purchase_count = customer.purchase_count if customer else 0
    avg_order_value = customer.avg_order_value if customer else 0
    days_since_event = 1.0
    if customer and customer.last_purchase_date:
        days_since_event = max((dt.datetime.utcnow() - customer.last_purchase_date).days, 0)

    prob = heuristic_recovery_probability(
        purchase_count=purchase_count,
        avg_order_value=avg_order_value,
        days_since_event=days_since_event,
        risk_score=risk_score,
        reason=reason,
    )

    return {
        "customer_id": customer_id,
        "order_id": order_id,
        "reason": reason,
        "customer_value": float(value or 0),
        "recovery_probability": prob,
        "risk_score": float(risk_score or 0),
    }


def suggest_discount(reason: str, recovery_probability: float) -> float:
    """Simple explainable discount ladder — higher intent needs less discount."""
    base = {"abandoned_cart": 5, "payment_failure": 0, "inactive_high_value": 10}.get(reason, 5)
    if recovery_probability < 0.3:
        base += 5
    return float(min(base, 20))


def run_recovery_pipeline(db: Session, merchant_id: int, upload_date: str) -> dict:
    """
    Full Recovery Agent pipeline: find candidates -> score -> optimize under
    budget -> persist Recovery rows -> draft LLM offer text for the
    top-ranked, budget-approved candidates -> persist as pending Offers
    awaiting merchant approval.
    """
    merchant = db.query(models.Merchant).get(merchant_id)
    budget = merchant.recovery_budget if merchant else 5000.0

    raw_candidates = find_recovery_candidates(db, merchant_id, upload_date)

    recovery_rows = []
    optimizer_input = []
    for c in raw_candidates:
        discount = suggest_discount(c["reason"], c["recovery_probability"])
        offer_cost = c["customer_value"] * (discount / 100)
        optimizer_input.append({
            "customer_id": c["customer_id"],
            "order_id": c["order_id"],
            "reason": c["reason"],
            "customer_value": c["customer_value"],
            "recovery_probability": c["recovery_probability"],
            "risk_score": c["risk_score"],
            "offer_cost": offer_cost,
            "discount": discount,
        })

    ranked = optimize_budget(optimizer_input, budget)

    top_for_rag = []
    offers_created = 0
    for r in ranked:
        action = (
            "Verify transaction before contacting customer" if r["risk_score"] >= 65
            else (f"Send a {r['discount']:.0f}% recovery offer" if r["priority_rank"] else "Low priority — hold for now")
        )
        rec = models.Recovery(
            merchant_id=merchant_id,
            customer_id=r["customer_id"],
            order_id=r.get("order_id"),
            reason=r["reason"],
            customer_value=r["customer_value"],
            recovery_probability=r["recovery_probability"],
            risk_score=r["risk_score"],
            recommended_action=action,
            priority_rank=r["priority_rank"],
            status="prioritized" if r["priority_rank"] else "identified",
        )
        db.add(rec)
        db.flush()  # get rec.id
        recovery_rows.append(rec)

        if r["priority_rank"] and r["risk_score"] < 65:
            top_for_rag.append({
                "reason": r["reason"], "customer_value": r["customer_value"],
                "recovery_probability": r["recovery_probability"], "recommended_action": action,
            })
            if r["priority_rank"] <= 20:  # cap LLM calls to top 20 to keep this fast/cheap
                message = draft_offer_message(r["reason"], r["customer_value"], r["discount"])
                offer = models.Offer(
                    merchant_id=merchant_id,
                    customer_id=r["customer_id"],
                    recovery_id=rec.id,
                    discount_percent=r["discount"],
                    message=message,
                    estimated_cost=r["offer_cost"],
                    merchant_status="pending",
                    customer_status="pending",
                    status="pending_approval",
                )
                db.add(offer)
                offers_created += 1

    db.commit()

    docs = build_recovery_documents(upload_date, top_for_rag)
    vector_store.add_documents(merchant_id, docs, metadatas=[{"date": upload_date, "type": "recovery"} for _ in docs])

    return {
        "candidates_found": len(raw_candidates),
        "prioritized": sum(1 for r in ranked if r["priority_rank"]),
        "offers_drafted": offers_created,
        "budget_used": round(sum(r["offer_cost"] for r in ranked if r["priority_rank"]), 2),
        "budget_total": budget,
    }


def draft_offer_message(reason: str, customer_value: float, discount_percent: float) -> str:
    reason_text = {
        "abandoned_cart": "left items in their cart without completing checkout",
        "payment_failure": "had a payment attempt that failed to go through",
        "inactive_high_value": "is a valuable customer who hasn't purchased recently",
    }.get(reason, reason)

    user_prompt = (
        f"Customer situation: {reason_text}. Cart/customer value: {customer_value:.0f}. "
        f"Approved discount: {discount_percent:.0f}%. "
        "Write ONE short customer-facing message offering this discount to bring them back. "
        "Under 30 words. No guarantees, no pressure tactics."
    )
    try:
        return chat(SYSTEM_PROMPT, user_prompt, temperature=0.5, max_tokens=80)
    except Exception:
        return f"🎁 Here's a {discount_percent:.0f}% offer to complete your order — valid for a limited time."


def what_if_simulate(reason_mix: dict, discount_percent: float, candidates: list[dict]) -> dict:
    """
    MODULE 7 — What-if Simulator. Uses the same elasticity-style assumption
    for every point on the curve: higher discount -> higher uptake, with
    diminishing returns, applied on top of each candidate's own baseline
    recovery probability so it stays grounded in real per-customer scores.
    """
    def adjusted_prob(base_prob: float, discount: float) -> float:
        # +2% probability per 1% discount, saturating — simple, explainable, tunable
        lift = min(discount * 0.02, 0.35)
        return min(base_prob + lift, 0.95)

    no_offer_recovery = sum(c["customer_value"] * c["recovery_probability"] for c in candidates)
    offer_recovery = sum(c["customer_value"] * adjusted_prob(c["recovery_probability"], discount_percent) for c in candidates)
    offer_cost = sum(c["customer_value"] * (discount_percent / 100) * adjusted_prob(c["recovery_probability"], discount_percent) for c in candidates)
    net_benefit = offer_recovery - offer_cost - no_offer_recovery

    return {
        "no_offer_expected_recovery": round(no_offer_recovery, 2),
        "offer_expected_recovery": round(offer_recovery, 2),
        "offer_cost": round(offer_cost, 2),
        "expected_net_benefit": round(net_benefit, 2),
    }


def explain_what_if(discount_percent: float, result: dict) -> str:
    user_prompt = (
        f"Simulated a {discount_percent:.0f}% recovery offer across current recovery candidates. "
        f"Result: {json.dumps(result)}. Explain in 2-3 sentences whether this looks worth doing "
        "and why, in plain business language."
    )
    try:
        return chat(SYSTEM_PROMPT, user_prompt, temperature=0.2, max_tokens=200)
    except Exception as e:
        return f"AI explanation unavailable: {e}"


def record_offer_outcome(db: Session, merchant_id: int, offer: models.Offer, accepted: bool):
    """Feeds the real outcome back into the RAG store — this is how the system 'learns' over time from actual results."""
    doc = build_offer_outcome_document(offer.discount_percent, accepted, offer.estimated_cost / max(offer.discount_percent / 100, 0.01))
    vector_store.add_documents(merchant_id, [doc], metadatas=[{"type": "offer_outcome"}])


def ask_assistant(db: Session, merchant_id: int, question: str) -> str:
    """MODULE 10 — 'Ask RevShield' merchant chat assistant, grounded via RAG retrieval."""
    retrieved = vector_store.query(merchant_id, question, top_k=6)

    history_rows = (
        db.query(models.AssistantMessage)
        .filter(models.AssistantMessage.merchant_id == merchant_id)
        .order_by(models.AssistantMessage.created_at.desc())
        .limit(6)
        .all()
    )
    history = [{"role": h.role, "content": h.content} for h in reversed(history_rows)]

    context_block = "\n".join(f"- {d}" for d in retrieved) if retrieved else "(no relevant indexed facts found for this merchant yet)"
    grounded_question = f"Retrieved context for this merchant:\n{context_block}\n\nMerchant question: {question}"

    history.append({"role": "user", "content": grounded_question})

    try:
        answer = chat_with_history(ASSISTANT_SYSTEM_PROMPT, history, temperature=0.3, max_tokens=350)
    except Exception as e:
        answer = f"AI assistant unavailable right now: {e}"

    db.add(models.AssistantMessage(merchant_id=merchant_id, role="user", content=question))
    db.add(models.AssistantMessage(merchant_id=merchant_id, role="assistant", content=answer))
    db.commit()

    return answer
