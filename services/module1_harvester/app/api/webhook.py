"""
Endpointهای Webhook متا
"""
import json
import logging
from fastapi import APIRouter, BackgroundTasks, Request, Query, HTTPException, status, Depends

from app.config import settings
from app.security import verify_webhook_signature
from app.meta_adapter import parse_webhook_payload
from app.schemas import WebhookResponse
from app.tasks.webhook_tasks import process_interaction_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["Meta Webhook"])


@router.get("", summary="Verify webhook (Meta handshake)")
def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    """
    متا برای تأیید Webhook یه GET با hub.challenge می‌فرسته.
    اگه verify_token درست بود، باید همون challenge رو برگردونیم.
    """
    if hub_mode == "subscribe" and hub_verify_token == settings.webhook_verify_token:
        logger.info("Webhook verified by Meta")
        return int(hub_challenge) if hub_challenge and hub_challenge.isdigit() else hub_challenge

    logger.warning("Webhook verification failed (mode=%s)", hub_mode)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Verification token mismatch",
    )


@router.post("", response_model=WebhookResponse, summary="Receive webhook events")
async def receive_webhook(
    request: Request,
    background: BackgroundTasks,
    raw_body: bytes = Depends(verify_webhook_signature),
):
    """
    دریافت رویداد (کامنت، دایرکت، منشن) از متا یا از شبیه‌ساز محلی.
    امضای HMAC بررسی می‌شود. رویدادها به Celery صف می‌شوند.
    """

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    events = parse_webhook_payload(payload)

    queued = 0
    for event in events:
        process_interaction_task.delay({
            "instagram_id": event.instagram_id,
            "username": event.username,
            "interaction_type": event.interaction_type.value,
            "text_content": event.text_content,
            "media_id": event.media_id,
            "comment_id": event.comment_id,
            "external_id": event.message_id or (
                f"comment:{event.comment_id}" if event.comment_id else None
            ),
        })
        queued += 1

    logger.info("Queued %d events from webhook", queued)
    return WebhookResponse(
        status="ok",
        events_received=len(events),
        events_queued=queued,
    )