from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api import create_app

NOW = datetime(2026, 10, 6, 12, 0, 0)


def iso(**delta):
    return (NOW - timedelta(**delta)).isoformat()


@pytest.fixture
def env(tmp_path):
    def make():
        app = create_app(tmp_path / "a.json", tmp_path / "q.json", now_func=lambda: NOW,
                         api_key="", drafts_path=tmp_path / "d.json")
        return TestClient(app)
    return make


def post(c, uid, content, **delta):
    return c.post("/activities", json={"user_id": uid, "content": content, "created_at": iso(**delta)})


def seed(c):
    # declining + پیام ۲ ساعت پیش ← پنجره باز
    for d in (8, 9, 10, 11, 12):
        post(c, "open", "Like Post", days=d)
    post(c, "open", "Message: قیمت مدل X چنده؟", hours=2)
    # early churn + پیام ۵ روز پیش ← پنجره بسته
    post(c, "closed", "Message: موجودی دارید؟", days=5)
    # حساس
    post(c, "angry", "Message: از خرید قبلی ناراضی هستم", days=5)
    c.post("/queue/sync")


def pending_by_user(c):
    return {i["user_id"]: i for i in c.get("/queue/pending").json()}


def test_reply_window_endpoint(env):
    c = env()
    seed(c)
    assert c.get("/users/open/reply-window").json()["is_open"] is True
    assert c.get("/users/closed/reply-window").json()["is_open"] is False
    assert c.get("/users/ghost/reply-window").status_code == 404


def test_pending_includes_live_window(env):
    c = env()
    seed(c)
    p = pending_by_user(c)
    assert p["open"]["can_auto_reply"] is True
    assert p["closed"]["can_auto_reply"] is False


def test_full_draft_flow(env):
    c = env()
    seed(c)
    item_id = pending_by_user(c)["open"]["id"]

    r = c.post(f"/queue/{item_id}/draft")
    assert r.status_code == 201
    draft = r.json()
    assert draft["state"] == "needs_approval" and draft["can_auto_reply"] is True

    again = c.post(f"/queue/{item_id}/draft")
    assert again.status_code == 200 and again.json()["id"] == draft["id"]

    did = draft["id"]
    assert c.post(f"/drafts/{did}/sent", json={}).status_code == 409   # بدون تأیید
    assert c.post(f"/drafts/{did}/approve", json={"reviewer": "sara", "text": " "}).status_code == 422
    ok = c.post(f"/drafts/{did}/approve", json={"reviewer": "sara", "text": "سلام! در خدمتیم. لغو"})
    assert ok.json()["state"] == "approved" and ok.json()["edited"] is True
    assert c.post(f"/drafts/{did}/approve", json={"reviewer": "sara"}).status_code == 409

    sent = c.post(f"/drafts/{did}/sent", json={"channel": "instagram_dm"})
    assert sent.json()["state"] == "sent"
    assert [e["action"] for e in sent.json()["audit"]] == ["created", "approved", "sent"]
    assert c.get(f"/drafts?state=sent").json()[0]["id"] == did


def test_closed_window_blocks_dm_but_not_phone(env):
    c = env()
    seed(c)
    d = c.post(f"/queue/{pending_by_user(c)['closed']['id']}/draft").json()
    assert d["can_auto_reply"] is False
    c.post(f"/drafts/{d['id']}/approve", json={"reviewer": "sara"})
    assert c.post(f"/drafts/{d['id']}/sent", json={"channel": "instagram_dm"}).status_code == 409
    assert c.post(f"/drafts/{d['id']}/sent", json={"channel": "phone"}).json()["state"] == "sent"


def test_sensitive_user_goes_to_handoff(env):
    c = env()
    seed(c)
    d = c.post(f"/queue/{pending_by_user(c)['angry']['id']}/draft").json()
    assert d["state"] == "handoff" and d["text"] is None
    assert c.post(f"/drafts/{d['id']}/approve", json={"reviewer": "sara"}).status_code == 409


def test_reject_and_not_found(env):
    c = env()
    seed(c)
    d = c.post(f"/queue/{pending_by_user(c)['open']['id']}/draft").json()
    assert c.post(f"/drafts/{d['id']}/reject", json={"reviewer": "sara", "reason": "x"}).json()["state"] == "rejected"
    assert c.post("/queue/999/draft").status_code == 404
    assert c.get("/drafts/999").status_code == 404
    assert c.post("/drafts/999/approve", json={"reviewer": "sara"}).status_code == 404


def test_drafts_persist_across_restart(env):
    c = env()
    seed(c)
    d = c.post(f"/queue/{pending_by_user(c)['open']['id']}/draft").json()
    c2 = env()
    assert c2.get(f"/drafts/{d['id']}").json()["text"] == d["text"]


def test_draft_for_closed_queue_item_is_409(env):
    c = env()
    seed(c)
    item_id = pending_by_user(c)["open"]["id"]
    c.post(f"/queue/{item_id}/done")
    assert c.post(f"/queue/{item_id}/draft").status_code == 409
