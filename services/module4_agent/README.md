# Aykal - ماژول ۴: دستیار گفتگوی هوشمند دایرکت

پاسخ‌گوی دایرکت بر پایه‌ی پایگاه دانش (RAG). اگر مدرک کافی نباشد، یا پیام شکایت/حساس باشد، یا کاربر انسان بخواهد، مکالمه به اپراتور ارجاع می‌شود و ربات ساکت می‌ماند.

## نصب
```
pip install -r requirements.txt
```

## تنظیمات (فایل .env؛ داخل گیت نگذارید)
نمونه در `.env.example`. مقدارهای ضروری: `OPENAI_API_KEY`، `OPENAI_MODEL`، `DATABASE_URL`.

| متغیر | کاربرد |
|---|---|
| ADMIN_API_KEY | قفل endpointهای اپراتور/پایگاه دانش/ارزیابی با هدر `X-API-Key` |
| OPERATOR_WEBHOOK_URL | آدرسی که برای هر ارجاع جدید پیام JSON می‌گیرد (مثل Slack/Mattermost) |
| BOT_DISCLOSURE_TEXT | متن اعلام «دستیار خودکار» در اولین پاسخ هر مکالمه |
| INSTAGRAM_VERIFY_TOKEN | هر رشته‌ی دلخواه؛ همان را در داشبورد Meta هم بنویسید |
| INSTAGRAM_APP_SECRET | App Secret برنامه‌ی Meta (برای بررسی امضا) |
| INSTAGRAM_ACCESS_TOKEN | توکن ارسال پیام |

## دیتابیس (PostgreSQL)
یک بار فایل `DataBase.sql` را اجرا کنید:
```
psql -U postgres -d DBNAME -f DataBase.sql
```

## اجرا
```
uvicorn app.main:app --reload
```
مستندات تعاملی (Swagger/OpenAPI): http://127.0.0.1:8000/docs

## اتصال به اینستاگرام (نیازمند دسترسی Meta)
1. در Meta for Developers یک اپ بسازید و دسترسی `instagram_business_manage_messages` را بگیرید.
2. آدرس webhook (باید HTTPS عمومی باشد؛ در توسعه مثلاً با ngrok): `https://دامنه/instagram/webhook`
3. Verify Token را همان `INSTAGRAM_VERIFY_TOKEN` بگذارید و فیلد `messages` را subscribe کنید.
4. ربات فقط به پیام کاربر جواب می‌دهد، فقط داخل ۲۴ ساعت از آخرین پیام او و فقط اگر opt-out نکرده باشد (ویوی `contactable_users`).

## داده‌ی نمونه و سنجش دقت
```
python -m app.seed_sample_data
```
سپس در Swagger: `POST /eval/run` (دقت و پذیرش ≥ ۸۵٪؛ نتیجه در جدول‌های eval_* ذخیره می‌شود).
برای کاتالوگ واقعی: `POST /kb/ingest` و `POST /eval/questions`.

## مسیر یک پیام
ذخیره پیام ← اگر مکالمه دست اپراتور است ربات ساکت می‌ماند ← قوانین شکایت/حساس/درخواست انسان ← بازیابی از پایگاه دانش ← اگر مدرکی نبود ارجاع، وگرنه پاسخ با منبع و میزان اطمینان.

## endpointها
- `POST /chat`، `POST /webhook`، `GET /conversations/{id}` (تست بدون اینستاگرام)
- `GET/POST /instagram/webhook` (دریافت پیام واقعی)
- `POST /kb/ingest`، `GET /kb/search`
- `GET /handoffs`، `POST /handoffs/{id}/assign`، `POST /handoffs/{id}/reply`، `POST /handoffs/{id}/resolve`
- `DELETE /users/{user_id}/data` (حذف داده‌ی مکالمه‌ی یک کاربر)
- `POST /eval/questions`، `POST /eval/run`

## حریم خصوصی
- فقط شناسه‌ی کاربر و متن مکالمه نگه داشته می‌شود؛ توکن‌ها فقط در `.env`.
- هر پاسخ، منبع و میزان اطمینانش را در جدول `messages` دارد.
- حذف داده: `DELETE /users/{user_id}/data`. سیاست نگهداری پیشنهادی: حذف مکالمه‌های بسته‌شده‌ی قدیمی‌تر از ۱۸۰ روز (دستی).

## تست
```
pytest -v
```

## محدودیت‌ها و وضعیت
- اتصال به اینستاگرام طبق مستندات رسمی Meta نوشته شده ولی روی اپ واقعی Meta آزمایش نشده (دسترسی نبود).
- پردازش پس‌زمینه با `BackgroundTasks` خود FastAPI انجام می‌شود، نه Celery/Redis.
- قوانین کلیدواژه‌ای ارجاع موقتی است. تشخیص نیت کار ماژول ۱ است.
- داده‌ی `seed_sample_data.py` ساختگی است؛ دقت روی آن، دقت روی کاتالوگ واقعی نیست.
- پیام اپراتور فقط داخل پنجره‌ی ۲۴ ساعته ارسال می‌شود.