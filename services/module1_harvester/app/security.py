"""
احراز هویت:
- HMAC برای Webhook متا
- API Key برای endpointهای داخلی
"""
import hmac
import hashlib
from fastapi import Request, HTTPException, status, Security
from fastapi.security import APIKeyHeader
from app.config import settings


# ============================================================
# Webhook Signature (Meta)
# ============================================================

def verify_meta_signature(
    raw_body: bytes,
    signature_header: str,
    app_secret: str,
) -> bool:
    """
    امضای X-Hub-Signature-256 رو با HMAC-SHA256 بررسی می‌کنه.
    مستندات: https://developers.facebook.com/docs/graph-api/webhooks/getting-started
    """
    # اگر App Secret تنظیم نشده باشد، هیچ امضایی معتبر نیست (جلوگیری از جعل با کلید خالی)
    if not app_secret:
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected = "sha256=" + hmac.new(
        app_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature_header)


async def verify_webhook_signature(request: Request) -> bytes:
    """
    Dependency: بدنه خام رو می‌خونه و امضا رو تأیید می‌کنه.
    اگه نامعتبر باشه 401 برمی‌گردونه.
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not verify_meta_signature(raw_body, signature, settings.meta_app_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )
    return raw_body


# ============================================================
# API Key (Endpointهای داخلی)
# ============================================================

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(api_key: str = Security(api_key_header)) -> str:
    """Dependency: بررسی API Key برای endpointهای داخلی"""
    if not settings.api_key or not api_key or api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return api_key