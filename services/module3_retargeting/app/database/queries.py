from .connection import pool
from app.modules.failure_policy import can_retry, get_next_retry_at
import logging

logger = logging.getLogger(__name__)


def get_inactive_users():
    """دریافت کاربران غیرفعال که دیگر کاری ندارد در پروژه"""
    try:
        with pool.connection() as conn:
            with conn.cursor() as cursor:

                q = """
                    SELECT iu.id, iu.user_id, iu.username, iu.reason, iu.detected_at, iu.processed
                    FROM inactive_users AS iu
                    LEFT JOIN LATERAL (
                        SELECT ra.status, ra.result, ra.next_retry_at
                        FROM retargeting_actions AS ra
                        WHERE ra.inactive_id = iu.id
                        ORDER BY ra.id DESC
                        LIMIT 1
                    ) AS last_action ON TRUE
                    WHERE iu.processed = FALSE
                    AND (
                        last_action.status IS NULL
                        OR (
                            last_action.status = 'failed'
                            AND last_action.next_retry_at IS NOT NULL
                            AND last_action.next_retry_at <= NOW()
                        )
                    )
                """

                cursor.execute(q)
                result = cursor.fetchall()
                return result
    except Exception as e:
        print(f"error at get_inactive_users func in database!\n{e}")
        

def claim_inactive_users():
    """به صورت اتمیک و همزمانی، دریافت کاربران واجد شرایط برای پردازش از کاربران غیرفعال برای چرخه های پردازش"""
    with pool.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                WITH eligible AS (
                    SELECT iu.id
                    FROM inactive_users AS iu
                    LEFT JOIN LATERAL (
                        SELECT ra.status, ra.next_retry_at
                        FROM retargeting_actions AS ra
                        WHERE ra.inactive_id = iu.id
                        ORDER BY ra.id DESC
                        LIMIT 1
                    ) AS last_action ON TRUE
                    WHERE iu.processed = FALSE
                      AND iu.processing = FALSE
                      AND (
                          last_action.status IS NULL
                          OR (
                              last_action.status = 'failed'
                              AND last_action.next_retry_at IS NOT NULL
                              AND last_action.next_retry_at <= NOW()
                          )
                      )
                    ORDER BY iu.detected_at, iu.id
                    FOR UPDATE OF iu SKIP LOCKED
                )
                UPDATE inactive_users AS iu
                SET processing = TRUE,
                    processing_started_at = NOW(),
                    processing_token = gen_random_uuid()
                FROM eligible
                WHERE iu.id = eligible.id
                RETURNING
                    iu.id,
                    iu.user_id,
                    iu.username,
                    iu.reason,
                    iu.detected_at,
                    iu.processed,
                    iu.processing_token
                """
            )
            claimed_users = cursor.fetchall()
        conn.commit()

    return claimed_users

        
def get_retargeting_actions():
    """دریافت اکشن های ری تارگت انجام شده تا الان"""
    try:
        with pool.connection() as conn:
            with conn.cursor() as cursor:
                q = """SELECT id, user_id, inactive_id, action, status, result, created_at FROM retargeting_actions"""
                cursor.execute(q)
                result = cursor.fetchall()
                return result
    except Exception as e:
            print(f"error at get_inactive_actions func in database!\n{e}")
   


def save_retargeting_action(user_id, inactive_id, action, status, result, processing_token,):
    """فرایند ری تارگت را سیو میکند اگر ورکر هنوز صاحب هست."""
    try:
        with pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id
                    FROM inactive_users
                    WHERE id = %s
                      AND processed = FALSE
                      AND processing = TRUE
                      AND processing_token = %s
                    FOR UPDATE
                    """,
                    (inactive_id, processing_token),
                )

                if cursor.fetchone() is None:
                    raise RuntimeError(
                        f"Claim is no longer owned for inactive_id={inactive_id}"
                    )

                cursor.execute(
                    """
                    SELECT COALESCE(MAX(attempt_count), 0)
                    FROM retargeting_actions
                    WHERE inactive_id = %s
                    """,
                    (inactive_id,),
                )

                previous_attempts = cursor.fetchone()[0]
                attempt_count = previous_attempts + 1

                next_retry_at = None

                if status == "failed" and can_retry(
                    result, attempt_count
                ):
                    next_retry_at = get_next_retry_at(attempt_count)

                cursor.execute(
                    """
                    INSERT INTO retargeting_actions (
                        user_id,
                        inactive_id,
                        action,
                        status,
                        result,
                        created_at,
                        attempt_count,
                        next_retry_at
                    )
                    VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s)
                    """,
                    (
                        user_id,
                        inactive_id,
                        action,
                        status,
                        result,
                        attempt_count,
                        next_retry_at,
                    ),
                )

            conn.commit()
            return {
                "attempt_count": attempt_count,
                "next_retry_at": next_retry_at,
            }

    except Exception:
        logger.exception("Failed to save retargeting action")
        raise


