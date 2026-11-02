"""
Aykal Project — Phase 1
ماژول Lead Harvester + Webhook + AI Analyzer
"""
import logging
from fastapi_offline import FastAPIOffline as FastAPI
from fastapi.openapi.docs import get_swagger_ui_html

from app.config import settings
from app.database import Base, engine
from app.api import webhook, leads, health

from app.api import webhook, leads, health, llm
# --- Logging ---
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# --- ساخت جداول (در production با Alembic انجام می‌شه) ---
#Base.metadata.create_all(bind=engine)

# --- App ---
app = FastAPI(
    title="iCall Project — Phase 1",
    description=(
        "ماژول سرنخ‌یابی، ذخیره‌سازی داده‌ها، و دریافت وب‌هوک‌های رسمی اینستاگرام.\n\n"
        "**فاز ۱** — طبق سند فنی iCall:\n"
        "- Lead Harvester\n"
        "- Webhook (HMAC verified)\n"
        "- AI Intent Classifier\n"
        "- Async processing با Celery\n"
    ),
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)

# --- Swagger UI سفارشی (ضدتحریم) ---
@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " — API Docs",
        swagger_js_url="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.9.0/swagger-ui-bundle.min.js",
        swagger_css_url="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.9.0/swagger-ui.min.css",
    )

# --- ثبت روترها ---
app.include_router(health.router)
app.include_router(webhook.router)
app.include_router(leads.router)
app.include_router(llm.router)

@app.get("/", include_in_schema=False)
def root():
    return {
        "project": "iCall Phase 1",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }


@app.on_event("startup")
async def on_startup():
    logger.info("🚀 iCall Phase 1 started (env=%s)", settings.app_env)