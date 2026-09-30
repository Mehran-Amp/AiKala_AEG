"""
AiKala - Backup & Restore Service (backup_service.py)
=====================================================
سرویس جامع و ایمن پشتیبان‌گیری و بازگردانی کلی سیستم:
۱. ساخت فایل یکپارچه ZIP شامل:
   - دیتابیس SQLite (bot_data.db) با تمام سفارشات، فاکتورها، تاریخچه‌ها و کانال‌ها
   - نقشه تصاویر و آلبوم‌های متصل به محصولات (verified_photos.json, channel_photos_map.json)
   - کاتالوگ جامع محصولات و مشخصات غنی‌شده هوش مصنوعی (catalog_products.json, laptops_catalog.json)
   - تنظیمات بانکی و پرداخت (bank_settings.json)
   - تنظیمات موتورهای هوش مصنوعی (ai_settings.json)
   - مانیفست کامل متادیتا (manifest.json) با آمار دقیق و زمان تولید
۲. بازگردانی کامل با رونویسی (Full Replace Restore) با ایجاد اسنپ‌شات ایمنی اضطراری
۳. ادغام هوشمند (Smart Merge / Append) جهت افزودن داده‌های بک‌آپ به سیستم جاری بدون حذف داده‌های جدید
۴. سیستم پشتیبان‌گیری خودکار ۲۴ ساعته (غیرفعال به صورت پیش‌فرض، با قابلیت فعال‌سازی از پنل ادمین)
"""
import re


import os
import io
import json
import time
import zipfile
import sqlite3
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Tuple, Optional, List

logger = logging.getLogger(__name__)

BACKUP_DIR = "backups"
BACKUP_SETTINGS_FILE = "backup_settings.json"

DEFAULT_BACKUP_SETTINGS = {
    "auto_backup_enabled": False,
    "interval_hours": 24,
    "last_auto_backup": "",
    "keep_max_backups": 7
}

