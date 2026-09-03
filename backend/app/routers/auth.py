from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.security import hash_password, verify_password, create_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=schemas.TokenResponse)
def signup(payload: schemas.MerchantSignup, db: Session = Depends(get_db)):
    existing = db.query(models.Merchant).filter(models.Merchant.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists.")

    merchant = models.Merchant(
        business_name=payload.business_name,
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    token = create_token(merchant.id)
    return schemas.TokenResponse(access_token=token, business_name=merchant.business_name)


@router.post("/login", response_model=schemas.TokenResponse)
def login(payload: schemas.MerchantLogin, db: Session = Depends(get_db)):
    merchant = db.query(models.Merchant).filter(models.Merchant.email == payload.email).first()
    if not merchant or not verify_password(payload.password, merchant.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    token = create_token(merchant.id)
    return schemas.TokenResponse(access_token=token, business_name=merchant.business_name)
