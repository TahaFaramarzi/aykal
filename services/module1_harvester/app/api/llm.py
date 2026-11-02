"""endpointهای آزمایشی LLM (فقط برای مدیر؛ با X-API-Key)"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.security import require_api_key
from app.schemas import InteractionType
from app.services.intent_classifier import classify_intent
from app.services.llm_service import generate_reply, is_llm_available

router = APIRouter(prefix="/api/v1/llm", tags=["LLM"], dependencies=[Depends(require_api_key)])


class TextIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)


@router.post("/classify", summary="تشخیص نیت یک متن (با LLM یا قوانین)")
def classify(body: TextIn):
    intent, score = classify_intent(body.text, InteractionType.COMMENT)
    return {"intent": intent.value, "score": score, "llm_used": is_llm_available()}


@router.post("/reply", summary="پیش‌نویس پاسخ (فقط وقتی LLM فعال است)")
def reply(body: TextIn):
    intent, _ = classify_intent(body.text, InteractionType.COMMENT)
    return {"intent": intent.value, "reply": generate_reply(body.text, intent)}
