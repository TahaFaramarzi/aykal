from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api import create_app

NOW = datetime(2026, 10, 6, 12, 0, 0)


def iso(days_ago):
    return (NOW - timedelta(days=days_ago)).isoformat()


@pytest.fixture
def paths(tmp_path):
    return tmp_path / "act.json", tmp_path / "queue.json"


@pytest.fixture
def client(paths):
    app = create_app(paths[0], paths[1], now_func=lambda: NOW, api_key="")
    return TestClient(app)


def post(client, uid, content, days_ago=None):
    body = {"user_id": uid, "content": content}
    if days_ago is not None:
        body["created_at"] = iso(days_ago)
    return client.post("/activities", json=body)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_docs_available(client):
    assert client.get("/docs").status_code == 200
    assert "/activities" in client.get("/openapi.json").json()["paths"]


def test_create_activity_and_analyze(client):
    r = post(client, "u1", "Upload Post")
    assert r.status_code == 201
    assert r.json()["type"] == "upload"
    a = client.get("/users/u1").json()
    assert a["score"] > 0 and a["level"] >= 1
    assert len(a["recent_activities"]) == 1


def test_validation_errors(client):
    assert client.post("/activities", json={"user_id": "", "content": "x"}).status_code == 422
    assert client.post("/activities", json={"user_id": "u1", "content": "   "}).status_code == 422
    assert client.post("/activities", json={"user_id": "u1"}).status_code == 422


def test_future_date_rejected(client):
    r = client.post("/activities", json={
        "user_id": "u1", "content": "Login", "created_at": (NOW + timedelta(days=2)).isoformat()})
    assert r.status_code == 422


def test_timezone_aware_date_accepted(client):
    r = client.post("/activities", json={
        "user_id": "u1", "content": "Login", "created_at": "2026-10-05T10:00:00+00:00"})
    assert r.status_code == 201


def test_unknown_user_is_404(client):
    assert client.get("/users/ghost").status_code == 404
    assert client.get("/users/ghost/churn").status_code == 404
    assert client.get("/users/ghost/activities").status_code == 404


def test_activities_days_filter(client):
    post(client, "u1", "Like Post", 1)
    post(client, "u1", "Like Post", 10)
    assert len(client.get("/users/u1/activities?days=3").json()) == 1
    assert len(client.get("/users/u1/activities?days=30").json()) == 2
    assert client.get("/users/u1/activities?days=0").status_code == 422


def test_register_user_is_never_active(client):
    assert client.post("/users", json={"user_id": "u6"}).status_code == 201
    assert client.get("/users/u6/churn").json()["status"] == "never_active"


def test_leaderboard(client):
    post(client, "a", "Login", 1)
    for _ in range(4):
        post(client, "b", "Upload Post", 0)
    board = client.get("/leaderboard?top_n=2").json()
    assert board[0]["user_id"] == "b"


def test_churn_list_excludes_healthy(client):
    post(client, "ok", "Like Post", 1)
    post(client, "quiet", "Like Post", 5)
    ids = [r["user_id"] for r in client.get("/churn").json()]
    assert ids == ["quiet"]
    all_ids = [r["user_id"] for r in client.get("/churn?include_healthy=true").json()]
    assert set(all_ids) == {"ok", "quiet"}


def test_queue_flow(client):
    post(client, "quiet", "Like Post", 5)
    synced = client.post("/queue/sync").json()
    assert [i["user_id"] for i in synced["enqueued"]] == ["quiet"]
    assert client.post("/queue/sync").json()["enqueued"] == []  # تکراری نمی‌سازد

    pending = client.get("/queue/pending").json()
    assert len(pending) == 1
    item_id = pending[0]["id"]

    assert client.post(f"/queue/{item_id}/done").json()["state"] == "done"
    assert client.post(f"/queue/{item_id}/done").status_code == 409
    assert client.post("/queue/999/done").status_code == 404
    assert client.get("/queue/pending").json() == []


def test_data_persists_across_restarts(paths):
    first = TestClient(create_app(paths[0], paths[1], now_func=lambda: NOW, api_key=""))
    post(first, "u1", "Like Post", 1)
    first.post("/users", json={"user_id": "u6"})
    first.post("/queue/sync")

    second = TestClient(create_app(paths[0], paths[1], now_func=lambda: NOW, api_key=""))
    assert second.get("/users/u1").status_code == 200
    assert second.get("/users/u6/churn").status_code == 200


def test_api_key_protection(paths):
    c = TestClient(create_app(paths[0], paths[1], now_func=lambda: NOW, api_key="secret"))
    assert c.get("/health").status_code == 200
    assert c.get("/leaderboard").status_code == 401
    assert c.get("/leaderboard", headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.get("/leaderboard", headers={"X-API-Key": "secret"}).status_code == 200
