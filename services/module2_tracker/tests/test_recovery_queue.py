from datetime import datetime, timedelta

import pytest

from app.churn import ChurnResult, ChurnStatus
from app.recovery_queue import QueueState, RecoveryQueue
from app.tracker import EngagementTracker

T0 = datetime(2026, 10, 6, 12, 0, 0)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def advance(self, days):
        self.now += timedelta(days=days)


def res(uid, status):
    return ChurnResult(uid, status, f"reason-{status.value}", None, None, 0.0, 0.0)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def queue(clock):
    return RecoveryQueue(now_func=clock)


def test_only_at_risk_users_are_enqueued(queue):
    report = queue.sync([
        res("a", ChurnStatus.EARLY_CHURN),
        res("b", ChurnStatus.HEALTHY),
        res("c", ChurnStatus.NEVER_ACTIVE),
        res("d", ChurnStatus.CHURNED),
    ])
    assert [i.user_id for i in report.enqueued] == ["a"]


def test_sync_is_idempotent(queue):
    results = [res("a", ChurnStatus.INACTIVE)]
    queue.sync(results)
    second = queue.sync(results)
    assert second.enqueued == []
    assert len(queue.items) == 1


def test_status_change_updates_same_item(queue):
    queue.sync([res("a", ChurnStatus.EARLY_CHURN)])
    report = queue.sync([res("a", ChurnStatus.INACTIVE)])
    assert len(queue.items) == 1
    assert report.updated[0].status == "inactive"


def test_recovery_resolves_item(queue):
    queue.sync([res("a", ChurnStatus.DECLINING)])
    report = queue.sync([res("a", ChurnStatus.HEALTHY)])
    assert report.resolved[0].state is QueueState.RESOLVED
    assert queue.pending() == []


def test_churned_user_item_expires(queue):
    queue.sync([res("a", ChurnStatus.INACTIVE)])
    report = queue.sync([res("a", ChurnStatus.CHURNED)])
    assert report.expired[0].state is QueueState.EXPIRED


def test_previous_status_is_recorded(queue):
    queue.sync([res("a", ChurnStatus.HEALTHY)])
    report = queue.sync([res("a", ChurnStatus.EARLY_CHURN)])
    assert report.enqueued[0].previous_status == "healthy"


def test_pending_sorted_by_priority(queue):
    queue.sync([res("z", ChurnStatus.INACTIVE), res("a", ChurnStatus.EARLY_CHURN)])
    assert [i.user_id for i in queue.pending()] == ["a", "z"]


def test_cooldown_after_done(queue, clock):
    results = [res("a", ChurnStatus.INACTIVE)]
    item = queue.sync(results).enqueued[0]
    queue.mark_done(item.id)

    clock.advance(5)
    assert queue.sync(results).enqueued == []   # هنوز در دوره‌ی استراحت

    clock.advance(20)
    assert len(queue.sync(results).enqueued) == 1  # دوره تمام شد، دوباره وارد صف می‌شود


def test_mark_done_errors(queue):
    with pytest.raises(KeyError):
        queue.mark_done(999)
    item = queue.sync([res("a", ChurnStatus.INACTIVE)]).enqueued[0]
    queue.mark_done(item.id)
    with pytest.raises(ValueError):
        queue.mark_done(item.id)


def test_save_and_load_roundtrip(tmp_path, queue, clock):
    queue.sync([res("a", ChurnStatus.EARLY_CHURN), res("b", ChurnStatus.INACTIVE)])
    path = tmp_path / "queue.json"
    queue.save(path)

    loaded = RecoveryQueue.load(path, now_func=clock)
    assert [i.to_dict() for i in loaded.items] == [i.to_dict() for i in queue.items]
    assert loaded.sync([res("a", ChurnStatus.EARLY_CHURN)]).enqueued == []  # حافظه‌ی قبلی حفظ شده
    new = loaded.sync([res("c", ChurnStatus.INACTIVE)]).enqueued[0]
    assert new.id == 3


def test_load_missing_file_gives_empty_queue(tmp_path):
    assert RecoveryQueue.load(tmp_path / "none.json").items == []


def test_integration_with_tracker(clock):
    tracker = EngagementTracker(now_func=clock)
    tracker.add_activity("fresh", "Like Post", T0 - timedelta(days=1))
    tracker.add_activity("quiet", "Like Post", T0 - timedelta(days=5))
    tracker.register_user("ghost")

    queue = RecoveryQueue(now_func=clock)
    report = queue.sync(tracker.get_churn_report(include_healthy=True))
    assert [i.user_id for i in report.enqueued] == ["quiet"]

    # کاربر quiet برمی‌گردد → آیتمش بسته می‌شود
    tracker.add_activity("quiet", "Upload Post", T0)
    report = queue.sync(tracker.get_churn_report(include_healthy=True))
    assert [i.user_id for i in report.resolved] == ["quiet"]
