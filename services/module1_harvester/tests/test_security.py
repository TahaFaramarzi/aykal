import hmac
import hashlib
from app.security import verify_meta_signature

APP_SECRET = "test_secret"


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()


def test_valid_signature():
    body = b'{"test": "data"}'
    assert verify_meta_signature(body, _sign(body), APP_SECRET) is True


def test_invalid_signature():
    body = b'{"test": "data"}'
    assert verify_meta_signature(body, "sha256=deadbeef", APP_SECRET) is False


def test_missing_prefix():
    body = b'{"test": "data"}'
    assert verify_meta_signature(body, "invalid", APP_SECRET) is False