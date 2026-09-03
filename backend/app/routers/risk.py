from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.security import get_current_merchant
from app.agents.analyst_agent import revenue_autopsy

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/transactions", response_model=list[schemas.TransactionOut])
def list_risky_transactions(
    limit: int = 50,
    merchant: models.Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(models.Transaction)
        .filter(models.Transaction.merchant_id == merchant.id)
        .order_by(models.Transaction.risk_score.desc())
        .limit(limit)
        .all()
    )
    return rows


@router.get("/incidents", response_model=list[schemas.IncidentOut])
def list_incidents(
    status: str | None = None,
    merchant: models.Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    q = db.query(models.Incident).filter(models.Incident.merchant_id == merchant.id)
    if status:
        q = q.filter(models.Incident.status == status)
    return q.order_by(models.Incident.detected_at.desc()).limit(100).all()


@router.put("/incidents/{incident_id}/resolve")
def resolve_incident(incident_id: int, merchant: models.Merchant = Depends(get_current_merchant), db: Session = Depends(get_db)):
    inc = (
        db.query(models.Incident)
        .filter(models.Incident.id == incident_id, models.Incident.merchant_id == merchant.id)
        .first()
    )
    if not inc:
        return {"ok": False, "detail": "Incident not found"}
    inc.status = "resolved"
    db.commit()
    return {"ok": True}


@router.get("/autopsy")
def get_autopsy(
    upload_date: str,
    merchant: models.Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    """MODULE 11 — 'why did revenue move on this date?' Analyst Agent explains, grounded in RAG + ML facts."""
    explanation = revenue_autopsy(db, merchant.id, upload_date)
    return {"upload_date": upload_date, "explanation": explanation}
