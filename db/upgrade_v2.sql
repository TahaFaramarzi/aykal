-- اضافه کردن ستون گروه‌بندی به کاربران برای کمپین‌های هدفمند (بنر)
ALTER TABLE ig_users ADD COLUMN IF NOT EXISTS segment VARCHAR(50) DEFAULT 'new_lead';
-- مقادیر: new_lead, hot_lead, customer, inactive, target_follower

-- ساخت جدول برای فالوورهای هدف (قابلیت جدید بنر)
CREATE TABLE IF NOT EXISTS target_followers (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    source_page VARCHAR(100), -- از پیج کدام رقیب پیدا شده
    status VARCHAR(20) DEFAULT 'pending', -- pending, contacted, converted
    added_at TIMESTAMPTZ DEFAULT NOW()
);

