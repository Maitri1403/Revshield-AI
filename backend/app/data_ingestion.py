"""
Handles merchant-uploaded daily/weekly/monthly business data (CSV).
This is the "feed" that keeps both the ML models and the RAG knowledge
base current — every upload is tagged with an upload_date and becomes
part of the merchant's growing history.

Expected CSV shapes (extra columns are ignored, missing optional columns
default sensibly):

customers.csv   customer_id, name, email, purchase_count, avg_order_value, total_spent, last_purchase_date
transactions.csv transaction_id, customer_id, amount, payment_method, channel, status, timestamp
orders.csv       order_id, customer_id, transaction_id, product_name, amount, status, created_at

status values recognised for transactions:
  success | failed | pending | debited_not_confirmed | reversed | suspicious
status values recognised for orders:
  completed | abandoned | pending
"""
from __future__ import annotations

import datetime as dt
import io

import pandas as pd
from sqlalchemy.orm import Session

from app import models


def _parse_date(value, default=None):
    if pd.isna(value) or value == "":
        return default
    try:
        return pd.to_datetime(value).to_pydatetime()
    except Exception:
        return default


def get_or_create_customer(db: Session, merchant_id: int, external_id: str, defaults: dict) -> models.Customer:
    customer = (
        db.query(models.Customer)
        .filter(models.Customer.merchant_id == merchant_id, models.Customer.external_id == str(external_id))
        .first()
    )
    if customer:
        for k, v in defaults.items():
            if v is not None:
                setattr(customer, k, v)
    else:
        customer = models.Customer(merchant_id=merchant_id, external_id=str(external_id), **defaults)
        db.add(customer)
        db.flush()
    return customer


def ingest_customers_csv(db: Session, merchant_id: int, file_bytes: bytes) -> int:
    df = pd.read_csv(io.BytesIO(file_bytes))
    count = 0
    for _, row in df.iterrows():
        defaults = {
            "name": str(row.get("name", "")),
            "email": str(row.get("email", "")),
            "purchase_count": int(row.get("purchase_count", 0) or 0),
            "avg_order_value": float(row.get("avg_order_value", 0) or 0),
            "total_spent": float(row.get("total_spent", 0) or 0),
            "last_purchase_date": _parse_date(row.get("last_purchase_date", None)),
            "status": str(row.get("status", "active") or "active"),
        }
        get_or_create_customer(db, merchant_id, row["customer_id"], defaults)
        count += 1
    db.commit()
    return count


def ingest_transactions_csv(db: Session, merchant_id: int, file_bytes: bytes, upload_date: str) -> int:
    df = pd.read_csv(io.BytesIO(file_bytes))
    count = 0
    for _, row in df.iterrows():
        customer = None
        cust_id = row.get("customer_id", None)
        if cust_id is not None and not pd.isna(cust_id):
            customer = get_or_create_customer(db, merchant_id, cust_id, {
                "name": str(row.get("customer_name", "")) or None,
            })

        txn = models.Transaction(
            merchant_id=merchant_id,
            customer_id=customer.id if customer else None,
            external_id=str(row.get("transaction_id", "")),
            amount=float(row.get("amount", 0) or 0),
            payment_method=str(row.get("payment_method", "unknown") or "unknown"),
            channel=str(row.get("channel", "unknown") or "unknown"),
            status=str(row.get("status", "success") or "success").strip().lower(),
            timestamp=_parse_date(row.get("timestamp", None), default=dt.datetime.utcnow()),
            upload_date=upload_date,
        )
        db.add(txn)
        count += 1
    db.commit()
    return count


def ingest_orders_csv(db: Session, merchant_id: int, file_bytes: bytes, upload_date: str) -> int:
    df = pd.read_csv(io.BytesIO(file_bytes))
    count = 0
    for _, row in df.iterrows():
        customer = None
        cust_id = row.get("customer_id", None)
        if cust_id is not None and not pd.isna(cust_id):
            customer = get_or_create_customer(db, merchant_id, cust_id, {})

        txn_id = None
        raw_txn_ext = row.get("transaction_id", None)
        if raw_txn_ext is not None and not pd.isna(raw_txn_ext):
            txn = (
                db.query(models.Transaction)
                .filter(models.Transaction.merchant_id == merchant_id, models.Transaction.external_id == str(raw_txn_ext))
                .first()
            )
            txn_id = txn.id if txn else None

        order = models.Order(
            merchant_id=merchant_id,
            customer_id=customer.id if customer else None,
            transaction_id=txn_id,
            product_name=str(row.get("product_name", "")),
            amount=float(row.get("amount", 0) or 0),
            status=str(row.get("status", "pending") or "pending").strip().lower(),
            created_at=_parse_date(row.get("created_at", None), default=dt.datetime.utcnow()),
            upload_date=upload_date,
        )
        db.add(order)
        count += 1
    db.commit()
    return count


def refresh_customer_aggregates(db: Session, merchant_id: int):
    """Recompute purchase_count / avg_order_value / total_spent / last_purchase_date from successful transactions."""
    customers = db.query(models.Customer).filter(models.Customer.merchant_id == merchant_id).all()
    for c in customers:
        successful = (
            db.query(models.Transaction)
            .filter(
                models.Transaction.merchant_id == merchant_id,
                models.Transaction.customer_id == c.id,
                models.Transaction.status == "success",
            )
            .all()
        )
        if successful:
            c.purchase_count = len(successful)
            c.total_spent = sum(t.amount for t in successful)
            c.avg_order_value = c.total_spent / len(successful)
            c.last_purchase_date = max(t.timestamp for t in successful)
    db.commit()
