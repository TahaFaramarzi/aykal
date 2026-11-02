from app.database.queries import (
    claim_inactive_users,
    save_retargeting_action,
    mark_inactive_user_processed,
    release_inactive_user_claim,
    release_stale_inactive_user_claims,
)
from app.modules.retargeting_service import RetargetingService
from app.modules.interaction_service import InteractionService
import logging

logger = logging.getLogger(__name__)


class RetargetingMiddle:

    def __init__(self):
        """ایجاد شی های سرویس انتخاب اکشن و تعامل
        """
        self.service = RetargetingService()
        self.interaction_service = InteractionService()

    def middle_way(self):
        """تابع میانی که باعث جدایی ماژول ها از پایگاه داده میشود
        """
        release_stale_inactive_user_claims(timeout_minutes=30)
        inactive_users = claim_inactive_users()

        for row in inactive_users:
            candidate = {
                "inactive_id": row[0],
                "user_id": row[1],
                "username": row[2],
                "reason": row[3],
            }
            processing_token = row[6]
            inactive_id = candidate["inactive_id"]

            try:
                decision = self.service.choose_action(candidate=candidate)

                execution_result = self.interaction_service.execute(
                    candidate["user_id"],
                    decision["action"],
                    inactive_id=inactive_id,
                    reason=candidate["reason"],
                )

                saved_result = save_retargeting_action(
                    user_id=candidate["user_id"],
                    inactive_id=inactive_id,
                    action=decision["action"],
                    status=execution_result["status"],
                    result=execution_result["result"],
                    processing_token=processing_token,
                )

                if execution_result["status"] in {"success", "skipped"}:
                    mark_inactive_user_processed(
                        inactive_id,
                        processing_token,
                    )

                elif saved_result["next_retry_at"] is None:
                    mark_inactive_user_processed(
                        inactive_id,
                        processing_token,
                    )

                else:
                    release_inactive_user_claim(
                        inactive_id,
                        processing_token,
                    )
                    
            except Exception:
                try:
                    release_inactive_user_claim(
                        inactive_id,
                        processing_token,
                    )
                except Exception:
                    logger.exception(
                        "Failed to release claim for inactive_id=%s",
                        inactive_id,
                    )
                raise