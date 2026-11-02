"""همه‌ی تنظیمات و اعداد قابل تغییر اینجا هستند (نه داخل منطق برنامه)."""
from __future__ import annotations

from typing import NamedTuple, Optional

from app.models import ActivityType


class WindowRule(NamedTuple):
    days: int              # طول بازه (روز)
    points_per_unit: float  # امتیاز هر واحد فعالیت در این بازه
    max_points: float       # سقف امتیاز این بازه


# بازه‌های امتیازدهی (حداکثر مجموع = ۲۰۰)
WINDOWS = (
    WindowRule(days=3, points_per_unit=10, max_points=50),
    WindowRule(days=7, points_per_unit=6, max_points=60),
    WindowRule(days=14, points_per_unit=3, max_points=50),
    WindowRule(days=30, points_per_unit=2, max_points=40),
)

# وزن هر نوع فعالیت (واحد فعالیت)
ACTIVITY_WEIGHTS = {
    ActivityType.LOGIN: 0.5,
    ActivityType.LOGOUT: 0.0,
    ActivityType.VIEW: 0.5,
    ActivityType.LIKE: 1.0,
    ActivityType.COMMENT: 2.0,
    ActivityType.FOLLOW: 1.5,
    ActivityType.UPLOAD: 3.0,
    ActivityType.MESSAGE: 2.0,
    ActivityType.MENTION: 2.0,
    ActivityType.REACTION: 1.0,
    ActivityType.OTHER: 1.0,
}

# (سقف امتیاز، سطح، علت) ـ None یعنی بدون سقف
LEVELS: tuple[tuple[Optional[float], int, str], ...] = (
    (10, 1, "کاربر کم‌فعال است (فعالیت کم در بازه‌های اخیر)"),
    (50, 2, "کاربر نیمه‌فعال است"),
    (100, 3, "کاربر فعال است"),
    (150, 4, "کاربر بسیار فعال است"),
    (None, 5, "کاربر سوپر اکتیو است (فعالیت بسیار زیاد)"),
)

REPORT_DAYS = 30  # بازه‌ی «فعالیت‌های اخیر» در گزارش

# ---------- تشخیص ریزش (churn) ----------
CHURN_COMPARE_DAYS = 7      # طول هر بازه برای مقایسه‌ی روند (اخیر در برابر قبلش)
CHURN_DECLINE_RATIO = 0.5   # افت ≥ ۵۰٪ یعنی «در حال ریزش»
CHURN_INACTIVE_DAYS = 7     # بدون فعالیت ≥ ۷ روز یعنی «بی‌فعال/در معرض ریزش»
CHURN_CHURNED_DAYS = 30     # بدون فعالیت ≥ ۳۰ روز یعنی «ریزش‌کرده»

# ---------- ریزش اولیه (Early Churn) ----------
CHURN_EARLY_QUIET_DAYS = 3      # اگر این چند روز اخیر هیچ تعاملی نبوده ...
CHURN_EARLY_LOOKBACK_DAYS = 14  # ... ولی در این بازه‌ی قبل‌تر فعال بوده → «ریزش اولیه»

# ---------- صف اقدامات ترمیمی ----------
# وضعیت‌هایی که وارد صف می‌شوند (مقدار ChurnStatus به‌صورت رشته)
QUEUE_STATUSES = ("early_churn", "declining", "inactive")
QUEUE_COOLDOWN_DAYS = 14  # بعد از انجام اقدام، تا این مدت کاربر دوباره وارد صف نمی‌شود

# ---------- مسیر فایل‌های داده (مشترک بین main.py و API) ----------
ACTIVITIES_PATH = "data/activities.json"
QUEUE_PATH = "data/queue.json"

# ---------- پیش‌نویس پیام ترمیمی ----------
REPLY_WINDOW_HOURS = 24            # پنجره‌ی مجاز پاسخ بعد از آخرین پیام خود کاربر
DRAFTS_PATH = "data/drafts.json"
DRAFT_MAX_CHARS = 300
DRAFT_MODEL = "claude-sonnet-5-5"  # فقط وقتی ANTHROPIC_API_KEY تنظیم باشد استفاده می‌شود
SENSITIVE_LOOKBACK_TEXTS = 5       # چند متن آخر کاربر برای تشخیص شکایت/انصراف بررسی شود

# فیلتر اولیه و ساده (کلیدواژه‌ای)؛ جایگزین بررسی انسانی نیست
SENSITIVE_KEYWORDS = (
    "شکایت", "ناراضی", "مرجوع", "پس بده", "پس بدید", "کلاهبردار", "اعتراض", "خسارت",
    "complaint", "refund", "scam",
)
OPT_OUT_KEYWORDS = (
    "لغو", "پیام نده", "پیام ندید", "نفرستید", "stop", "unsubscribe",
)
