"""API وب با FastAPI. اجرا:  uvicorn app.api:create_app --factory --reload"""
from __future__ import annotations

import os
import secrets
import threading
from datetime import datetime, timedelta
from typing import Callable, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response, Security
from fastapi.security import APIKeyHeader

from app.config import ACTIVITIES_PATH, DRAFT_MODEL, DRAFTS_PATH, QUEUE_PATH
from app.drafting import (
    ClaudeDraftGenerator,
    DraftGenerator,
    LocalChatDraftGenerator,
    TemplateDraftGenerator,
)
from app.drafts import DraftConflict, DraftService, DraftState, DraftStore
from app.messaging import get_reply_window
from app.recovery_queue import QueueState, RecoveryQueue, SyncReport
from app.schemas import (
    ActivityIn,
    ActivityOut,
    ApproveIn,
    ChurnOut,
    DraftOut,
    LeaderboardEntry,
    PendingItemOut,
    QueueItemOut,
    RejectIn,
    ReplyWindowOut,
    SentIn,
    SyncReportOut,
    UserAnalysis,
    UserIn,
)
from app.storage import JsonStorage
from app.tracker import EngagementTracker


class Services:
    """همه‌ی اجزای برنامه (تراکر، صف، ذخیره‌سازی) در یک جا."""

    def __init__(self, activities_path, queue_path, now_func: Callable[[], datetime],
                 drafts_path=DRAFTS_PATH, generator: Optional[DraftGenerator] = None):
        self.lock = threading.RLock()  # درخواست‌ها هم‌زمان می‌آیند؛ قفل جلوی تداخل را می‌گیرد
        self.storage = JsonStorage(activities_path)
        self.queue_path = queue_path
        self.tracker = EngagementTracker(self.storage.load(), now_func)
        for uid in self.storage.load_users():
            self.tracker.register_user(uid)
        self.queue = RecoveryQueue.load(queue_path, now_func)
        self.drafts_path = drafts_path
        self.drafts = DraftService(DraftStore.load(drafts_path), generator, now_func)
        self.now = now_func

    def save_drafts(self) -> None:
        self.drafts.store.save(self.drafts_path)

    def save_activities(self) -> None:
        self.storage.save(self.tracker.all_activities, users=self.tracker.user_ids)

    def save_queue(self) -> None:
        self.queue.save(self.queue_path)


# ---------- وابستگی‌ها ----------
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_services(request: Request) -> Services:
    return request.app.state.services


def verify_api_key(request: Request, key: Optional[str] = Security(api_key_header)) -> None:
    expected = request.app.state.api_key
    if expected and not (key and secrets.compare_digest(key, expected)):
        raise HTTPException(status_code=401, detail="کلید API نامعتبر است")


def require_user(s: Services, user_id: str) -> None:
    if not s.tracker.has_user(user_id):
        raise HTTPException(status_code=404, detail=f"کاربر «{user_id}» پیدا نشد")


router = APIRouter(dependencies=[Depends(verify_api_key)])


# ---------- فعالیت‌ها و کاربران ----------
@router.post("/activities", response_model=ActivityOut, status_code=201,
             tags=["فعالیت‌ها"], summary="ثبت یک فعالیت جدید")
def create_activity(body: ActivityIn, s: Services = Depends(get_services)):
    with s.lock:
        created_at = body.created_at
        if created_at is not None:
            if created_at.tzinfo is not None:  # به ساعت محلی و بدون منطقه‌ی زمانی تبدیل می‌شود
                created_at = created_at.astimezone().replace(tzinfo=None)
            if created_at > s.tracker.now() + timedelta(minutes=1):
                raise HTTPException(status_code=422, detail="زمان فعالیت نمی‌تواند در آینده باشد")
        try:
            activity = s.tracker.add_activity(body.user_id, body.content, created_at)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        s.save_activities()
    return {**activity.to_dict(), "type": activity.type.value}


@router.post("/users", status_code=201, tags=["کاربران"],
             summary="ثبت یک کاربر بدون فعالیت (برای تشخیص «هرگز فعال نبوده»)")
