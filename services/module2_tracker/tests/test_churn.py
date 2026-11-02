from datetime import datetime, timedelta

import pytest

from app.churn import ChurnStatus, assess_churn
from app.models import UserActivity
from app.tracker import EngagementTracker

NOW = datetime(2026, 10, 6, 12, 0, 0)


def acts(days_ago_list, content="Like Post", uid="u1"):
    return [UserActivity(uid, content, NOW - timedelta(days=d)) for d in days_ago_list]


def test_no_activity_is_never_active():
    r = assess_churn("u1", [], NOW)
    assert r.status is ChurnStatus.NEVER_ACTIVE
    assert r.days_since_last is None


def test_long_absence_is_churned():
    r = assess_churn("u1", acts([45]), NOW)
    assert r.status is ChurnStatus.CHURNED
    assert r.days_since_last == 45


def test_medium_absence_is_inactive():
    r = assess_churn("u1", acts([15, 16]), NOW)
    assert r.status is ChurnStatus.INACTIVE
    assert r.days_since_last == 15


def test_sharp_drop_is_declining():
    # ۵ فعالیت در هفته‌ی قبل، فقط ۱ فعالیت در هفته‌ی اخیر
    r = assess_churn("u1", acts([8, 9, 10, 11, 12, 1]), NOW)
    assert r.status is ChurnStatus.DECLINING
    assert "کاهش" in r.reason


def test_stable_user_is_healthy():
    r = assess_churn("u1", acts([1, 2, 3, 8, 9, 10]), NOW)
    assert r.status is ChurnStatus.HEALTHY


def test_new_user_without_history_is_healthy():
    assert assess_churn("u1", acts([0, 1]), NOW).status is ChurnStatus.HEALTHY


def test_logout_only_counts_as_stopped_engagement():
    # Logout وزن صفر دارد، پس تعامل واقعی حساب نمی‌شود
    items = acts([8, 9, 10, 11], "Like Post") + acts([1], "Logout")
    assert assess_churn("u1", items, NOW).status is ChurnStatus.EARLY_CHURN


def test_early_churn_recently_active_then_quiet():
    # تا ۵ روز پیش فعال بود، ۳ روز اخیر هیچ تعاملی ندارد
    r = assess_churn("u1", acts([5, 6, 7]), NOW)
    assert r.status is ChurnStatus.EARLY_CHURN
    assert "ریزش اولیه" in r.reason


def test_not_early_churn_if_active_in_last_3_days():
    r = assess_churn("u1", acts([1, 5, 6, 7]), NOW)
    assert r.status is not ChurnStatus.EARLY_CHURN


def test_long_absence_wins_over_early_churn():
    assert assess_churn("u1", acts([10]), NOW).status is ChurnStatus.INACTIVE


@pytest.fixture
def tracker():
    t = EngagementTracker(now_func=lambda: NOW)
    t.add_activity("healthy", "Like Post", NOW - timedelta(days=1))
    t.add_activity("healthy", "Like Post", NOW - timedelta(days=9))
    t.add_activity("gone", "Login", NOW - timedelta(days=50))
    t.add_activity("away", "Login", NOW - timedelta(days=12))
    t.register_user("ghost")
    return t


def test_report_excludes_healthy_by_default(tracker):
    ids = [r.user_id for r in tracker.get_churn_report()]
    assert "healthy" not in ids
    assert set(ids) == {"gone", "away", "ghost"}


def test_report_includes_healthy_when_asked(tracker):
    assert "healthy" in [r.user_id for r in tracker.get_churn_report(include_healthy=True)]


def test_report_priority_order(tracker):
    statuses = [r.status for r in tracker.get_churn_report()]
    assert statuses == [ChurnStatus.INACTIVE, ChurnStatus.CHURNED, ChurnStatus.NEVER_ACTIVE]


def test_register_user_rejects_empty(tracker):
    with pytest.raises(ValueError):
        tracker.register_user("")