def load_backup_settings() -> Dict[str, Any]:
    """بارگذاری تنظیمات بک‌آپ خودکار"""
    settings = dict(DEFAULT_BACKUP_SETTINGS)
    if os.path.exists(BACKUP_SETTINGS_FILE):
        try:
            with open(BACKUP_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    settings.update(data)
        except Exception as e:
            logger.warning(f"Error loading backup_settings.json: {e}")
    return settings

def save_backup_settings(settings: Dict[str, Any]) -> bool:
    """ذخیره تنظیمات بک‌آپ خودکار"""
    try:
        with open(BACKUP_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving backup_settings.json: {e}")
        return False

def set_auto_backup_state(enabled: bool) -> Dict[str, Any]:
    """تغییر وضعیت فعال/غیرفعال بودن بک‌آپ خودکار"""
    settings = load_backup_settings()
    settings["auto_backup_enabled"] = enabled
    settings["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_backup_settings(settings)
    return settings


def _collect_database_summary(db_path: str = "bot_data.db") -> Dict[str, int]:
    """جمع‌آوری خلاصه آماری جداول دیتابیس برای درج در مانیفست"""
    summary = {}
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cur.fetchall() if not r[0].startswith("sqlite_")]
            for t in tables:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {t}")
                    cnt = cur.fetchone()[0]
                    summary[t] = cnt
                except Exception:
                    pass
            conn.close()
        except Exception as e:
            logger.warning(f"Error reading db summary: {e}")
    return summary


def create_full_backup_zip(prefix: str = "AiKala_Backup") -> Tuple[str, Dict[str, Any]]:
    """
    تولید یک فایل فشرده ZIP حاوی تمام داده‌های حیاتی پروژه.
    خروجی: (مسیر_فایل_زیپ, دیکشنری_مانیفست)
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    msec = int(time.time() * 1000) % 1000
    readable_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    zip_filename = f"{prefix}_{timestamp}_{msec:03d}.zip"
    zip_path = os.path.join(BACKUP_DIR, zip_filename)

    db_summary = _collect_database_summary("bot_data.db")

    # جمع‌آوری آمار کاتالوگ و تصاویر
    catalog_count = 0
    if os.path.exists("catalog_products.json"):
        try:
            with open("catalog_products.json", "r", encoding="utf-8") as f:
                c_data = json.load(f)
                catalog_count = len(c_data)
        except Exception:
            pass

    verified_photos_count = 0
    if os.path.exists("verified_photos.json"):
        try:
            with open("verified_photos.json", "r", encoding="utf-8") as f:
                v_data = json.load(f)
                verified_photos_count = len(v_data)
        except Exception:
            pass

    ai_cached_count = 0
    if os.path.exists("ai_content_cache.json"):
        try:
            with open("ai_content_cache.json", "r", encoding="utf-8") as f:
                ai_d = json.load(f)
                ai_cached_count = len(ai_d.get("products", ai_d))
        except Exception:
            pass

    woo_synced_count = 0
    if os.path.exists("woo_product_map.json"):
        try:
            with open("woo_product_map.json", "r", encoding="utf-8") as f:
                woo_synced_count = len(json.load(f))
        except Exception:
            pass

    manifest = {
        "backup_name": zip_filename,
        "created_at": readable_date,
        "version": "3.2.0",
        "orders_count": db_summary.get("orders", 0),
        "products_catalog_count": catalog_count,
        "audio_catalog_count": 0,
        "aeg_products_count": 0,
        "verified_photos_count": verified_photos_count,
        "ai_content_cached_count": ai_cached_count,
        "woo_synced_count": woo_synced_count,
        "sub_admins_count": 0,
        "database_summary": db_summary,
        "included_files": []
    }

    # محاسبه آمار محصولات صوتی و آاگ و ادمین‌ها
    if os.path.exists("audio_catalog.json"):
        try:
            with open("audio_catalog.json", "r", encoding="utf-8") as f:
                manifest["audio_catalog_count"] = len(json.load(f))
        except Exception:
            pass

    if os.path.exists("aeg_products.json"):
        try:
            with open("aeg_products.json", "r", encoding="utf-8") as f:
                manifest["aeg_products_count"] = len(json.load(f))
        except Exception:
            pass

    if os.path.exists("admin_ids.json"):
        try:
            with open("admin_ids.json", "r", encoding="utf-8") as f:
                adm_data = json.load(f)
                manifest["sub_admins_count"] = len(adm_data) if isinstance(adm_data, list) else len(adm_data.keys())
        except Exception:
            pass

    # تشخیص دیتابیس فعال و اجرای چک‌پوینت WAL جهت اطمینان از اعمال کلیه تراکنش‌ها
    active_db = os.getenv("DB_PATH", "bot_data.db")
    if not os.path.exists(active_db):
        for cand in ["bot_data.db", "aikala_bot.db", "aikala.db"]:
            if os.path.exists(cand):
                active_db = cand
                break

    if os.path.exists(active_db):
        try:
            conn = sqlite3.connect(active_db, timeout=5)
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            conn.close()
        except Exception as e:
            logger.warning(f"WAL checkpoint warning: {e}")

    files_to_pack = [
        # ۱. پایگاه داده اصلی
        (active_db, "database/bot_data.db"),
        # ۲. کاتالوگ‌ها و درخت دسته‌بندی‌ها
        ("catalog_products.json", "catalogs/catalog_products.json"),
        ("momtazkalla_all_products.json", "catalogs/momtazkalla_all_products.json"),
        ("audio_catalog.json", "catalogs/audio_catalog.json"),
        ("aeg_products.json", "catalogs/aeg_products.json"),
        ("laptops_catalog.json", "catalogs/laptops_catalog.json"),
        ("categories_tree.json", "catalogs/categories_tree.json"),
        ("hidden_products.json", "catalogs/hidden_products.json"),
        # ۳. تصاویر و ارتباط آلبوم‌ها
        ("verified_photos.json", "photos/verified_photos.json"),
        ("channel_photos_map.json", "photos/channel_photos_map.json"),
        # ۴. مخزن محتواهای غنی‌شده هوش مصنوعی (کش متمرکز متون، ویژگی‌ها و جداول)
        ("ai_content_cache.json", "ai_cache/ai_content_cache.json"),
        # ۵. همگام‌سازی و نگاشت محصولات با ووکامرس (ضد-تکرار و متادیتا)
        ("woo_product_map.json", "woocommerce/woo_product_map.json"),
        ("woo_model_map.json", "woocommerce/woo_model_map.json"),
        ("woo_settings.json", "woocommerce/woo_settings.json"),
        ("woo_review_queue.json", "woocommerce/woo_review_queue.json"),
        ("woo_batch_state.json", "woocommerce/woo_batch_state.json"),
        ("content_sources.json", "woocommerce/content_sources.json"),
        # ۶. ادمین‌ها و دسترسی‌ها و امنیت
        ("admin_ids.json", "settings/admin_ids.json"),
        ("credentials.json", "settings/credentials.json"),
        # ۷. تنظیمات و متاداده‌های سیستم
        ("bank_settings.json", "settings/bank_settings.json"),
        ("ai_settings.json", "settings/ai_settings.json"),
        ("backup_settings.json", "settings/backup_settings.json"),
        ("price_sync_info.json", "settings/price_sync_info.json"),
        ("monitor_state.json", "settings/monitor_state.json"),
        ("bot_freeze_state.json", "settings/bot_freeze_state.json"),
    ]

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, arc in files_to_pack:
            if os.path.exists(src):
                try:
                    zf.write(src, arcname=arc)
                    manifest["included_files"].append({
                        "source": src,
                        "archive_path": arc,
                        "size_bytes": os.path.getsize(src)
                    })
                except Exception as e:
                    logger.warning(f"Error adding {src} to backup zip: {e}")

        # درج شناسنامه (manifest.json) در ریشه فایل زیپ
        manifest_data = json.dumps(manifest, ensure_ascii=False, indent=2)
        zf.writestr("manifest.json", manifest_data)

    logger.info(f"Full backup created successfully: {zip_path} (Orders: {manifest['orders_count']}, Products: {manifest['products_catalog_count']})")
    return zip_path, manifest


def inspect_backup_zip(zip_file_bytes_or_path) -> Optional[Dict[str, Any]]:
    """
    بررسی و اعتبارسنجی فایل زیپ آپلود شده توسط ادمین و استخراج مانیفست.
    در صورت نامعتبر بودن یا عدم وجود فایل‌های حیاتی، None برمی‌گرداند.
    """
    try:
        zf = zipfile.ZipFile(zip_file_bytes_or_path, "r")
        namelist = zf.namelist()
        manifest = {}

        if "manifest.json" in namelist:
            try:
                manifest_raw = zf.read("manifest.json").decode("utf-8")
                manifest = json.loads(manifest_raw)
            except Exception:
                manifest = {}

        # بررسی وجود دیتابیس یا کاتالوگ
        has_db = any(n.endswith(".db") for n in namelist)
        has_catalog = any(
            os.path.basename(n) in ["catalog_products.json", "momtazkalla_all_products.json", "audio_catalog.json", "aeg_products.json"]
            for n in namelist
        )

        if not has_db and not has_catalog:
            zf.close()
            return None

        # استخراج آمار فرعی در صورتی که در مانیفست نباشد
        if "sub_admins_count" not in manifest or manifest["sub_admins_count"] == 0:
            adm_member = next((n for n in namelist if os.path.basename(n) == "admin_ids.json"), None)
            if adm_member:
                try:
                    adm_raw = json.loads(zf.read(adm_member).decode("utf-8"))
                    manifest["sub_admins_count"] = len(adm_raw) if isinstance(adm_raw, list) else len(adm_raw.keys())
                except Exception:
                    pass

        # استخراج آمار هوش مصنوعی و ووکامرس در صورت عدم وجود در مانیفست‌های قدیمی
        if "ai_content_cached_count" not in manifest or manifest["ai_content_cached_count"] == 0:
            ai_member = next((n for n in namelist if os.path.basename(n) == "ai_content_cache.json"), None)
            if ai_member:
                try:
                    ai_raw = json.loads(zf.read(ai_member).decode("utf-8"))
                    prods = ai_raw.get("products", ai_raw)
                    manifest["ai_content_cached_count"] = len(prods)
                except Exception:
                    pass

        if "woo_synced_count" not in manifest or manifest["woo_synced_count"] == 0:
            woo_member = next((n for n in namelist if os.path.basename(n) == "woo_product_map.json"), None)
            if woo_member:
                try:
                    w_raw = json.loads(zf.read(woo_member).decode("utf-8"))
                    manifest["woo_synced_count"] = len(w_raw)
                except Exception:
                    pass

        manifest["namelist"] = namelist
        manifest["has_db"] = has_db
        manifest["has_catalog"] = has_catalog
        zf.close()
        return manifest
    except Exception as e:
        logger.error(f"Failed to inspect backup zip: {e}")
        return None


def restore_full_replace(zip_file_bytes_or_path) -> Tuple[bool, str]:
    """
    بازگردانی کامل (Replace All):
    ۱. ساخت بک‌آپ اضطراری از داده‌های فعلی (Safety Snapshot)
    ۲. جایگزینی کامل دیتابیس، کلیه کاتالوگ‌ها، عکس‌ها، ادمین‌ها و تنظیمات با محتوای فایل زیپ
    """
    try:
        # ساخت اسنپ‌شات ایمنی قبل از بازنویسی
        safety_path, _ = create_full_backup_zip(prefix="Safety_Snapshot_Before_Restore")
        logger.info(f"Safety snapshot saved before full restore: {safety_path}")

        zf = zipfile.ZipFile(zip_file_bytes_or_path, "r")
        namelist = zf.namelist()

        restored_items = []

        # ۱. استخراج دیتابیس SQLite
        for name in namelist:
            if name.endswith(".db"):
                data = zf.read(name)
                # حذف فایلهای موقت WAL برای جلوگیری از خطای کش SQLite
                for wal_ext in ["bot_data.db-wal", "bot_data.db-shm"]:
                    if os.path.exists(wal_ext):
                        try:
                            os.remove(wal_ext)
                        except Exception:
                            pass
                with open("bot_data.db", "wb") as f:
                    f.write(data)
                orig_name = os.path.basename(name)
                restored_items.append(f"پایگاه داده اصلی سفارشات و کانال‌ها ({orig_name} -> bot_data.db)")
                break

        # جدول مپ فایل‌های پروژه و برچسب فارسی آنها
        FILE_DESTINATIONS = {
            "catalog_products.json": ("catalog_products.json", "کاتالوگ جامع محصولات و مشخصات فنی"),
            "momtazkalla_all_products.json": ("momtazkalla_all_products.json", "کاتالوگ پایه محصولات ممتازکالا"),
            "audio_catalog.json": ("audio_catalog.json", "کاتالوگ سیستم‌های صوتی و پارتی‌باکس"),
            "aeg_products.json": ("aeg_products.json", "کاتالوگ محصولات تخصصی آاگ (AEG)"),
            "laptops_catalog.json": ("laptops_catalog.json", "کاتالوگ لپ‌تاپ‌ها"),
            "categories_tree.json": ("categories_tree.json", "درخت دسته‌بندی‌ها و فیلترها"),
            "hidden_products.json": ("hidden_products.json", "لیست وضعیت کالاهای پنهان/فعال"),
            "verified_photos.json": ("verified_photos.json", "تصاویر تایید شده و آلبوم‌ها"),
            "channel_photos_map.json": ("channel_photos_map.json", "نقشه پست‌های کانال عکس"),
            "ai_content_cache.json": ("ai_content_cache.json", "مخزن محتواهای هوش مصنوعی و مشخصات فنی"),
            "woo_product_map.json": ("woo_product_map.json", "نگاشت محصولات متصل به ووکامرس"),
            "woo_model_map.json": ("woo_model_map.json", "نگاشت پارت‌نامبرها و مدل‌های سایت"),
            "woo_settings.json": ("woo_settings.json", "تنظیمات همگام‌سازی ووکامرس"),
            "woo_review_queue.json": ("woo_review_queue.json", "صف بازبینی دستی محصولات سایت"),
            "woo_batch_state.json": ("woo_batch_state.json", "وضعیت پارت‌بندی و ارسال دسته‌ای ووکامرس"),
            "content_sources.json": ("content_sources.json", "لاگ مراجع رسمی و اعتبارسنجی محتوا"),
            "admin_ids.json": ("admin_ids.json", "لیست ادمین‌های فرعی و دسترسی‌ها"),
            "credentials.json": ("credentials.json", "اطلاعات دسترسی سرویس‌ها"),
            "bank_settings.json": ("bank_settings.json", "تنظیمات حساب بانکی و بیعانه"),
            "ai_settings.json": ("ai_settings.json", "تنظیمات هوش مصنوعی کالا"),
            "backup_settings.json": ("backup_settings.json", "تنظیمات زمان‌بندی پشتیبان‌گیری"),
            "price_sync_info.json": ("price_sync_info.json", "اطلاعات همگام‌سازی قیمت‌ها"),
            "monitor_state.json": ("monitor_state.json", "وضعیت پایش پیام‌های کانال‌ها"),
            "bot_freeze_state.json": ("bot_freeze_state.json", "وضعیت و پیام فریز ربات"),
        }

        for name in namelist:
            base = os.path.basename(name)
            if base in FILE_DESTINATIONS and base != "bot_data.db":
                target_file, label = FILE_DESTINATIONS[base]
                data = zf.read(name)
                with open(target_file, "wb") as f:
                    f.write(data)
                restored_items.append(label)

        zf.close()

        # بازخوانی حافظه رم کلیه سرویس‌ها
        _reload_in_memory_services()

        msg = f"✅ <b>بازگردانی کامل با موفقیت انجام شد:</b>\n" + "\n".join([f"▫️ {it}" for it in restored_items])
        return True, msg
    except Exception as e:
        logger.error(f"Full restore failed: {e}", exc_info=True)
        return False, f"خطا در بازگردانی فایل بک‌آپ: {e}"


def restore_smart_merge(zip_file_bytes_or_path) -> Tuple[bool, str, Dict[str, int]]:
    """
    ادغام هوشمند (Smart Merge / Append):
    - سفارش‌های موجود در بک‌آپ که در دیتابیس فعلی نیستند، اضافه می‌شوند (INSERT OR IGNORE).
    - ادمین‌های فرعی موجود در بک‌آپ به لیست جاری اضافه می‌شوند.
    - تصاویر تایید شده و نقشه عکس‌ها با حفظ موارد قبلی ادغام می‌گردند.
    - مشخصات کاتالوگ محصولات، سیستم‌های صوتی و آاگ تکمیل و ادغام می‌شوند.
    - کانال‌های پایش و تاریخچه بدون حذف داده‌های فعلی اضافه می‌شوند.
    - هیچ داده فعلی حذف یا بازنویسی نمی‌شود.
    """
    stats = {
        "orders_added": 0,
        "admins_added": 0,
        "photos_added": 0,
        "channel_photos_added": 0,
        "products_enriched": 0,
        "audio_added": 0,
        "aeg_added": 0,
        "channels_added": 0,
        "ai_content_merged": 0,
        "woo_mappings_added": 0,
    }

    try:
        zf = zipfile.ZipFile(zip_file_bytes_or_path, "r")
        namelist = zf.namelist()

        # ۱. ادغام دیتابیس SQLite
        db_member = next((n for n in namelist if n.endswith(".db")), None)
        if db_member and os.path.exists("bot_data.db"):
            temp_db_path = "temp_backup_restore.db"
            try:
                with open(temp_db_path, "wb") as f:
                    f.write(zf.read(db_member))

                curr_conn = sqlite3.connect("bot_data.db")
                backup_conn = sqlite3.connect(temp_db_path)

                # ادغام سفارشات (orders)
                try:
                    b_cur = backup_conn.cursor()
                    b_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='orders'")
                    if b_cur.fetchone():
                        b_cur.execute("PRAGMA table_info(orders)")
                        cols = [r[1] for r in b_cur.fetchall() if r[1] != "id"]
                        cols_str = ", ".join(cols)
                        placeholders = ", ".join(["?"] * len(cols))

                        b_cur.execute(f"SELECT {cols_str} FROM orders")
                        b_orders = b_cur.fetchall()

                        c_cur = curr_conn.cursor()
                        for row in b_orders:
                            try:
                                c_cur.execute(
                                    f"INSERT OR IGNORE INTO orders ({cols_str}) VALUES ({placeholders})",
                                    row
                                )
                                if c_cur.rowcount > 0:
                                    stats["orders_added"] += 1
                            except Exception:
                                pass
                        curr_conn.commit()
                except Exception as e:
                    logger.warning(f"Error merging orders: {e}")

                # ادغام کانال‌های تحت پایش (monitored_channels)
                try:
                    b_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='monitored_channels'")
                    if b_cur.fetchone():
                        b_cur.execute("SELECT channel_id, channel_name, keywords, active FROM monitored_channels")
                        channels = b_cur.fetchall()
                        c_cur = curr_conn.cursor()
                        for ch in channels:
                            try:
                                c_cur.execute(
                                    "INSERT OR IGNORE INTO monitored_channels (channel_id, channel_name, keywords, active) VALUES (?, ?, ?, ?)",
                                    ch
                                )
                                if c_cur.rowcount > 0:
                                    stats["channels_added"] += 1
                            except Exception:
                                pass
                        curr_conn.commit()
                except Exception as e:
                    logger.warning(f"Error merging monitored channels: {e}")

                # ادغام پست‌های کانال (channel_posts)
                try:
                    b_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='channel_posts'")
                    if b_cur.fetchone():
                        b_cur.execute("SELECT channel_id, message_id, post_text, post_date, product_id, is_catalog FROM channel_posts")
                        posts = b_cur.fetchall()
                        c_cur = curr_conn.cursor()
                        for p in posts:
                            try:
                                c_cur.execute(
                                    "INSERT OR IGNORE INTO channel_posts (channel_id, message_id, post_text, post_date, product_id, is_catalog) VALUES (?, ?, ?, ?, ?, ?)",
                                    p
                                )
                            except Exception:
                                pass
                        curr_conn.commit()
                except Exception as e:
                    logger.warning(f"Error merging channel posts: {e}")

                # ادغام پشتیبانان (support_agents)
                try:
                    b_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='support_agents'")
                    if b_cur.fetchone():
                        b_cur.execute("PRAGMA table_info(support_agents)")
                        b_cols = [r[1] for r in b_cur.fetchall() if r[1] != "id"]
                        if b_cols:
                            col_str = ", ".join(b_cols)
                            placeholders = ", ".join(["?" for _ in b_cols])
                            b_cur.execute(f"SELECT {col_str} FROM support_agents")
                            agents = b_cur.fetchall()
                            c_cur = curr_conn.cursor()
                            for ag in agents:
                                try:
                                    c_cur.execute(
                                        f"INSERT OR IGNORE INTO support_agents ({col_str}) VALUES ({placeholders})",
                                        ag
                                    )
                                except Exception:
                                    pass
                            curr_conn.commit()
                except Exception as e:
                    logger.warning(f"Error merging support agents: {e}")

                curr_conn.close()
                backup_conn.close()
            finally:
                if os.path.exists(temp_db_path):
                    try:
                        os.remove(temp_db_path)
                    except Exception:
                        pass

        # ۲. ادغام ادمین‌های فرعی (admin_ids.json)
        admin_member = next((n for n in namelist if os.path.basename(n) == "admin_ids.json"), None)
        if admin_member:
            try:
                curr_admins = []
                if os.path.exists("admin_ids.json"):
                    with open("admin_ids.json", "r", encoding="utf-8") as f:
                        curr_admins = json.load(f)
                        if not isinstance(curr_admins, list):
                            curr_admins = []

                curr_ids = set()
                for item in curr_admins:
                    if isinstance(item, dict) and "id" in item:
                        try:
                            curr_ids.add(int(item["id"]))
                        except Exception:
                            pass
                    elif str(item).isdigit():
                        curr_ids.add(int(item))

                b_admins = json.loads(zf.read(admin_member).decode("utf-8"))
                added_admins = 0
                if isinstance(b_admins, list):
                    for item in b_admins:
                        uid = None
                        nm = "همکار"
                        if isinstance(item, dict) and "id" in item:
                            try:
                                uid = int(item["id"])
                                nm = str(item.get("name", "همکار")).strip() or "همکار"
                            except Exception:
                                pass
                        elif str(item).isdigit():
                            uid = int(item)
                        if uid and uid not in curr_ids and uid != 86900909:
                            curr_admins.append({"id": uid, "name": nm})
                            curr_ids.add(uid)
                            added_admins += 1

                if added_admins > 0:
                    with open("admin_ids.json", "w", encoding="utf-8") as f:
                        json.dump(curr_admins, f, ensure_ascii=False, indent=2)
                    stats["admins_added"] = added_admins
            except Exception as e:
                logger.warning(f"Error merging admin_ids: {e}")

        # ۳. ادغام تصاویر تایید شده (verified_photos.json)
        v_member = next((n for n in namelist if os.path.basename(n) == "verified_photos.json"), None)
        if v_member:
            try:
                b_photos = json.loads(zf.read(v_member).decode("utf-8"))
                curr_photos = {}
                if os.path.exists("verified_photos.json"):
                    with open("verified_photos.json", "r", encoding="utf-8") as f:
                        curr_photos = json.load(f)

                added = 0
                if isinstance(b_photos, dict):
                    for pid, pdata in b_photos.items():
                        if pid not in curr_photos:
                            curr_photos[pid] = pdata
                            added += 1
                        elif isinstance(pdata, dict) and isinstance(curr_photos[pid], dict):
                            if not curr_photos[pid].get("album") and pdata.get("album"):
                                curr_photos[pid]["album"] = pdata["album"]
                                added += 1
                if added > 0:
                    with open("verified_photos.json", "w", encoding="utf-8") as f:
                        json.dump(curr_photos, f, ensure_ascii=False, indent=2)
                    stats["photos_added"] = added
            except Exception as e:
                logger.warning(f"Error merging verified photos: {e}")

        # ۴. ادغام نقشه پست‌های کانال عکس (channel_photos_map.json)
        cp_member = next((n for n in namelist if os.path.basename(n) == "channel_photos_map.json"), None)
        if cp_member:
            try:
                b_cp = json.loads(zf.read(cp_member).decode("utf-8"))
                curr_cp = {}
                if os.path.exists("channel_photos_map.json"):
                    with open("channel_photos_map.json", "r", encoding="utf-8") as f:
                        curr_cp = json.load(f)
                cp_added = 0
                if isinstance(b_cp, dict):
                    for k, v in b_cp.items():
                        if k not in curr_cp:
                            curr_cp[k] = v
                            cp_added += 1
                if cp_added > 0:
                    with open("channel_photos_map.json", "w", encoding="utf-8") as f:
                        json.dump(curr_cp, f, ensure_ascii=False, indent=2)
                    stats["channel_photos_added"] = cp_added
            except Exception as e:
                logger.warning(f"Error merging channel photos map: {e}")

        # ۵. ادغام کاتالوگ اصلی محصولات و مشخصات فنی (catalog_products.json)
        c_member = next((n for n in namelist if os.path.basename(n) == "catalog_products.json"), None)
        if c_member and os.path.exists("catalog_products.json"):
            try:
                b_catalog = json.loads(zf.read(c_member).decode("utf-8"))
                with open("catalog_products.json", "r", encoding="utf-8") as f:
                    curr_catalog = json.load(f)

                enriched_count = 0
                if isinstance(curr_catalog, dict) and isinstance(b_catalog, dict):
                    for pid, b_prod in b_catalog.items():
                        if pid in curr_catalog:
                            c_prod = curr_catalog[pid]
                            changed = False
                            for fld in ["ai_generated_description", "ai_specs", "extra_description", "image_url", "images", "specs", "brand", "model_number", "score"]:
                                if not c_prod.get(fld) and b_prod.get(fld):
                                    c_prod[fld] = b_prod[fld]
                                    changed = True
                            if changed:
                                enriched_count += 1
                        else:
                            curr_catalog[pid] = b_prod
                            enriched_count += 1

                if enriched_count > 0:
                    with open("catalog_products.json", "w", encoding="utf-8") as f:
                        json.dump(curr_catalog, f, ensure_ascii=False, indent=2)
                    stats["products_enriched"] = enriched_count
            except Exception as e:
                logger.warning(f"Error merging catalog: {e}")

        # ۶. ادغام کاتالوگ سیستم‌های صوتی (audio_catalog.json)
        aud_member = next((n for n in namelist if os.path.basename(n) == "audio_catalog.json"), None)
        if aud_member:
            try:
                b_audio = json.loads(zf.read(aud_member).decode("utf-8"))
                curr_audio = []
                if os.path.exists("audio_catalog.json"):
                    with open("audio_catalog.json", "r", encoding="utf-8") as f:
                        curr_audio = json.load(f)
                audio_map = {str(it.get("product_id") or it.get("id") or it.get("code")): it for it in curr_audio if isinstance(it, dict)}
                aud_added = 0
                if isinstance(b_audio, list):
                    for it in b_audio:
                        if isinstance(it, dict):
                            pid = str(it.get("product_id") or it.get("id") or it.get("code"))
                            if pid and pid not in audio_map:
                                curr_audio.append(it)
                                audio_map[pid] = it
                                aud_added += 1
                            elif pid and pid in audio_map:
                                c_item = audio_map[pid]
                                for fld in ["ai_generated_description", "ai_specs", "specs", "image_url"]:
                                    if not c_item.get(fld) and it.get(fld):
                                        c_item[fld] = it[fld]
                if aud_added > 0:
                    with open("audio_catalog.json", "w", encoding="utf-8") as f:
                        json.dump(curr_audio, f, ensure_ascii=False, indent=2)
                    stats["audio_added"] = aud_added
            except Exception as e:
                logger.warning(f"Error merging audio catalog: {e}")

        # ۷. ادغام کاتالوگ محصولات تخصصی آاگ (aeg_products.json)
        aeg_member = next((n for n in namelist if os.path.basename(n) == "aeg_products.json"), None)
        if aeg_member:
            try:
                b_aeg = json.loads(zf.read(aeg_member).decode("utf-8"))
                curr_aeg = []
                if os.path.exists("aeg_products.json"):
                    with open("aeg_products.json", "r", encoding="utf-8") as f:
                        curr_aeg = json.load(f)
                aeg_map = {str(it.get("product_id") or it.get("wp_id")): it for it in curr_aeg if isinstance(it, dict)}
                aeg_added = 0
                if isinstance(b_aeg, list):
                    for it in b_aeg:
                        if isinstance(it, dict):
                            pid = str(it.get("product_id") or it.get("wp_id"))
                            if pid and pid not in aeg_map:
                                curr_aeg.append(it)
                                aeg_map[pid] = it
                                aeg_added += 1
                            elif pid and pid in aeg_map:
                                c_item = aeg_map[pid]
                                for fld in ["ai_generated_description", "ai_specs", "specs", "image_url"]:
                                    if not c_item.get(fld) and it.get(fld):
                                        c_item[fld] = it[fld]
                if aeg_added > 0:
                    with open("aeg_products.json", "w", encoding="utf-8") as f:
                        json.dump(curr_aeg, f, ensure_ascii=False, indent=2)
                    stats["aeg_added"] = aeg_added
            except Exception as e:
                logger.warning(f"Error merging aeg catalog: {e}")

        # ۸. ادغام درخت دسته‌بندی‌ها (categories_tree.json)
        tree_member = next((n for n in namelist if os.path.basename(n) == "categories_tree.json"), None)
        if tree_member:
            try:
                b_tree = json.loads(zf.read(tree_member).decode("utf-8"))
                curr_tree = {}
                if os.path.exists("categories_tree.json"):
                    with open("categories_tree.json", "r", encoding="utf-8") as f:
                        curr_tree = json.load(f)
                if isinstance(curr_tree, dict) and isinstance(b_tree, dict):
                    tree_mod = False
                    for ck, cv in b_tree.items():
                        if ck not in curr_tree:
                            curr_tree[ck] = cv
                            tree_mod = True
                        elif isinstance(cv, dict) and isinstance(curr_tree[ck], dict):
                            for sk, sv in cv.items():
                                if sk not in curr_tree[ck]:
                                    curr_tree[ck][sk] = sv
                                    tree_mod = True
                    if tree_mod:
                        with open("categories_tree.json", "w", encoding="utf-8") as f:
                            json.dump(curr_tree, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"Error merging categories tree: {e}")

        # ۹. ادغام مخزن محتواهای هوش مصنوعی (ai_content_cache.json)
        ai_member = next((n for n in namelist if os.path.basename(n) == "ai_content_cache.json"), None)
        if ai_member:
            try:
                from ai_content_cache import merge_ai_content_cache_data
                b_ai_data = json.loads(zf.read(ai_member).decode("utf-8"))
                merged_ai = merge_ai_content_cache_data(b_ai_data)
                stats["ai_content_merged"] = merged_ai
            except Exception as e:
                logger.warning(f"Error merging ai content cache: {e}")

        # ۱۰. ادغام نگاشت‌های ووکامرس (woo_product_map.json و woo_model_map.json)
        w_map_member = next((n for n in namelist if os.path.basename(n) == "woo_product_map.json"), None)
        if w_map_member:
            try:
                b_wmap = json.loads(zf.read(w_map_member).decode("utf-8"))
                curr_wmap = {}
                if os.path.exists("woo_product_map.json"):
                    with open("woo_product_map.json", "r", encoding="utf-8") as f:
                        loaded_w = json.load(f)
                        if isinstance(loaded_w, dict):
                            curr_wmap = loaded_w
                w_added = 0
                if isinstance(b_wmap, dict):
                    for k, v in b_wmap.items():
                        if k not in curr_wmap:
                            curr_wmap[k] = v
                            w_added += 1
                if w_added > 0:
                    with open("woo_product_map.json", "w", encoding="utf-8") as f:
                        json.dump(curr_wmap, f, ensure_ascii=False, indent=2)
                    stats["woo_mappings_added"] = w_added
            except Exception as e:
                logger.warning(f"Error merging woo_product_map: {e}")

        w_m_member = next((n for n in namelist if os.path.basename(n) == "woo_model_map.json"), None)
        if w_m_member:
            try:
                b_mmap = json.loads(zf.read(w_m_member).decode("utf-8"))
                curr_mmap = {}
                if os.path.exists("woo_model_map.json"):
                    with open("woo_model_map.json", "r", encoding="utf-8") as f:
                        loaded_m = json.load(f)
                        if isinstance(loaded_m, dict):
                            curr_mmap = loaded_m
                if isinstance(b_mmap, dict):
                    m_changed = False
                    for k, v in b_mmap.items():
                        if k not in curr_mmap:
                            curr_mmap[k] = v
                            m_changed = True
                    if m_changed:
                        with open("woo_model_map.json", "w", encoding="utf-8") as f:
                            json.dump(curr_mmap, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"Error merging woo_model_map: {e}")

        # ۱۱. ادغام صف بازبینی دستی (woo_review_queue.json)
        rq_member = next((n for n in namelist if os.path.basename(n) == "woo_review_queue.json"), None)
        if rq_member:
            try:
                b_rq = json.loads(zf.read(rq_member).decode("utf-8"))
                curr_rq = []
                if os.path.exists("woo_review_queue.json"):
                    with open("woo_review_queue.json", "r", encoding="utf-8") as f:
                        curr_rq = json.load(f)
                existing_pids = {str(it.get("product_id")) for it in curr_rq if isinstance(it, dict)}
                rq_changed = False
                if isinstance(b_rq, list):
                    for it in b_rq:
                        if isinstance(it, dict) and str(it.get("product_id")) not in existing_pids:
                            curr_rq.append(it)
                            existing_pids.add(str(it.get("product_id")))
                            rq_changed = True
                if rq_changed:
                    with open("woo_review_queue.json", "w", encoding="utf-8") as f:
                        json.dump(curr_rq, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"Error merging woo_review_queue: {e}")

        zf.close()
        _reload_in_memory_services()

        msg = (
            f"✅ <b>ادغام هوشمند داده‌ها با موفقیت انجام شد:</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"▫️ سفارش‌های جدید اضافه‌شده: <b>{stats['orders_added']}</b> مورد\n"
            f"▫️ ادمین‌های فرعی افزوده شده: <b>{stats['admins_added']}</b> نفر\n"
            f"▫️ تصاویر اختصاصی متصل‌شده: <b>{stats['photos_added']}</b> کالا\n"
            f"▫️ مشخصات و کالاهای تکمیل‌شده: <b>{stats['products_enriched']}</b> قلم\n"
            f"▫️ سیستم‌های صوتی افزوده شده: <b>{stats['audio_added']}</b> دستگاه\n"
            f"▫️ محصولات آاگ افزوده شده: <b>{stats['aeg_added']}</b> کالا\n"
            f"▫️ محتواهای هوش مصنوعی ادغام‌شده: <b>{stats.get('ai_content_merged', 0)}</b> کالا\n"
            f"▫️ پیوندهای سایت ووکامرس (ضد-تکرار): <b>{stats.get('woo_mappings_added', 0)}</b> مورد\n"
            f"▫️ کانال‌های پایش جدید: <b>{stats['channels_added']}</b> کانال\n\n"
            f"✨ <i>تمام داده‌های جاری بدون کم‌وکاست حفظ گردیدند.</i>"
        )
        return True, msg, stats
    except Exception as e:
        logger.error(f"Smart merge failed: {e}", exc_info=True)
        return False, f"خطا در ادغام هوشمند فایل بک‌آپ: {e}", stats


def _reload_in_memory_services():
    """بازنشانی متغیرهای درون حافظه بعد از بازگردانی فایل‌ها"""
    try:
        import photo_service
        photo_service.load_verified_photos()
    except Exception:
        pass

    try:
        import search_engine
        search_engine.load_json_products()
    except Exception:
        pass

    try:
        import config
        config.BANK_SETTINGS = config._load_bank_settings()
        config.DEPOSIT_CARD_NUMBER = config.BANK_SETTINGS.get("card_number", config.DEPOSIT_CARD_NUMBER)
        config.DEPOSIT_CARD_NAME = config.BANK_SETTINGS.get("card_holder", config.DEPOSIT_CARD_NAME)
        config.DEPOSIT_CARD_SHABA = config.BANK_SETTINGS.get("card_shaba", config.DEPOSIT_CARD_SHABA)
        config.DEPOSIT_PERCENT = config.BANK_SETTINGS.get("deposit_percent", config.DEPOSIT_PERCENT)
    except Exception:
        pass

    try:
        from ai_content_cache import load_ai_content_cache
        load_ai_content_cache()
    except Exception:
        pass

    try:
        import search_engine
        search_engine.load_hidden_product_ids()
    except Exception:
        pass

    try:
        import woo_sync_service
        woo_sync_service.load_woo_mappings()
        woo_sync_service.load_woo_settings()
        woo_sync_service.load_woo_review_queue()
        woo_sync_service.get_woo_batch_state()
    except Exception:
        pass


# =====================================================================
# ⏰ تسک بک‌آپ خودکار ۲۴ ساعته (پیش‌فرض غیرفعال)
# =====================================================================

async def auto_backup_background_task(bot, admin_ids: List[int]):
    """
    تسک پس‌زمینه پشتیبان‌گیری دوره‌ای:
    - هر ساعت بررسی می‌کند.
    - اگر توسط ادمین فعال شده باشد و ۲۴ ساعت از آخرین بک‌آپ گذشته باشد، بک‌آپ می‌گیرد
      و فایل آن را مستقیماً برای ادمین در تلگرام ارسال می‌کند.
    """
    logger.info("Auto-backup background scheduler initialized.")
    while True:
        try:
            settings = load_backup_settings()
            if settings.get("auto_backup_enabled"):
                interval_hours = settings.get("interval_hours", 24)
                last_backup_str = settings.get("last_auto_backup", "")
                should_run = False

                if not last_backup_str:
                    should_run = True
                else:
                    try:
                        last_dt = datetime.strptime(last_backup_str, "%Y-%m-%d %H:%M:%S")
                        elapsed_hours = (datetime.now() - last_dt).total_seconds() / 3600.0
                        if elapsed_hours >= interval_hours:
                            should_run = True
                    except Exception:
                        should_run = True

                if should_run:
                    logger.info("Executing scheduled 24-hour backup...")
                    zip_path, manifest = create_full_backup_zip()
                    settings["last_auto_backup"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    save_backup_settings(settings)

                    caption = (
                        f"⏰ <b>پشتیبان‌گیری خودکار ۲۴ ساعته سیستم:</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"📦 نام فایل: <code>{manifest['backup_name']}</code>\n"
                        f"📅 تاریخ: <b>{manifest['created_at']}</b>\n"
                        f"▫️ تعداد سفارش‌ها: <b>{manifest['orders_count']}</b>\n"
                        f"▫️ کاتالوگ محصولات: <b>{manifest['products_catalog_count']}</b>\n"
                        f"▫️ تصاویر اختصاصی: <b>{manifest['verified_photos_count']}</b>\n\n"
                        f"💡 <i>این فایل به صورت خودکار ذخیره و در فضای امن تلگرام آرشیو گردید.</i>"
                    )

                    for aid in admin_ids:
                        try:
                            with open(zip_path, "rb") as f_zip:
                                await bot.send_document(
                                    chat_id=aid,
                                    document=f_zip,
                                    filename=manifest["backup_name"],
                                    caption=caption,
                                    parse_mode="HTML"
                                )
                        except Exception as e:
                            logger.warning(f"Could not send auto-backup to admin {aid}: {e}")
        except Exception as e:
            logger.error(f"Error in auto_backup_background_task: {e}")

        # بررسی هر ۱ ساعت
        await asyncio.sleep(3600)


# =====================================================================
# 🧨 ریست کلی دیتابیس به صفر مطلق (Hard Reset To Absolute Zero)
# =====================================================================

def reset_sqlite_database_cleanly(db_path: str = "bot_data.db"):
    """پاکسازی و بازسازی دیتابیس SQLite به صفر مطلق با حفظ کامل و ۱۰۰٪ ساختار اسکیما"""
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables = [r[0] for r in c.fetchall()]
            for t in tables:
                c.execute(f"DROP TABLE IF EXISTS {t}")
            conn.commit()
            conn.execute("VACUUM")
            conn.close()
        except Exception as e:
            logger.warning(f"Error dropping tables from {db_path}: {e}")

    # حذف فایل‌های موقت WAL
    for wal_f in [f"{db_path}-wal", f"{db_path}-shm"]:
        if os.path.exists(wal_f):
            try:
                os.remove(wal_f)
            except Exception:
                pass

    # ساخت مجدد کلیه جداول استاندارد سیستم (مطابق اسکیما اصلی database.py)
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT UNIQUE,
                data_id TEXT,
                category_key TEXT,
                category_name TEXT,
                subcategory TEXT,
                name TEXT,
                model_number TEXT,
                brand TEXT,
                size TEXT,
                price INTEGER DEFAULT 0,
                status TEXT DEFAULT 'b',
                assembly TEXT,
                score TEXT,
                year TEXT,
                resolution TEXT,
                panel TEXT,
                refresh_rate TEXT,
                backlight TEXT,
                os TEXT,
                capacity_btu TEXT,
                ac_type TEXT,
                temp_range TEXT,
                room_size TEXT,
                energy_consumption TEXT,
                performance TEXT,
                key_features TEXT,
                plan TEXT,
                capacity_foot TEXT,
                num_doors TEXT,
                capacity_kg TEXT,
                baskets TEXT,
                more_details TEXT,
                ai_generated_description TEXT DEFAULT '',
                category TEXT DEFAULT 'default',
                colors_json TEXT DEFAULT '{}',
                specs_json TEXT DEFAULT '{}',
                url TEXT,
                image_url TEXT,
                source TEXT DEFAULT 'MomtazKalla',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT UNIQUE NOT NULL,
                channel_name TEXT,
                keywords TEXT DEFAULT '',
                active INTEGER DEFAULT 1,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS channel_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL,
                channel_name TEXT,
                message_id INTEGER,
                text TEXT,
                cleaned_text TEXT,
                date TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS user_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER,
                user_id INTEGER NOT NULL,
                username TEXT,
                product_id TEXT,
                product_name TEXT NOT NULL,
                city TEXT,
                color TEXT,
                status TEXT DEFAULT 'Pending',
                admin_response TEXT,
                final_price TEXT,
                shipping_method TEXT DEFAULT 'freight',
                invoice_link TEXT,
                request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_code TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                product_id TEXT,
                product_name TEXT,
                full_name TEXT,
                phone1 TEXT,
                phone2 TEXT,
                province_city TEXT,
                address TEXT,
                postal_code TEXT,
                total_price TEXT DEFAULT '0',
                deposit_amount TEXT,
                shipping_method TEXT DEFAULT 'freight',
                receipt_file_id TEXT,
                receipt_text TEXT,
                status TEXT DEFAULT 'Awaiting_Payment',
                admin_note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL,
                price TEXT,
                color TEXT,
                date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS user_last_view (
                user_id INTEGER PRIMARY KEY,
                last_view_date TIMESTAMP DEFAULT '1970-01-01'
            );

            CREATE TABLE IF NOT EXISTS monitored_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT UNIQUE NOT NULL,
                channel_name TEXT,
                keywords TEXT DEFAULT '',
                active INTEGER DEFAULT 1,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS support_agents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                title TEXT,
                telegram_username TEXT,
                phone TEXT,
                working_hours TEXT DEFAULT '۹ الی ۲۳',
                is_active INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS channel_reposts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_channel TEXT NOT NULL,
                source_msg_id INTEGER NOT NULL,
                target_channel TEXT NOT NULL,
                target_msg_id INTEGER,
                has_photo INTEGER DEFAULT 1,
                reposted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_channel, source_msg_id)
            );

            CREATE TABLE IF NOT EXISTS downloader_users (
                user_id INTEGER PRIMARY KEY,
                download_count INTEGER DEFAULT 0,
                unlocked INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_download_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS downloader_referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inviter_id INTEGER NOT NULL,
                invited_id INTEGER UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS dynamic_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_key TEXT UNIQUE,
                title TEXT,
                tree_json TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Error creating full core schema in reset: {e}")

    # ساخت مجدد ساختار دیتابیس کالکشن محصولات
    try:
        from db_bridge import init_product_tables
        init_product_tables()
    except Exception as e:
        logger.warning(f"Error initializing product tables: {e}")


def perform_hard_reset_to_zero(bot=None, notify_user_id: Optional[int] = None, reset_woo: bool = True) -> Tuple[bool, str, Optional[str]]:
    """
    ریست کلی دیتابیس به صفر مطلق (Hard Reset):
    ۱. ساخت بک‌آپ اضطراری ایمن از وضعیت کنونی سیستم (Safety Snapshot)
    ۲. پاکسازی کامل تمام جداول دیتابیس SQLite و بازسازی جداول خالی
    ۳. پاکسازی فایل‌های کاتالوگ محصولات، عکس‌ها و کش هوش مصنوعی
    ۴. پاکسازی اختیاری نگاشت‌ها و وضعیت ارسال ووکامرس (بر اساس reset_woo)
    ۵. بارگذاری مجدد سرویس‌ها در حافظه موقت (In-Memory)
    """
    try:
        # ۱. ساخت بکاپ اضطراری ایمنی پیش از ریست
        snapshot_path, manifest = create_full_backup_zip(prefix="Emergency_Snapshot_Before_Hard_Reset")
        logger.info(f"Emergency snapshot created at: {snapshot_path}")

        # ۲. پاکسازی کامل SQLite دیتابیس
        active_db = os.getenv("DB_PATH", "bot_data.db")
        if not os.path.exists(active_db):
            active_db = "bot_data.db"
        reset_sqlite_database_cleanly(active_db)

        # ۳. بازنشانی فایل‌های داده، عکس‌ها و کش‌های کاتالوگ ربات
        json_empty_maps = {
            "catalog_products.json": {},
            "momtazkalla_all_products.json": {},
            "audio_catalog.json": {},
            "aeg_products.json": {},
            "laptops_catalog.json": {},
            "hidden_products.json": {},
            "categories_tree.json": {},
            "verified_photos.json": {},
            "channel_photos_map.json": {},
            "content_sources.json": [],
            "ai_content_cache.json": {"products": {}, "models": {}},
            "price_sync_info.json": {},
            "monitor_state.json": {},
        }

        # اگر ادمین تایید کرده باشد که ووکامرس هم صفر شود
        if reset_woo:
            json_empty_maps["woo_product_map.json"] = {}
            json_empty_maps["woo_model_map.json"] = {}
            json_empty_maps["woo_review_queue.json"] = []
            try:
                from woo_sync_service import reset_woo_batch_state
                reset_woo_batch_state()
            except Exception as e_bs:
                logger.warning(f"Error resetting woo_batch_state: {e_bs}")

        for fn, empty_val in json_empty_maps.items():
            try:
                with open(fn, "w", encoding="utf-8") as f:
                    json.dump(empty_val, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"Error resetting {fn}: {e}")

        # ۴. بازنشانی حافظه موقت سرویس‌ها و حفاظت قطعی از .env
        if os.path.isfile(".env.vault") and not os.path.isfile(".env"):
            try:
                import shutil
                shutil.copy2(".env.vault", ".env")
            except Exception:
                pass

        _reload_in_memory_services()

        woo_status_note = (
            "✅ وضعیت پارت‌بندی و نگاشت‌های ووکامرس کاملاً صفر و ریست شدند."
            if reset_woo else
            "🛡 <b>پیوندهای ووکامرس و وضعیت پارت‌بندی سایت حفظ شدند</b> (جهت جلوگیری از ارسال تکراری کالاها به سایت)."
        )

        res_msg = (
            f"🧨 <b>دیتابیس سیستم با موفقیت بازنشانی شد!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔒 <b>فایل پیکربندی (.env) و توکن‌ها کاملاً دست‌نخورده و ایمن حفظ شدند.</b>\n"
            f"✅ تمام سفارش‌ها، فاکتورها و استعلام‌های دیتابیس صفر شدند.\n"
            f"✅ کاتالوگ جامع محصولات، صوتی، لپ‌تاپ و AEG پاکسازی شدند.\n"
            f"✅ تمامی آلبوم‌ها و تصاویر متصل‌شده به کالاها حذف شدند.\n"
            f"✅ مخزن کش محتواهای هوش مصنوعی و مشخصات فنی صفر گردید.\n"
            f"▫️ {woo_status_note}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡 <b>توجه امنیتی:</b> یک فایل بک‌آپ اضطراری کامل (شامل تمام اطلاعات قبلی) قبل از شروع ریست ایجاد گردید.\n"
            f"📁 نام فایل اسنپ‌شات: <code>{manifest['backup_name']}</code>"
        )
        return True, res_msg, snapshot_path
    except Exception as e:
        logger.error(f"Hard reset failed: {e}", exc_info=True)
        return False, f"❌ خطا در اجرای ریست کلی دیتابیس: {e}", None