def register_user(body: UserIn, s: Services = Depends(get_services)):
    with s.lock:
        try:
            s.tracker.register_user(body.user_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        s.save_activities()
    return {"user_id": body.user_id}


@router.get("/users", response_model=dict[str, UserAnalysis], tags=["کاربران"],
            summary="تحلیل همه‌ی کاربران")
def analyze_all(s: Services = Depends(get_services)):
    with s.lock:
        return s.tracker.analyze_all_users()


@router.get("/users/{user_id}", response_model=UserAnalysis, tags=["کاربران"],
            summary="امتیاز، سطح و علت یک کاربر")
def analyze_user(user_id: str, s: Services = Depends(get_services)):
    with s.lock:
        require_user(s, user_id)
        return s.tracker.analyze_user(user_id)


@router.get("/users/{user_id}/activities", response_model=list[ActivityOut],
            tags=["کاربران"], summary="فعالیت‌های اخیر یک کاربر")
def user_activities(user_id: str, days: int = Query(7, ge=1, le=365),
                    s: Services = Depends(get_services)):
    with s.lock:
        require_user(s, user_id)
        return [a.to_dict() | {"type": a.type.value}
                for a in s.tracker.get_recent_activities(user_id, days)]


@router.get("/users/{user_id}/churn", response_model=ChurnOut, tags=["ریزش"],
            summary="وضعیت ریزش یک کاربر")
def user_churn(user_id: str, s: Services = Depends(get_services)):
    with s.lock:
        require_user(s, user_id)
        return s.tracker.get_churn_status(user_id).to_dict()


@router.get("/leaderboard", response_model=list[LeaderboardEntry], tags=["کاربران"],
            summary="برترین کاربران")
def leaderboard(top_n: int = Query(5, ge=1, le=100), s: Services = Depends(get_services)):
    with s.lock:
        return [{"user_id": u, "score": sc} for u, sc in s.tracker.get_leaderboard(top_n)]


# ---------- ریزش ----------
@router.get("/churn", response_model=list[ChurnOut], tags=["ریزش"],
            summary="کاربران در حال ریزش (به ترتیب اولویت)")
def churn_report(include_healthy: bool = False, s: Services = Depends(get_services)):
    with s.lock:
        return [r.to_dict() for r in s.tracker.get_churn_report(include_healthy)]


# ---------- صف اقدامات ترمیمی ----------
def _report_out(report: SyncReport) -> dict:
    return {name: [i.to_dict() for i in getattr(report, name)]
            for name in ("enqueued", "updated", "resolved", "expired")}


@router.post("/queue/sync", response_model=SyncReportOut, tags=["صف"],
             summary="به‌روزرسانی صف بر اساس وضعیت فعلی کاربران")
def queue_sync(s: Services = Depends(get_services)):
    with s.lock:
        report = s.queue.sync(s.tracker.get_churn_report(include_healthy=True))
        s.save_queue()
        return _report_out(report)


@router.get("/queue/pending", response_model=list[PendingItemOut], tags=["صف"],
            summary="اقدامات در انتظار (به ترتیب اولویت) همراه با وضعیت پنجره‌ی ۲۴ ساعته")
def queue_pending(s: Services = Depends(get_services)):
    with s.lock:
        now = s.now()
        out = []
        for item in s.queue.pending():
            window = get_reply_window(s.tracker.get_activities(item.user_id), now)
            out.append(item.to_dict() | {
                "can_auto_reply": window.is_open,
                "window_expires_at": window.to_dict()["expires_at"],
            })
        return out


@router.post("/queue/{item_id}/done", response_model=QueueItemOut, tags=["صف"],
             summary="علامت‌گذاری یک اقدام به‌عنوان انجام‌شده")
def queue_done(item_id: int, s: Services = Depends(get_services)):
    with s.lock:
        try:
            item = s.queue.mark_done(item_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        s.save_queue()
        return item.to_dict()


# ---------- پنجره‌ی پاسخ و پیش‌نویس‌ها ----------
@router.get("/users/{user_id}/reply-window", response_model=ReplyWindowOut, tags=["پیش‌نویس"],
            summary="آیا الان در پنجره‌ی مجاز ۲۴ ساعته‌ی این کاربر هستیم؟")
def reply_window(user_id: str, s: Services = Depends(get_services)):
    with s.lock:
        require_user(s, user_id)
        return get_reply_window(s.tracker.get_activities(user_id), s.now()).to_dict()


@router.post("/queue/{item_id}/draft", response_model=DraftOut, status_code=201, tags=["پیش‌نویس"],
             summary="ساخت پیش‌نویس پیام برای یک آیتم صف (نیازمند تأیید انسانی)")
def create_draft(item_id: int, response: Response, s: Services = Depends(get_services)):
    with s.lock:
        try:
            item = s.queue.get_item(item_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
        if item.state is not QueueState.PENDING:
            raise HTTPException(status_code=409, detail="این آیتم دیگر در انتظار نیست")
        record, created = s.drafts.create(item, s.tracker.get_activities(item.user_id))
        if created:
            s.save_drafts()
        else:
            response.status_code = 200  # پیش‌نویس باز از قبل وجود داشت
        return record.to_dict()


@router.get("/drafts", response_model=list[DraftOut], tags=["پیش‌نویس"], summary="فهرست پیش‌نویس‌ها")
def list_drafts(state: Optional[DraftState] = None, s: Services = Depends(get_services)):
    with s.lock:
        return [r.to_dict() for r in s.drafts.store.list(state)]


def _draft_action(s: Services, draft_id: int, action: Callable):
    with s.lock:
        try:
            record = action()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
        except DraftConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        s.save_drafts()
        return record.to_dict()


@router.get("/drafts/{draft_id}", response_model=DraftOut, tags=["پیش‌نویس"], summary="یک پیش‌نویس")
def get_draft(draft_id: int, s: Services = Depends(get_services)):
    with s.lock:
        try:
            return s.drafts.store.get(draft_id).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc


@router.post("/drafts/{draft_id}/approve", response_model=DraftOut, tags=["پیش‌نویس"],
             summary="تأیید پیش‌نویس توسط اپراتور (با امکان ویرایش متن)")
def approve_draft(draft_id: int, body: ApproveIn, s: Services = Depends(get_services)):
    return _draft_action(s, draft_id, lambda: s.drafts.approve(draft_id, body.reviewer, body.text))


@router.post("/drafts/{draft_id}/reject", response_model=DraftOut, tags=["پیش‌نویس"],
             summary="رد پیش‌نویس")
def reject_draft(draft_id: int, body: RejectIn, s: Services = Depends(get_services)):
    return _draft_action(s, draft_id, lambda: s.drafts.reject(draft_id, body.reviewer, body.reason))


@router.post("/drafts/{draft_id}/sent", response_model=DraftOut, tags=["پیش‌نویس"],
             summary="ثبت اینکه اپراتور پیام را فرستاده است (سیستم خودش ارسال نمی‌کند)")
def sent_draft(draft_id: int, body: SentIn, s: Services = Depends(get_services)):
    def action():
        record = s.drafts.store.get(draft_id)
        return s.drafts.mark_sent(draft_id, s.tracker.get_activities(record.user_id), body.channel)
    return _draft_action(s, draft_id, action)


# ---------- ساخت برنامه ----------
# ---------- اتصال به دیتابیس مشترک ----------
@router.post("/sync/db", tags=["دیتابیس"],
             summary="خواندن interactions از PostgreSQL و ثبت کاربران ریزش‌کرده در inactive_users")
def sync_db():
    from app import db_sync

    try:
        conn = db_sync.get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    try:
        with conn:
            return db_sync.sync_inactive_users(conn)
    finally:
        conn.close()


def create_app(
    activities_path=ACTIVITIES_PATH,
    queue_path=QUEUE_PATH,
    now_func: Callable[[], datetime] = datetime.now,
    api_key: Optional[str] = None,
    drafts_path=DRAFTS_PATH,
    draft_generator: Optional[DraftGenerator] = None,
) -> FastAPI:
    """
    api_key: اگر مقدار داده شود (یا متغیر محیطی API_KEY تنظیم باشد)، همه‌ی مسیرها
             به‌جز /health هدر X-API-Key می‌خواهند.
    """
    app = FastAPI(
        title="Engagement Tracker API",
        version="1.0.0",
        description="پایش میزان مشارکت کاربران، تشخیص ریزش و صف اقدامات ترمیمی.",
    )
    if draft_generator is None:
        llm_base = os.environ.get("LLM_BASE_URL")
        claude_key = os.environ.get("ANTHROPIC_API_KEY")
        if llm_base:
            draft_generator = LocalChatDraftGenerator(
                llm_base,
                model=os.environ.get("LLM_MODEL") or DRAFT_MODEL,
                api_key=os.environ.get("LLM_API_KEY") or "ollama",
            )
        elif claude_key:
            draft_generator = ClaudeDraftGenerator(claude_key)
        else:
            draft_generator = TemplateDraftGenerator()
    app.state.services = Services(activities_path, queue_path, now_func, drafts_path, draft_generator)
    app.state.api_key = api_key if api_key is not None else os.environ.get("API_KEY")
    app.include_router(router)

    @app.get("/health", tags=["سلامت"], summary="بررسی زنده بودن سرویس")
    def health():
        return {"status": "ok"}

    return app
