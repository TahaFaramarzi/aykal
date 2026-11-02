"""
تبدیل payload خام Meta Graph API به فرمت داخلی پروژه
مستندات payload: https://developers.facebook.com/docs/messenger-platform/webhooks
"""
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from app.schemas import InteractionType

logger = logging.getLogger(__name__)


@dataclass
class ParsedEvent:
    """یه رویداد parse شده از payload متا"""
    instagram_id: str
    username: Optional[str]
    interaction_type: InteractionType
    text_content: Optional[str]
    media_id: Optional[str] = None
    comment_id: Optional[str] = None
    timestamp: Optional[int] = None
    message_id: Optional[str] = None


def parse_webhook_payload(payload: Dict[str, Any]) -> List[ParsedEvent]:
    """
    payload خام Meta رو به لیستی از ParsedEvent تبدیل می‌کنه.
    یه payload می‌تونه چند entry و هر entry چند رویداد داشته باشه.
    """
    events: List[ParsedEvent] = []

    if payload.get("object") != "instagram":
        logger.warning("Received non-instagram webhook: %s", payload.get("object"))
        return events

    for entry in payload.get("entry", []):
        # --- ۱. کامنت‌ها و منشن‌ها (changes) ---
        for change in entry.get("changes", []):
            field = change.get("field")
            value = change.get("value", {})

            if field == "comments":
                event = _parse_comment(value)
                if event:
                    events.append(event)
            elif field == "mentions":
                event = _parse_mention(value)
                if event:
                    events.append(event)

        # --- ۲. دایرکت‌ها و استوری‌ها (messaging) ---
        for msg in entry.get("messaging", []):
            event = _parse_direct_message(msg) # این تابع حالا استوری را هم تشخیص می‌دهد
            if event:
                events.append(event)

    logger.info("Parsed %d events from webhook payload", len(events))
    return events


def _parse_comment(value: Dict[str, Any]) -> Optional[ParsedEvent]:
    """parse یه کامنت"""
    from_data = value.get("from", {})
    ig_id = from_data.get("id")
    if not ig_id:
        return None

    return ParsedEvent(
        instagram_id=ig_id,
        username=from_data.get("username"),
        interaction_type=InteractionType.COMMENT,
        text_content=value.get("text"),
        media_id=value.get("media", {}).get("id"),
        comment_id=value.get("id"),
        timestamp=value.get("created_time"),
    )


def _parse_mention(value: Dict[str, Any]) -> Optional[ParsedEvent]:
    """parse یه منشن"""
    from_data = value.get("from", {})
    ig_id = from_data.get("id")
    if not ig_id:
        return None

    return ParsedEvent(
        instagram_id=ig_id,
        username=from_data.get("username"),
        interaction_type=InteractionType.MENTION,
        text_content=value.get("text") or value.get("caption"),
        media_id=value.get("media_id"),
        timestamp=value.get("created_time"),
    )


def _parse_direct_message(msg: Dict[str, Any]) -> Optional[ParsedEvent]:
    """parse یه پیام دایرکت (حالا با تشخیص استوری)"""
    message = msg.get("message", {})

    # پیام‌های echo (که خودمون فرستادیم) رو skip کن
    if message.get("is_echo"):
        return None

    sender_id = msg.get("sender", {}).get("id")
    if not sender_id:
        return None

    # >>> تشخیص اینکه آیا این پیام پاسخ به یک استوری است یا خیر <<<
    interaction_type = InteractionType.DIRECT
    media_id = None
    
    # در وب‌هوک متا، اگر پیام پاسخ به استوری باشد، فیلد reply_to با type='story' وجود دارد
    reply_to = message.get("reply_to", {})
    if reply_to.get("type") == "story":
        interaction_type = InteractionType.STORY_REPLY
        media_id = reply_to.get("story", {}).get("id") # شناسه استوری

    return ParsedEvent(
        instagram_id=sender_id,
        username=None,  # در دایرکت webhook یوزرنیم نمیاد
        interaction_type=interaction_type,
        text_content=message.get("text"),
        media_id=media_id,
        timestamp=msg.get("timestamp"),
        message_id=message.get("mid"),
    )