from datetime import datetime, timedelta

import pytest

from app.drafts import (
    DraftService,
    DraftState,
    DraftStore,
    InvalidDraftState,
    WindowClosed,
)
from app.models import UserActivity
from app.recovery_queue import QueueItem, QueueState

NOW = datetime(2026, 10, 6, 12, 0, 0)


def item(item_id=1, uid="u1", status="declining"):
    return QueueItem(item_id, uid, status, "r", QueueState.PENDING, None, NOW, NOW)


def msg(hours_ago, text="قیمت مدل X چنده؟"):
    return UserActivity("u1", f"Message: {text}", NOW - timedelta(hours=hours_ago))


class FakeGenerator:
    def __init__(self, name="claude", text=None, error=None):
        self.name, self._text, self._error = name, text, error

    def generate(self, ctx):
        if self._error:
            raise self._error
        return self._text


@pytest.fixture
def svc():
    return DraftService(DraftStore(), now_func=lambda: NOW)


def test_draft_created_in_open_window(svc):
    rec, created = svc.create(item(), [msg(2)])
    assert created
    assert rec.state is DraftState.NEEDS_APPROVAL
    assert rec.can_auto_reply is True
    assert rec.source == "template"
    assert "لغو" in rec.text
    assert rec.facts["last_inbound_message"] == "قیمت مدل X چنده؟"
    assert rec.audit[0]["action"] == "created"


def test_draft_created_but_window_closed(svc):
    rec, _ = svc.create(item(), [msg(50)])
    assert rec.state is DraftState.NEEDS_APPROVAL
    assert rec.can_auto_reply is False


def test_no_prior_message_goes_to_handoff(svc):
    rec, _ = svc.create(item(), [UserActivity("u1", "Comment: عالی بود", NOW)])
    assert rec.state is DraftState.HANDOFF
    assert rec.text is None
    assert "پیام مستقیم" in rec.handoff_reason


def test_sensitive_goes_to_handoff(svc):
    rec, _ = svc.create(item(), [msg(2, "از خرید قبلی ناراضی هستم")])
    assert rec.state is DraftState.HANDOFF and rec.text is None
    assert "حساس" in rec.handoff_reason


def test_opt_out_goes_to_handoff(svc):
    rec, _ = svc.create(item(), [msg(40), msg(2, "لطفا پیام نده")])
    assert rec.state is DraftState.HANDOFF
    assert "انصراف" in rec.handoff_reason


def test_old_sensitive_message_still_blocks(svc):
    rec, _ = svc.create(item(), [msg(200, "میخوام شکایت کنم"), msg(2, "سلام")])
    assert rec.state is DraftState.HANDOFF


def test_create_is_idempotent_per_item(svc):
    first, c1 = svc.create(item(), [msg(2)])
    second, c2 = svc.create(item(), [msg(2)])
    assert c1 and not c2 and first.id == second.id
    assert len(svc.store.items) == 1


def test_llm_error_falls_back_to_template():
    svc = DraftService(DraftStore(), FakeGenerator(error=RuntimeError("boom")), lambda: NOW)
    rec, _ = svc.create(item(), [msg(2)])
    assert rec.source == "template_fallback"
    assert "RuntimeError" in rec.audit[0]["fallback_reason"]
    assert "لغو" in rec.text


def test_llm_invalid_output_falls_back():
    svc = DraftService(DraftStore(), FakeGenerator(text="سلام! تخفیف: https://x.com"), lambda: NOW)
    rec, _ = svc.create(item(), [msg(2)])
    assert rec.source == "template_fallback"
    assert "https" not in rec.text


def test_llm_valid_output_is_kept():
    svc = DraftService(DraftStore(), FakeGenerator(text="سلام! در خدمتیم. «لغو» را بنویسید تا نفرستیم."), lambda: NOW)
    rec, _ = svc.create(item(), [msg(2)])
    assert rec.source == "claude"


def test_approve_with_edit(svc):
    rec, _ = svc.create(item(), [msg(2)])
    approved = svc.approve(rec.id, " sara ", text="متن جدید من. لغو")
    assert approved.state is DraftState.APPROVED
    assert approved.edited and approved.text == "متن جدید من. لغو"
    assert approved.audit[-1]["actor"] == "sara"


def test_approve_validation_and_state_errors(svc):
    rec, _ = svc.create(item(), [msg(2)])
    with pytest.raises(ValueError):
        svc.approve(rec.id, "sara", text="   ")
    with pytest.raises(ValueError):
        svc.approve(rec.id, "  ")
    svc.approve(rec.id, "sara")
    with pytest.raises(InvalidDraftState):
        svc.approve(rec.id, "sara")
    with pytest.raises(KeyError):
        svc.approve(999, "sara")


def test_handoff_cannot_be_approved(svc):
    rec, _ = svc.create(item(), [msg(2, "ناراضی‌ام")])
    with pytest.raises(InvalidDraftState):
        svc.approve(rec.id, "sara")


def test_reject(svc):
    rec, _ = svc.create(item(), [msg(2)])
    assert svc.reject(rec.id, "sara", "مناسب نیست").state is DraftState.REJECTED
    new, created = svc.create(item(), [msg(2)])  # بعد از رد می‌شود دوباره ساخت
    assert created and new.id != rec.id


def test_sent_requires_approval(svc):
    rec, _ = svc.create(item(), [msg(2)])
    with pytest.raises(InvalidDraftState):
        svc.mark_sent(rec.id, [msg(2)])


def test_sent_dm_rechecks_window(svc):
    rec, _ = svc.create(item(), [msg(2)])
    svc.approve(rec.id, "sara")
    with pytest.raises(WindowClosed):          # در فاصله‌ی تأیید، پنجره بسته شد
        svc.mark_sent(rec.id, [msg(30)])
    assert rec.state is DraftState.APPROVED


def test_sent_other_channel_allowed_when_window_closed(svc):
    rec, _ = svc.create(item(), [msg(50)])
    svc.approve(rec.id, "sara")
    sent = svc.mark_sent(rec.id, [msg(50)], channel="phone")
    assert sent.state is DraftState.SENT
    assert sent.audit[-1]["channel"] == "phone"


def test_persistence_roundtrip(tmp_path, svc):
    rec, _ = svc.create(item(), [msg(2)])
    svc.approve(rec.id, "sara", text="متن. لغو")
    path = tmp_path / "drafts.json"
    svc.store.save(path)
    loaded = DraftStore.load(path)
    assert [r.to_dict() for r in loaded.items] == [r.to_dict() for r in svc.store.items]
    assert loaded.add(**{**{k: getattr(rec, k) for k in (
        "queue_item_id", "user_id", "state", "text", "source", "can_auto_reply",
        "window_expires_at", "handoff_reason", "facts", "created_at", "updated_at")}}).id == 2
