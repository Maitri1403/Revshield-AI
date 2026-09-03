import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.security import get_current_merchant

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/activity")
def get_activity(merchant: models.Merchant = Depends(get_current_merchant), db: Session = Depends(get_db)):
    """
    A merged, time-sorted feed of everything the AI has actually done for
    this merchant, so changes from an upload or an approval are visible
    without hunting through separate tabs.
    """
    events = []

    for u in (
        db.query(models.DailyUpload)
        .filter(models.DailyUpload.merchant_id == merchant.id)
        .order_by(models.DailyUpload.created_at.desc())
        .limit(15)
        .all()
    ):
        events.append({
            "time": u.created_at.isoformat(),
            "type": "ok",
            "text": f"Data uploaded for {u.upload_date} — {u.transactions_count} txns, {u.orders_count} orders, {u.customers_count} customers. AI analysis ran.",
        })

    for inc in (
        db.query(models.Incident)
        .filter(models.Incident.merchant_id == merchant.id)
        .order_by(models.Incident.detected_at.desc())
        .limit(15)
        .all()
    ):
        events.append({
            "time": inc.detected_at.isoformat(),
            "type": "bad" if inc.status == "open" else "ok",
            "text": f"{inc.incident_type.replace('_', ' ').title()}: {inc.description}"
            + (" — resolved" if inc.status == "resolved" else ""),
        })

    for o in (
        db.query(models.Offer)
        .filter(models.Offer.merchant_id == merchant.id)
        .order_by(models.Offer.created_at.desc())
        .limit(15)
        .all()
    ):
        if o.merchant_status == "pending":
            events.append({
                "time": o.created_at.isoformat(),
                "type": "warn",
                "text": f"AI drafted a recovery offer ({o.discount_percent:.0f}% off, est. cost ₹{o.estimated_cost:,.0f}) — awaiting your approval.",
            })
        else:
            outcome = (
                "customer accepted — recovered" if o.customer_status == "accepted"
                else "customer declined" if o.customer_status == "declined"
                else o.merchant_status
            )
            events.append({
                "time": o.created_at.isoformat(),
                "type": "ok" if o.customer_status == "accepted" else "warn",
                "text": f"Offer {o.merchant_status} — {outcome}.",
            })

    events.sort(key=lambda e: e["time"], reverse=True)
    return events[:30]


def _latest_upload_date(db: Session, merchant_id: int):
    row = (
        db.query(models.DailyUpload)
        .filter(models.DailyUpload.merchant_id == merchant_id)
        .order_by(models.DailyUpload.upload_date.desc())
        .first()
    )
    return row.upload_date if row else None


@router.get("", response_model=schemas.DashboardMetrics)
def get_dashboard(merchant: models.Merchant = Depends(get_current_merchant), db: Session = Depends(get_db)):
    latest_date = _latest_upload_date(db, merchant.id)

    revenue_today = 0.0
    revenue_at_risk = 0.0
    ai_priorities = ["No data uploaded yet — upload today's transactions to get started."]

    if latest_date:
        upload_row = (
            db.query(models.DailyUpload)
            .filter(models.DailyUpload.merchant_id == merchant.id, models.DailyUpload.upload_date == latest_date)
            .first()
        )
        try:
            summary = json.loads(upload_row.summary_json)
        except Exception:
            summary = {}
        revenue_today = summary.get("revenue", 0.0)
        revenue_at_risk = summary.get("revenue_at_risk_high", 0.0) or 0.0
        ai_priorities = summary.get("ai_priorities") or ["Analysis pending — this can take a few seconds after upload."]

    risky_transactions = (
        db.query(models.Transaction)
        .filter(models.Transaction.merchant_id == merchant.id, models.Transaction.is_anomalous == True)  # noqa: E712
        .count()
    )
    payment_incidents = (
        db.query(models.Incident)
        .filter(models.Incident.merchant_id == merchant.id, models.Incident.status == "open")
        .count()
    )

    recoverable_revenue = (
        db.query(models.Recovery)
        .filter(models.Recovery.merchant_id == merchant.id, models.Recovery.status == "prioritized")
        .all()
    )
    recoverable_total = sum(r.customer_value * r.recovery_probability for r in recoverable_revenue)

    growth_customers = (
        db.query(models.Recovery)
        .filter(models.Recovery.merchant_id == merchant.id, models.Recovery.reason == "inactive_high_value")
        .all()
    )
    growth_opportunity = sum(r.customer_value for r in growth_customers)

    return schemas.DashboardMetrics(
        revenue_today=round(revenue_today, 2),
        revenue_at_risk=round(revenue_at_risk, 2),
        recoverable_revenue=round(recoverable_total, 2),
        growth_opportunity=round(growth_opportunity, 2),
        risky_transactions=risky_transactions,
        payment_incidents=payment_incidents,
        ai_priorities=ai_priorities,
    )
