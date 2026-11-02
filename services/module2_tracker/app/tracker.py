"""کلاس اصلی EngagementTracker."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Callable, Iterable, Optional

from app.churn import STATUS_ORDER, ChurnResult, ChurnStatus, assess_churn
from app.config import REPORT_DAYS
from app.models import UserActivity
from app.scoring import calculate_score, classify

logger = logging.getLogger(__name__)


class EngagementTracker:
    def __init__(
        self,
        activities: Optional[Iterable[UserActivity]] = None,
        now_func: Callable[[], datetime] = datetime.now,
    ):
        """
        activities: فعالیت‌های اولیه (اختیاری)
        now_func:   تابع زمان فعلی؛ در تست می‌توان زمان ثابت داد.
        """
        self._now = now_func
        self._by_user: dict[str, list[UserActivity]] = defaultdict(list)
        for activity in activities or []:
            self._by_user[activity.user_id].append(activity)

    def now(self) -> datetime:
        return self._now()

    def has_user(self, user_id: str) -> bool:
        return user_id in self._by_user

    # ---------- نوشتن ----------
    def register_user(self, user_id: str) -> None:
        """کاربری را بدون فعالیت ثبت می‌کند (برای تشخیص «هرگز فعال نبوده»)."""
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("user_id نباید خالی باشد")
        self._by_user[user_id]  # defaultdict ورودی خالی می‌سازد

    def add_activity(
        self, user_id: str, content: str, created_at: Optional[datetime] = None
    ) -> UserActivity:
        activity = UserActivity(user_id, content, created_at or self._now())
        self._by_user[user_id].append(activity)
        logger.info("فعالیت جدید برای %s: %s", user_id, content)
        return activity

    # ---------- خواندن ----------
    @property
    def all_activities(self) -> list[UserActivity]:
        return [a for items in self._by_user.values() for a in items]

    def get_activities(self, user_id: str) -> list[UserActivity]:
        """همه‌ی فعالیت‌های یک کاربر (کپی لیست)."""
        return list(self._by_user.get(user_id, []))

    @property
    def user_ids(self) -> list[str]:
        return sorted(self._by_user)

    def get_recent_activities(self, user_id: str, days: int) -> list[UserActivity]:
        from datetime import timedelta

        start = self._now() - timedelta(days=days)
        return [a for a in self._by_user.get(user_id, []) if a.created_at >= start]

    # ---------- امتیاز و سطح ----------
    def get_user_activity_score(self, user_id: str) -> int:
        return calculate_score(self._by_user.get(user_id, []), self._now())

    def get_user_level(self, user_id: str) -> int:
        return classify(self.get_user_activity_score(user_id))[0]

    # ---------- تحلیل ----------
    def analyze_user(self, user_id: str) -> dict:
        score = self.get_user_activity_score(user_id)  # فقط یک بار محاسبه
        level, reason = classify(score)
        recent = sorted(
            self.get_recent_activities(user_id, REPORT_DAYS),
            key=lambda a: a.created_at,
        )
        return {
            "score": score,
            "level": level,
            "reason": reason,
            "recent_activities": [a.to_dict() for a in recent],
        }

    def analyze_all_users(self) -> dict:
        return {uid: self.analyze_user(uid) for uid in self.user_ids}

    def get_leaderboard(self, top_n: int = 5) -> list[tuple[str, int]]:
        """برترین کاربران بر اساس امتیاز (نزولی)."""
        ranking = [(uid, self.get_user_activity_score(uid)) for uid in self.user_ids]
        ranking.sort(key=lambda item: (-item[1], item[0]))
        return ranking[:top_n]

    # ---------- ریزش ----------
    def get_churn_status(self, user_id: str) -> ChurnResult:
        return assess_churn(user_id, self._by_user.get(user_id, []), self._now())

    def get_churn_report(self, include_healthy: bool = False) -> list[ChurnResult]:
        """کاربران در حال ریزش؛ مرتب بر اساس اولویت و سپس مدت بی‌فعالیتی."""
        now = self._now()
        results = [assess_churn(uid, self._by_user[uid], now) for uid in self.user_ids]
        if not include_healthy:
            results = [r for r in results if r.status is not ChurnStatus.HEALTHY]
        results.sort(key=lambda r: (STATUS_ORDER.index(r.status), -(r.days_since_last or 0), r.user_id))
        return results
