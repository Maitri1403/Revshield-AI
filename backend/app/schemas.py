import datetime as dt
from typing import Optional, List

from pydantic import BaseModel, EmailStr


class MerchantSignup(BaseModel):
    business_name: str
    email: EmailStr
    password: str


class MerchantLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    business_name: str


class DashboardMetrics(BaseModel):
    revenue_today: float
    revenue_at_risk: float
    recoverable_revenue: float
    growth_opportunity: float
    risky_transactions: int
    payment_incidents: int
    ai_priorities: List[str]


class IncidentOut(BaseModel):
    id: int
    incident_type: str
    description: str
    status: str
    detected_at: dt.datetime

    class Config:
        from_attributes = True


class TransactionOut(BaseModel):
    id: int
    external_id: Optional[str]
    amount: float
    payment_method: str
    channel: str
    status: str
    risk_score: float
    is_anomalous: bool
    timestamp: dt.datetime

    class Config:
        from_attributes = True


class RecoveryOut(BaseModel):
    id: int
    reason: str
    customer_value: float
    recovery_probability: float
    risk_score: float
    recommended_action: str
    priority_rank: Optional[int]
    status: str

    class Config:
        from_attributes = True


class OfferOut(BaseModel):
    id: int
    discount_percent: float
    message: str
    estimated_cost: float
    merchant_status: str
    customer_status: str
    status: str

    class Config:
        from_attributes = True


class OfferDecision(BaseModel):
    action: str  # "approve" | "reject" | "edit"
    discount_percent: Optional[float] = None
    message: Optional[str] = None


class WhatIfRequest(BaseModel):
    discount_percent: float


class WhatIfResponse(BaseModel):
    no_offer_expected_recovery: float
    offer_expected_recovery: float
    offer_cost: float
    expected_net_benefit: float
    explanation: str


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str


class UploadSummary(BaseModel):
    upload_date: str
    transactions_ingested: int
    orders_ingested: int
    customers_ingested: int
    anomalies_detected: int
    analysis_triggered: bool
