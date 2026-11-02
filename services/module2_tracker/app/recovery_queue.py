"""صف اقدامات ترمیمی: فقط «تغییر وضعیت»ها وارد صف می‌شوند، نه هر بار کل گزارش.

قواعد:
- کاربر در وضعیت‌های QUEUE_STATUSES وارد صف می‌شود (یک آیتم باز برای هر کاربر).
- اگر وضعیتش تغییر کند ولی هنوز در صف‌شدنی‌ها باشد، همان آیتم به‌روز می‌شود (تکراری نمی‌سازد).
- اگر سالم شود → RESOLVED. اگر به وضعیتی برود که دیگر قابل ترمیم نیست (مثلاً churned) → EXPIRED.
- بعد از mark_done، تا QUEUE_COOLDOWN_DAYS کاربر دوباره وارد صف نمی‌شود.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Iterable, Optional

from app.churn import STATUS_ORDER, ChurnResult, ChurnStatus
from app.config import QUEUE_COOLDOWN_DAYS, QUEUE_STATUSES
from app.models import DATE_FORMAT
from app.storage import read_json, write_report


class QueueState(str, Enum):
    PENDING = "pending"    # در انتظار اقدام
    DONE = "done"          # اقدام انجام شد
    RESOLVED = "resolved"  # کاربر خودش برگشت و سالم شد
    EXPIRED = "expired"    # دیگر قابل ترمیم با اقدام نرم نیست


def _fmt(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime(DATE_FORMAT) if dt else None


def _parse(text: Optional[str]) -> Optional[datetime]:
    return datetime.strptime(text, DATE_FORMAT) if text else None


@dataclass
class QueueItem:
    id: int
    user_id: str
    status: str                      # مقدار ChurnStatus
    reason: str
    state: QueueState
    previous_status: Optional[str]   # وضعیت قبلی کاربر هنگام ورود به صف
    enqueued_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "status": self.status,
            "reason": self.reason,
            "state": self.state.value,
            "previous_status": self.previous_status,
            "enqueued_at": _fmt(self.enqueued_at),
            "updated_at": _fmt(self.updated_at),
            "closed_at": _fmt(self.closed_at),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "QueueItem":
        return cls(
            id=d["id"],
            user_id=d["user_id"],
            status=d["status"],
            reason=d["reason"],
            state=QueueState(d["state"]),
            previous_status=d.get("previous_status"),
            enqueued_at=_parse(d["enqueued_at"]),
            updated_at=_parse(d["updated_at"]),
            closed_at=_parse(d.get("closed_at")),
        )


@dataclass
class SyncReport:
    enqueued: list[QueueItem] = field(default_factory=list)
    updated: list[QueueItem] = field(default_factory=list)
    resolved: list[QueueItem] = field(default_factory=list)
    expired: list[QueueItem] = field(default_factory=list)


class RecoveryQueue:
    def __init__(self, now_func: Callable[[], datetime] = datetime.now):
        self._now = now_func
        self._items: list[QueueItem] = []
        self._last_status: dict[str, str] = {}
        self._next_id = 1

    # ---------- پرس‌وجو ----------
    @property
    def items(self) -> list[QueueItem]:
        return list(self._items)

    def get_open_item(self, user_id: str) -> Optional[QueueItem]:
        for item in self._items:
            if item.user_id == user_id and item.state is QueueState.PENDING:
                return item
        return None

    def get_item(self, item_id: int) -> QueueItem:
        for item in self._items:
            if item.id == item_id:
                return item
        raise KeyError(f"آیتمی با شناسه‌ی {item_id} وجود ندارد")

    def pending(self) -> list[QueueItem]:
        """آیتم‌های در انتظار؛ به ترتیب اولویت و سپس قدیمی‌ترین."""
        items = [i for i in self._items if i.state is QueueState.PENDING]
        items.sort(key=lambda i: (STATUS_ORDER.index(ChurnStatus(i.status)), i.enqueued_at, i.id))
        return items

    def _in_cooldown(self, user_id: str, now: datetime) -> bool:
        limit = timedelta(days=QUEUE_COOLDOWN_DAYS)
        return any(
            i.user_id == user_id and i.state is QueueState.DONE
            and i.closed_at is not None and now - i.closed_at < limit
            for i in self._items
        )

    # ---------- تغییر وضعیت ----------
    def sync(self, results: Iterable[ChurnResult]) -> SyncReport:
        """
        نتیجه‌ی تحلیل **همه‌ی کاربران** (حتی سالم‌ها) را می‌گیرد و صف را به‌روز می‌کند.
        چند بار اجرا کردنش با همان داده بی‌اثر است (idempotent).
        """
        now = self._now()
        report = SyncReport()

        for r in results:
            status = r.status.value
            queueable = status in QUEUE_STATUSES
            open_item = self.get_open_item(r.user_id)

            if open_item:
                if r.status is ChurnStatus.HEALTHY:
                    self._close(open_item, QueueState.RESOLVED, now)
                    report.resolved.append(open_item)
                elif queueable:
                    if open_item.status != status:
                        open_item.status = status
                        open_item.reason = r.reason
                        open_item.updated_at = now
                        report.updated.append(open_item)
                else:
                    self._close(open_item, QueueState.EXPIRED, now)
                    report.expired.append(open_item)
            elif queueable and not self._in_cooldown(r.user_id, now):
                item = QueueItem(
                    id=self._next_id,
                    user_id=r.user_id,
                    status=status,
                    reason=r.reason,
                    state=QueueState.PENDING,
                    previous_status=self._last_status.get(r.user_id),
                    enqueued_at=now,
                    updated_at=now,
                )
                self._next_id += 1
                self._items.append(item)
                report.enqueued.append(item)

            self._last_status[r.user_id] = status

        return report

    def mark_done(self, item_id: int) -> QueueItem:
        for item in self._items:
            if item.id == item_id:
                if item.state is not QueueState.PENDING:
                    raise ValueError(f"آیتم {item_id} در انتظار نیست (وضعیت: {item.state.value})")
                self._close(item, QueueState.DONE, self._now())
                return item
        raise KeyError(f"آیتمی با شناسه‌ی {item_id} وجود ندارد")

    def _close(self, item: QueueItem, state: QueueState, now: datetime) -> None:
        item.state = state
        item.updated_at = now
        item.closed_at = now

    # ---------- ذخیره‌سازی ----------
    def to_dict(self) -> dict:
        return {
            "next_id": self._next_id,
            "last_status": dict(self._last_status),
            "items": [i.to_dict() for i in self._items],
        }

    def save(self, path) -> None:
        write_report(self.to_dict(), path)

    @classmethod
    def load(cls, path, now_func: Callable[[], datetime] = datetime.now) -> "RecoveryQueue":
        raw = read_json(path)
        q = cls(now_func)
        q._next_id = raw.get("next_id", 1)
        q._last_status = dict(raw.get("last_status", {}))
        q._items = [QueueItem.from_dict(d) for d in raw.get("items", [])]
        return q
