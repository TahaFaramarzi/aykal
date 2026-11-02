from datetime import datetime, timedelta

import pytest

from app.messaging import find_opt_out, find_sensitive, get_reply_window
from app.models import UserActivity

NOW = datetime(2026, 10, 6, 12, 0, 0)


def msg(hours_ago, text="سلام"):
    return UserActivity("u1", f"Message: {text}", NOW - timedelta(hours=hours_ago))


def test_window_open_within_24h():
    w = get_reply_window([msg(2)], NOW)
    assert w.is_open and w.hours_left == 22


def test_window_closed_after_24h():
    w = get_reply_window([msg(25)], NOW)
    assert not w.is_open and w.hours_left == 0


def test_window_boundary_exactly_24h_is_closed():
    assert not get_reply_window([msg(24)], NOW).is_open


def test_uses_latest_inbound_message():
    assert get_reply_window([msg(30), msg(1)], NOW).is_open


def test_no_message_means_closed():
    w = get_reply_window([UserActivity("u1", "Like Post", NOW)], NOW)
    assert not w.is_open and w.last_inbound_at is None


def test_comments_do_not_open_window():
    assert not get_reply_window([UserActivity("u1", "Comment: hi", NOW)], NOW).is_open


def test_future_messages_ignored():
    assert not get_reply_window([msg(-5)], NOW).is_open


@pytest.mark.parametrize("text", [
    "من از این خرید ناراضی هستم", "میخوام شکایت کنم", "پس‌بده پولم رو", "پس بدید پولمو",
    "I want a REFUND", "كلاهبردار",
])
def test_sensitive_detected(text):
    assert find_sensitive([text]) is not None


def test_normal_text_not_sensitive():
    assert find_sensitive(["سلام قیمت مدل X چنده؟"]) is None


@pytest.mark.parametrize("text", ["لغو", "لطفا پیام نده", "STOP", "پیام‌ندید"])
def test_opt_out_detected(text):
    assert find_opt_out([text]) is not None


def test_not_opt_out():
    assert find_opt_out(["سلام وقت بخیر"]) is None
