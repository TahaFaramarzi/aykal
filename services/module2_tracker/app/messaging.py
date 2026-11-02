"""قواعد پیام‌رسانی: پنجره‌ی مجاز پاسخ، تشخیص شکایت و انصراف. توابع خالص."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional

from app.config import OPT_OUT_KEYWORDS, REPLY_WINDOW_HOURS, SENSITIVE_KEYWORDS
from app.models import ActivityType, UserActivity


@dataclass(frozen=True)
class ReplyWindow:
    is_open: bool
    last_inbound_at: Optional[datetime]
    expires_at: Optional[datetime]
    hours_left: float  # اگر بسته باشد ۰

    def to_dict(self) -> dict:
        fmt = "%Y-%m-%d %H:%M:%S"
        return {
            "is_open": self.is_open,
            "last_inbound_at": self.last_inbound_at.strftime(fmt) if self.last_inbound_at else None,
            "expires_at": self.expires_at.strftime(fmt) if self.expires_at else None,
            "hours_left": self.hours_left,
        }


def get_reply_window(
    activities: Iterable[UserActivity], now: datetime, hours: int = REPLY_WINDOW_HOURS
) -> ReplyWindow:
    """آیا هنوز در بازه‌ی `hours` ساعت از آخرین پیام ورودی خود کاربر هستیم؟"""
    inbound = [
        a.created_at for a in activities
        if a.type is ActivityType.MESSAGE and a.created_at <= now
    ]
    if not inbound:
        return ReplyWindow(False, None, None, 0.0)
    last = max(inbound)
    expires = last + timedelta(hours=hours)
    left = (expires - now).total_seconds() / 3600
    return ReplyWindow(left > 0, last, expires, round(max(left, 0.0), 2))


def _normalize(text: str) -> str:
    text = text.lower().replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")
    return " ".join(text.split())


def _find(texts: Iterable[str], keywords: Iterable[str]) -> Optional[str]:
    normalized = [_normalize(t) for t in texts]
    for kw in keywords:
        nk = _normalize(kw)
        if any(nk in t for t in normalized):
            return kw
    return None


def find_sensitive(texts: Iterable[str]) -> Optional[str]:
    """اگر متنی شکایت/موضوع حساس به نظر برسد، کلیدواژه‌ی منطبق را برمی‌گرداند."""
    return _find(texts, SENSITIVE_KEYWORDS)


def find_opt_out(texts: Iterable[str]) -> Optional[str]:
    """اگر کاربر خواسته پیام نفرستیم، کلیدواژه‌ی منطبق را برمی‌گرداند."""
    return _find(texts, OPT_OUT_KEYWORDS)
