import os

# Dummy values so the app can be imported without a real .env
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test")

import hashlib
import hmac
import io
import json
import urllib.error

import pytest

import app.main as main
from app import instagram


def sign(body: bytes, secret: str = "secret") -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class FakeResponse:
    def __init__(self, data: bytes):
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


# webhook verification and signature

def test_verify_challenge(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_VERIFY_TOKEN", "tok")

    assert instagram.verify_challenge("subscribe", "tok", "123") == "123"
    assert instagram.verify_challenge("subscribe", "bad", "123") is None
    assert instagram.verify_challenge("unsubscribe", "tok", "123") is None
    assert instagram.verify_challenge("subscribe", "tok", None) is None
    assert instagram.verify_challenge("subscribe", "توکن", "1") is None


def test_verify_challenge_without_configuration(monkeypatch):
    monkeypatch.delenv("INSTAGRAM_VERIFY_TOKEN", raising=False)

    assert instagram.verify_challenge("subscribe", "tok", "123") is None


def test_verify_signature(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", "secret")
    body = b'{"object":"instagram"}'

    assert instagram.verify_signature(body, sign(body))
    assert not instagram.verify_signature(body, sign(body, "other-secret"))
    assert not instagram.verify_signature(b"changed", sign(body))
    assert not instagram.verify_signature(body, None)
    assert not instagram.verify_signature(body, "sha1=abc")


# parsing

def test_parse_incoming_messages_keeps_only_user_text():
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "BIZ",
                "messaging": [
                    {"sender": {"id": "111"}, "recipient": {"id": "BIZ"},
                     "message": {"mid": "m1", "text": "  سلام  "}},
                    {"sender": {"id": "BIZ"}, "recipient": {"id": "111"},
                     "message": {"mid": "m2", "text": "echo", "is_echo": True}},
                    {"sender": {"id": "111"}, "recipient": {"id": "BIZ"},
                     "message": {"mid": "m3", "is_deleted": True}},
                    {"sender": {"id": "111"}, "recipient": {"id": "BIZ"},
                     "message": {"mid": "m4", "attachments": [{}]}},
                    {"sender": {"id": "111"}, "recipient": {"id": "BIZ"},
                     "postback": {"payload": "x"}},
                ],
            },
            "junk",
        ],
    }

    assert instagram.parse_incoming_messages(payload) == [
        {"sender_id": "111", "recipient_id": "BIZ", "mid": "m1", "text": "سلام"}
    ]


def test_parse_incoming_messages_ignores_other_objects():
    assert instagram.parse_incoming_messages({"object": "page"}) == []
    assert instagram.parse_incoming_messages("not a dict") == []


# splitting and sending

def test_split_text_respects_byte_limit():
    long_text = ("کلمه " * 400).strip()
    parts = instagram.split_text(long_text)

    assert len(parts) > 1
    assert all(len(part.encode("utf-8")) <= 1000 for part in parts)
    assert " ".join(parts).split() == long_text.split()


def test_split_text_edge_cases():
    assert instagram.split_text("hello") == ["hello"]
    assert instagram.split_text("   ") == []

    blob = "ا" * 1500
    parts = instagram.split_text(blob)

    assert all(len(part.encode("utf-8")) <= 1000 for part in parts)
    assert "".join(parts) == blob


def test_send_text_builds_the_documented_request(monkeypatch):
    sent = []

    def fake_urlopen(request, timeout=None):
        sent.append((request.full_url, dict(request.header_items()), json.loads(request.data)))
        return FakeResponse(b'{"recipient_id":"111","message_id":"mm"}')

    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "TKN")
    monkeypatch.delenv("INSTAGRAM_API_VERSION", raising=False)
    monkeypatch.delenv("META_MODE", raising=False)
    monkeypatch.setattr(instagram.urllib.request, "urlopen", fake_urlopen)

    assert instagram.send_messages("111", "سلام دنیا") == 1

    url, headers, body = sent[0]
    assert url == "https://graph.instagram.com/v25.0/me/messages"
    assert headers["Authorization"] == "Bearer TKN"
    assert body == {"recipient": {"id": "111"}, "message": {"text": "سلام دنیا"}}


def test_send_text_requires_token(monkeypatch):
    monkeypatch.delenv("INSTAGRAM_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_MODE", raising=False)

    with pytest.raises(instagram.InstagramError):
        instagram.send_text("111", "hi")


