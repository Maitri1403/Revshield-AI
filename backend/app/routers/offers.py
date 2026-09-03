import random

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.security import get_current_merchant
from app.agents.recovery_agent import record_offer_outcome

router = APIRouter(prefix="/offers", tags=["offers"])


def _auto_resolve_customer_response(db: Session, offer: models.Offer, merchant_id: int):
    """
    Human-in-the-loop stops at the merchant's approval — once approved, the
    AI system is trusted to carry the offer to the customer and record the
    outcome itself, instead of making the merchant click a second button.
    We simulate the customer's response here using the recovery model's own
    probability estimate, so the odds match what the AI already told the
    merchant on the recovery/offer card.
    """
    probability = 0.45
    if offer.recovery_id:
        rec = db.query(models.Recovery).get(offer.recovery_id)
        if rec and rec.recovery_probability:
            probability = max(0.02, min(0.95, rec.recovery_probability))

    accepted = random.random() < probability
    offer.customer_status = "accepted" if accepted else "declined"
    offer.status = "completed" if accepted else "closed"
    db.commit()

    record_offer_outcome(db, merchant_id, offer, accepted)

    if offer.recovery_id:
        rec = db.query(models.Recovery).get(offer.recovery_id)
        if rec:
            rec.status = "actioned"
            db.commit()


@router.get("", response_model=list[schemas.OfferOut])
def list_offers(
    merchant_status: str | None = None,
    merchant: models.Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    q = db.query(models.Offer).filter(models.Offer.merchant_id == merchant.id)
    if merchant_status:
        q = q.filter(models.Offer.merchant_status == merchant_status)
    return q.order_by(models.Offer.created_at.desc()).limit(200).all()


@router.put("/{offer_id}/decision", response_model=schemas.OfferOut)
def merchant_decision(
    offer_id: int,
    payload: schemas.OfferDecision,
    merchant: models.Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    """
    Human-in-the-loop step: AI drafted this offer, the merchant now
    approves / rejects / edits it before the customer ever sees it.
    """
    offer = db.query(models.Offer).filter(models.Offer.id == offer_id, models.Offer.merchant_id == merchant.id).first()
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")

    if payload.action == "approve":
        offer.merchant_status = "approved"
        offer.status = "awaiting_customer"
        db.commit()
        _auto_resolve_customer_response(db, offer, merchant.id)
    elif payload.action == "reject":
        offer.merchant_status = "rejected"
        offer.status = "closed"
        db.commit()
    elif payload.action == "edit":
        offer.merchant_status = "edited"
        offer.status = "awaiting_customer"
        if payload.discount_percent is not None:
            offer.discount_percent = payload.discount_percent
        if payload.message is not None:
            offer.message = payload.message
        db.commit()
        _auto_resolve_customer_response(db, offer, merchant.id)
    else:
        raise HTTPException(status_code=400, detail="action must be approve | reject | edit")

    db.refresh(offer)
    return offer


@router.put("/{offer_id}/customer-response", response_model=schemas.OfferOut)
def customer_response(
    offer_id: int,
    accepted: bool,
    merchant: models.Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    """Simulates the customer's accept/decline of an approved offer (Module 6, step 3-4)."""
    offer = db.query(models.Offer).filter(models.Offer.id == offer_id, models.Offer.merchant_id == merchant.id).first()
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if offer.merchant_status not in ("approved", "edited"):
        raise HTTPException(status_code=400, detail="Offer has not been approved by the merchant yet.")

    offer.customer_status = "accepted" if accepted else "declined"
    offer.status = "completed" if accepted else "closed"
    db.commit()

    record_offer_outcome(db, merchant.id, offer, accepted)

    if offer.recovery_id:
        rec = db.query(models.Recovery).get(offer.recovery_id)
        if rec:
            rec.status = "actioned"
            db.commit()

    db.refresh(offer)
    return offer