def mark_inactive_user_processed(inactive_user_id, processing_token):
    """ثبت کاربری به عنوان پردازش شده"""
    try:
        with pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE inactive_users
                    SET processed = TRUE,
                        processing = FALSE,
                        processing_started_at = NULL,
                        processing_token = NULL
                    WHERE id = %s
                      AND processing = TRUE
                      AND processing_token = %s
                    """,
                    (inactive_user_id, processing_token),
                )

                if cursor.rowcount != 1:
                    raise RuntimeError(
                        "Cannot mark cycle as processed: "
                        "claim is no longer owned by this worker."
                    )

            conn.commit()
    except Exception as e:
        print(
            f"error at mark_inactive_user_processed func in database!\n{e}"
        )
        raise
    

def release_inactive_user_claim(inactive_user_id, processing_token):
    """زمانی مالکیتی را رها میکند که ورکر هنوز صاحب آن هست"""
    try:
        with pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE inactive_users
                    SET processing = FALSE,
                        processing_started_at = NULL,
                        processing_token = NULL
                    WHERE id = %s
                      AND processed = FALSE
                      AND processing = TRUE
                      AND processing_token = %s
                    """,
                    (inactive_user_id, processing_token),
                )

                if cursor.rowcount != 1:
                    raise RuntimeError(
                        "Cannot release claim: "
                        "claim is no longer owned by this worker."
                    )

            conn.commit()
    except Exception as e:
        print(
            f"error at release_inactive_user_claim func in database!\n{e}"
        )
        raise
    
def release_stale_inactive_user_claims(timeout_minutes=30):
    """تصاحب های شناور و بدون فرایندی را آزاد میکند"""
    try:
        with pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE inactive_users
                    SET processing = FALSE,
                        processing_started_at = NULL,
                        processing_token = NULL
                    WHERE processing = TRUE
                      AND processed = FALSE
                      AND processing_started_at IS NOT NULL
                      AND processing_started_at
                          < NOW() - (%s * INTERVAL '1 minute')
                    RETURNING id
                    """,
                    (timeout_minutes,),
                )
                released_ids = cursor.fetchall()
            conn.commit()

        return [row[0] for row in released_ids]

    except Exception as e:
        print(
            "error at release_stale_inactive_user_claims "
            f"func in database!\n{e}"
        )
        raise

    except Exception as e:
        print(
            "error at release_stale_inactive_user_claims "
            f"func in database!\n{e}"
        )
        raise

# ---------- صف کارهای اپراتور (خروجی مجاز ماژول ۳) ----------
def create_operator_task(user_id, inactive_id, kind, suggestion):
    """یک پیشنهاد اقدام برای اپراتور ثبت می‌کند (هیچ پیامی ارسال نمی‌شود)."""
    with pool.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO operator_tasks (user_id, inactive_id, kind, suggestion)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (user_id, inactive_id, kind, suggestion),
            )
            task_id = cursor.fetchone()[0]
        conn.commit()
    return task_id


def list_operator_tasks(status="pending", limit=100):
    with pool.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, user_id, inactive_id, kind, suggestion, status, created_at
                FROM operator_tasks
                WHERE status = %s
                ORDER BY created_at
                LIMIT %s
                """,
                (status, limit),
            )
            cols = [c.name for c in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]


def resolve_operator_task(task_id, new_status):
    """done یا dismissed؛ فقط کارهای pending قابل تغییرند. تعداد ردیف تغییرکرده را برمی‌گرداند."""
    with pool.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE operator_tasks
                SET status = %s, resolved_at = NOW()
                WHERE id = %s AND status = 'pending'
                """,
                (new_status, task_id),
            )
            changed = cursor.rowcount
        conn.commit()
    return changed
