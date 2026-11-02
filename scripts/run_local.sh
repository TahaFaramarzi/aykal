#!/usr/bin/env bash
# اجرای محلی بدون Docker (برای توسعه).
# پیش‌نیاز: PostgreSQL در حال اجرا و پایتون ۳.۱۱+.  Redis لازم نیست (Celery درجا اجرا می‌شود).
#   1) cp .env.example .env  و پر کردن آن
#   2) export DATABASE_URL=postgresql://postgres:رمز@localhost:5432/icall_db
#   3) psql "$DATABASE_URL" -f db/schema.sql
#   4) pip install -r services/module{1_harvester,2_tracker,3_retargeting,4_agent}/requirements.txt
#   5) bash scripts/run_local.sh
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && { set -a; source .env; set +a; }
: "${DATABASE_URL:?DATABASE_URL را تنظیم کنید}"

export CELERY_EAGER=true
export INSTAGRAM_VERIFY_TOKEN="${WEBHOOK_VERIFY_TOKEN:-}"
export INSTAGRAM_APP_SECRET="${META_APP_SECRET:-}"
export INSTAGRAM_ACCESS_TOKEN="${IG_ACCESS_TOKEN:-}"
export ADMIN_API_KEY="${API_KEY:-}"
export MODULE4_WEBHOOK_URL="http://127.0.0.1:8004/instagram/webhook"

pids=()
trap 'kill "${pids[@]}" 2>/dev/null || true' EXIT
start() { (cd "services/$1" && shift && "$@") & pids+=($!); }

start module1_harvester python3 -m uvicorn app.main:app --port 8001
start module2_tracker   python3 -m uvicorn app.api:create_app --factory --port 8002
start module3_retargeting python3 -m uvicorn app.main:app --port 8003
start module4_agent     python3 -m uvicorn app.main:app --port 8004
echo "سرویس‌ها روی پورت‌های ۸۰۰۱ تا ۸۰۰۴ بالا آمدند. برای توقف Ctrl+C بزنید."
wait
