"""
تسک‌های async برای پردازش webhook
"""
import logging
import os
import requests
from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.schemas import IncomingInteraction, InteractionType
from app.services.lead_harvester import process_interaction, mark_inactive_leads
from app.models import Interaction # برای پیدا کردن پاسخ تولید شده

logger = logging.getLogger(__name__)

# آدرس ماژول ۴ را از محیط بخوانید (پیش‌فرض: http://module4:8004)
MODULE4_URL = os.getenv("MODULE4_URL", "http://module4:8004")

@celery_app.task(name="app.tasks.webhook_tasks.process_interaction_task", bind=True, max_retries=3)
def process_interaction_task(self, payload: dict):
    """
    پردازش یه تعامل در پس‌زمینه.
    اگه خطا داد، تا ۳ بار retry می‌کنه (با backoff).
    """
    db = SessionLocal()
    try:
        data = IncomingInteraction(
            instagram_id=payload["instagram_id"],
            username=payload.get("username"),
            interaction_type=InteractionType(payload["interaction_type"]),
            text_content=payload.get("text_content"),
            media_id=payload.get("media_id"),
            comment_id=payload.get("comment_id"),
            external_id=payload.get("external_id"),
        )
        
        # ۱. پردازش تعامل (ثبت در دیتابیس، تولید پاسخ و...)
        lead = process_interaction(db, data)
        logger.info("Processed interaction for @%s (score=%d)", lead.username, lead.lead_score)
        
        last_interaction = db.query(Interaction).filter(
            Interaction.external_id == data.external_id
        ).first()

        # دایرکت: متن خود کاربر به ماژول ۴ می‌رود (نه پیش‌نویس سرنخ)
        is_dm = data.interaction_type in (
            InteractionType.DIRECT,
            InteractionType.STORY_REPLY,
        )
        if is_dm and data.text_content:
            try:
                response = requests.post(
                    f"{MODULE4_URL}/chat",
                    json={
                        "user_id": str(data.instagram_id),
                        "message": data.text_content,
                    },
                    timeout=60,
                )
                response.raise_for_status()
                if last_interaction:
                    last_interaction.reply_status = "sent"
                    db.commit()
            except Exception as e:
                logger.error("Failed to send DM to Module 4: %s", e)
                if last_interaction:
                    last_interaction.reply_status = "failed"
                    db.commit()
        elif last_interaction and not last_interaction.generated_reply:
            logger.warning(
                "No generated reply for interaction %s (external_id=%s)",
                last_interaction.id if last_interaction else "None",
                data.external_id,
            )
        
        return {"status": "ok", "lead_id": lead.id, "score": lead.lead_score}

    except Exception as exc:
        logger.exception("Failed to process interaction")
        db.rollback()
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
    finally:
        db.close()


@celery_app.task(name="app.tasks.webhook_tasks.mark_inactive_leads_task")
def mark_inactive_leads_task():
    """تسک دوره‌ای برای علامت‌گذاری کاربران غیرفعال"""
    db = SessionLocal()
    try:
        return mark_inactive_leads(db)
    finally:
        db.close()