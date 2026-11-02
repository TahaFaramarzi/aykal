import logging
from datetime import datetime
from app.database.connection import pool

logger = logging.getLogger(__name__)

def update_user_segments():
    """
    این تابع کاربران را بر اساس رفتارشان دسته‌بندی می‌کند (قابلیت گروه‌بندی بنر)
    """
    logger.info(f"[{datetime.now()}] Starting user segmentation...")
    
    try:
        with pool.connection() as conn:
            with conn.cursor() as cursor:
                # ۱. کاربرانی که قصد خرید داشتند = مشتری (Customer)
                cursor.execute("""
                    UPDATE ig_users SET segment = 'customer' 
                    WHERE user_id IN (
                        SELECT user_id FROM interactions 
                        WHERE detected_intent = 'purchase' AND occurred_at > NOW() - INTERVAL '30 days'
                    );
                """)
                customers_count = cursor.rowcount
                
                # ۲. کاربرانی که ۷ روز است تعامل ندارند = غیرفعال (Inactive)
                cursor.execute("""
                    UPDATE ig_users SET segment = 'inactive' 
                    WHERE last_seen_at < NOW() - INTERVAL '7 days' 
                    AND segment != 'customer';
                """)
                inactive_count = cursor.rowcount
                
                # ۳. کاربرانی که امتیاز سرنخ بالایی دارند = سرنخ گرم (Hot Lead)
                cursor.execute("""
                    UPDATE ig_users SET segment = 'hot_lead' 
                    WHERE user_id IN (
                        SELECT user_id FROM leads WHERE lead_score > 50 AND status != 'converted'
                    );
                """)
                hot_leads_count = cursor.rowcount
                
                conn.commit()
                
        logger.info(f"Segmentation complete. Customers: {customers_count}, Inactive: {inactive_count}, Hot Leads: {hot_leads_count}")
        
    except Exception as e:
        logger.error(f"Error updating segments: {e}")