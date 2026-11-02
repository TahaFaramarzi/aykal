"""
تنظیمات مرکزی ماژول ۱ (pydantic-settings).
همه‌ی مقدارها از فایل .env ریشه‌ی پروژه یا متغیرهای محیطی خوانده می‌شوند؛
هیچ رمز یا کلیدی در کد نگه‌داری نمی‌شود.
"""
import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    # --- Meta / Instagram ---
    # local = simulated inbox (no developers.facebook.com). live = real Graph API.
    meta_mode: str = "local"
    ig_access_token: str = ""
    ig_user_id: str = ""
    meta_app_secret: str = ""
    webhook_verify_token: str = ""

    # --- Database (یک DATABASE_URL مشترک برای همه‌ی ماژول‌ها) ---
    database_url_env: str = ""          # از متغیر DATABASE_URL خوانده می‌شود (پایین‌تر)
    db_user: str = "postgres"
    db_password: str = ""
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "icall_db"

    # --- Redis / Celery ---
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    celery_eager: bool = False          # true = بدون Redis و درجا اجرا شود (برای تست و دمو)

    # --- App ---
    app_env: str = "development"
    debug: bool = False
    api_key: str = ""                   # کلید endpointهای مدیریتی؛ در تولید حتماً مقداردهی شود

    # --- LLM (Ollama by default; Groq only if llm_base_url is empty) ---
    groq_api_key: str = ""
    llm_api_key: str = "ollama"
    llm_base_url: str = ""
    llm_model: str = "llama3.2"
    llm_enabled: bool = False

    # --- اتصال به ماژول ۴ ---
    # رویدادهای دایرکت با همان امضای اصلی متا به این آدرس هم ارسال می‌شود
    module4_webhook_url: str = ""

    @property
    def database_url(self) -> str:
        url = os.getenv("DATABASE_URL") or self.database_url_env
        if url:
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
            return url
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
