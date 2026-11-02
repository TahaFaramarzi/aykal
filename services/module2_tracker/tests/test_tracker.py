from datetime import datetime, timedelta

import pytest

from app.models import UserActivity
from app.storage import JsonStorage
from app.tracker import EngagementTracker

NOW = datetime(2026, 10, 6, 12, 0, 0)


@pytest.fixture
def tracker():
    return EngagementTracker(now_func=lambda: NOW)


def test_unknown_user_is_level_1(tracker):
    assert tracker.get_user_level("ghost") == 1


def test_add_activity_uses_injected_clock(tracker):
    a = tracker.add_activity("u1", "Login")
    assert a.created_at == NOW


def test_recent_activities_filters_by_days_and_user(tracker):
    tracker.add_activity("u1", "Login", NOW - timedelta(days=2))
    tracker.add_activity("u1", "Login", NOW - timedelta(days=10))
    tracker.add_activity("u2", "Login", NOW - timedelta(days=1))
    assert len(tracker.get_recent_activities("u1", 3)) == 1
    assert len(tracker.get_recent_activities("u1", 30)) == 2


def test_active_user_gets_higher_level_than_inactive(tracker):
    for c in ["Like Post", "Comment: hi", "Upload Post", "Follow User x", "View Story"]:
        tracker.add_activity("busy", c)
    tracker.add_activity("lazy", "Logout", NOW - timedelta(days=20))
    assert tracker.get_user_level("busy") > tracker.get_user_level("lazy")


def test_analyze_all_users_includes_every_user_sorted(tracker):
    tracker.add_activity("u2", "Login")
    tracker.add_activity("u1", "Login")
    report = tracker.analyze_all_users()
    assert list(report) == ["u1", "u2"]
    assert set(report["u1"]) == {"score", "level", "reason", "recent_activities"}


def test_leaderboard_order(tracker):
    tracker.add_activity("a", "Login")
    for _ in range(5):
        tracker.add_activity("b", "Upload Post")
    assert tracker.get_leaderboard(2)[0][0] == "b"


def test_storage_roundtrip(tmp_path, tracker):
    tracker.add_activity("u1", "Login")
    store = JsonStorage(tmp_path / "act.json")
    store.save(tracker.all_activities)
    loaded = store.load()
    assert loaded == tracker.all_activities


def test_missing_storage_file_returns_empty(tmp_path):
    assert JsonStorage(tmp_path / "nope.json").load() == []
