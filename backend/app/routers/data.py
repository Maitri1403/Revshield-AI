import datetime as dt
import json

from fastapi import APIRouter, Depends, UploadFile, File, Query, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas, data_ingestion
from app.database import get_db
from app.security import get_current_merchant
from app.agents import analyst_agent, recovery_agent

router = APIRouter(prefix="/data", tags=["data"])


@router.post("/upload", response_model=schemas.UploadSummary)
async def upload_data(
    data_type: str = Query(..., pattern="^(transactions|orders|customers)$"),
    upload_date: str = Query(default=None, description="YYYY-MM-DD, defaults to today"),
    file: UploadFile = File(...),
    run_analysis: bool = Query(default=True),
    merchant: models.Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    """
    Merchants upload their daily/weekly/monthly business data here as CSV.
    Every upload is tagged with upload_date; uploading day-by-day gives the
    best analysis quality since both the ML models and the RAG knowledge
    base build up a richer picture over time.
    """
    if not upload_date:
        upload_date = dt.date.today().isoformat()

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")

    try:
        if data_type == "customers":
            n = data_ingestion.ingest_customers_csv(db, merchant.id, content)
        elif data_type == "transactions":
            n = data_ingestion.ingest_transactions_csv(db, merchant.id, content, upload_date)
        else:
            n = data_ingestion.ingest_orders_csv(db, merchant.id, content, upload_date)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {e}")

    data_ingestion.refresh_customer_aggregates(db, merchant.id)

    upload_row = (
        db.query(models.DailyUpload)
        .filter(models.DailyUpload.merchant_id == merchant.id, models.DailyUpload.upload_date == upload_date)
        .first()
    )
    if not upload_row:
        upload_row = models.DailyUpload(merchant_id=merchant.id, upload_date=upload_date)
        db.add(upload_row)
        db.commit()
        db.refresh(upload_row)

    if data_type == "transactions":
        upload_row.transactions_count += n
    elif data_type == "orders":
        upload_row.orders_count += n
    else:
        upload_row.customers_count += n
    db.commit()

    anomalies = 0
    triggered = False
    if run_analysis and data_type in ("transactions", "orders"):
        analysis_result = analyst_agent.run_full_analysis(db, merchant.id, upload_date)
        recovery_agent.run_recovery_pipeline(db, merchant.id, upload_date)
        anomalies = analysis_result["anomalies_detected"]
        triggered = True

    return schemas.UploadSummary(
        upload_date=upload_date,
        transactions_ingested=n if data_type == "transactions" else 0,
        orders_ingested=n if data_type == "orders" else 0,
        customers_ingested=n if data_type == "customers" else 0,
        anomalies_detected=anomalies,
        analysis_triggered=triggered,
    )


@router.get("/uploads")
def list_uploads(merchant: models.Merchant = Depends(get_current_merchant), db: Session = Depends(get_db)):
    rows = (
        db.query(models.DailyUpload)
        .filter(models.DailyUpload.merchant_id == merchant.id)
        .order_by(models.DailyUpload.upload_date.desc())
        .limit(60)
        .all()
    )
    out = []
    for r in rows:
        try:
            summary = json.loads(r.summary_json)
        except Exception:
            summary = {}
        out.append({
            "upload_date": r.upload_date,
            "transactions_count": r.transactions_count,
            "orders_count": r.orders_count,
            "customers_count": r.customers_count,
            "success_rate": summary.get("success_rate"),
            "revenue": summary.get("revenue"),
        })
    return out
