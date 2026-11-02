from datetime import datetime

import pytest

from app.models import ActivityType, UserActivity


def test_created_at_defaults_to_now():
    a = UserActivity("u1", "Login")
    assert isinstance(a.created_at, datetime)


def test_string_date_is_parsed():
    a = UserActivity("u1", "Login", "2026-10-03 10:00:00")
    assert a.created_at == datetime(2026, 10, 3, 10, 0, 0)


@pytest.mark.parametrize("uid, content", [("", "x"), ("  ", "x"), ("u1", ""), ("u1", " ")])
def test_empty_fields_rejected(uid, content):
    with pytest.raises(ValueError):
        UserActivity(uid, content)


def test_bad_date_rejected():
    with pytest.raises(ValueError):
        UserActivity("u1", "Login", "03/10/2026")


def test_dict_roundtrip():
    a = UserActivity("u1", "Login", "2026-10-03 10:00:00")
    assert UserActivity.from_dict(a.to_dict()) == a


@pytest.mark.parametrize("content, expected", [
    ("Login", ActivityType.LOGIN),
    ("Comment: Nice photo!", ActivityType.COMMENT),
    ("Upload Post", ActivityType.UPLOAD),
    ("something else", ActivityType.OTHER),
])
def test_activity_type_detection(content, expected):
    assert UserActivity("u1", content).type == expected
