"""
تشخیص نیت کاربر از روی متن (rule-based برای فاز ۱)
در فاز ۳ با LLM + RAG جایگزین می‌شه.
"""
from typing import Optional
from app.schemas import InteractionType, LeadIntent
from app.services.llm_service import classify_intent_with_llm
# ============================================================
# کلیدواژه‌ها و وزن‌ها (قابل توسعه در فاز ۳ با LLM)
# ============================================================

INTENT_KEYWORDS = {
    LeadIntent.PURCHASE_INQUIRY: {
        "keywords": ["قیمت", "چند", "هزینه", "خرید", "سفارش", "بخرم", "موجود", "ارسال",
                     "تخفیف", "پرداخت", "کارت", "درگاه", "سایز", "رنگ", "مدل"],
        "score": 9,
    },
    LeadIntent.SUPPORT_COMPLAINT: {
        "keywords": ["خرابه", "خراب", "شکایت", "دیر", "نرسید", "مشکل", "پشتیبانی",
                     "گارانتی", "مرجوع", "عودت", "پول", "کلاهبرداری", "بی‌کیفیت"],
        "score": 7,
    },
    LeadIntent.LOCATION_INFO: {
        "keywords": ["آدرس", "کجاست", "کجا", "ساعت کاری", "شعبه", "نقشه",
                     "موقعیت", "باز", "تعطیل", "شنبه", "جمعه"],
        "score": 5,
    },
    LeadIntent.HUMAN_HANDOFF: {
        "keywords": ["اپراتور", "انسان", "مدیر", "مسئول", "پشتیبان واقعی",
                     "با کی حرف", "کارشناس", "آدم واقعی"],
        "score": 8,
    },
    LeadIntent.SPAM: {
        "keywords": ["فالوور رایگان", "لینک بایو", "کلیک کن", "جایزه", "برنده",
                     "کریپتو", "بیت‌کوین", "سرمایه‌گذاری", "پولدار"],
        "score": 0,
    },
}


def classify_intent(
    text: Optional[str],
    interaction_type: InteractionType,
) -> tuple[LeadIntent, int]:
    """
    نیت کاربر رو تشخیص می‌ده:
    1. اول با LLM (اگه فعال باشه)
    2. اگه LLM جواب نداد، با rule-based
    """
    # ۱. تلاش با LLM
    llm_result = classify_intent_with_llm(text or "", interaction_type)
    if llm_result is not None:
        intent, score, _confidence = llm_result
        return intent, score

    # ۲. Fallback به rule-based
    return _classify_intent_rule_based(text, interaction_type)


def _classify_intent_rule_based(
    text: Optional[str],
    interaction_type: InteractionType,
) -> tuple[LeadIntent, int]:
    """نسخه rule-based (همون کد قبلی)"""
    # لایک تنها → امتیاز پایین
    if interaction_type == InteractionType.LIKE:
        return LeadIntent.GENERAL_ENGAGEMENT, 2

    if not text or not text.strip():
        return LeadIntent.UNKNOWN, 1

    text_lower = text.strip().lower()

    # اول spam رو چک کن
    if _matches(text_lower, INTENT_KEYWORDS[LeadIntent.SPAM]["keywords"]):
        return LeadIntent.SPAM, 0

    # بقیه نیت‌ها به ترتیب اولویت
    # شکایت و درخواست انسان باید قبل از «خرید» بررسی شوند؛
    # مثلاً «سفارشم دیر رسید، شکایت دارم» نباید استعلام خرید حساب شود.
    priority_order = [
        LeadIntent.HUMAN_HANDOFF,
        LeadIntent.SUPPORT_COMPLAINT,
        LeadIntent.PURCHASE_INQUIRY,
        LeadIntent.LOCATION_INFO,
    ]

    for intent in priority_order:
        config = INTENT_KEYWORDS[intent]
        if _matches(text_lower, config["keywords"]):
            return intent, config["score"]

    # اگه کامنت بود ولی هیچی match نشد
    if interaction_type == InteractionType.COMMENT:
        return LeadIntent.GENERAL_COMMENT, 3

    return LeadIntent.GENERAL_ENGAGEMENT, 2

def _matches(text: str, keywords: list[str]) -> bool:
    """بررسی می‌کنه که آیا حداقل یکی از کلیدواژه‌ها در متن هست"""
    return any(kw in text for kw in keywords)