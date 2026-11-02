import os

from app.database.queries import create_operator_task

VALID_ACTIONS = {
    "message",
    "public_reply",
    "operator_suggestion",
    "ad_audience",
    "like",
    "story_view",
    "no_action",
}

# متن پیشنهادی برای اپراتور بر اساس دلیل غیرفعال‌شدن
SUGGESTIONS = {
    "engagement_drop": (
        "تعامل این کاربر نسبت به هفته‌های قبل افت کرده است. "
        "پیشنهاد: اگر کامنت یا پیام بی‌پاسخ دارد جواب بدهید، یا محتوای مرتبط با علاقه‌اش را به او نشان دهید."
    ),
    "low_activity": (
        "این کاربر مدتی است تعاملی با پیج نداشته است. "
        "پیشنهاد: در یک محتوای عمومی (پست یا استوری) او را به گفتگو دعوت کنید؛ "
        "پیام مستقیم فقط بعد از اینکه خودش پیام بدهد مجاز است."
    ),
}
DEFAULT_SUGGESTION = "این کاربر نیاز به پیگیری انسانی دارد."


class InteractionService:
    """
    اجرای اقدام. طبق قوانین پلتفرم (پنجره‌ی ۲۴ ساعته و ممنوعیت پیام سرد و لایک/دیدن استوری خودکار)،
    این سرویس هیچ اقدامی روی اینستاگرام انجام نمی‌دهد؛ هر اقدامِ تصمیم‌گیری‌شده به
    «پیشنهاد برای اپراتور» (جدول operator_tasks) تبدیل می‌شود و انسان تصمیم نهایی را می‌گیرد.
    """

    def execute(self, user_id: int, action: str, inactive_id: int | None = None,
                reason: str | None = None) -> dict:
        """اجرای فرایند تعامل

        Args:
            user_id: شناسه‌ی کاربر
            action: اقدام انتخاب‌شده توسط RetargetingService
            inactive_id: رکورد غیرفعال مربوط (برای ثبت در صف اپراتور)
            reason: دلیل غیرفعال بودن (engagement_drop یا low_activity)

        Returns:
            dict: status، result و response
        """
        if action not in VALID_ACTIONS:
            return {"status": "failed", "result": "invalid_action", "response": None}

        # شبیه‌سازی خطا فقط برای تست‌ها (با متغیر محیطی)
        if os.getenv("RETARGETING_SIMULATE_FAILURES", "").lower() == "true":
            if user_id == 310:
                return {"status": "failed", "result": "temporary_api_error", "response": None}
            if user_id == 210:
                return {"status": "failed", "result": "banned", "response": None}

        if action == "no_action":
            return {"status": "skipped", "result": "no_action", "response": None}

        kind = {"public_reply": "public_reply", "ad_audience": "ad_audience"}.get(action, "follow_up")
        suggestion = SUGGESTIONS.get(reason or "", DEFAULT_SUGGESTION)
        try:
            task_id = create_operator_task(user_id, inactive_id, kind, suggestion)
        except Exception:
            return {"status": "failed", "result": "unknown_error", "response": None}

        return {"status": "success", "result": "queued_for_operator", "response": {"task_id": task_id}}
