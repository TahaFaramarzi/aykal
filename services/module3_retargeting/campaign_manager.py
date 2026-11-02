import time
import random
import logging
from datetime import datetime
from app.database.connection import pool

logger = logging.getLogger(__name__)

def send_targeted_campaign(segment_name: str, message_text: str):
    """
    ارسال پیام به یک گروه خاص با رعایت تاخیرهای تصادفی برای جلوگیری از بلاک شدن.
    """
    logger.info(f"[{datetime.now()}] Starting campaign for segment: '{segment_name}'")
    
    try:
        with pool.connection() as conn:
            with conn.cursor() as cursor:
                # پیدا کردن کاربران مجاز (طبق ویو contactable_users برای رعایت قانون ۲۴ ساعته)
                cursor.execute("""
                    SELECT c.user_id, c.conversation_id 
                    FROM contactable_users c
                    JOIN ig_users u ON u.user_id = c.user_id
                    WHERE u.segment = %s
                """, (segment_name,))
                
                users = cursor.fetchall()
                logger.info(f"Found {len(users)} eligible users in this segment.")
                
                for user_id, conversation_id in users:
                    try:
                        # ---------------------------------------------------------
                        # تابع ارسال دایرکت خود را اینجا صدا بزنید
                        # send_instagram_dm(user_id, message_text) 
                        # ---------------------------------------------------------
                        
                        logger.info(f"Sent to user {user_id}")
                        
                        # ثبت در دیتابیس برای گزارش‌گیری
                        cursor.execute("""
                            INSERT INTO operator_tasks (user_id, kind, suggestion, status)
                            VALUES (%s, 'bulk_campaign', %s, 'done')
                        """, (user_id, message_text))
                        conn.commit()

                        # تاخیر تصادفی بین ۱۰ تا ۳۰ ثانیه (شبیه‌سازی رفتار انسانی)
                        delay = random.uniform(10, 30)
                        time.sleep(delay) 
                        
                    except Exception as e:
                        logger.error(f"Failed to send to {user_id}: {e}")
                        conn.rollback()
                        time.sleep(60) # اگر خطا داد، یک دقیقه صبر کن

        logger.info(f"[{datetime.now()}] Campaign finished.")

    except Exception as e:
        logger.error(f"Database connection error: {e}")