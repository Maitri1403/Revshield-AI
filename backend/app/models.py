import datetime as dt

from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean
)
from sqlalchemy.orm import relationship

from app.database import Base


def now():
    return dt.datetime.utcnow()


class Merchant(Base):
    __tablename__ = "merchants"

    id = Column(Integer, primary_key=True, index=True)
    business_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    recovery_budget = Column(Float, default=5000.0)
    created_at = Column(DateTime, default=now)

    customers = relationship("Customer", back_populates="merchant")
    transactions = relationship("Transaction", back_populates="merchant")


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=False)
    external_id = Column(String, index=True)
    name = Column(String)
    email = Column(String)
    purchase_count = Column(Integer, default=0)
    avg_order_value = Column(Float, default=0.0)
    total_spent = Column(Float, default=0.0)
    last_purchase_date = Column(DateTime, nullable=True)
    status = Column(String, default="active")  # active / inactive

    merchant = relationship("Merchant", back_populates="customers")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    external_id = Column(String, index=True)
    amount = Column(Float, default=0.0)
    payment_method = Column(String, default="unknown")
    channel = Column(String, default="unknown")  # e.g. mobile / desktop
    status = Column(String, default="success")
    # success / failed / pending / debited_not_confirmed / reversed / suspicious
    risk_score = Column(Float, default=0.0)
    is_anomalous = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=now)
    upload_date = Column(String, index=True)  # YYYY-MM-DD of the batch it came in with

    merchant = relationship("Merchant", back_populates="transactions")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    product_name = Column(String, default="")
    amount = Column(Float, default=0.0)
    status = Column(String, default="pending")  # completed / abandoned / pending
    created_at = Column(DateTime, default=now)
    upload_date = Column(String, index=True)


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=False)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    incident_type = Column(String)  # e.g. debited_not_confirmed / high_risk / failure_spike
    description = Column(Text)
    status = Column(String, default="open")  # open / resolved
    detected_at = Column(DateTime, default=now)


class Recovery(Base):
    __tablename__ = "recoveries"

    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    reason = Column(String)  # abandoned_cart / payment_failure / inactive_high_value
    customer_value = Column(Float, default=0.0)
    recovery_probability = Column(Float, default=0.0)
    risk_score = Column(Float, default=0.0)
    recommended_action = Column(Text, default="")
    priority_rank = Column(Integer, nullable=True)  # set by budget optimizer
    status = Column(String, default="identified")  # identified / prioritized / skipped / actioned
    created_at = Column(DateTime, default=now)


class Offer(Base):
    __tablename__ = "offers"

    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    recovery_id = Column(Integer, ForeignKey("recoveries.id"), nullable=True)
    discount_percent = Column(Float, default=0.0)
    message = Column(Text, default="")
    estimated_cost = Column(Float, default=0.0)
    merchant_status = Column(String, default="pending")  # pending/approved/rejected/edited
    customer_status = Column(String, default="pending")  # pending/accepted/declined
    status = Column(String, default="pending_approval")
    created_at = Column(DateTime, default=now)


class DailyUpload(Base):
    __tablename__ = "daily_uploads"

    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=False)
    upload_date = Column(String, index=True)
    transactions_count = Column(Integer, default=0)
    orders_count = Column(Integer, default=0)
    customers_count = Column(Integer, default=0)
    summary_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=now)


class AssistantMessage(Base):
    __tablename__ = "assistant_messages"

    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=False)
    role = Column(String)  # user / assistant
    content = Column(Text)
    created_at = Column(DateTime, default=now)
