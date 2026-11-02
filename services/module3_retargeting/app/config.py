import os
from dotenv import load_dotenv

load_dotenv()

# یک آدرس مشترک برای همه‌ی ماژول‌ها (اولویت با آن است)
DATABASE_URL_ENV = os.getenv("DATABASE_URL")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "icall_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

API_KEY = os.getenv("API_KEY", "")
# اگر بزرگ‌تر از صفر باشد، چرخه‌ی بازاریابی مجدد هر N ثانیه خودکار اجرا می‌شود
RETARGETING_INTERVAL_SECONDS = int(os.getenv("RETARGETING_INTERVAL_SECONDS", "0"))
