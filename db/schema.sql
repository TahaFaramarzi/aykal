-- ایکال (iCall / Aykal): اسکیمای یکپارچه PostgreSQL (پیش‌نویس نسخه ۱)
-- بر پایه کدی که اعضای تیم تا الان نوشته‌اند:
--   ماژول ۱ (رنجبر)  : leads و interactions
--   ماژول ۲ (عنصری)  : engagement_snapshots که نتیجه‌اش در inactive_users نوشته می‌شود
--   ماژول ۳ (بلالی)  : inactive_users و retargeting_actions (نام ستون‌ها مثل کد خودش)
--   ماژول ۴ (شمشیری) : conversations و messages و handoffs
-- اجرا:  psql -U postgres -d icall_db -f icall_schema.sql

BEGIN;

-- ---------------------------------------------------------------
-- مشترک: یک ردیف برای هر کاربر اینستاگرام (شناسه اینستاگرام در BIGINT جا می‌شود)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ig_users (
    user_id          BIGINT PRIMARY KEY,
    username         VARCHAR(100),              -- ممکن است عوض شود، پس هویت کاربر حساب نمی‌شود
    first_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    do_not_contact   BOOLEAN NOT NULL DEFAULT FALSE   -- «قانون ۱» بلالی: دیگر هدف قرار نگیرد
);

