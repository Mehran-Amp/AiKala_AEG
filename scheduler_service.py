# -*- coding: utf-8 -*-
"""
scheduler_service.py
سرویس زمان‌بندی خودکار:
1. به‌روزرسانی ۲ ساعته قیمت‌های زنده ربات از ممتازکالا (سبک، سریع و امن)
2. به‌روزرسانی ۱۲ ساعته قیمت‌های سایت ووکامرس (AiKala.ir) - فقط کالاهای همگام‌شده، بدون ایجاد محصول جدید و بدون دست زدن به آاگ
3. به‌روزرسانی هفتگی کاتالوگ پایه و بازسازی درخت دسته‌بندی
"""

import time
import threading
import sync_prices
import sync_catalog
import db_bridge

def start_background_scheduler():
    def worker():
        print("🚀 [SCHEDULER] Automated background scheduler started.")
        # بررسی اولیه قیمت‌های زنده ربات
        sync_prices.update_live_prices()
        
        last_weekly_check = time.time()
        last_woo_price_check = time.time()
        
        while True:
            try:
                # هر 2 ساعت (7200 ثانیه): بروزرسانی قیمت‌های ربات از منبع ممتازکالا
                time.sleep(7200)
                print("⏰ [SCHEDULER] Running 2-hour live price synchronization for Bot...")
                sync_prices.update_live_prices()

                # هر 12 ساعت (43200 ثانیه): بروزرسانی خودکار قیمت محصولات سایت ووکامرس (AiKala.ir)
                # استثنای قطعی: محصولات آاگ (AEG) دستی هستند و دستکاری نمی‌شوند؛ هیچ محصول جدیدی هم خودکار ساخته نمی‌شود.
                if time.time() - last_woo_price_check >= 12 * 3600:
                    print("🌐 [SCHEDULER] Running 12-hour WooCommerce automated price sync (Non-AEG mapped products only)...")
                    try:
                        import woo_sync_service
                        updated, failed, _ = woo_sync_service.sync_prices_to_woocommerce()
                        print(f"✅ [SCHEDULER] WooCommerce price sync completed. Updated: {updated}, Failed: {failed}")
                    except Exception as woo_err:
                        print(f"⚠️ [SCHEDULER] Error during WooCommerce price sync: {woo_err}")
                    last_woo_price_check = time.time()

                # هر 7 روز یک‌بار: بازسازی درخت کاتالوگ، موجودی و دسته‌بندی‌ها
                if time.time() - last_weekly_check >= 7 * 86400:
                    print("📅 [SCHEDULER] Running weekly catalog rebuild, inventory and categorization...")
                    sync_catalog.run_full_catalog_and_category_sync()
                    last_weekly_check = time.time()

            except Exception as e:
                print("❌ [SCHEDULER] Error in automated scheduler:", e)
                time.sleep(60)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t

if __name__ == "__main__":
    start_background_scheduler()
    while True:
        time.sleep(1)
