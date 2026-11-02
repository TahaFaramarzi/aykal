import hmac
import hashlib
import json
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings

client = TestClient(app)


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(
        settings.meta_app_secret.encode(), body, hashlib.sha256
    ).hexdigest()


def test_webhook_verify_success():
    r = client.get("/webhook", params={
        "hub.mode": "subscribe",
        "hub.challenge": "123456",
        "hub.verify_token": settings.webhook_verify_token,
    })
    assert r.status_code == 200
    assert r.text == "123456" or r.json() == 123456


def test_webhook_verify_wrong_token():
    r = client.get("/webhook", params={
        "hub.mode": "subscribe",
        "hub.challenge": "123456",
        "hub.verify_token": "wrong",
    })
    assert r.status_code == 403


def test_webhook_post_invalid_signature():
    payload = {"object": "instagram", "entry": []}
    r = client.post(
        "/webhook",
        content=json.dumps(payload),
        headers={"X-Hub-Signature-256": "sha256=invalid"},
    )
    assert r.status_code == 401