-- ---------------------------------------------------------------
-- ماژول ۱: سرنخ‌یابی (Lead Harvester)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS interactions (
    id                BIGSERIAL PRIMARY KEY,
    user_id           BIGINT NOT NULL REFERENCES ig_users(user_id),
    lead_id           BIGINT,                    -- ارجاع به leads.id (مثل مدل رنجبر)؛ بعد از ساخت جدول leads کلید خارجی اضافه می‌شود
    interaction_type  VARCHAR(32) NOT NULL
                      CHECK (interaction_type IN ('comment','direct','story_reply','mention','like')),
    content           TEXT,
    media_id          VARCHAR(64),
    comment_id        VARCHAR(64),
    detected_intent   VARCHAR(64),
    intent_score      INTEGER NOT NULL DEFAULT 0,
    -- پاسخ تولیدشده توسط LLM (ستون‌های مدل رنجبر):
    generated_reply   TEXT,
    reply_sent_at     TIMESTAMPTZ,
    reply_status      VARCHAR(32),               -- pending | sent | failed | skipped
    external_id       VARCHAR(100) UNIQUE,       -- شناسه رویداد یا کامنت یا پیام در متا؛ جلوی رکورد تکراری هنگام ارسال مجدد webhook را می‌گیرد
    occurred_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),   -- زمان واقعی وقوع تعامل
    received_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),   -- زمان دریافت در سرور ما
    raw_payload       JSONB                      -- داده خام webhook برای بررسی خطا
);
CREATE INDEX IF NOT EXISTS idx_interactions_user_time ON interactions (user_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_interactions_comment ON interactions (comment_id);

CREATE TABLE IF NOT EXISTS leads (
    id                 BIGSERIAL PRIMARY KEY,
    user_id            BIGINT NOT NULL UNIQUE REFERENCES ig_users(user_id),
    full_name          VARCHAR(255),
    intent             VARCHAR(50),
    lead_score         INTEGER NOT NULL DEFAULT 0,
    status             VARCHAR(20) NOT NULL DEFAULT 'active'
                       CHECK (status IN ('active','engaged','warm','hot','cold','converted','lost')),
    total_interactions INTEGER NOT NULL DEFAULT 0,
    last_interaction_at TIMESTAMPTZ,
    first_seen_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE interactions DROP CONSTRAINT IF EXISTS fk_interactions_lead;
ALTER TABLE interactions ADD CONSTRAINT fk_interactions_lead
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_leads_status_score ON leads (status, lead_score DESC);

-- ---------------------------------------------------------------
-- ماژول ۲: پایش تعامل (Engagement Tracker)
-- (جایگزین لیست داخل حافظه‌ی عنصری؛ منبع داده همان جدول interactions است)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS engagement_snapshots (
    id               BIGSERIAL PRIMARY KEY,
    user_id          BIGINT NOT NULL REFERENCES ig_users(user_id),
    window_days      SMALLINT NOT NULL CHECK (window_days IN (3,7,14,30)),
    recent_count     INTEGER NOT NULL,           -- تعداد فعالیت در پنجره اخیر
    previous_count   INTEGER NOT NULL,           -- تعداد فعالیت در پنجره قبل از آن (برای تشخیص افت تعامل)
    score            INTEGER,
    level            SMALLINT,
    computed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_snapshots_user ON engagement_snapshots (user_id, computed_at DESC);

-- قرارداد بین ماژول ۲ (می‌نویسد) و ماژول ۳ (می‌خواند).
-- شش ستون اول دقیقاً جدول فعلی بلالی است، پس کوئری‌های او بدون تغییر کار می‌کنند.
CREATE TABLE IF NOT EXISTS inactive_users (
    id                  SERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES ig_users(user_id),
    username            VARCHAR(100) NOT NULL,
    reason              VARCHAR(100) NOT NULL
                        CHECK (reason IN ('engagement_drop','low_activity')),
    detected_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    processed           BOOLEAN NOT NULL DEFAULT FALSE,   -- تا اجرای موفق اکشن false می‌ماند
    -- ستون‌های اضافه که سند طراحی بلالی می‌خواهد:
    last_interaction_at TIMESTAMPTZ,
    window_days         SMALLINT,
    -- مکانیزم قفل/claim که کد بلالی لازم دارد (جلوگیری از پردازش همزمان یک رکورد):
    processing            BOOLEAN NOT NULL DEFAULT FALSE,
    processing_started_at TIMESTAMPTZ,
    processing_token      VARCHAR(64)
);
CREATE INDEX IF NOT EXISTS idx_inactive_unprocessed ON inactive_users (processed, detected_at) WHERE processed = FALSE;
-- برای یک کاربر و یک دلیل، همزمان بیش از یک رویداد باز ثبت نشود
CREATE UNIQUE INDEX IF NOT EXISTS uq_inactive_open ON inactive_users (user_id, reason) WHERE processed = FALSE;

-- ---------------------------------------------------------------
-- ماژول ۳: بازاریابی مجدد (Retargeting) — هفت ستون اول مثل کد بلالی
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS retargeting_actions (
    id              SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES ig_users(user_id),
    action          VARCHAR(50) NOT NULL
                    CHECK (action IN ('message','public_reply','operator_suggestion','ad_audience',
                                      'like','story_view','no_action')),
                    -- like و story_view فقط تا زمانی مجازند که با API رسمی متا بررسی نشده‌اند
                    -- و بعد از بررسی، اگر پشتیبانی نشد باید حذف شوند
    status          VARCHAR(50),                 -- success یا failed یا skipped
    result          VARCHAR(255),                -- مثل user_blocked یا api_timeout
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    inactive_id     INTEGER REFERENCES inactive_users(id),
    -- اضافه‌ها از سند طراحی (تصمیم‌گیری و اجرا دو مفهوم جدا هستند):
    decision_reason VARCHAR(100),                -- چرا این اکشن انتخاب شد
    attempt_count   SMALLINT NOT NULL DEFAULT 0, -- تعداد تلاش‌ها برای retry کنترل‌شده
    executed_at     TIMESTAMPTZ,
    next_retry_at   TIMESTAMPTZ                  -- زمان تلاش بعدی بعد از شکست موقت (در کوئری‌های بلالی استفاده می‌شود)
);
CREATE INDEX IF NOT EXISTS idx_actions_user_time ON retargeting_actions (user_id, created_at DESC);

-- صف کارهای اپراتور: خروجی مجاز ماژول ۳ (پیشنهاد اقدام برای انسان؛ ارسال خودکار انجام نمی‌شود)
CREATE TABLE IF NOT EXISTS operator_tasks (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES ig_users(user_id),
    inactive_id   INTEGER REFERENCES inactive_users(id) ON DELETE SET NULL,
    kind          VARCHAR(30) NOT NULL DEFAULT 'follow_up',   -- follow_up | public_reply | ad_audience
    suggestion    TEXT NOT NULL,                              -- متن پیشنهادی برای اپراتور
    status        VARCHAR(20) NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','done','dismissed')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_operator_tasks_pending ON operator_tasks (status, created_at) WHERE status = 'pending';

-- ---------------------------------------------------------------
-- ماژول ۴: دستیار گفتگوی هوشمند (Conversational Agent)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversations (
    id                   BIGSERIAL PRIMARY KEY,
    user_id              BIGINT NOT NULL REFERENCES ig_users(user_id),
    status               VARCHAR(20) NOT NULL DEFAULT 'bot'
                         CHECK (status IN ('bot','handoff','closed')),   -- bot: پاسخ خودکار / handoff: در اختیار اپراتور
    last_user_message_at TIMESTAMPTZ,            -- مبنای پنجره ۲۴ ساعته پیام‌رسانی
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations (user_id);

CREATE TABLE IF NOT EXISTS messages (
    id               BIGSERIAL PRIMARY KEY,
    conversation_id  BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    direction        VARCHAR(3) NOT NULL CHECK (direction IN ('in','out')),   -- in: از کاربر / out: از ربات یا اپراتور
    text             TEXT NOT NULL,
    intent           VARCHAR(50),
    confidence       NUMERIC(4,3),               -- میزان اطمینان؛ اگر پایین بود ارجاع به اپراتور
    sources          JSONB,                      -- بخش‌های پایگاه دانشی که پاسخ از آن‌ها ساخته شد (راهنمای پروژه ثبتش را می‌خواهد)
    external_id      VARCHAR(100) UNIQUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()   -- همیشه UTC، مثل کاری که شمشیری الان می‌کند
);
CREATE INDEX IF NOT EXISTS idx_messages_conv_time ON messages (conversation_id, created_at);

CREATE TABLE IF NOT EXISTS handoffs (
    id               BIGSERIAL PRIMARY KEY,
    conversation_id  BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    reason           VARCHAR(100) NOT NULL,      -- low_confidence یا complaint یا sensitive یا unknown
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    assigned_to      VARCHAR(100),               -- اپراتور مسئول
    resolved_at      TIMESTAMPTZ
);

-- ---------------------------------------------------------------
-- ارزیابی دقت (معیار پذیرش: دقت بالای ۸۵٪)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eval_questions (
    id               SERIAL PRIMARY KEY,
    question         TEXT NOT NULL,              -- سؤال استاندارد کاتالوگ
    expected_answer  TEXT NOT NULL               -- پاسخ درست مرجع
);
CREATE TABLE IF NOT EXISTS eval_runs (
    id               SERIAL PRIMARY KEY,
    run_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    model            VARCHAR(100),               -- مدل یا نسخه‌ای که ارزیابی شد
    total            INTEGER,
    correct          INTEGER,
    accuracy         NUMERIC(5,2)
);
CREATE TABLE IF NOT EXISTS eval_results (
    run_id           INTEGER NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    question_id      INTEGER NOT NULL REFERENCES eval_questions(id),
    answer           TEXT,
    is_correct       BOOLEAN,
    PRIMARY KEY (run_id, question_id)
);

-- ---------------------------------------------------------------
-- ابزار رعایت قوانین: ربات همین حالا اجازه دارد به چه کسانی پیام بدهد؟
-- فقط کاربرانی که در ۲۴ ساعت اخیر خودشان پیام داده‌اند و opt-out نیستند.
-- ماژول ۳ و ۴ باید قبل از هر ارسال از این ویو بخوانند.
-- ---------------------------------------------------------------
CREATE OR REPLACE VIEW contactable_users AS
SELECT c.user_id, c.id AS conversation_id, c.last_user_message_at
FROM conversations c
JOIN ig_users u ON u.user_id = c.user_id
WHERE u.do_not_contact = FALSE
  AND c.last_user_message_at > NOW() - INTERVAL '24 hours';

-- اختیاری، برای RAG (نیاز به افزونه pgvector دارد؛ بُعد بردار را با مدل embedding هماهنگ کنید):
-- CREATE EXTENSION IF NOT EXISTS vector;
-- CREATE TABLE kb_chunks (
--     id BIGSERIAL PRIMARY KEY, source VARCHAR(200), content TEXT NOT NULL, embedding vector(1024)
-- );

COMMIT;
