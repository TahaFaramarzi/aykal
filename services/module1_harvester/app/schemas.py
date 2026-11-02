"""
Pydantic Schemas برای ورودی/خروجی API
"""
from datetime import datetime
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict


# ============================================================
# Enums
# ============================================================

class InteractionType(str, Enum):
    COMMENT = "comment"
    DIRECT = "direct"
    LIKE = "like"
    MENTION = "mention"
    STORY_REPLY = "story_reply"


class LeadIntent(str, Enum):
    PURCHASE_INQUIRY = "purchase_inquiry"
    SUPPORT_COMPLAINT = "support_complaint"
    LOCATION_INFO = "location_info"
    HUMAN_HANDOFF = "human_handoff_request"
    GENERAL_COMMENT = "general_comment"
    GENERAL_ENGAGEMENT = "general_engagement"
    SPAM = "spam"
    UNKNOWN = "unknown"


class LeadStatus(str, Enum):
    ACTIVE = "active"
    ENGAGED = "engaged"
    WARM = "warm"
    HOT = "hot"
    COLD = "cold"
    CONVERTED = "converted"
    LOST = "lost"


# ============================================================
# Interaction
# ============================================================

class IncomingInteraction(BaseModel):
    """تعامل ورودی — از Webhook یا تست دستی"""
    instagram_id: str = Field(..., pattern=r"^\d{1,19}$")   # شناسه‌ی اینستاگرام همیشه عددی است
    username: Optional[str] = None
    interaction_type: InteractionType
    text_content: Optional[str] = None
    media_id: Optional[str] = None
    comment_id: Optional[str] = None
    external_id: Optional[str] = None     # شناسه‌ی رویداد در متا؛ برای جلوگیری از ثبت تکراری


class InteractionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    instagram_id: str
    interaction_type: str
    content: Optional[str]
    detected_intent: Optional[str]
    intent_score: int
    generated_reply: Optional[str] = None
    reply_sent_at: Optional[datetime] = None
    reply_status: Optional[str] = None
    created_at: datetime


# ============================================================
# Lead
# ============================================================

class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    instagram_id: str
    username: Optional[str]
    full_name: Optional[str]
    intent: str
    lead_score: int
    status: str
    total_interactions: int
    last_interaction_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class LeadDetailResponse(LeadResponse):
    interactions: List[InteractionResponse] = []


class LeadUpdateStatus(BaseModel):
    status: LeadStatus


# ============================================================
# Webhook
# ============================================================

class WebhookResponse(BaseModel):
    status: str = "ok"
    events_received: int = 0
    events_queued: int = 0


# ============================================================
# Health
# ============================================================

class HealthResponse(BaseModel):
    status: str
    phase: int
    module: str
    database: str
    redis: str
    timestamp: datetime