"""
تنظیمات Celery برای پردازش async
"""
from celery import Celery
from app.config import settings

celery_app = Celery(
    "icall",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.webhook_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,
    task_soft_time_limit=240,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=100,
    task_always_eager=settings.celery_eager,   # بدون Redis: تسک درجا اجرا می‌شود
    task_eager_propagates=True,
)

# زمان‌بندی تسک‌های دوره‌ای
celery_app.conf.beat_schedule = {
    "mark-inactive-leads-daily": {
        "task": "app.tasks.webhook_tasks.mark_inactive_leads_task",
        "schedule": 86400.0,  # هر ۲۴ ساعت
    },
}