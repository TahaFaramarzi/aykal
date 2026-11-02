"""
اتصال ماژول ۲ به دیتابیس مشترک.

جریان: interactions (نوشته‌ی ماژول ۱)  ←  EngagementTracker  ←  inactive_users (خوانده‌ی ماژول ۳)

نگاشت وضعیت ریزش به دلیلی که ماژول ۳ می‌شناسد:
    declining                          → engagement_drop
    early_churn / inactive / churned   → low_activity
healthy و never_active وارد جدول نمی‌شوند.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from app.churn import ChurnStatus
from app.config import CHURN_COMPARE_DAYS
from app.models import UserActivity
from app.tracker import EngagementTracker

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 60       # فقط تعامل‌های این بازه خوانده می‌شود
COOLDOWN_DAYS = 7        # تا این مدت بعد از ثبت، همان کاربر دوباره ثبت نمی‌شود

# نوع تعامل در دیتابیس → نوع فعالیت در تراکر
TYPE_TO_CONTENT = {
    "comment": "Comment",
    "direct": "Message",
    "story_reply": "Message",
    "mention": "Mention",
    "like": "Like",
}

STATUS_TO_REASON = {
    ChurnStatus.DECLINING: "engagement_drop",
    ChurnStatus.EARLY_CHURN: "low_activity",
    ChurnStatus.INACTIVE: "low_activity",
    ChurnStatus.CHURNED: "low_activity",
}


def get_connection():
    import psycopg2

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL تنظیم نشده است")
    return psycopg2.connect(url)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def load_tracker(conn, now_func=_utcnow) -> tuple[EngagementTracker, dict[str, str]]:
    """تراکر را از جدول interactions می‌سازد. خروجی دوم: نام کاربری هر user_id."""
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, interaction_type, occurred_at FROM interactions "
        "WHERE occurred_at > NOW() - make_interval(days => %s)",
        (LOOKBACK_DAYS,),
    )
    activities = [
        UserActivity(
            str(uid),
            TYPE_TO_CONTENT.get(itype, "Other"),
            _naive_utc(occurred),
        )
        for uid, itype, occurred in cur.fetchall()
    ]
    tracker = EngagementTracker(activities, now_func)

    cur.execute("SELECT user_id, username, do_not_contact FROM ig_users")
    names: dict[str, str] = {}
    blocked: set[str] = set()
    for uid, username, dnc in cur.fetchall():
        tracker.register_user(str(uid))
        names[str(uid)] = username or str(uid)
        if dnc:
            blocked.add(str(uid))
    names["__blocked__"] = ",".join(sorted(blocked))
    return tracker, names


def sync_inactive_users(conn, now_func=_utcnow, cooldown_days: int = COOLDOWN_DAYS) -> dict:
    """گزارش ریزش را در inactive_users می‌نویسد (idempotent)."""
    tracker, names = load_tracker(conn, now_func)
    blocked = set(filter(None, names.pop("__blocked__", "").split(",")))
    cur = conn.cursor()
    stats = {"inserted": 0, "skipped_cooldown": 0, "skipped_blocked": 0, "skipped_status": 0}

    for r in tracker.get_churn_report(include_healthy=True):
        reason = STATUS_TO_REASON.get(r.status)
        if reason is None:
            stats["skipped_status"] += 1
            continue
        if r.user_id in blocked:
            stats["skipped_blocked"] += 1
            continue

        cur.execute(
            "SELECT 1 FROM inactive_users WHERE user_id = %s "
            "AND detected_at > NOW() - make_interval(days => %s) LIMIT 1",
            (int(r.user_id), cooldown_days),
        )
        if cur.fetchone():
            stats["skipped_cooldown"] += 1
            continue

        cur.execute(
            "INSERT INTO inactive_users (user_id, username, reason, last_interaction_at, window_days) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (user_id, reason) WHERE processed = FALSE DO NOTHING",
            (
                int(r.user_id),
                names.get(r.user_id, r.user_id),
                reason,
                r.last_activity.replace(tzinfo=timezone.utc) if r.last_activity else None,
                CHURN_COMPARE_DAYS,
            ),
        )
        stats["inserted"] += cur.rowcount
    conn.commit()
    logger.info("inactive_users sync: %s", stats)
    return stats


if __name__ == "__main__":
    # python -m app.db_sync            ← یک بار اجرا
    # python -m app.db_sync --loop 3600 ← هر ۳۶۰۰ ثانیه تکرار
    import sys
    import time

    logging.basicConfig(level=logging.INFO)
    interval = int(sys.argv[sys.argv.index("--loop") + 1]) if "--loop" in sys.argv else 0
    while True:
        try:
            connection = get_connection()
            try:
                print(sync_inactive_users(connection), flush=True)
            finally:
                connection.close()
        except Exception:
            logger.exception("sync failed")
            if not interval:
                raise
        if not interval:
            break
        time.sleep(interval)
