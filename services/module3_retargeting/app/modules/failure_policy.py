from datetime import datetime, timedelta, timezone

# خطاهایی که باید باعد اتمام پردازش شوند.
PERMANENT_FAILURES = {
    "user_not_found",
    "user_blocked",
    "permission_denied",
    "invalid_action",
    "banned",
}

# خطایی ها که میتوان دوباره تلاش کرد
TEMPORARY_FAILURES = {
    "rate_limit",
    "api_timeout",
    "temporary_api_error",
    "network_error",
}

# بالاترین سطح مجاز تلاش
MAX_ATTEMPTS = 3


def is_retryable(result: str) -> bool:
    """نتیجه تعامل شکست خورده را میگیرد و میگوید که شکست
    موقی هست یا خیر

    Args:
        result (str): نیتجه تعامل شکست خورده

    Returns:
        bool: شکست موقت
    """
    if result in PERMANENT_FAILURES:
        return False

    if result in TEMPORARY_FAILURES:
        return True

    if result == "unknown_error":
        return True

    return False

def can_retry(result: str, attempt_count: int) -> bool:
    """نشان میدهد که تلاش کند دوباره رخ دهد یا نه

    Args:
        result (str): نتیجه تعامل را میگیرد
        attempt_count (int): تعداد تلاش هارو میگیرد

    Returns:
        bool: میگوید که تلاش کند یا نه
    """
    if not is_retryable(result):
        return False

    return attempt_count < MAX_ATTEMPTS

def get_retry_delay(attempt_count: int) -> timedelta | None:
    """ایجاد وقفه بین هر تلاش

    Args:
        attempt_count (int): تعداد دفعات تلاش

    Returns:
        timedelta | None: فاصله زمانی که تلاش بعدی کی باشد
    """
    if attempt_count == 1:
        return timedelta(seconds=30)

    if attempt_count == 2:
        return timedelta(minutes=2)

    return None


def get_next_retry_at(attempt_count: int) -> datetime | None:
    """دادن تایم تلاش بعدی

    Args:
        attempt_count (int): دفعات تلاش

    Returns:
        datetime | None: زمان بعدی
    """
    delay = get_retry_delay(attempt_count)

    if delay is None:
        return None

    return datetime.now(timezone.utc) + delay
