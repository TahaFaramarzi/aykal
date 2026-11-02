"""
سرویس LLM (اختیاری). پیش‌فرض: مدل محلی روی Ollama
(OpenAI-compatible). اگر LLM_ENABLED=false باشد، قوانین کلیدواژه‌ای.
"""
import json
import logging
from typing import Optional

import httpx

from app.config import settings
from app.schemas import InteractionType, LeadIntent

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# امتیاز هر نیت (هم‌راستا با قوانین کلیدواژه‌ای)
INTENT_SCORES = {
    LeadIntent.PURCHASE_INQUIRY: 9,
    LeadIntent.HUMAN_HANDOFF: 8,
    LeadIntent.SUPPORT_COMPLAINT: 7,
    LeadIntent.LOCATION_INFO: 5,
    LeadIntent.GENERAL_COMMENT: 3,
    LeadIntent.GENERAL_ENGAGEMENT: 2,
    LeadIntent.UNKNOWN: 1,
    LeadIntent.SPAM: 0,
}


def is_llm_available() -> bool:
    """LLM فعال است (Ollama محلی یا Groq) — بدون تماس شبکه"""
    return bool(
        settings.llm_enabled
        and (settings.llm_base_url or settings.groq_api_key)
    )


def _chat(messages: list[dict], max_tokens: int = 300) -> Optional[str]:
    if not is_llm_available():
        return None
    base = (settings.llm_base_url or "").rstrip("/")
    if base:
        url = f"{base}/chat/completions"
        token = settings.llm_api_key or "ollama"
    else:
        url = GROQ_URL
        token = settings.groq_api_key
    try:
        r = httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "model": settings.llm_model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0.2,
            },
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as exc:  # شبکه، سهمیه، پاسخ نامعتبر: همه به fallback می‌روند
        logger.warning("LLM call failed: %s", type(exc).__name__)
        return None


def classify_intent_with_llm(
    text: str, interaction_type: InteractionType
) -> Optional[tuple[LeadIntent, int, float]]:
    """(نیت، امتیاز، اطمینان) یا None اگر LLM در دسترس نبود"""
    if not text or not text.strip():
        return None
    valid = [i.value for i in LeadIntent]
    content = _chat([
        {"role": "system", "content": (
            "تو یک دسته‌بند پیام‌های اینستاگرام یک فروشگاه هستی. "
            f"فقط یک JSON بده: {{\"intent\": <یکی از {valid}>, \"confidence\": <عدد ۰ تا ۱>}}"
        )},
        {"role": "user", "content": f"نوع تعامل: {interaction_type.value}\nمتن: {text[:500]}"},
    ], max_tokens=60)
    if not content:
        return None
    try:
        data = json.loads(content[content.index("{"): content.rindex("}") + 1])
        intent = LeadIntent(data["intent"])
        confidence = float(data.get("confidence", 0))
    except Exception:
        return None
    return intent, INTENT_SCORES[intent], max(0.0, min(confidence, 1.0))


def generate_reply(text: str, intent: LeadIntent) -> Optional[str]:
    """پیش‌نویس پاسخ کوتاه فارسی (فقط ذخیره می‌شود، ارسال خودکار نیست)"""
    if intent == LeadIntent.SPAM:
        return None
    
    content = _chat([
        {"role": "system", "content": (
            "تو دستیار یک فروشگاه هستی. یک پاسخ کوتاه، مؤدبانه و فارسی (حداکثر ۲۵۰ کاراکتر) بنویس. "
            "قیمت یا موجودی را حدس نزن؛ اگر اطلاعاتی نداری بگو همکاران پیگیری می‌کنند."
        )},
        {"role": "user", "content": f"نیت پیام: {intent.value}\nپیام: {text[:500]}"},
    ], max_tokens=200)
    
    # >>> اگر LLM در دسترس نبود یا پاسخی نداد، پاسخ پیش‌فرض برگردان <<<
    if not content:
        if intent == LeadIntent.PURCHASE_INQUIRY:
            return "ممنون از پیام شما! همکاران ما به زودی برای مشاوره خرید با شما تماس می‌گیرند."
        elif intent == LeadIntent.SUPPORT_COMPLAINT:
            return "از نارضایتی شما متأسفیم. همکاران پشتیبانی ما به زودی مشکل شما را بررسی می‌کنند."
        elif intent == LeadIntent.LOCATION_INFO:
            return "برای اطلاعات بیشتر درباره آدرس و ساعات کاری، لطفاً به وب‌سایت ما مراجعه کنید یا با پشتیبانی تماس بگیرید."
        else:
            return "ممنون که به استوری ما پاسخ دادید! چطور می‌تونیم کمکتون کنیم؟"
    
    return content.strip()