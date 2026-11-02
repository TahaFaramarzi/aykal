"""موتور امتیازدهی: توابع خالص، بدون I/O و بدون وابستگی به زمان سیستم."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from app.config import ACTIVITY_WEIGHTS, LEVELS, WINDOWS
from app.models import UserActivity


def weighted_count(activities: Iterable[UserActivity], now: datetime, days: int) -> float:
    """مجموع وزن فعالیت‌هایی که در `days` روز گذشته انجام شده‌اند."""
    start = now - timedelta(days=days)
    return sum(
        ACTIVITY_WEIGHTS[a.type]
        for a in activities
        if start <= a.created_at <= now
    )


def calculate_score(activities: Iterable[UserActivity], now: datetime) -> int:
    """امتیاز کاربر. کاربر بدون فعالیت دقیقاً امتیاز ۰ می‌گیرد."""
    activities = list(activities)
    total = 0.0
    for rule in WINDOWS:
        units = weighted_count(activities, now, rule.days)
        total += min(units * rule.points_per_unit, rule.max_points)
    return round(total)


def classify(score: float) -> tuple[int, str]:
    """(سطح، علت) را از روی امتیاز برمی‌گرداند؛ تنها منبع آستانه‌ها."""
    for limit, level, reason in LEVELS:
        if limit is None or score <= limit:
            return level, reason
    raise RuntimeError("LEVELS باید یک ردیف بدون سقف داشته باشد")
