"""تشخیص کاربران در حال ریزش بر اساس بی‌فعالیتی و افت روند. توابع خالص."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Iterable, Optional

from app.config import (
    ACTIVITY_WEIGHTS,
    CHURN_CHURNED_DAYS,
    CHURN_COMPARE_DAYS,
    CHURN_DECLINE_RATIO,
    CHURN_EARLY_LOOKBACK_DAYS,
    CHURN_EARLY_QUIET_DAYS,
    CHURN_INACTIVE_DAYS,
)
from app.models import DATE_FORMAT, UserActivity


class ChurnStatus(str, Enum):
    HEALTHY = "healthy"            # سالم
    EARLY_CHURN = "early_churn"    # ریزش اولیه: تا همین چند روز پیش فعال بود، الان ساکت است
    DECLINING = "declining"        # فعالیتش افت کرده
    INACTIVE = "inactive"          # چند روز است غیب است (در معرض ریزش)
    CHURNED = "churned"            # مدت زیادی غیب است (ریزش‌کرده)
    NEVER_ACTIVE = "never_active"  # هرگز فعالیتی نداشته


# ترتیب نمایش در گزارش (اولویت پیگیری)
STATUS_ORDER = (
    ChurnStatus.EARLY_CHURN,
    ChurnStatus.DECLINING,
    ChurnStatus.INACTIVE,
    ChurnStatus.CHURNED,
    ChurnStatus.NEVER_ACTIVE,
    ChurnStatus.HEALTHY,
)


@dataclass(frozen=True)
class ChurnResult:
    user_id: str
    status: ChurnStatus
    reason: str
    last_activity: Optional[datetime]
    days_since_last: Optional[int]
    recent_units: float
    previous_units: float

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "status": self.status.value,
            "reason": self.reason,
            "last_activity": (
                self.last_activity.strftime(DATE_FORMAT) if self.last_activity else None
            ),
            "days_since_last": self.days_since_last,
            "recent_units": self.recent_units,
            "previous_units": self.previous_units,
        }


def _units_between(activities: list[UserActivity], start: datetime, end: datetime) -> float:
    """مجموع وزن فعالیت‌ها در بازه‌ی (start, end]."""
    return sum(ACTIVITY_WEIGHTS[a.type] for a in activities if start < a.created_at <= end)


def assess_churn(
    user_id: str, activities: Iterable[UserActivity], now: datetime
) -> ChurnResult:
    activities = list(activities)
    n = CHURN_COMPARE_DAYS

    if not activities:
        return ChurnResult(user_id, ChurnStatus.NEVER_ACTIVE,
                           "هیچ فعالیتی برای این کاربر ثبت نشده است",
                           None, None, 0.0, 0.0)

    last = max(a.created_at for a in activities)
    days_since = max((now - last).days, 0)

    recent = _units_between(activities, now - timedelta(days=n), now)
    previous = _units_between(activities, now - timedelta(days=2 * n), now - timedelta(days=n))

    def result(status: ChurnStatus, reason: str) -> ChurnResult:
        return ChurnResult(user_id, status, reason, last, days_since, recent, previous)

    if days_since >= CHURN_CHURNED_DAYS:
        return result(ChurnStatus.CHURNED,
                      f"{days_since} روز است که هیچ فعالیتی نداشته (ریزش‌کرده)")
    if days_since >= CHURN_INACTIVE_DAYS:
        return result(ChurnStatus.INACTIVE,
                      f"{days_since} روز است که فعالیتی نداشته (در معرض ریزش)")
    quiet = CHURN_EARLY_QUIET_DAYS
    quiet_units = _units_between(activities, now - timedelta(days=quiet), now)
    earlier_units = _units_between(
        activities,
        now - timedelta(days=CHURN_EARLY_LOOKBACK_DAYS),
        now - timedelta(days=quiet),
    )
    if quiet_units == 0 and earlier_units > 0:
        return result(ChurnStatus.EARLY_CHURN,
                      f"در {CHURN_EARLY_LOOKBACK_DAYS} روز گذشته فعال بوده ولی "
                      f"{quiet} روز اخیر تعاملی نداشته (ریزش اولیه)")
    if previous > 0 and recent <= previous * (1 - CHURN_DECLINE_RATIO):
        drop = round((1 - recent / previous) * 100)
        return result(ChurnStatus.DECLINING,
                      f"فعالیت در {n} روز اخیر نسبت به {n} روز قبل‌تر {drop}٪ کاهش یافته")
    return result(ChurnStatus.HEALTHY, "فعالیت پایدار است")
