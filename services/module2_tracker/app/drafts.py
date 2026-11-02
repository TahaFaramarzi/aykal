"""چرخه‌ی عمر پیش‌نویس‌ها: تولید ← تأیید انسانی ← ارسال، همراه با لاگ داخلی.

نکته: این ماژول **پیامی ارسال نمی‌کند**؛ `mark_sent` فقط ثبت می‌کند که اپراتور ارسال کرده است.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Iterable, Optional

from app.config import SENSITIVE_LOOKBACK_TEXTS
from app.drafting import (
    DraftContext,
    DraftGenerator,
    TemplateDraftGenerator,
    validate_generated,
    validate_text,
)
from app.messaging import find_opt_out, find_sensitive, get_reply_window
from app.models import DATE_FORMAT, ActivityType, UserActivity
from app.recovery_queue import QueueItem
from app.storage import read_json, write_report

INBOUND_CHANNEL = "instagram_dm"


class DraftState(str, Enum):
    NEEDS_APPROVAL = "needs_approval"  # منتظر تأیید اپراتور
    APPROVED = "approved"              # تأیید شد، هنوز ارسال نشده
    REJECTED = "rejected"
    SENT = "sent"
    HANDOFF = "handoff"                # پیش‌نویسی ساخته نشد؛ مستقیم به اپراتور


class DraftConflict(Exception):
    """عملیات با وضعیت فعلی پیش‌نویس سازگار نیست (در API → 409)."""


class InvalidDraftState(DraftConflict):
    pass


class WindowClosed(DraftConflict):
    pass


def _fmt(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime(DATE_FORMAT) if dt else None


def _parse(text: Optional[str]) -> Optional[datetime]:
    return datetime.strptime(text, DATE_FORMAT) if text else None


@dataclass
class DraftRecord:
    id: int
    queue_item_id: int
    user_id: str
    state: DraftState
    text: Optional[str]
    source: Optional[str]                 # template | claude | template_fallback | None
    can_auto_reply: bool                  # عکس لحظه‌ی ساخت؛ هنگام ارسال دوباره بررسی می‌شود
    window_expires_at: Optional[datetime]
    handoff_reason: Optional[str]
    facts: dict                           # اطلاعاتی که پیش‌نویس بر پایه‌ی آن‌ها ساخته شد
    created_at: datetime
    updated_at: datetime
    edited: bool = False
    audit: list[dict] = field(default_factory=list)

    def log(self, action: str, now: datetime, actor: str = "system", **details) -> None:
        self.audit.append({"time": _fmt(now), "action": action, "actor": actor, **details})
        self.updated_at = now

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "queue_item_id": self.queue_item_id,
            "user_id": self.user_id,
            "state": self.state.value,
            "text": self.text,
            "source": self.source,
            "can_auto_reply": self.can_auto_reply,
            "window_expires_at": _fmt(self.window_expires_at),
            "handoff_reason": self.handoff_reason,
            "facts": self.facts,
            "created_at": _fmt(self.created_at),
            "updated_at": _fmt(self.updated_at),
            "edited": self.edited,
            "audit": self.audit,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DraftRecord":
        return cls(
            id=d["id"], queue_item_id=d["queue_item_id"], user_id=d["user_id"],
            state=DraftState(d["state"]), text=d.get("text"), source=d.get("source"),
            can_auto_reply=d["can_auto_reply"],
            window_expires_at=_parse(d.get("window_expires_at")),
            handoff_reason=d.get("handoff_reason"), facts=d.get("facts", {}),
            created_at=_parse(d["created_at"]), updated_at=_parse(d["updated_at"]),
            edited=d.get("edited", False), audit=list(d.get("audit", [])),
        )


class DraftStore:
    def __init__(self):
        self._items: list[DraftRecord] = []
        self._next_id = 1

    @property
    def items(self) -> list[DraftRecord]:
        return list(self._items)

    def get(self, draft_id: int) -> DraftRecord:
        for r in self._items:
            if r.id == draft_id:
                return r
        raise KeyError(f"پیش‌نویسی با شناسه‌ی {draft_id} وجود ندارد")

    def open_for_item(self, queue_item_id: int) -> Optional[DraftRecord]:
        open_states = (DraftState.NEEDS_APPROVAL, DraftState.APPROVED)
        for r in self._items:
            if r.queue_item_id == queue_item_id and r.state in open_states:
                return r
        return None

    def list(self, state: Optional[DraftState] = None) -> list[DraftRecord]:
        return [r for r in self._items if state is None or r.state is state]

    def add(self, **fields) -> DraftRecord:
        record = DraftRecord(id=self._next_id, **fields)
        self._next_id += 1
        self._items.append(record)
        return record

    def save(self, path) -> None:
        write_report({"next_id": self._next_id, "items": [r.to_dict() for r in self._items]}, path)

    @classmethod
    def load(cls, path) -> "DraftStore":
        raw = read_json(path)
        store = cls()
        store._next_id = raw.get("next_id", 1)
        store._items = [DraftRecord.from_dict(d) for d in raw.get("items", [])]
        return store


class DraftService:
    def __init__(
        self,
        store: DraftStore,
        generator: Optional[DraftGenerator] = None,
        now_func: Callable[[], datetime] = datetime.now,
    ):
        self.store = store
        self.generator = generator or TemplateDraftGenerator()
        self._fallback = TemplateDraftGenerator()
        self._now = now_func

    # ---------- ساخت ----------
    def create(self, item: QueueItem, activities: Iterable[UserActivity]) -> tuple[DraftRecord, bool]:
        """(رکورد، آیا_تازه_ساخته_شد). برای هر آیتم صف حداکثر یک پیش‌نویس باز وجود دارد."""
        existing = self.store.open_for_item(item.id)
        if existing:
            return existing, False

        now = self._now()
        activities = sorted(activities, key=lambda a: a.created_at)
        window = get_reply_window(activities, now)
        inbound = [a for a in activities if a.type is ActivityType.MESSAGE and a.created_at <= now]
        user_texts = [
            a.detail for a in activities
            if a.type in (ActivityType.MESSAGE, ActivityType.COMMENT) and a.detail
        ][-SENSITIVE_LOOKBACK_TEXTS:]

        facts: dict = {"churn_status": item.status}
        if inbound:
            facts["last_inbound_message_at"] = _fmt(inbound[-1].created_at)
            facts["last_inbound_message"] = inbound[-1].detail[:200]  # حداقل‌گرایی در داده

        reason = None
        if (kw := find_opt_out(user_texts)):
            reason = f"کاربر درخواست انصراف داده است ({kw})"
        elif (kw := find_sensitive(user_texts)):
            reason = f"محتوای حساس یا شکایت ({kw}) ← فقط اپراتور"
        elif not inbound:
            reason = "کاربر هرگز پیام مستقیم نداده؛ ارسال پیام ابتدایی مجاز نیست"

        common = dict(
            queue_item_id=item.id, user_id=item.user_id, facts=facts,
            created_at=now, updated_at=now,
        )

        if reason:
            record = self.store.add(
                state=DraftState.HANDOFF, text=None, source=None, can_auto_reply=False,
                window_expires_at=window.expires_at, handoff_reason=reason, **common)
            record.log("handoff", now, reason=reason)
            return record, True

        ctx = DraftContext(
            status=item.status,
            last_message=inbound[-1].detail,
            days_since_last_message=(now - inbound[-1].created_at).days,
        )
        text, source, fallback_reason = None, self.generator.name, None
        try:
            text = self.generator.generate(ctx)
            issues = validate_generated(text)
            if issues:
                fallback_reason = "خروجی نامعتبر: " + "، ".join(issues)
        except Exception as exc:  # هر خطای مولد → جایگزین قالبی
            fallback_reason = f"خطای مولد: {type(exc).__name__}"
        if fallback_reason and self.generator.name != self._fallback.name:
            text, source = self._fallback.generate(ctx), "template_fallback"

        record = self.store.add(
            state=DraftState.NEEDS_APPROVAL, text=text, source=source,
            can_auto_reply=window.is_open, window_expires_at=window.expires_at,
            handoff_reason=None, **common)
        record.log("created", now, source=source, can_auto_reply=window.is_open,
                   fallback_reason=fallback_reason)
        return record, True

    # ---------- تأیید انسانی ----------
    def approve(self, draft_id: int, reviewer: str, text: Optional[str] = None) -> DraftRecord:
        record = self.store.get(draft_id)
        if record.state is not DraftState.NEEDS_APPROVAL:
            raise InvalidDraftState(f"پیش‌نویس در وضعیت {record.state.value} است و قابل تأیید نیست")
        if not reviewer or not reviewer.strip():
            raise ValueError("نام تأییدکننده الزامی است")
        edited = False
        if text is not None:
            issues = validate_text(text)
            if issues:
                raise ValueError("؛ ".join(issues))
            edited = text.strip() != (record.text or "")
            record.text = text.strip()
            record.edited = record.edited or edited
        record.state = DraftState.APPROVED
        record.log("approved", self._now(), actor=reviewer.strip(), edited=edited)
        return record

    def reject(self, draft_id: int, reviewer: str, reason: Optional[str] = None) -> DraftRecord:
        record = self.store.get(draft_id)
        if record.state is not DraftState.NEEDS_APPROVAL:
            raise InvalidDraftState(f"پیش‌نویس در وضعیت {record.state.value} است و قابل رد نیست")
        if not reviewer or not reviewer.strip():
            raise ValueError("نام تأییدکننده الزامی است")
        record.state = DraftState.REJECTED
        record.log("rejected", self._now(), actor=reviewer.strip(), reason=reason)
        return record

    def mark_sent(self, draft_id: int, activities: Iterable[UserActivity],
                  channel: str = INBOUND_CHANNEL) -> DraftRecord:
        """ثبت اینکه اپراتور پیام را فرستاده. برای دایرکت، پنجره‌ی ۲۴ ساعته دوباره چک می‌شود."""
        record = self.store.get(draft_id)
        if record.state is not DraftState.APPROVED:
            raise InvalidDraftState("فقط پیش‌نویس تأییدشده قابل ثبت به‌عنوان ارسال‌شده است")
        now = self._now()
        if channel == INBOUND_CHANNEL and not get_reply_window(activities, now).is_open:
            raise WindowClosed("پنجره‌ی ۲۴ ساعته‌ی دایرکت بسته شده؛ از کانال دیگری پیگیری کنید")
        record.state = DraftState.SENT
        record.log("sent", now, channel=channel)
        return record
