from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.security import get_current_merchant
from app.agents.recovery_agent import ask_assistant

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("/ask", response_model=schemas.AskResponse)
def ask(
    payload: schemas.AskRequest,
    merchant: models.Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    """MODULE 10 — 'Ask RevShield'. Retrieves grounded context from the RAG store, then calls the real LLM."""
    answer = ask_assistant(db, merchant.id, payload.question)
    return schemas.AskResponse(answer=answer)


@router.get("/history")
def history(merchant: models.Merchant = Depends(get_current_merchant), db: Session = Depends(get_db)):
    rows = (
        db.query(models.AssistantMessage)
        .filter(models.AssistantMessage.merchant_id == merchant.id)
        .order_by(models.AssistantMessage.created_at.asc())
        .limit(100)
        .all()
    )
    return [{"role": r.role, "content": r.content, "created_at": r.created_at} for r in rows]
