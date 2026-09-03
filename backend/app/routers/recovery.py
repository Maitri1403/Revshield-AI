from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.security import get_current_merchant
from app.agents.recovery_agent import what_if_simulate, explain_what_if

router = APIRouter(prefix="/recovery", tags=["recovery"])


@router.get("/candidates", response_model=list[schemas.RecoveryOut])
def list_recovery_candidates(
    only_prioritized: bool = False,
    merchant: models.Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    q = db.query(models.Recovery).filter(models.Recovery.merchant_id == merchant.id)
    if only_prioritized:
        q = q.filter(models.Recovery.status == "prioritized")
    rows = q.limit(200).all()
    rows.sort(key=lambda r: (r.priority_rank is None, r.priority_rank if r.priority_rank is not None else 0))
    return rows


@router.get("/budget")
def get_budget_status(merchant: models.Merchant = Depends(get_current_merchant), db: Session = Depends(get_db)):
    prioritized = (
        db.query(models.Recovery)
        .filter(models.Recovery.merchant_id == merchant.id, models.Recovery.status == "prioritized")
        .all()
    )
    offers = (
        db.query(models.Offer)
        .filter(models.Offer.merchant_id == merchant.id, models.Offer.recovery_id.in_([r.id for r in prioritized] or [-1]))
        .all()
    )
    used = sum(o.estimated_cost for o in offers)
    return {
        "total_budget": merchant.recovery_budget,
        "used": round(used, 2),
        "remaining": round(merchant.recovery_budget - used, 2),
        "candidates_selected": len(prioritized),
    }


@router.put("/budget")
def set_budget(amount: float, merchant: models.Merchant = Depends(get_current_merchant), db: Session = Depends(get_db)):
    merchant.recovery_budget = amount
    db.commit()
    return {"ok": True, "recovery_budget": merchant.recovery_budget}


@router.post("/what-if", response_model=schemas.WhatIfResponse)
def what_if(
    payload: schemas.WhatIfRequest,
    merchant: models.Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    """MODULE 8 — What-if Simulator: 'what if I offered X% instead?'"""
    candidates = (
        db.query(models.Recovery)
        .filter(models.Recovery.merchant_id == merchant.id, models.Recovery.status.in_(["prioritized", "identified"]))
        .all()
    )
    candidate_dicts = [
        {"customer_value": c.customer_value, "recovery_probability": c.recovery_probability}
        for c in candidates
    ]
    result = what_if_simulate({}, payload.discount_percent, candidate_dicts)
    explanation = explain_what_if(payload.discount_percent, result)

    return schemas.WhatIfResponse(**result, explanation=explanation)