def test_send_text_local_mode_does_not_call_graph(monkeypatch):
    def must_not_be_called(*args, **kwargs):
        pytest.fail("Graph must not be called in META_MODE=local")

    monkeypatch.setenv("META_MODE", "local")
    monkeypatch.delenv("INSTAGRAM_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(instagram.urllib.request, "urlopen", must_not_be_called)

    result = instagram.send_text("111", "hi")
    assert result["message_id"] == "local.simulated"


def test_send_text_reports_http_errors(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 400, "bad", {}, io.BytesIO(b'{"error":"nope"}')
        )

    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "TKN")
    monkeypatch.delenv("META_MODE", raising=False)
    monkeypatch.setattr(instagram.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(instagram.InstagramError) as error:
        instagram.send_text("111", "hi")

    assert "400" in str(error.value)


# message flow (database and Instagram are replaced)

def test_duplicate_event_is_ignored(monkeypatch):
    called = []

    monkeypatch.setattr(main, "message_already_processed", lambda mid: True)
    monkeypatch.setattr(main, "run_pipeline", lambda *args: called.append(args))

    main.process_instagram_event({"sender_id": "111", "mid": "m1", "text": "hi"})

    assert called == []


def test_event_reply_is_sent(monkeypatch):
    sent = []

    monkeypatch.setattr(main, "message_already_processed", lambda mid: False)
    monkeypatch.setattr(
        main,
        "run_pipeline",
        lambda uid, text, mid: {
            "conversation_id": 7, "reply": "answer", "confidence": 0.5,
            "sources": [], "handoff_reason": None,
        },
    )
    monkeypatch.setattr(
        main, "send_reply_to_user", lambda uid, cid, text: sent.append((uid, cid, text))
    )

    main.process_instagram_event({"sender_id": "111", "mid": "m1", "text": "hi"})

    assert sent == [(111, 7, "answer")]


def test_event_errors_never_raise(monkeypatch):
    def broken(*args):
        raise RuntimeError("database is down")

    monkeypatch.setattr(main, "message_already_processed", lambda mid: False)
    monkeypatch.setattr(main, "run_pipeline", broken)

    main.process_instagram_event({"sender_id": "111", "mid": "m1", "text": "hi"})
    main.process_instagram_event({"sender_id": "abc", "mid": "m2", "text": "hi"})


def test_pipeline_passes_message_id_only_when_known(monkeypatch):
    calls = []

    def fake_save(*args):
        calls.append(args)
        return {"conversation_id": 1, "status": "bot", "received_at": "t"}

    monkeypatch.setattr(main, "save_user_message", fake_save)
    monkeypatch.setattr(
        main,
        "generate_llm_response",
        lambda cid, msg: {"text": "ok", "sources": [], "confidence": 0.5, "handoff_reason": None},
    )
    monkeypatch.setattr(main, "save_assistant_message", lambda *args: None)

    main.run_pipeline(1, "hello")
    main.run_pipeline(1, "hello", "mid1")

    assert calls == [(1, "hello"), (1, "hello", "mid1")]


def test_reply_is_not_sent_without_token(monkeypatch):
    sent = []

    monkeypatch.delenv("INSTAGRAM_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(main.instagram, "send_messages", lambda rid, text: sent.append(text))

    main.send_reply_to_user(111, 7, "answer")

    assert sent == []


def test_reply_is_not_sent_outside_24_hour_window(monkeypatch):
    sent = []

    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "TKN")
    monkeypatch.setattr(main, "is_contactable", lambda uid: False)
    monkeypatch.setattr(main.instagram, "send_messages", lambda rid, text: sent.append(text))

    main.send_reply_to_user(111, 7, "answer")

    assert sent == []


def test_first_reply_starts_with_bot_notice(monkeypatch):
    sent = []

    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "TKN")
    monkeypatch.setattr(main, "is_contactable", lambda uid: True)
    monkeypatch.setattr(main, "count_assistant_messages", lambda cid: 1)
    monkeypatch.setattr(main.instagram, "send_messages", lambda rid, text: sent.append((rid, text)))

    main.send_reply_to_user(111, 7, "answer")

    assert sent[0][0] == "111"
    assert sent[0][1].startswith(main.BOT_DISCLOSURE_TEXT)
    assert sent[0][1].endswith("answer")


def test_later_replies_have_no_notice(monkeypatch):
    sent = []

    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "TKN")
    monkeypatch.setattr(main, "is_contactable", lambda uid: True)
    monkeypatch.setattr(main, "count_assistant_messages", lambda cid: 4)
    monkeypatch.setattr(main.instagram, "send_messages", lambda rid, text: sent.append((rid, text)))

    main.send_reply_to_user(111, 7, "answer")

    assert sent == [("111", "answer")]


def test_operators_are_notified_once_per_handoff(monkeypatch):
    notified = []

    monkeypatch.setattr(main, "save_assistant_message", lambda *args: None)
    monkeypatch.setattr(main, "notify_operators", lambda *args: notified.append(args))

    monkeypatch.setattr(main, "create_handoff", lambda cid, reason: (5, True))
    main.run_handoff(2, "complaint", "شکایت", 0.0)

    monkeypatch.setattr(main, "create_handoff", lambda cid, reason: (5, False))
    main.run_handoff(2, "complaint", "شکایت", 0.0)

    assert notified == [(5, 2, "complaint", "شکایت")]


def test_notify_operators_without_url_does_nothing(monkeypatch):
    def must_not_be_called(*args, **kwargs):
        pytest.fail("No request should be made without OPERATOR_WEBHOOK_URL.")

    monkeypatch.setattr(main, "OPERATOR_WEBHOOK_URL", None)
    monkeypatch.setattr(main.urllib.request, "urlopen", must_not_be_called)

    main.notify_operators(1, 2, "complaint", "message")


def test_notify_operators_failure_is_swallowed(monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("down")

    monkeypatch.setattr(main, "OPERATOR_WEBHOOK_URL", "https://hooks.example/x")
    monkeypatch.setattr(main.urllib.request, "urlopen", broken)

    main.notify_operators(1, 2, "complaint", "message")