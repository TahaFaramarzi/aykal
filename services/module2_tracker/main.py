import json
import logging
from datetime import datetime, timedelta

from app.config import ACTIVITIES_PATH, QUEUE_PATH
from app.models import UserActivity
from app.recovery_queue import RecoveryQueue
from app.storage import JsonStorage, write_report
from app.tracker import EngagementTracker

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# داده‌های اولیه
initial = [
    UserActivity("u1", "Login", "2026-10-03 10:00:00"),
    UserActivity("u1", "View Profile", "2026-10-04 11:00:00"),
    UserActivity("u2", "Logout", "2026-10-05 12:00:00"),
]

# کاربران نمونه برای نمایش تشخیص ریزش (تاریخ‌ها نسبت به «الان»)
now = datetime.now()
ago = lambda d: now - timedelta(days=d)
initial += [
    UserActivity("u3", "Login", ago(16)), UserActivity("u3", "Like Post", ago(15)),
    UserActivity("u4", "Like Post", ago(8)), UserActivity("u4", "Like Post", ago(9)),
    UserActivity("u4", "Comment: hi", ago(10)), UserActivity("u4", "Upload Post", ago(11)),
    UserActivity("u4", "Like Post", ago(12)), UserActivity("u4", "Login", ago(1)),
    UserActivity("u5", "Upload Post", ago(45)),
    UserActivity("u7", "Like Post", ago(5)), UserActivity("u7", "View Story", ago(6)),
    # پیام‌های مستقیم نمونه برای نمایش پیش‌نویس
    UserActivity("u4", "Message: سلام، قیمت مدل X چنده؟", ago(0.1)),       # پنجره‌ی ۲۴ ساعته باز
    UserActivity("u3", "Message: سلام، این محصول موجوده؟", ago(16)),        # پنجره بسته
    UserActivity("u7", "Message: از خرید قبلی ناراضی هستم", ago(5.5)),      # حساس ← اپراتور
]

tracker = EngagementTracker(initial)
tracker.register_user("u6")  # ثبت‌نام کرده ولی هیچ فعالیتی نداشته

# اضافه کردن فعالیت‌های جدید
for content in ["Like Post", "Comment: Nice photo!", "Follow User u2",
                "View Story", "Upload Post"]:
    tracker.add_activity("u1", content)

# فعالیت‌های اخیر
print("Recent activities for user u1 in the last 7 days:")
for a in tracker.get_recent_activities("u1", 7):
    print(f"- {a.content} at {a.created_at:%Y-%m-%d %H:%M:%S}")

print("\nUser u1 level:", tracker.get_user_level("u1"))

print("\nLeaderboard:")
for rank, (uid, score) in enumerate(tracker.get_leaderboard(), start=1):
    print(f"{rank}. {uid} -> {score}")

print("\nChurn report (users at risk):")
churn = tracker.get_churn_report()
for r in churn:
    print(f"- {r.user_id} [{r.status.value}] {r.reason}")
write_report({r.user_id: r.to_dict() for r in churn}, "churn_report.json")

# صف اقدامات ترمیمی: فقط «تغییر وضعیت»ها وارد صف می‌شوند
queue = RecoveryQueue.load(QUEUE_PATH)
sync = queue.sync(tracker.get_churn_report(include_healthy=True))
print(f"\nQueue sync: {len(sync.enqueued)} new, {len(sync.updated)} updated, "
      f"{len(sync.resolved)} resolved, {len(sync.expired)} expired")
print("Pending recovery actions:")
for item in queue.pending():
    print(f"- #{item.id} {item.user_id} [{item.status}] since {item.enqueued_at:%Y-%m-%d %H:%M}")
queue.save(QUEUE_PATH)

# ذخیره‌ی خروجی تحلیل و خود فعالیت‌ها
write_report(tracker.analyze_all_users(), "analysis.json")
JsonStorage(ACTIVITIES_PATH).save(tracker.all_activities, users=tracker.user_ids)
print("\nAnalysis saved to analysis.json")
