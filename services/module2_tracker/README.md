# Engagement Tracker

تحلیل میزان مشارکت کاربران بر اساس فعالیت‌های اخیر (امتیاز، سطح ۱ تا ۵ و علت).

## نصب و اجرا
```bash
pip install -r requirements.txt
python main.py          # اجرا از ریشه‌ی پروژه
pytest                  # اجرای تست‌ها
```

## ساختار
| فایل | وظیفه |
|---|---|
| `app/models.py` | `UserActivity` و `ActivityType` |
| `app/config.py` | بازه‌ها، وزن‌ها، آستانه‌ی سطح‌ها |
| `app/scoring.py` | محاسبه‌ی امتیاز و سطح (توابع خالص) |
| `app/storage.py` | ذخیره/بارگذاری JSON |
| `app/churn.py` | تشخیص ریزش (بی‌فعالیتی و افت روند) |
| `app/recovery_queue.py` | صف اقدامات ترمیمی (فقط تغییر وضعیت‌ها) |
| `app/api.py`, `app/schemas.py` | API وب (FastAPI) و شکل داده‌های آن |
| `app/tracker.py` | کلاس `EngagementTracker` |
| `tests/` | تست‌های pytest |

## نمونه
```python
from app.tracker import EngagementTracker
t = EngagementTracker()
t.add_activity("u1", "Upload Post")
print(t.get_user_level("u1"), t.get_leaderboard())
```

## تشخیص ریزش
```python
for r in tracker.get_churn_report():
    print(r.user_id, r.status.value, r.reason)
```
وضعیت‌ها: `early_churn` (ریزش اولیه)، `declining` (افت روند)، `inactive` (چند روز غیب)، `churned` (مدت زیاد غیب)، `never_active` (هرگز فعال نبوده).
آستانه‌ها در `app/config.py` قابل تغییرند.

## صف اقدامات ترمیمی
```python
queue = RecoveryQueue.load("data/queue.json")
queue.sync(tracker.get_churn_report(include_healthy=True))  # فقط تغییر وضعیت‌ها وارد صف می‌شوند
for item in queue.pending():
    ...                      # اقدام مجاز (مثلاً گزارش داخلی به اپراتور)
    queue.mark_done(item.id)
queue.save("data/queue.json")
```

## API (FastAPI)
```bash
python main.py   # (اختیاری) ساخت داده‌ی نمونه در data/
python -m uvicorn app.api:create_app --factory --reload
```
- مستندات و صفحه‌ی تست تعاملی: http://127.0.0.1:8000/docs
- برای محافظت با کلید: متغیر محیطی `API_KEY` را تنظیم کنید؛ سپس همه‌ی مسیرها (جز `/health`) هدر `X-API-Key` می‌خواهند.
- با یک worker اجرا کنید (داده‌ها در فایل JSON هستند).

| مسیر | کار |
|---|---|
| `POST /activities` | ثبت فعالیت |
| `POST /users` | ثبت کاربر بدون فعالیت |
| `GET /users`, `GET /users/{id}` | تحلیل کاربران |
| `GET /users/{id}/activities?days=7` | فعالیت‌های اخیر |
| `GET /users/{id}/churn` | وضعیت ریزش یک کاربر |
| `GET /leaderboard?top_n=5` | برترین کاربران |
| `GET /churn` | کاربران در حال ریزش |
| `POST /queue/sync`, `GET /queue/pending`, `POST /queue/{id}/done` | صف اقدامات ترمیمی |
| `GET /health` | سلامت سرویس |

## پیش‌نویس پیام ترمیمی (با تأیید انسانی)
جریان: آیتم صف ← بررسی انصراف/شکایت ← بررسی پنجره‌ی ۲۴ ساعته ← پیش‌نویس ← **تأیید اپراتور** ← ثبت ارسال.
سیستم **خودش پیام نمی‌فرستد**؛ `POST /drafts/{id}/sent` فقط ثبت می‌کند که اپراتور فرستاده است.

| مسیر | کار |
|---|---|
| `GET /users/{id}/reply-window` | آیا الان در پنجره‌ی ۲۴ ساعته هستیم؟ |
| `POST /queue/{item_id}/draft` | ساخت پیش‌نویس (یا `handoff` اگر نباید پیش‌نویس ساخت) |
| `GET /drafts?state=needs_approval` | فهرست پیش‌نویس‌ها |
| `POST /drafts/{id}/approve` | تأیید (با امکان ویرایش متن) |
| `POST /drafts/{id}/reject` | رد |
| `POST /drafts/{id}/sent` | ثبت ارسال (برای دایرکت، پنجره دوباره چک می‌شود) |

- بدون کلید، مولد قالبی (آفلاین) استفاده می‌شود. با تنظیم `ANTHROPIC_API_KEY`، پیش‌نویس را Claude می‌نویسد
  و اگر خروجی نامعتبر بود (لینک، بدون گزینه‌ی «لغو»، بیش‌ازحد طولانی) یا خطا داد، به قالب برمی‌گردد.
- هر پیش‌نویس `facts` (اطلاعات مبنا) و `audit` (لاگ رویدادها) دارد.
- فیلتر شکایت/انصراف کلیدواژه‌ای و اولیه است؛ جایگزین بررسی انسانی نیست.
