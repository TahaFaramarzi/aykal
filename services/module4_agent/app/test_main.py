import os
from datetime import datetime, timezone

# Dummy values so the app can be imported without a real .env
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test")

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.main as main
from app.main import (
    MAX_CHUNK_CHARS,
    build_retrieval_query,
    chunk_text,
    cosine_similarity,
    detect_handoff_reason,
    get_handoff_message,
    is_small_talk,
    lexical_embed,
    normalize_text,
    parse_user_id,
)

# The lifespan (database setup) is not started here, so no database is needed.
client = TestClient(main.app)


def fake_saved(status="bot"):
    return lambda ig_user_id, text: {
        "conversation_id": 1,
        "status": status,
        "received_at": datetime.now(timezone.utc),
    }


# pure functions

def test_chunk_text_respects_limit_and_keeps_text():
    text = "\n\n".join(["ا" * 500, "ب" * 500, "ج" * 900])
    chunks = chunk_text(text)

    assert all(len(chunk) <= MAX_CHUNK_CHARS for chunk in chunks)
    assert len("".join(chunks).replace("\n", "")) == 1900


def test_chunk_text_one_chunk_per_paragraph():
    assert chunk_text("الف\n\nب") == ["الف", "ب"]


def test_chunk_text_empty():
    assert chunk_text("   \n\n  ") == []


def test_normalize_text_unifies_letters_and_half_space():
    assert normalize_text("كتاب") == "کتاب"
    assert normalize_text("می\u200cخوام") == "می خوام"


def test_small_talk():
    assert is_small_talk("سلام")
    assert is_small_talk("ممنون!")
    assert not is_small_talk("قیمت آیفون چنده؟")


def test_handoff_reasons():
    assert detect_handoff_reason("من شکایت دارم") == "complaint"
    assert detect_handoff_reason("شماره کارت من اینه") == "sensitive"
    assert detect_handoff_reason("میخوام با اپراتور صحبت کنم") == "unknown"
    assert detect_handoff_reason("هزینه ارسال چقدره") is None


def test_lexical_embed_is_stable_and_normalized():
    a = lexical_embed("قیمت هدفون نوا ۱")
    b = lexical_embed("قیمت هدفون نوا ۱")
    c = lexical_embed("شرایط بازگشت کالا")
    assert a == b
    assert cosine_similarity(a, a) == pytest.approx(1.0)
    assert cosine_similarity(a, c) < 0.99


def test_cosine_similarity():
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine_similarity([0, 0], [1, 1]) == 0.0


def test_parse_user_id():
    assert parse_user_id("12345") == 12345

    with pytest.raises(HTTPException) as error:
        parse_user_id("abc")
    assert error.value.status_code == 400

    with pytest.raises(HTTPException):
        parse_user_id("-5")


def test_handoff_message_language():
    assert "همکاران" in get_handoff_message("سلام")
    assert "team members" in get_handoff_message("hello")


def test_retrieval_query_uses_last_two_user_messages():
    history = [
        {"role": "user", "content": "یک"},
        {"role": "assistant", "content": "جواب"},
        {"role": "user", "content": "دو"},
        {"role": "user", "content": "سه"},
    ]
    assert build_retrieval_query(history) == "دو\nسه"


# endpoints (database and LLM are replaced with fakes)

def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_chat_invalid_user_id_returns_400():
    response = client.post(
        "/chat", json={"user_id": "abc", "message": "سلام"}
    )

    assert response.status_code == 400


def test_chat_returns_answer_with_sources(monkeypatch):
    stored = []

    monkeypatch.setattr(main, "save_user_message", fake_saved())
    monkeypatch.setattr(
        main,
        "generate_llm_response",
        lambda cid, msg: {
            "text": "۵۰ هزار تومان",
            "sources": [{"source": "catalog", "chunk_id": 1, "score": 0.8}],
            "confidence": 0.8,
            "handoff_reason": None,
        },
    )
    monkeypatch.setattr(
        main,
        "save_assistant_message",
        lambda cid, text, sources, confidence: stored.append(text),
    )

    response = client.post(
        "/chat",
        json={"user_id": "12345", "message": "هزینه ارسال به تهران چقدره؟"},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["handoff"] is False
    assert body["sources"] == ["catalog"]
    assert stored == ["۵۰ هزار تومان"]


def test_chat_complaint_is_handed_off(monkeypatch):
    monkeypatch.setattr(main, "save_user_message", fake_saved())
    monkeypatch.setattr(
        main, "run_handoff", lambda cid, reason, msg, conf: "ارجاع شد"
    )

    response = client.post(
        "/chat", json={"user_id": "12345", "message": "من شکایت دارم"}
    )
    body = response.json()

    assert body["status"] == "handoff"
    assert body["handoff_reason"] == "complaint"
    assert body["response"] == "ارجاع شد"


def test_chat_without_evidence_is_handed_off(monkeypatch):
    monkeypatch.setattr(main, "save_user_message", fake_saved())
    monkeypatch.setattr(
        main,
        "generate_llm_response",
        lambda cid, msg: {
            "text": None,
            "sources": [],
            "confidence": 0.1,
            "handoff_reason": "low_confidence",
        },
    )
    monkeypatch.setattr(
        main, "run_handoff", lambda cid, reason, msg, conf: "ارجاع شد"
    )

    response = client.post(
        "/chat", json={"user_id": "12345", "message": "قیمت آیفون چنده؟"}
    )
    body = response.json()

    assert body["handoff"] is True
    assert body["handoff_reason"] == "low_confidence"


def test_chat_stays_silent_when_operator_has_conversation(monkeypatch):
    monkeypatch.setattr(main, "save_user_message", fake_saved("handoff"))
    monkeypatch.setattr(
        main, "get_open_handoff_reason", lambda cid: "complaint"
    )

    def must_not_be_called(*args, **kwargs):
        pytest.fail("The bot must not answer when an operator has the conversation.")

    monkeypatch.setattr(main, "generate_llm_response", must_not_be_called)

    response = client.post(
        "/chat", json={"user_id": "12345", "message": "سلام"}
    )
    body = response.json()

    assert body["response"] is None
    assert body["handoff"] is True