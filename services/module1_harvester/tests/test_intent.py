import pytest
from app.services.intent_classifier import classify_intent
from app.schemas import InteractionType, LeadIntent


@pytest.mark.parametrize("text,expected_intent", [
    ("سلام قیمت این محصول چنده؟", LeadIntent.PURCHASE_INQUIRY),
    ("سفارش چطور ثبت کنم؟", LeadIntent.PURCHASE_INQUIRY),
    ("سفارشم دیر رسید، شکایت دارم", LeadIntent.SUPPORT_COMPLAINT),
    ("آدرس فروشگاه کجاست؟", LeadIntent.LOCATION_INFO),
    ("میشه با اپراتور صحبت کنم؟", LeadIntent.HUMAN_HANDOFF),
    ("فالوور رایگان بزن لینک بایو", LeadIntent.SPAM),
    ("عالی بود 👏", LeadIntent.GENERAL_COMMENT),
])
def test_intent_classification(text, expected_intent):
    intent, score = classify_intent(text, InteractionType.COMMENT)
    assert intent == expected_intent
    assert score >= 0


def test_like_gets_low_score():
    intent, score = classify_intent(None, InteractionType.LIKE)
    assert intent == LeadIntent.GENERAL_ENGAGEMENT
    assert score == 2


def test_empty_text():
    intent, score = classify_intent("", InteractionType.COMMENT)
    assert intent == LeadIntent.UNKNOWN