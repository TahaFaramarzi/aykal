from datetime import datetime, timedelta

import pytest

from app.models import UserActivity
from app.scoring import calculate_score, classify

NOW = datetime(2026, 10, 6, 12, 0, 0)


def act(content, days_ago):
    return UserActivity("u1", content, NOW - timedelta(days=days_ago))


def test_inactive_user_scores_zero_and_level_1():
    score = calculate_score([], NOW)
    assert score == 0
    assert classify(score)[0] == 1


def test_old_activity_is_ignored():
    assert calculate_score([act("Upload Post", 60)], NOW) == 0


def test_more_activity_means_higher_score():
    few = [act("Like Post", 1)]
    many = [act("Like Post", 1)] * 10
    assert calculate_score(many, NOW) > calculate_score(few, NOW)


def test_upload_is_worth_more_than_login():
    assert calculate_score([act("Upload Post", 1)], NOW) > calculate_score([act("Login", 1)], NOW)


def test_score_is_capped():
    assert calculate_score([act("Upload Post", 0)] * 500, NOW) == 200


@pytest.mark.parametrize("score, level", [
    (0, 1), (10, 1), (11, 2), (50, 2), (51, 3), (100, 3), (101, 4), (150, 4), (151, 5), (200, 5),
])
def test_level_boundaries(score, level):
    assert classify(score)[0] == level


def test_reason_matches_level():
    assert "کم‌فعال" in classify(0)[1]
    assert "سوپر" in classify(200)[1]
