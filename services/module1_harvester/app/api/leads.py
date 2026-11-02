"""
Endpointهای مدیریت سرنخ‌ها
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Lead
from app.schemas import LeadResponse, LeadDetailResponse, LeadUpdateStatus, LeadStatus
from app.security import require_api_key
from app.services.lead_harvester import get_lead_clusters

from app.models import Interaction
from app.schemas import InteractionResponse

router = APIRouter(prefix="/api/v1/leads", tags=["Lead Harvester"])


@router.get("", response_model=List[LeadResponse], dependencies=[Depends(require_api_key)])
def list_leads(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status_filter: str = Query(None, alias="status"),
    intent_filter: str = Query(None, alias="intent"),
    min_score: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """لیست سرنخ‌ها با فیلتر و صفحه‌بندی"""
    query = db.query(Lead)

    if status_filter:
        query = query.filter(Lead.status == status_filter)
    if intent_filter:
        query = query.filter(Lead.intent == intent_filter)
    if min_score > 0:
        query = query.filter(Lead.lead_score >= min_score)

    return query.order_by(Lead.lead_score.desc()).offset(offset).limit(limit).all()


@router.get("/stats", dependencies=[Depends(require_api_key)])
def lead_stats(db: Session = Depends(get_db)):
    """آمار خوشه‌بندی سرنخ‌ها"""
    return get_lead_clusters(db)


@router.get("/{lead_id}", response_model=LeadDetailResponse, dependencies=[Depends(require_api_key)])
def get_lead(lead_id: int, db: Session = Depends(get_db)):
    """جزئیات یه سرنخ همراه تعاملاتش"""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.patch("/{lead_id}/status", response_model=LeadResponse, dependencies=[Depends(require_api_key)])
def update_lead_status(
    lead_id: int,
    payload: LeadUpdateStatus,
    db: Session = Depends(get_db),
):
    """به‌روزرسانی دستی وضعیت سرنخ"""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    lead.status = payload.status.value
    db.commit()
    db.refresh(lead)
    return lead

@router.get(
    "/{lead_id}/interactions",
    response_model=List[InteractionResponse],
    dependencies=[Depends(require_api_key)],
    summary="تعاملات یه سرنخ (شامل پاسخ‌های AI)",
)
def get_lead_interactions(
    lead_id: int,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """
    لیست تعاملات یه سرنخ + پاسخ‌های تولید شده توسط AI
    """
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    return (
        db.query(Interaction)
        .filter(Interaction.lead_id == lead_id)
        .order_by(Interaction.created_at.desc())
        .limit(limit)
        .all()
    )