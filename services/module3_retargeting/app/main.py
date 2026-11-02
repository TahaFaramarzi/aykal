"""
ماژول ۳ — بازاریابی مجدد (Retargeting) به‌صورت سرویس وب.

  GET  /health                          سلامت سرویس و دیتابیس
  POST /run-cycle                       یک چرخه‌ی پردازش کاربران غیرفعال (نیاز به X-API-Key)
  GET  /operator-tasks                  پیشنهادهای در انتظار اپراتور
  POST /operator-tasks/{id}/done        اپراتور انجام داد
  POST /operator-tasks/{id}/dismiss     اپراتور رد کرد
  POST /api/v1/segments/update          اجرای گروه‌بندی کاربران (جدید)
  POST /api/v1/campaigns/send           ارسال کمپین هدفمند (جدید)

اگر RETARGETING_INTERVAL_SECONDS بزرگ‌تر از صفر باشد، چرخه خودکار هم اجرا می‌شود.
"""
import asyncio
import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Security, BackgroundTasks
from fastapi.security import APIKeyHeader

from app.config import API_KEY, RETARGETING_INTERVAL_SECONDS
from app.database.connection import open_pool, pool
from app.database.queries import list_operator_tasks, resolve_operator_task
from app.modules.retargeting_middle import RetargetingMiddle

# ایمپورت کردن ماژول‌های جدید
from segment_manager import update_user_segments
from campaign_manager import send_targeted_campaign

logger = logging.getLogger(__name__)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(key: str | None = Security(api_key_header)) -> None:
    # بدون API_KEY تنظیم‌شده، هیچ درخواستی پذیرفته نمی‌شود
    if not API_KEY or not key or not secrets.compare_digest(key, API_KEY):
        raise HTTPException(status_code=401, detail="کلید API نامعتبر است")


def run_cycle() -> None:
    RetargetingMiddle().middle_way()


async def _periodic():
    while True:
        try:
            await asyncio.to_thread(run_cycle)
        except Exception:
            logger.exception("retargeting cycle failed")
        await asyncio.sleep(RETARGETING_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool()
    task = asyncio.create_task(_periodic()) if RETARGETING_INTERVAL_SECONDS > 0 else None
    yield
    if task:
        task.cancel()
    pool.close()


app = FastAPI(title="Retargeting Engine (Module 3)", version="1.0.0", lifespan=lifespan)


@app.get("/health")
def health():
    try:
        with pool.connection() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "database": "ok"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"database: {type(exc).__name__}")


@app.post("/run-cycle", dependencies=[Depends(verify_api_key)])
def run_cycle_endpoint():
    run_cycle()
    return {"status": "ok", "pending_operator_tasks": len(list_operator_tasks("pending", 1000))}


@app.get("/operator-tasks", dependencies=[Depends(verify_api_key)])
def get_operator_tasks(status: str = "pending", limit: int = 100):
    if status not in {"pending", "done", "dismissed"}:
        raise HTTPException(status_code=422, detail="status نامعتبر است")
    return list_operator_tasks(status, min(limit, 500))


def _resolve(task_id: int, new_status: str):
    if resolve_operator_task(task_id, new_status) == 0:
        raise HTTPException(status_code=404, detail="کار پیدا نشد یا قبلاً بسته شده است")
    return {"id": task_id, "status": new_status}


@app.post("/operator-tasks/{task_id}/done", dependencies=[Depends(verify_api_key)])
def task_done(task_id: int):
    return _resolve(task_id, "done")


@app.post("/operator-tasks/{task_id}/dismiss", dependencies=[Depends(verify_api_key)])
def task_dismiss(task_id: int):
    return _resolve(task_id, "dismissed")

# ============================================================
# بخش‌های جدید برای قابلیت‌های بنر (گروه‌بندی و کمپین)
# ============================================================

@app.post("/api/v1/segments/update", dependencies=[Depends(verify_api_key)])
def trigger_segment_update(background_tasks: BackgroundTasks):
    """اجرای دسته‌بندی کاربران در پس‌زمینه"""
    background_tasks.add_task(update_user_segments)
    return {"status": "ok", "message": "User segmentation started in background."}


@app.post("/api/v1/campaigns/send", dependencies=[Depends(verify_api_key)])
def trigger_campaign(segment_name: str, message: str, background_tasks: BackgroundTasks):
    """ارسال کمپین هدفمند به یک گروه خاص در پس‌زمینه"""
    background_tasks.add_task(send_targeted_campaign, segment_name, message)
    return {"status": "ok", "message": f"Campaign for segment '{segment_name}' started in background."}