"""شکل داده‌های ورودی/خروجی API (Pydantic). Swagger از روی همین‌ها ساخته می‌شود."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ActivityIn(BaseModel):
    user_id: str = Field(min_length=1, description="شناسه‌ی کاربر", examples=["u1"])
    content: str = Field(min_length=1, description="متن فعالیت", examples=["Like Post"])
    created_at: Optional[datetime] = Field(
        default=None, description="زمان فعالیت؛ اگر خالی باشد «همین الان» ثبت می‌شود"
    )


class UserIn(BaseModel):
    user_id: str = Field(min_length=1, examples=["u6"])


class ActivityOut(BaseModel):
    user_id: str
    content: str
    created_at: str
    type: Optional[str] = None


class UserAnalysis(BaseModel):
    score: int
    level: int
    reason: str
    recent_activities: list[ActivityOut]


class ChurnOut(BaseModel):
    user_id: str
    status: str
    reason: str
    last_activity: Optional[str]
    days_since_last: Optional[int]
    recent_units: float
    previous_units: float


class LeaderboardEntry(BaseModel):
    user_id: str
    score: int


class QueueItemOut(BaseModel):
    id: int
    user_id: str
    status: str
    reason: str
    state: str
    previous_status: Optional[str]
    enqueued_at: str
    updated_at: str
    closed_at: Optional[str]


class SyncReportOut(BaseModel):
    enqueued: list[QueueItemOut]
    updated: list[QueueItemOut]
    resolved: list[QueueItemOut]
    expired: list[QueueItemOut]


class ReplyWindowOut(BaseModel):
    is_open: bool
    last_inbound_at: Optional[str]
    expires_at: Optional[str]
    hours_left: float


class PendingItemOut(QueueItemOut):
    can_auto_reply: bool = Field(description="آیا همین الان در پنجره‌ی ۲۴ ساعته هستیم؟")
    window_expires_at: Optional[str] = None


class DraftOut(BaseModel):
    id: int
    queue_item_id: int
    user_id: str
    state: str
    text: Optional[str]
    source: Optional[str]
    can_auto_reply: bool
    window_expires_at: Optional[str]
    handoff_reason: Optional[str]
    facts: dict
    created_at: str
    updated_at: str
    edited: bool
    audit: list[dict]


class ApproveIn(BaseModel):
    reviewer: str = Field(min_length=1, description="نام اپراتور تأییدکننده", examples=["sara"])
    text: Optional[str] = Field(default=None, description="متن ویرایش‌شده (اختیاری)")


class RejectIn(BaseModel):
    reviewer: str = Field(min_length=1, examples=["sara"])
    reason: Optional[str] = None


class SentIn(BaseModel):
    channel: str = Field(default="instagram_dm", description="کانالی که پیام از آن ارسال شد",
                         examples=["instagram_dm", "phone", "email"])
