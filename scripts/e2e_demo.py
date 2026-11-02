"""
تست سرتاسری کل سیستم (بدون نیاز به اینستاگرام واقعی):

  webhook امضاشده ← ماژول ۱ (سرنخ) ← ماژول ۴ (دایرکت)
  کاربران ساکت (داده‌ی ساختگی با تاریخ قدیمی) ← ماژول ۲ (ریزش) ← inactive_users
  ماژول ۳ ← operator_tasks (پیشنهاد برای اپراتور)

اجرا (وقتی سرویس‌ها بالا هستند):
  META_APP_SECRET=... API_KEY=... DATABASE_URL=... python scripts/e2e_demo.py
"""
import hashlib
import hmac
import json
import os
import sys
import time

import httpx
import psycopg2

SECRET = os.environ["META_APP_SECRET"]
KEY = os.environ["API_KEY"]
DB = os.environ["DATABASE_URL"]
M1 = os.getenv("M1_URL", "http://127.0.0.1:8001")
M2 = os.getenv("M2_URL", "http://127.0.0.1:8002")
M3 = os.getenv("M3_URL", "http://127.0.0.1:8003")
M4 = os.getenv("M4_URL", "http://127.0.0.1:8004")
H = {"X-API-Key": KEY}
failed = []


def check(name, ok, detail=""):
    print(("  ✅ " if ok else "  ❌ ") + name + (f"   {detail}" if detail else ""))
    if not ok:
        failed.append(name)


def signed_post(payload):
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return httpx.post(f"{M1}/webhook", content=body, timeout=30,
                      headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"})


print("۱) سلامت سرویس‌ها")
for name, url in (("module1", M1), ("module2", M2), ("module3", M3), ("module4", M4)):
    try:
        r = httpx.get(f"{url}/health", timeout=10)
        check(name, r.status_code == 200, f"HTTP {r.status_code}")
    except Exception as exc:
        check(name, False, type(exc).__name__)

print("۲) webhook امضاشده به ماژول ۱")
run = str(int(time.time()))[-6:]
commenter, dmer = int("9100" + run), int("9200" + run)
r = signed_post({"object": "instagram", "entry": [{"id": "1", "changes": [{"field": "comments", "value": {
    "id": f"c{run}", "text": "سلام قیمت این محصول چنده؟", "from": {"id": str(commenter), "username": "demo_buyer"},
    "media": {"id": "m1"}}}]}]})
check("کامنت پذیرفته شد", r.status_code == 200 and r.json()["events_queued"] == 1)
r2 = signed_post({"object": "instagram", "entry": [{"id": "1", "changes": [{"field": "comments", "value": {
    "id": f"c{run}", "text": "سلام قیمت این محصول چنده؟", "from": {"id": str(commenter), "username": "demo_buyer"},
    "media": {"id": "m1"}}}]}]})
check("ارسال مجدد همان webhook تکراری ثبت نمی‌شود", r2.status_code == 200)
bad = httpx.post(f"{M1}/webhook", content=b"{}", headers={"X-Hub-Signature-256": "sha256=bad"}, timeout=10)
check("امضای نامعتبر رد می‌شود (401)", bad.status_code == 401)
r3 = signed_post({"object": "instagram", "entry": [{"id": "1", "messaging": [{
    "sender": {"id": str(dmer)}, "recipient": {"id": "1"}, "timestamp": int(time.time() * 1000),
    "message": {"mid": f"mid.{run}", "text": "میخوام با اپراتور صحبت کنم"}}]}]})
check("دایرکت پذیرفته شد", r3.status_code == 200)
time.sleep(2)  # فرصت برای ارسال پس‌زمینه به ماژول ۴

conn = psycopg2.connect(DB)
conn.autocommit = True
cur = conn.cursor()
cur.execute("SELECT count(*) FROM interactions WHERE user_id = %s", (commenter,))
check("ماژول ۱: فقط یک تعامل برای کامنت ثبت شده", cur.fetchone()[0] == 1)
cur.execute("SELECT intent, lead_score FROM leads WHERE user_id = %s", (commenter,))
row = cur.fetchone()
check("ماژول ۱: سرنخ با نیت خرید ساخته شد", bool(row) and row[0] == "purchase_inquiry", str(row))
cur.execute("SELECT status FROM conversations WHERE user_id = %s", (dmer,))
row = cur.fetchone()
check("ماژول ۴: گفتگو ساخته و به اپراتور ارجاع شد", bool(row) and row[0] == "handoff", str(row))

print("۳) ماژول ۲: تشخیص ریزش (کاربران ساختگی با تاریخ قدیمی)")
quiet, dropping = int("9300" + run), int("9400" + run)
for uid, name in ((quiet, "demo_quiet"), (dropping, "demo_dropping")):
    cur.execute("INSERT INTO ig_users (user_id, username) VALUES (%s, %s) ON CONFLICT DO NOTHING", (uid, name))
cur.execute("INSERT INTO interactions (user_id, interaction_type, content, occurred_at) "
            "VALUES (%s, 'comment', 'demo', NOW() - interval '20 days')", (quiet,))
for d in (13, 12, 11, 10, 9):
    cur.execute("INSERT INTO interactions (user_id, interaction_type, content, occurred_at) "
                "VALUES (%s, 'comment', 'demo', NOW() - make_interval(days => %s))", (dropping, d))
cur.execute("INSERT INTO interactions (user_id, interaction_type, content, occurred_at) "
            "VALUES (%s, 'like', 'demo', NOW() - interval '1 day')", (dropping,))
r = httpx.post(f"{M2}/sync/db", headers=H, timeout=60)
check("POST /sync/db", r.status_code == 200, str(r.json()) if r.status_code == 200 else r.text[:100])
cur.execute("SELECT user_id, reason FROM inactive_users WHERE user_id IN (%s, %s)", (quiet, dropping))
found = dict(cur.fetchall())
check("کاربر ساکت ← low_activity", found.get(quiet) == "low_activity")
check("کاربر در حال افت ← engagement_drop", found.get(dropping) == "engagement_drop")

print("۴) ماژول ۳: تبدیل به پیشنهاد اپراتور")
r = httpx.post(f"{M3}/run-cycle", headers=H, timeout=60)
check("POST /run-cycle", r.status_code == 200, r.text[:100])
cur.execute("SELECT user_id, kind, status FROM operator_tasks WHERE user_id IN (%s, %s)", (quiet, dropping))
tasks = cur.fetchall()
check("برای هر دو کاربر یک پیشنهاد ثبت شد", len(tasks) == 2, str(tasks))
cur.execute("SELECT processed FROM inactive_users WHERE user_id IN (%s, %s)", (quiet, dropping))
check("رکوردهای inactive_users پردازش‌شده علامت خوردند", all(p for (p,) in cur.fetchall()))
r = httpx.get(f"{M3}/operator-tasks", headers=H, timeout=30)
check("GET /operator-tasks", r.status_code == 200 and len(r.json()) >= 2)

print()
print("نتیجه:", "همه‌ی بررسی‌ها موفق بود ✅" if not failed else f"{len(failed)} مورد ناموفق ❌")
sys.exit(1 if failed else 0)
