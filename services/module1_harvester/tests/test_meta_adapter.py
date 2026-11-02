from app.meta_adapter import parse_webhook_payload
from app.schemas import InteractionType


def test_parse_comment():
    payload = {
        "object": "instagram",
        "entry": [{
            "id": "ig_page_id",
            "changes": [{
                "field": "comments",
                "value": {
                    "id": "comment_123",
                    "text": "سلام قیمت چنده؟",
                    "from": {"id": "456456", "username": "ali"},
                    "media": {"id": "media_789"},
                    "created_time": 1700000000,
                }
            }]
        }]
    }
    events = parse_webhook_payload(payload)
    assert len(events) == 1
    assert events[0].instagram_id == "456456"
    assert events[0].interaction_type == InteractionType.COMMENT
    assert "قیمت" in events[0].text_content


def test_parse_direct_message():
    payload = {
        "object": "instagram",
        "entry": [{
            "id": "ig_page_id",
            "messaging": [{
                "sender": {"id": "999999"},
                "recipient": {"id": "ig_page_id"},
                "timestamp": 1700000000,
                "message": {"mid": "mid.123", "text": "سلام"},
            }]
        }]
    }
    events = parse_webhook_payload(payload)
    assert len(events) == 1
    assert events[0].instagram_id == "999999"
    assert events[0].interaction_type == InteractionType.DIRECT


def test_skip_echo_messages():
    payload = {
        "object": "instagram",
        "entry": [{
            "messaging": [{
                "sender": {"id": "page"},
                "message": {"is_echo": True, "text": "پاسخ ما"},
            }]
        }]
    }
    assert parse_webhook_payload(payload) == []


def test_non_instagram_object():
    assert parse_webhook_payload({"object": "page"}) == []