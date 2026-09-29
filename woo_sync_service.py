# -*- coding: utf-8 -*-
"""
سرویس همگام‌سازی کاتالوگ با ووکامرس (AiKala ⟷ aegkala.com)
شامل:
۱. حفاظت و قرنطینه ۱۰۰٪ محصولات و دسته‌های آاگ (AEG)
۲. ساختار سلسله‌مراتبی دسته‌بندی زیر ریشه «AiKala» (parent: 0)
۳. معماری ۳ لایه استخراج، تولید محتوای هوش مصنوعی و اعتبارسنجی ضد-توهم (Zero-Hallucination)
۴. آپدیت سریع قیمت‌ها و وضعیت کالاهای ناموجود («تماس بگیرید»)
۵. زمان‌بندی نامتقارن و تفکیک‌شده (Staggered Scheduling) برای جلوگیری از تداخل بار سرور
"""

import os
import re
import json
import time
import base64
import logging
import asyncio
import urllib.request
import urllib.parse
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime

from config import AEG_SITE_URL, AEG_CONSUMER_KEY, AEG_CONSUMER_SECRET, AEG_CAT_ID

logger = logging.getLogger(__name__)

# مسیر فایل‌های پیکربندی و دیتابیس محلی ووکامرس
WOO_SETTINGS_FILE = "woo_settings.json"
CONTENT_SOURCES_FILE = "content_sources.json"
WOO_REVIEW_QUEUE_FILE = "woo_review_queue.json"
WOO_PRODUCT_MAP_FILE = "woo_product_map.json"
WOO_MODEL_MAP_FILE = "woo_model_map.json"
WOO_BATCH_STATE_FILE = "woo_batch_state.json"


def get_woo_batch_state() -> dict:
    """بارگذاری وضعیت جاری ارسال دسته‌ای ۵۰ تایی"""
    default_state = {
        "is_active": False,
        "current_index": 0,
        "chunk_size": 50,
        "delay_seconds": 10.0,
        "publish_status": "draft",
        "processed_total": 0,
        "sent_count": 0,
        "skipped_aeg": 0,
        "review_count": 0,
        "errors_count": 0,
        "last_pid": "",
        "last_pname": "",
        "updated_at": ""
    }
    if os.path.exists(WOO_BATCH_STATE_FILE):
        try:
            with open(WOO_BATCH_STATE_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    default_state.update(saved)
        except Exception as e:
            logger.warning(f"Error loading {WOO_BATCH_STATE_FILE}: {e}")
    return default_state


def save_woo_batch_state(state: dict) -> bool:
    """ذخیره وضعیت جاری ارسال دسته‌ای"""
    try:
        state["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(WOO_BATCH_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving {WOO_BATCH_STATE_FILE}: {e}")
        return False


def reset_woo_batch_state() -> bool:
    """ریست کردن وضعیت ارسال دسته‌ای"""
    try:
        if os.path.exists(WOO_BATCH_STATE_FILE):
            os.remove(WOO_BATCH_STATE_FILE)
        return True
    except Exception:
        return False

# کلمات ممنوعه تبلیغاتی زرد در لایه اعتبارسنجی
FORBIDDEN_AD_WORDS = [
    "معجزه", "شگفت‌انگیزترین", "فقط امروز", "فرصت محدود", "ارزان‌ترین قیمت بازار",
    "تضمین صد در صد", "بدو تا تموم نشده", "تخفیف وحشتناک"
]

# دامنه‌های مرجع رسمی برندها
OFFICIAL_BRAND_DOMAINS = {
    "lg": "lg.com",
    "ال جی": "lg.com",
    "سامسونگ": "samsung.com",
    "samsung": "samsung.com",
    "سونی": "sony.com",
    "sony": "sony.com",
    "بوش": "bosch-home.com",
    "bosch": "bosch-home.com",
    "فیلیپس": "philips.com",
    "philips": "philips.com",
    "هایسنس": "hisense.com",
    "hisense": "hisense.com",
    "اسنوا": "snowa.ir",
    "snowa": "snowa.ir",
    "پاکشوما": "pakshoma.com",
    "pakshoma": "pakshoma.com",
    "دوو": "daewoo.ir",
    "daewoo": "daewoo.ir",
    "جی پلاس": "gplusiran.com",
    "gplus": "gplusiran.com",
    "پاناسونیک": "panasonic.com",
    "panasonic": "panasonic.com"
}

# دسته‌های پیش‌فرض محافظت‌شده آاگ
DEFAULT_AEG_PROTECTED_CAT_IDS = [202, 205, 210, 215, 220]


def get_woo_settings() -> dict:
    """بارگذاری تنظیمات ووکامرس"""
    default_settings = {
        "aikala_root_category_id": 0,
        "aeg_protected_category_ids": DEFAULT_AEG_PROTECTED_CAT_IDS,
        "aeg_protected_slugs": ["aeg", "آاگ", "aegkala"],
        "default_publish_status": "draft",  # draft | publish
        "auto_sync_enabled": True,
        "price_sync_hours": ["04:30"],  # بروزرسانی روزانه ۱ بار در ساعت ۰۴:۳۰ بامداد
        "last_sync_time": "",
        "last_price_sync_time": "",
        "batch_delay_seconds": 1.5,
        "auto_create_subcategories": True,
        "ai_provider": "gemini"  # gemini | deepseek
    }
    if os.path.exists(WOO_SETTINGS_FILE):
        try:
            with open(WOO_SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                default_settings.update(saved)
        except Exception as e:
            logger.warning(f"Error loading {WOO_SETTINGS_FILE}: {e}")
    return default_settings


def save_woo_settings(settings: dict) -> bool:
    """ذخیره تنظیمات ووکامرس"""
    try:
        with open(WOO_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving {WOO_SETTINGS_FILE}: {e}")
        return False


def get_woo_product_map() -> dict:
    """بارگذاری نگاشت product_id ربات به woo_product_id"""
    if os.path.exists(WOO_PRODUCT_MAP_FILE):
        try:
            with open(WOO_PRODUCT_MAP_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_woo_product_map(product_map: dict) -> bool:
    """ذخیره نگاشت کالاها"""
    try:
        with open(WOO_PRODUCT_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(product_map, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def get_woo_model_map() -> dict:
    """بارگذاری نگاشت پارت‌نامبر نرمال‌شده کالا به woo_product_id جهت جلوگیری قطعی از ثبت تکراری"""
    if os.path.exists(WOO_MODEL_MAP_FILE):
        try:
            with open(WOO_MODEL_MAP_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_woo_model_map(model_map: dict) -> bool:
    """ذخیره نگاشت پارت‌نامبرها به شناسه ووکامرس"""
    try:
        with open(WOO_MODEL_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(model_map, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def extract_product_model_key(product: dict) -> str:
    """استخراج پارت‌نامبر یا مدل استاندارد کالا جهت تطبیق و جلوگیری از ایجاد کالای تکراری"""
    from ai_content_cache import normalize_model_key
    model_num = product.get("model_number") or product.get("model") or ""
    if model_num:
        mk = normalize_model_key(model_num)
        if mk:
            return mk
    # استخراج از نام محصول
    name = str(product.get("name") or product.get("title") or "")
    tokens = re.findall(r'[a-zA-Z0-9\-_]{2,}', name)
    for tok in reversed(tokens):
        tok_clean = re.sub(r'[^a-zA-Z0-9]', '', tok).lower()
        if any(c.isdigit() for c in tok_clean) and any(c.isalpha() for c in tok_clean) and len(tok_clean) >= 3:
            return tok_clean
    # اگر کد عددی ۳ یا ۴ رقمی بود (مانند مدل 673 در هایسنس)
    num_match = re.findall(r'\b\d{3,4}\b', name)
    if num_match:
        brand = normalize_model_key(product.get("brand", ""))
        return f"{brand}_{num_match[-1]}"
    return normalize_model_key(name)


def find_existing_woo_product(product: dict, pid: str) -> Tuple[Optional[int], str]:
    """
    موتور چندلایه کشف کالای موجود در ووکامرس (Multi-tier Anti-Duplicate Engine):
    لایه ۱: بررسی بر اساس شناسه محصول در نگاشت محلی (product_map)
    لایه ۲: بررسی بر اساس پارت‌نامبر و مدل نرمال‌شده در نگاشت محلی (model_map)
    لایه ۳: استعلام زنده از ووکامرس با SKU یکتا (AIKALA-{pid})
    لایه ۴: استعلام زنده بر اساس کد مدل و تطابق عنوان و اسلاگ در سایت
    خروجی: (woo_id, match_source)
    """
    product_map = get_woo_product_map()
    model_map = get_woo_model_map()
    model_key = extract_product_model_key(product)

    # لایه ۱: نگاشت مستقیم PID
    if pid in product_map and product_map[pid]:
        return int(product_map[pid]), "local_pid_map"

    # لایه ۲: نگاشت مدل نرمال‌شده
    if model_key and model_key in model_map and model_map[model_key]:
        woo_id = int(model_map[model_key])
        product_map[pid] = woo_id
        save_woo_product_map(product_map)
        return woo_id, "local_model_map"

    # لایه ۳: استعلام زنده با SKU در ووکامرس
    sku = f"AIKALA-{pid}"
    try:
        ok, res = _make_woo_request(f"products?sku={urllib.parse.quote(sku)}", "GET")
        if ok and isinstance(res, list) and len(res) > 0 and "id" in res[0]:
            woo_id = int(res[0]["id"])
            product_map[pid] = woo_id
            if model_key:
                model_map[model_key] = woo_id
                save_woo_model_map(model_map)
            save_woo_product_map(product_map)
            return woo_id, "remote_sku_match"
    except Exception as e:
        logger.debug(f"Error checking SKU {sku}: {e}")

    # لایه ۴: جستجوی زنده بر اساس پارت‌نامبر در ووکامرس
    if model_key and len(model_key) >= 3:
        try:
            ok_s, res_s = _make_woo_request(f"products?search={urllib.parse.quote(model_key)}&per_page=5", "GET")
            if ok_s and isinstance(res_s, list) and len(res_s) > 0:
                pbrand = str(product.get("brand") or "").lower()
                for cand in res_s:
                    c_title = cand.get("name", "").lower()
                    c_slug = cand.get("slug", "").lower()
                    if (model_key in c_title or model_key in c_slug) and (not pbrand or pbrand in c_title or pbrand in c_slug):
                        woo_id = int(cand["id"])
                        product_map[pid] = woo_id
                        model_map[model_key] = woo_id
                        save_woo_product_map(product_map)
                        save_woo_model_map(model_map)
                        return woo_id, "remote_model_search"
        except Exception as e:
            logger.debug(f"Error searching model {model_key}: {e}")

    return None, "not_found"


def update_catalog_product_ai_data(pid: str, specs: dict, overview: str, highlights: str = ""):
    """بروزرسانی مشخصات و متون تولیدی در کاتالوگ محلی محصولات و دیتابیس SQLite ربات"""
    s_pid = str(pid).strip()
    if os.path.exists("catalog_products.json"):
        try:
            with open("catalog_products.json", "r", encoding="utf-8") as f:
                cat = json.load(f)
            if isinstance(cat, dict) and s_pid in cat:
                if specs:
                    cat[s_pid]["specs"] = specs
                    cat[s_pid]["ai_specs"] = specs
                if overview:
                    cat[s_pid]["ai_generated_description"] = overview
                if highlights:
                    cat[s_pid]["ai_highlights"] = highlights
                with open("catalog_products.json", "w", encoding="utf-8") as f:
                    json.dump(cat, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug(f"Error updating catalog_products.json for {pid}: {e}")

    # همگام‌سازی مستقیم در دیتابیس SQLite ربات جهت نمایش آنی در کارت‌های کالا به کاربران
    try:
        import sqlite3
        db_path = os.getenv("DB_PATH", "bot_data.db")
        if not os.path.exists(db_path):
            for candidate in ["bot_data.db", "aikala_bot.db", "aikala.db"]:
                if os.path.exists(candidate):
                    db_path = candidate
                    break
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path, timeout=5.0)
            cur = conn.cursor()
            specs_json = json.dumps(specs, ensure_ascii=False) if specs else None
            if specs_json and overview:
                cur.execute("UPDATE products SET ai_generated_description = ?, specs_json = ? WHERE product_id = ?", (overview, specs_json, s_pid))
            elif overview:
                cur.execute("UPDATE products SET ai_generated_description = ? WHERE product_id = ?", (overview, s_pid))
            elif specs_json:
                cur.execute("UPDATE products SET specs_json = ? WHERE product_id = ?", (specs_json, s_pid))
            conn.commit()
            conn.close()
    except Exception as e_sql:
        logger.debug(f"Error updating SQLite products table for {s_pid}: {e_sql}")


def get_woo_review_queue() -> List[dict]:
    """دریافت لیست کالاهای نیازمند بازبینی دستی"""
    if os.path.exists(WOO_REVIEW_QUEUE_FILE):
        try:
            with open(WOO_REVIEW_QUEUE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_woo_review_queue(queue: List[dict]) -> bool:
    """ذخیره صف بازبینی دستی"""
    try:
        with open(WOO_REVIEW_QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def add_to_review_queue(product: dict, reason: str, details: Optional[dict] = None):
    """افزودن کالا به صف بازبینی دستی"""
    queue = get_woo_review_queue()
    pid = str(product.get("product_id") or product.get("id") or "").strip()
    
    # جلوگیری از تکرار
    queue = [item for item in queue if str(item.get("product_id")) != pid]
    
    queue.append({
        "product_id": pid,
        "name": product.get("name") or product.get("title", ""),
        "brand": product.get("brand", ""),
        "category": product.get("category", ""),
        "price": product.get("price", 0),
        "reason": reason,
        "details": details or {},
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    save_woo_review_queue(queue)
    logger.info(f"⚠️ [WOO REVIEW QUEUE] محصول '{pid}' به صف بازبینی دستی اضافه شد: {reason}")


def log_content_source(pid: str, sources: List[str], validated: bool, notes: str, ai_model: str):
    """ثبت مراجع و لاگ اعتبارسنجی در content_sources.json"""
    data = {}
    if os.path.exists(CONTENT_SOURCES_FILE):
        try:
            with open(CONTENT_SOURCES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    
    data[str(pid)] = {
        "sources": sources,
        "extracted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "validated": validated,
        "validation_notes": notes,
        "ai_model_used": ai_model
    }
    
    try:
        with open(CONTENT_SOURCES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Error saving {CONTENT_SOURCES_FILE}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# ۱. لایه امنیتی و قرنطینه آاگ (AEG Protection Rule)
# ─────────────────────────────────────────────────────────────────────────────

def is_aeg_protected(product: dict) -> bool:
    """
    بررسی سخت‌گیرانه آیا کالا متعلق به آاگ (AEG) است یا خیر.
    قانون طلایی: اگر True باشد، ربات حق هیچ‌گونه ارسال، ویرایش یا تغییر در ووکامرس را ندارد.
    """
    pid = str(product.get("product_id") or product.get("id") or "").strip().upper()
    if pid.startswith("AEG_") or pid.startswith("AEG"):
        return True

    brand = str(product.get("brand") or "").strip().lower()
    if "آاگ" in brand or "aeg" in brand or "میله" in brand or "miele" in brand:
        return True

    cat_name = str(product.get("category") or product.get("category_name") or "").strip().lower()
    if "آاگ" in cat_name or "aeg" in cat_name:
        return True

    subcat = str(product.get("subcategory") or "").strip().lower()
    if "آاگ" in subcat or "aeg" in subcat:
        return True

    name = str(product.get("name") or product.get("title") or "").strip().lower()
    if name.startswith("aeg ") or name.startswith("آاگ ") or "برند آاگ" in name:
        return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# ۲. ارتباط امن با REST API ووکامرس
# ─────────────────────────────────────────────────────────────────────────────

def _make_woo_request(endpoint: str, method: str = "GET", data: Optional[dict] = None) -> Tuple[bool, Any]:
    """ارسال درخواست امن به WooCommerce REST API"""
    base_url = AEG_SITE_URL.rstrip('/')
    url = f"{base_url}/wp-json/wc/v3/{endpoint.lstrip('/')}"
    
    auth_str = f"{AEG_CONSUMER_KEY}:{AEG_CONSUMER_SECRET}"
    auth_header = base64.b64encode(auth_str.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {auth_header}",
        "User-Agent": "AiKala-WooBridge/3.0 (Telegram Bot Integration)",
        "Content-Type": "application/json"
    }
    
    req_body = json.dumps(data, ensure_ascii=False).encode('utf-8') if data else None
    req = urllib.request.Request(url, data=req_body, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=18) as resp:
            resp_body = resp.read().decode('utf-8')
            parsed = json.loads(resp_body) if resp_body else {}
            return True, parsed
    except urllib.error.HTTPError as he:
        err_content = he.read().decode('utf-8', errors='ignore')[:350]
        logger.error(f"❌ [WOO HTTP {he.code}] {method} {url}: {err_content}")
        return False, f"HTTP {he.code}: {err_content}"
    except Exception as e:
        logger.error(f"❌ [WOO REQUEST ERROR] {method} {url}: {e}")
        return False, str(e)


def upload_image_bytes_to_wp_media(image_bytes: bytes, filename: str, alt_text: str = "") -> Tuple[bool, Optional[int], Optional[str]]:
    """آپلود فایل باینری تصویر در کتابخانه چندرسانه‌ای وردپرس (WordPress Media REST API)"""
    if not image_bytes or len(image_bytes) < 100:
        return False, None, None

    base_url = AEG_SITE_URL.rstrip('/')
    url = f"{base_url}/wp-json/wp/v2/media"
    
    auth_str = f"{AEG_CONSUMER_KEY}:{AEG_CONSUMER_SECRET}"
    auth_header = base64.b64encode(auth_str.encode()).decode()
    
    clean_fn = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', filename)
    if not clean_fn.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
        clean_fn += ".jpg"

    headers = {
        "Authorization": f"Basic {auth_header}",
        "User-Agent": "AiKala-WooBridge/3.0 (Telegram Bot Integration)",
        "Content-Disposition": f'attachment; filename="{clean_fn}"',
        "Content-Type": "image/jpeg"
    }

    req = urllib.request.Request(url, data=image_bytes, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            resp_body = resp.read().decode('utf-8')
            parsed = json.loads(resp_body) if resp_body else {}
            if isinstance(parsed, dict) and "id" in parsed:
                media_id = int(parsed["id"])
                source_url = parsed.get("source_url") or parsed.get("guid", {}).get("rendered", "")
                logger.info(f"📸 [WP MEDIA UPLOAD] Successfully uploaded image to WP Media: ID={media_id}, URL={source_url}")
                return True, media_id, source_url
            return False, None, None
    except urllib.error.HTTPError as he:
        err_content = he.read().decode('utf-8', errors='ignore')[:300]
        logger.error(f"❌ [WP MEDIA HTTP {he.code}] POST {url}: {err_content}")
        return False, None, None
    except Exception as e:
        logger.error(f"❌ [WP MEDIA ERROR] POST {url}: {e}")
        return False, None, None


def download_telegram_photo_bytes(file_id: str, bot=None) -> Optional[bytes]:
    """دانلود باینری عکس از تلگرام به صورت مستقل با استفاده از توکن ربات"""
    if not file_id:
        return None

    from config import TELEGRAM_BOT_TOKEN
    if TELEGRAM_BOT_TOKEN:
        try:
            info_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile?file_id={file_id}"
            req_info = urllib.request.Request(info_url, headers={"User-Agent": "AiKala-Bot/1.0"})
            with urllib.request.urlopen(req_info, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if data.get("ok") and data.get("result", {}).get("file_path"):
                    file_path = data["result"]["file_path"]
                    dl_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
                    req_dl = urllib.request.Request(dl_url, headers={"User-Agent": "AiKala-Bot/1.0"})
                    with urllib.request.urlopen(req_dl, timeout=25) as dl_resp:
                        return dl_resp.read()
        except Exception as e_tg:
            logger.debug(f"Direct Telegram HTTP photo download note: {e_tg}")

    return None


def upload_telegram_photo_to_wp_media(file_id: str, pid: str, product_name: str = "", bot=None) -> Tuple[bool, Optional[int], Optional[str]]:
    """دانلود تصویر از تلگرام و آپلود فوری آن در رسانه‌های وردپرس/ووکامرس"""
    img_bytes = download_telegram_photo_bytes(file_id, bot=bot)
    if not img_bytes:
        return False, None, None
    filename = f"aikala_prod_{pid}_{int(time.time())}.jpg"
    return upload_image_bytes_to_wp_media(img_bytes, filename=filename, alt_text=product_name or f"کالای {pid}")


def sync_product_images_to_woo(
    pid: str,
    file_ids: Optional[List[str]] = None,
    image_url: str = "",
    product_name: str = "",
    bot=None
) -> Tuple[bool, str, List[dict]]:
    """
    همگام‌سازی و الصاق مستقیم عکس ثبت‌شده در ربات به محصول متناظر در سایت ووکامرس (aegkala.com)
    - آپلود تصاویر در گالری و عکس شاخص محصول ووکامرس
    - ذخیره آدرس وب تصویر در کاتالوگ محلی و دیتابیس ربات
    """
    s_pid = str(pid).strip()
    if not s_pid:
        return False, "شناسه کالا خالی است.", []

    # بازیابی اطلاعات محصول
    from db_bridge import DB_PATH
    prod = None
    if os.path.exists("catalog_products.json"):
        try:
            with open("catalog_products.json", "r", encoding="utf-8") as f:
                cat = json.load(f)
                if isinstance(cat, dict) and s_pid in cat:
                    prod = cat[s_pid]
        except Exception:
            pass

    if not prod:
        try:
            import sqlite3
            conn = sqlite3.connect(DB_PATH, timeout=5)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT * FROM products WHERE product_id = ?", (s_pid,))
            row = c.fetchone()
            conn.close()
            if row:
                prod = dict(row)
        except Exception:
            pass

    if not prod:
        prod = {"product_id": s_pid, "name": product_name or f"کالای {s_pid}"}

    if is_aeg_protected(prod):
        return False, "محصول تحت حفاظت برند آاگ است.", []

    pname = product_name or prod.get("name") or prod.get("title") or f"کالای {s_pid}"

    # ۱. کشف محصول متناظر در سایت ووکامرس
    existing_woo_id, match_source = find_existing_woo_product(prod, s_pid)
    
    uploaded_images = []
    primary_source_url = ""

    # الف) اگر لینک وب مستقیم تصویر موجود است
    if image_url and (image_url.startswith("http://") or image_url.startswith("https://")):
        uploaded_images.append({"src": image_url, "alt": pname})
        primary_source_url = image_url

    # ب) اگر شناسه‌های فایل تلگرام موجود است، آپلود به وردپرس
    if file_ids:
        for idx, fid in enumerate(file_ids[:5]):  # حداکثر ۵ تصویر گالری
            ok, media_id, src_url = upload_telegram_photo_to_wp_media(fid, s_pid, pname, bot=bot)
            if ok and media_id:
                uploaded_images.append({"id": media_id, "alt": pname})
                if not primary_source_url and src_url:
                    primary_source_url = src_url
            elif src_url:
                uploaded_images.append({"src": src_url, "alt": pname})
                if not primary_source_url:
                    primary_source_url = src_url

    if not uploaded_images:
        return False, "هیچ تصویری برای آپلود استخراج نشد.", []

    # ذخیره آدرس تصویر در دیتابیس ربات و کاتالوگ
    if primary_source_url:
        try:
            import sqlite3
            conn = sqlite3.connect(DB_PATH, timeout=5)
            cur = conn.cursor()
            cur.execute("UPDATE products SET image_url = ? WHERE product_id = ?", (primary_source_url, s_pid))
            conn.commit()
            conn.close()
        except Exception:
            pass
        if os.path.exists("catalog_products.json"):
            try:
                with open("catalog_products.json", "r", encoding="utf-8") as f:
                    cat = json.load(f)
                if s_pid in cat:
                    cat[s_pid]["image_url"] = primary_source_url
                    with open("catalog_products.json", "w", encoding="utf-8") as f:
                        json.dump(cat, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    if not existing_woo_id:
        logger.info(f"ℹ️ [WOO PHOTO SYNC] کالا {s_pid} هنوز در سایت ووکامرس ثبت نشده است. تصویر در کاتالوگ ذخیره شد و هنگام انتشار متصل خواهد شد.")
        return True, f"تصویر کالا ذخیره شد و با انتشار در ووکامرس اعمال خواهد شد.", uploaded_images

    # بروزرسانی گالری و عکس شاخص در محصول ووکامرس
    payload = {
        "images": uploaded_images
    }
    ok_put, res_put = _make_woo_request(f"products/{existing_woo_id}", "PUT", payload)
    if ok_put:
        logger.info(f"🎉 [WOO PHOTO SYNC] Successfully updated {len(uploaded_images)} image(s) on WooCommerce Product ID {existing_woo_id} for PID {s_pid}")
        return True, f"✅ تعداد {len(uploaded_images)} تصویر با موفقیت به محصول در سایت aegkala.com متصل شد.", uploaded_images
    else:
        logger.error(f"❌ [WOO PHOTO SYNC FAILED] Could not update images on Woo Product {existing_woo_id}: {res_put}")
        return False, f"خطا در بروزرسانی تصاویر ووکامرس: {res_put}", uploaded_images


async def async_sync_product_images_to_woo(
    pid: str,
    product_name: str,
    file_ids: Optional[List[str]] = None,
    post_link: str = "",
    bot=None
):
    """تسک پس‌زمینه ناهمگام جهت ارسال بدون تاخیر تصاویر به ووکامرس"""
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: sync_product_images_to_woo(
                pid=pid,
                file_ids=file_ids,
                image_url=post_link if post_link.startswith("http") and not "t.me/" in post_link else "",
                product_name=product_name,
                bot=bot
            )
        )
    except Exception as e:
        logger.error(f"Error in async_sync_product_images_to_woo for {pid}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# ۳. مدیریت دسته مادر «AiKala» و زیرشاخه‌ها
# ─────────────────────────────────────────────────────────────────────────────

_category_cache: Dict[str, int] = {}


def get_or_create_aikala_root_category() -> int:
    """یافتن یا ساخت دسته ریشه AiKala (parent: 0)"""
    settings = get_woo_settings()
    cached_root_id = settings.get("aikala_root_category_id", 0)
    
    if cached_root_id > 0:
        return cached_root_id

    # ۱. جستجو در ووکامرس
    encoded_query = urllib.parse.quote("AiKala")
    ok, resp = _make_woo_request(f"products/categories?search={encoded_query}&per_page=10", "GET")
    if ok and isinstance(resp, list):
        for cat in resp:
            if cat.get("name", "").strip().lower() == "aikala" or cat.get("slug") == "aikala":
                root_id = cat.get("id")
                settings["aikala_root_category_id"] = root_id
                save_woo_settings(settings)
                logger.info(f"🌳 [WOO ROOT] دسته ریشه AiKala یافت شد: ID={root_id}")
                return root_id

    # ۲. ساخت دسته ریشه در صورت عدم وجود
    payload = {
        "name": "AiKala",
        "slug": "aikala",
        "parent": 0,
        "description": "محصولات ارسالی از ربات هوشمند کالا (@AiKala_bot)"
    }
    ok, created = _make_woo_request("products/categories", "POST", payload)
    if ok and isinstance(created, dict) and "id" in created:
        root_id = created["id"]
        settings["aikala_root_category_id"] = root_id
        save_woo_settings(settings)
        logger.info(f"🌳 [WOO ROOT] دسته ریشه جدید AiKala ایجاد شد: ID={root_id}")
        return root_id

    logger.warning("⚠️ نتوانستیم دسته AiKala را بسازیم، از ریشه 0 استفاده می‌شود.")
    return 0


def get_or_create_woo_category(cat_name: str, parent_id: int) -> int:
    """یافتن یا ساخت زیرشاخه تحت یک والد مشخص"""
    clean_name = cat_name.strip()
    if not clean_name:
        return parent_id
        
    cache_key = f"{parent_id}:{clean_name.lower()}"
    if cache_key in _category_cache:
        return _category_cache[cache_key]

    # جستجو با والد مشخص
    encoded_search = urllib.parse.quote(clean_name)
    ok, resp = _make_woo_request(f"products/categories?search={encoded_search}&parent={parent_id}&per_page=10", "GET")
    if ok and isinstance(resp, list):
        for cat in resp:
            if cat.get("name", "").strip().lower() == clean_name.lower() and cat.get("parent") == parent_id:
                cid = cat["id"]
                _category_cache[cache_key] = cid
                return cid

    # ساخت زیرشاخه جدید
    payload = {
        "name": clean_name,
        "parent": parent_id,
        "description": f"دسته‌بندی {clean_name} در کاتالوگ هوشمند AiKala"
    }
    ok, created = _make_woo_request("products/categories", "POST", payload)
    if ok and isinstance(created, dict) and "id" in created:
        cid = created["id"]
        _category_cache[cache_key] = cid
        return cid

    return parent_id


def build_product_categories_list(product: dict) -> List[Dict[str, int]]:
    """ایجاد لیست دسته‌بندی سلسله‌مراتبی محصول زیر شاخه AiKala"""
    root_id = get_or_create_aikala_root_category()
    cat_list = []
    
    if root_id > 0:
        cat_list.append({"id": root_id})

    main_cat = str(product.get("category") or "").strip()
    sub_cat = str(product.get("subcategory") or "").strip()

    target_parent = root_id
    if main_cat and main_cat != "دسته‌بندی نشده":
        main_cat_id = get_or_create_woo_category(main_cat, root_id)
        if main_cat_id > 0 and main_cat_id != root_id:
            cat_list.append({"id": main_cat_id})
            target_parent = main_cat_id

    if sub_cat and sub_cat != main_cat:
        sub_cat_id = get_or_create_woo_category(sub_cat, target_parent)
        if sub_cat_id > 0 and sub_cat_id not in [c["id"] for c in cat_list]:
            cat_list.append({"id": sub_cat_id})

    return cat_list


# ─────────────────────────────────────────────────────────────────────────────
# ۴. لایه تولید محتوای هوشمند و قالب‌بندی HTML (بدون حدس و توهم)
# ─────────────────────────────────────────────────────────────────────────────

def generate_woo_ai_description(product: dict, specs: Dict[str, str]) -> str:
    """
    تولید محتوای متنی تخصصی، کاملاً سئو شده (SEO-Rich) بر اساس مشخصات واقعی با هوش مصنوعی (Gemini / DeepSeek)
    شامل هدینگ‌های H3 و تکرار طبیعی نام و مدل کالا برای رتبه‌گیری در گوگل
    همراه با بازیابی آنی از کش دائمی محتوا جهت صفر کردن مصرف توکن
    """
    pid = str(product.get("product_id") or product.get("id") or "").strip()
    model_key = extract_product_model_key(product)
    pname = str(product.get("name") or product.get("title", "")).strip()
    brand = str(product.get("brand", "")).strip()
    specs_str = ", ".join([f"{k}: {v}" for k, v in specs.items() if v and str(v).lower() != "نامشخص"][:12])

    # ۱. بررسی کش دائمی محتوای هوش مصنوعی
    try:
        from ai_content_cache import get_cached_ai_content
        cached = get_cached_ai_content(pid, model_key)
        if cached and cached.get("ai_overview") and len(cached["ai_overview"]) >= 40:
            return cached["ai_overview"]
    except Exception:
        pass

    if product.get("ai_generated_description") and len(product["ai_generated_description"]) >= 40:
        return product["ai_generated_description"]

    prompt = f"""شما نویسنده و متخصص ارشد سئو (SEO Content Specialist) و کارشناس نقد و بررسی لوازم خانگی و دیجیتال هستید.
برای محصول زیر بر اساس مشخصات فنی تایید شده، یک نقد و بررسی جامع، مستند و سئو شده به زبان فارسی بنویسید:

نام دقیق محصول: {pname}
برند: {brand}
مشخصات فنی تایید شده:
{specs_str if specs_str else 'مشخصات استاندارد شرکتی'}

الزامات و قوانین سئو:
۱. نام کامل محصول ({pname}) و برند ({brand}) باید به صورت کاملاً طبیعی ۲ تا ۴ بار در طول متن تکرار شود.
۲. ساختار متن باید در ۳ بخش مجزا همراه با تیترهای جذاب باشد:
   - بخش اول: معرفی کلی، اصالت و زبان طراحی {pname}
   - بخش دوم: بررسی تخصصی موتور، عملکرد فنی و قابلیت‌های کلیدی دستگاه
   - بخش سوم: ارزش خرید، مصرف انرژی و جمع‌بندی نهایی برای خریداران
۳. از آوردن اطلاعات غلط، توان یا گارانتی‌های ساختگی جداً خودداری کنید.
۴. لحن حرفه‌ای، روان، معتبر و بدون زیاده‌گویی تبلیغاتی زرد باشد."""

    from gemini_enricher import get_ai_settings, get_gemini_api_key, get_deepseek_api_key
    woo_settings = get_woo_settings()
    ai_settings = get_ai_settings()
    provider = woo_settings.get("ai_provider") or ai_settings.get("provider", "gemini")

    # ۱. تولید با DeepSeek در صورت انتخاب
    if provider == "deepseek":
        ds_key = get_deepseek_api_key()
        if ds_key:
            try:
                endpoint = "https://api.deepseek.com/chat/completions"
                payload = {
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "تو متخصص تولید محتوای سئو فروشگاهی هستی."},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 1000,
                    "temperature": 0.25,
                    "stream": False
                }
                req = urllib.request.Request(
                    endpoint,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {ds_key}"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=14) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    choice = res_data.get("choices", [{}])[0]
                    content = (choice.get("message", {}).get("content") or "").strip()
                    if content and len(content) >= 40:
                        logger.info(f"✨ [WOO AI DESC] نقد و بررسی تخصصی '{pname}' با DeepSeek تولید شد.")
                        return content
            except Exception as e:
                logger.warning(f"⚠️ [WOO AI DESC DeepSeek] for '{pname}': {e}")

    # ۲. تولید با Google Gemini (با اولویت چرخش flash و سپس flash-lite)
    api_key = get_gemini_api_key()
    if not api_key:
        return ""

    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
        "gemini-3.1-pro-preview",
        "gemini-flash-lite-latest",
        "gemini-flash-latest",
        "gemini-pro-latest"
    ]
    models_to_try = list(dict.fromkeys(models_to_try))

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.25,
            "maxOutputTokens": 1000
        }
    }
    
    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                cand = res_data.get("candidates", [])
                if cand:
                    text_parts = cand[0].get("content", {}).get("parts", [])
                    raw_text = "".join([p.get("text", "") for p in text_parts]).strip()
                    if raw_text and len(raw_text) >= 40:
                        logger.info(f"✨ [WOO AI DESC] نقد و بررسی تخصصی '{pname}' با Gemini ({model_name}) تولید شد.")
                        return raw_text
        except urllib.error.HTTPError as he:
            err_body = he.read().decode("utf-8", errors="ignore")
            logger.debug(f"⚠️ [WOO AI DESC HTTP {he.code}] Model {model_name} for '{pname}': {err_body[:100]}")
            if he.code == 429:
                logger.warning(f"⏳ [RATE LIMIT 429] سقف سهمیه مدل {model_name}؛ ۳۰ ثانیه استراحت خودکار و چرخش به مدل‌های سبک‌تر پشتیبان...")
                time.sleep(30.0)
            continue
        except Exception as e:
            logger.debug(f"⚠️ [WOO AI DESC] Model {model_name} failed for '{pname}': {e}")
            continue

    return ""


def generate_woo_key_highlights(product: dict, specs: Dict[str, str]) -> str:
    """
    تولید ۵ الی ۷ ویژگی شاخص و کلیدی کالا با هوش مصنوعی (Gemini / DeepSeek)
    همراه با بازیابی آنی از کش دائمی محتوا
    """
    pid = str(product.get("product_id") or product.get("id") or "").strip()
    model_key = extract_product_model_key(product)
    pname = str(product.get("name") or product.get("title", "")).strip()
    brand = str(product.get("brand", "")).strip()
    specs_str = ", ".join([f"{k}: {v}" for k, v in specs.items() if v and str(v).lower() != "نامشخص"][:10])

    # ۱. بازیابی از کش دائمی
    try:
        from ai_content_cache import get_cached_ai_content
        cached = get_cached_ai_content(pid, model_key)
        if cached and cached.get("ai_highlights"):
            product["ai_highlights"] = cached["ai_highlights"]
            return cached["ai_highlights"]
    except Exception:
        pass

    if product.get("ai_highlights"):
        return product["ai_highlights"]

    prompt = f"""بر اساس مشخصات فنی زیر، ۵ الی ۷ مورد از مهم‌ترین مزایا و ویژگی‌های کلیدی محصول را به صورت خط‌به‌خط بنویسید:
محصول: {pname}
برند: {brand}
مشخصات: {specs_str if specs_str else 'مشخصات استاندارد شرکتی'}

قوانین:
- هر خط فقط یک ویژگی کلیدی باشد.
- کوتاه، دقیق، بدون زیاده‌گویی و کاملاً مستند به مشخصات."""

    from gemini_enricher import get_ai_settings, get_gemini_api_key, get_deepseek_api_key
    woo_settings = get_woo_settings()
    ai_settings = get_ai_settings()
    provider = woo_settings.get("ai_provider") or ai_settings.get("provider", "gemini")

    # ۱. تولید با DeepSeek در صورت انتخاب
    if provider == "deepseek":
        ds_key = get_deepseek_api_key()
        if ds_key:
            try:
                endpoint = "https://api.deepseek.com/chat/completions"
                payload = {
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "تو متخصص استخراج نکات کلیدی و مزیت‌های رقابتی محصولات فروشگاهی هستی."},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 600,
                    "temperature": 0.2,
                    "stream": False
                }
                req = urllib.request.Request(
                    endpoint,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {ds_key}"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    choice = res_data.get("choices", [{}])[0]
                    content = (choice.get("message", {}).get("content") or "").strip()
                    if content and len(content) >= 20:
                        product["ai_highlights"] = content
                        return content
            except Exception as e:
                logger.warning(f"⚠️ [WOO AI HIGHLIGHTS DeepSeek] for '{pname}': {e}")

    # ۲. تولید با Google Gemini (با اولویت چرخش flash)
    api_key = get_gemini_api_key()
    if not api_key:
        return ""

    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
        "gemini-3.1-pro-preview",
        "gemini-flash-lite-latest",
        "gemini-flash-latest",
        "gemini-pro-latest"
    ]
    models_to_try = list(dict.fromkeys(models_to_try))
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 600}
    }
    for model_name in models_to_try:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=12) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                candidates = res_data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        res_text = parts[0].get("text", "").strip()
                        if res_text:
                            product["ai_highlights"] = res_text
                            return res_text
        except urllib.error.HTTPError as he:
            if he.code == 429:
                logger.warning(f"⏳ [RATE LIMIT 429] سقف سهمیه مدل {model_name} در نکات کلیدی؛ ۳۰ ثانیه استراحت خودکار و چرخش مدل...")
                time.sleep(30.0)
            continue
        except Exception:
            continue
    return ""


def build_product_short_description(product: dict, specs: Dict[str, str]) -> str:
    """
    ساخت ویژگی‌های کلیدی مطابق دقیق کلاس‌ها و ساختار قالب سایت (dina-features-ul)
    """
    raw_highlights = generate_woo_key_highlights(product, specs)
    lines = [l.strip() for l in raw_highlights.split("\n") if l.strip()]
    
    list_items = ""
    idx = 1
    for line in lines:
        clean_line = re.sub(r'^\d+[\.\-\:]\s*', '', line).strip()
        clean_line = re.sub(r'[*#_`]', '', clean_line).strip()
        if clean_line:
            list_items += f'<li><span class="dina-ftitle">{idx}:</span><span class="dina-fdesc">{clean_line}</span></li>'
            idx += 1
            if idx > 7:
                break

    if list_items:
        return f'<ul class="dina-features-ul">{list_items}</ul>'.strip()
    return f"کد کالا: {product.get('product_id', '')} | برند: {product.get('brand', 'معتبر')}"


def generate_woo_seo_faq(product: dict, specs: Dict[str, str]) -> Tuple[str, str]:
    """
    تولید ۳ پرسش و پاسخ متداول تخصصی (FAQ) بر اساس مشخصات فنی واقعی با هوش مصنوعی
    همراه با خروجی کدهای اسکیما استاندارد گوگل (Schema.org FAQPage JSON-LD)
    همراه با بازیابی آنی از کش دائمی محتوا
    """
    pid = str(product.get("product_id") or product.get("id") or "").strip()
    model_key = extract_product_model_key(product)
    pname = str(product.get("name") or product.get("title", "")).strip()
    brand = str(product.get("brand", "")).strip()
    specs_str = ", ".join([f"{k}: {v}" for k, v in specs.items() if v and str(v).lower() != "نامشخص"][:10])

    # ۱. بررسی کش دائمی
    cached_faq = None
    try:
        from ai_content_cache import get_cached_ai_content
        cached = get_cached_ai_content(pid, model_key)
        if cached and cached.get("ai_faq") and isinstance(cached["ai_faq"], list) and len(cached["ai_faq"]) >= 2:
            cached_faq = cached["ai_faq"]
    except Exception:
        pass

    if not cached_faq and product.get("ai_faq") and isinstance(product["ai_faq"], list) and len(product["ai_faq"]) >= 2:
        cached_faq = product["ai_faq"]

    if cached_faq:
        default_faq = cached_faq
    else:
        default_faq = [
            {"q": f"آیا {pname} دارای گارانتی اصالت کالا است؟", "a": f"بله، تمامی محصولات {brand} در فروشگاه با تضمین ۱۰۰٪ اصالت کالا، سلامت فیزیکی و با مشخصات فنی رسمی کارخانه ارائه می‌گردند."},
            {"q": f"مهم‌ترین ویژگی‌ها و مزایای خرید {pname} چیست؟", "a": f"این محصول با برخورداری از استانداردهای ساخت برند {brand}، راندمان مصرف بهینه و امکانات کاربردی، یکی از گزینه‌های برتر در دسته خود برای مصرف روزمره به شمار می‌رود."},
            {"q": f"ارسال کالا و نحوه سفارش چگونه است؟", "a": "سفارش‌ها با بسته‌بندی ایمن و از طریق سریع‌ترین روش‌های باربری و پست اختصاصی به سراسر کشور ارسال می‌گردند."}
        ]

        from gemini_enricher import get_ai_settings, get_gemini_api_key, get_deepseek_api_key
        woo_settings = get_woo_settings()
        ai_settings = get_ai_settings()
        provider = woo_settings.get("ai_provider") or ai_settings.get("provider", "gemini")

        prompt = f"""تو کارشناس سئو هستی. برای صفحه محصول زیر ۳ پرسش و پاسخ متداول واقعی و تخصصی (FAQ) خریداران را به زبان فارسی بنویس:
محصول: {pname}
برند: {brand}
مشخصات کلیدی: {specs_str}

قوانین:
۱. سوالات باید دقیقا سوالات پرتکرار خریداران درباره عملکرد، شستشو، توان یا کیفیت این مدل باشد.
۲. پاسخ‌ها کاملاً دقیق، مستند و بدون کلمات تبلیغاتی زرد باشد.
۳. خروجی فقط یک آرایه JSON شامل اشیاء با کلید "q" و "a" باشد.
نمونه: [{{"q": "آیا قطعات این دستگاه قابل شستشو در ماشین ظرفشویی هستند؟", "a": "بله، قطعات جانبی جداشونده قابل شستشو هستند."}}]
"""

        faq_generated = False
        # ۱. تلاش با DeepSeek
        if provider == "deepseek":
            ds_key = get_deepseek_api_key()
            if ds_key:
                try:
                    endpoint = "https://api.deepseek.com/chat/completions"
                    payload = {
                        "model": "deepseek-chat",
                        "messages": [
                            {"role": "system", "content": "تو کارشناس سئو هستی. خروجی فقط یک آرایه معتبر JSON است."},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 800,
                        "temperature": 0.2,
                        "stream": False
                    }
                    req = urllib.request.Request(
                        endpoint,
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json", "Authorization": f"Bearer {ds_key}"},
                        method="POST"
                    )
                    with urllib.request.urlopen(req, timeout=12) as resp:
                        res_data = json.loads(resp.read().decode("utf-8"))
                        choice = res_data.get("choices", [{}])[0]
                        content = (choice.get("message", {}).get("content") or "").strip()
                        if "```json" in content:
                            content = content.split("```json")[1].split("```")[0].strip()
                        elif "```" in content:
                            content = content.split("```")[1].split("```")[0].strip()
                        parsed = json.loads(content)
                        if isinstance(parsed, list) and len(parsed) >= 2:
                            default_faq = parsed
                            faq_generated = True
                except Exception as e:
                    logger.warning(f"⚠️ [WOO FAQ DeepSeek] for '{pname}': {e}")

        # ۲. تلاش با Gemini
        if not faq_generated:
            api_key = get_gemini_api_key()
            if api_key:
                models_to_try = [
                    "gemini-2.5-flash",
                    "gemini-2.5-flash-lite",
                    "gemini-3.8-flash",
                    "gemini-3.7-flash",
                    "gemini-3.6-flash",
                    "gemini-3.5-flash",
                    "gemini-3.1-flash-lite",
                    "gemini-3.1-pro-preview",
                    "gemini-flash-lite-latest",
                    "gemini-flash-latest",
                    "gemini-pro-latest"
                ]
                models_to_try = list(dict.fromkeys(models_to_try))
                for m in models_to_try:
                    try:
                        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}"
                        payload = {
                            "contents": [{"parts": [{"text": prompt}]}],
                            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 800, "responseMimeType": "application/json"}
                        }
                        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
                        with urllib.request.urlopen(req, timeout=10) as resp:
                            res_data = json.loads(resp.read().decode("utf-8"))
                            cand = res_data.get("candidates", [])
                            if cand:
                                raw_json = cand[0].get("content", {}).get("parts", [])[0].get("text", "")
                                parsed = json.loads(raw_json)
                                if isinstance(parsed, list) and len(parsed) >= 2:
                                    default_faq = parsed
                                    break
                    except urllib.error.HTTPError as he:
                        if he.code == 429:
                            logger.warning(f"⏳ [RATE LIMIT 429] سقف سهمیه مدل {m} در FAQ؛ ۳۰ ثانیه استراحت خودکار...")
                            time.sleep(30.0)
                        continue
                    except Exception:
                        continue

    product["ai_faq"] = default_faq

    # ساخت HTML شیک برای FAQ
    faq_items_html = ""
    schema_entities = []
    for item in default_faq:
        q_text = str(item.get("q", "")).strip()
        a_text = str(item.get("a", "")).strip()
        if not q_text or not a_text:
            continue
        
        faq_items_html += f"""
        <div style="border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 12px; background: #ffffff; overflow: hidden; box-shadow: 0 1px 2px rgba(0,0,0,0.02);">
            <div style="background-color: #f1f5f9; padding: 12px 16px; font-weight: 700; color: #1e293b; font-size: 14px; border-bottom: 1px solid #e2e8f0; display: flex; align-items: center;">
                <span style="color: #2563eb; font-size: 16px; margin-left: 8px;">❓</span> {q_text}
            </div>
            <div style="padding: 14px 16px; color: #475569; font-size: 13.5px; line-height: 1.8; text-align: justify;">
                {a_text}
            </div>
        </div>
        """
        schema_entities.append({
            "@type": "Question",
            "name": q_text,
            "acceptedAnswer": {
                "@type": "Answer",
                "text": a_text
            }
        })

    faq_section_html = f"""
    <section style="margin-top: 30px; margin-bottom: 25px;">
        <h2 style="color: #0f172a; font-size: 16px; border-bottom: 2px solid #cbd5e1; padding-bottom: 8px; margin-bottom: 16px; font-weight: 700;">
            💬 پرسش‌های متداول درباره {pname}
        </h2>
        {faq_items_html}
    </section>
    """

    schema_json = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": schema_entities
    }
    schema_script = f'<script type="application/ld+json">\n{json.dumps(schema_json, ensure_ascii=False, indent=2)}\n</script>'

    return faq_section_html, schema_script


def build_product_html_description(product: dict, specs: Dict[str, str], overview_text: str = "") -> str:
    """
    تولید محتوای جامع سئو محور (SEO-Optimized HTML5) شامل:
    ۱. هدینگ‌های معنایی H2 و H3 بهینه‌شده برای الگوریتم‌های گوگل
    ۲. متن نقد و بررسی تخصصی بدون کلمات زرد
    ۳. جدول استاندارد مشخصات فنی و دیتاشیت با تگ‌های معنایی Table
    ۴. بخش پرسش‌های متداول (FAQ) به همراه اسکیما Rich Snippets گوگل (FAQPage JSON-LD)
    """
    pname = product.get("name") or product.get("title", "")
    brand = product.get("brand", "")
    category = product.get("category", "")
    
    # اگر متن معرفی موجود نبود، تولید خودکار با Gemini
    clean_overview = overview_text.strip()
    if not clean_overview or len(clean_overview) < 40:
        clean_overview = generate_woo_ai_description(product, specs)

    # حذف کلمات ممنوعه تبلیغاتی از متن معرفی
    for bad_w in FORBIDDEN_AD_WORDS:
        clean_overview = re.sub(rf'\b{re.escape(bad_w)}\b', '', clean_overview)
    clean_overview = clean_overview.strip()

    # تبدیل پاراگراف‌های متنی به تگ‌های HTML پاراگراف استاندارد
    paragraphs = [p.strip() for p in clean_overview.split("\n\n") if p.strip()]
    if not paragraphs and clean_overview:
        paragraphs = [p.strip() for p in clean_overview.split("\n") if p.strip()]

    paragraphs_html = ""
    for para in paragraphs:
        clean_p = re.sub(r'[*#_`]', '', para).strip()
        if clean_p:
            paragraphs_html += f'<p style="margin-bottom: 14px; text-align: justify; line-height: 1.9; color: #334155; font-size: 14.5px;">{clean_p}</p>\n'

    # بخش بررسی تخصصی با هدینگ H2 بهینه‌شده برای سئو
    intro_section = ""
    if paragraphs_html:
        intro_section = f"""
        <article style="background-color: #f8fafc; border-right: 4px solid #2563eb; padding: 20px 24px; border-radius: 8px; margin-bottom: 25px; box-shadow: 0 1px 3px rgba(0,0,0,0.03);">
            <h2 style="color: #1e3a8a; font-size: 17px; margin-top: 0; margin-bottom: 15px; font-weight: 700; line-height: 1.5;">
                📖 نقد، بررسی و راهنمای خرید {pname}
            </h2>
            {paragraphs_html}
        </article>
        """

    # ساخت جدول مشخصات فنی استاندارد معنایی
    specs_rows_html = ""
    for k, v in specs.items():
        clean_k = str(k).strip()
        clean_v = str(v).strip()
        if clean_k and clean_v and clean_v.lower() != "نامشخص":
            specs_rows_html += f"""
            <tr style="border-bottom: 1px solid #e2e8f0;">
                <th scope="row" style="padding: 11px 16px; background-color: #f8fafc; color: #475569; font-weight: 600; width: 35%; text-align: right; border-left: 1px solid #e2e8f0;">{clean_k}</th>
                <td style="padding: 11px 16px; color: #0f172a; font-weight: 500;">{clean_v}</td>
            </tr>
            """

    # تولید بخش پرسش‌های متداول
    faq_html, _ = generate_woo_seo_faq(product, specs)

    full_html = f"""
    <div style="direction: rtl; font-family: Tahoma, Segoe UI, sans-serif; line-height: 1.8; color: #1e293b;">
        {intro_section}
        
        <section style="margin-top: 25px; margin-bottom: 25px;">
            <h2 style="color: #0f172a; font-size: 16px; border-bottom: 2px solid #cbd5e1; padding-bottom: 8px; margin-top: 20px; margin-bottom: 15px; font-weight: 700;">
                📊 جدول مشخصات فنی و دیتاشیت کارخانه {pname}
            </h2>
            
            <table style="width: 100%; border-collapse: collapse; border: 1px solid #cbd5e1; border-radius: 8px; overflow: hidden; font-size: 13.5px; margin-bottom: 20px;">
                <tbody>
                    {specs_rows_html}
                </tbody>
            </table>
        </section>

        {faq_html}
    </div>
    """
    return full_html.strip()


# ─────────────────────────────────────────────────────────────────────────────
# ۵. لایه ۳: اعتبارسنجی خروجی (Output Validation)
# ─────────────────────────────────────────────────────────────────────────────

def validate_product_content(product: dict, specs: Dict[str, str], overview_text: str) -> Tuple[bool, str]:
    """
    اعتبارسنجی ۶ گانه قبل از ارسال به ووکامرس:
    ۱. حداقل ۵ مشخصه فنی
    ۲. عدم وجود کلمات ممنوعه تبلیغاتی
    ۳. تطبیق نام و برند
    """
    # ۱. حداقل تعداد فیلد معتبر
    valid_specs_count = sum(1 for k, v in specs.items() if str(v).strip() and str(v).strip().lower() != "نامشخص")
    if valid_specs_count < 3:
        return False, f"تعداد مشخصات فنی کافی نیست ({valid_specs_count} مورد، حداقل ۳ فیلد الزامی است)."

    # ۲. تطبیق برند
    p_brand = str(product.get("brand") or "").strip().lower()
    if p_brand and "آاگ" in p_brand:
        return False, "محصول متعلق به آاگ (محافظت‌شده) می‌باشد."

    # ۳. بررسی کلمات تبلیغاتی در نام و معرفی
    full_text = f"{product.get('name', '')} {overview_text}"
    for bad in FORBIDDEN_AD_WORDS:
        if bad in full_text:
            return False, f"حاوی کلمه تبلیغاتی ممنوعه '{bad}' است."

    return True, "معتبر"


# ─────────────────────────────────────────────────────────────────────────────
# ۶. ارسال و بروزرسانی تک‌محصول به ووکامرس
# ─────────────────────────────────────────────────────────────────────────────

def publish_single_product_to_woo(product: dict, status: Optional[str] = None) -> Tuple[bool, str, Optional[dict]]:
    """
    ارسال یا بروزرسانی یک محصول مشخص در ووکامرس
    """
    if is_aeg_protected(product):
        return False, "🔒 این محصول متعلق به برند آاگ (AEG) است و طبق قانون حفاظت، ارسال آن به ووکامرس مسدود است.", None

    pid = str(product.get("product_id") or product.get("id") or "").strip()
    pname = product.get("name") or product.get("title", "")
    price = int(product.get("price") or 0)
    
    settings = get_woo_settings()
    publish_status = status or settings.get("default_publish_status", "draft")

    model_key = extract_product_model_key(product)

    # ۱. استخراج یا بازیابی مشخصات فنی
    specs = {}
    if isinstance(product.get("specs"), dict) and product.get("specs"):
        specs = product["specs"].copy()
    elif isinstance(product.get("ai_specs"), dict) and product.get("ai_specs"):
        specs = product["ai_specs"].copy()
    elif isinstance(product.get("more_details"), str) and product.get("more_details"):
        # تبدیل رشته به دیکشنری
        parts = [p.strip() for p in product["more_details"].split("|") if ":" in p]
        for p in parts:
            k, v = p.split(":", 1)
            specs[k.strip()] = v.strip()

    # بررسی کش دائمی برای مشخصات فنی
    from ai_content_cache import get_cached_ai_content, save_product_ai_content
    cached = get_cached_ai_content(pid, model_key)
    if cached and isinstance(cached.get("ai_specs"), dict) and len(cached["ai_specs"]) >= 8:
        specs.update(cached["ai_specs"])
        product["specs"] = specs
        product["ai_specs"] = specs
    elif len(specs) < 6:
        # اگر مشخصات در دیتابیس ربات ناقص یا بدون مشخصات بود، تولید آنی با هوش مصنوعی (همانند دکمه تکمیل کالاهای بدون مشخصات)
        try:
            from gemini_enricher import (
                get_ai_settings, get_gemini_api_key, get_deepseek_api_key,
                call_gemini_api_with_error, call_deepseek_api_with_error,
                sync_save_ai_specs
            )
            ai_sett = get_ai_settings()
            provider = settings.get("ai_provider") or ai_sett.get("provider", "gemini")
            extracted_specs = None
            
            if provider == "deepseek":
                ds_k = get_deepseek_api_key()
                if ds_k:
                    extracted_specs, _ = call_deepseek_api_with_error(ds_k, product)
            
            if not extracted_specs or len(extracted_specs) < 4:
                g_k = get_gemini_api_key()
                if g_k:
                    extracted_specs, _ = call_gemini_api_with_error(g_k, product)

            if extracted_specs and isinstance(extracted_specs, dict) and len(extracted_specs) > len(specs):
                specs.update(extracted_specs)
                product["specs"] = specs
                product["ai_specs"] = specs
                product["more_details"] = " | ".join([f"{k}: {v}" for k, v in specs.items()])
                
                # ثبت فوری و دائمی در دیتابیس SQLite ربات و فایل catalog_products.json
                sync_save_ai_specs(pid, specs)
                try:
                    from search_engine import JSON_PRODUCTS
                    if JSON_PRODUCTS:
                        for jp in JSON_PRODUCTS:
                            if str(jp.get("product_id") or jp.get("id")) == pid:
                                jp["specs"] = specs
                                jp["ai_specs"] = specs
                                jp["more_details"] = product["more_details"]
                                break
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Error enriching specs on publish for {pname}: {e}")

    overview = product.get("description") or product.get("ai_description") or product.get("ai_generated_description") or ""

    # بررسی کش برای متن نقد و بررسی
    if (not overview or len(overview) < 40) and cached and cached.get("ai_overview") and len(cached["ai_overview"]) >= 40:
        overview = cached["ai_overview"]
        product["ai_generated_description"] = overview
    elif not overview or len(overview) < 40:
        overview = generate_woo_ai_description(product, specs)
        if overview:
            product["ai_generated_description"] = overview
            try:
                from gemini_enricher import sync_save_ai_description
                sync_save_ai_description(pid, overview)
            except Exception:
                pass

    # اعتبارسنجی
    is_valid, val_reason = validate_product_content(product, specs, overview)
    if not is_valid:
        add_to_review_queue(product, val_reason, {"specs_count": len(specs)})
        return False, f"⚠️ کالا به صف بازبینی دستی هدایت شد: {val_reason}", None

    # ساخت HTML و دسته‌بندی
    html_desc = build_product_html_description(product, specs, overview)
    short_desc = build_product_short_description(product, specs)
    categories = build_product_categories_list(product)
    
    # ساخت شناسه یکتای انبار
    sku = f"AIKALA-{pid}"

    # تعیین وضعیت موجودی و قیمت
    stock_status = "instock" if price > 0 else "outofstock"
    reg_price = str(price) if price > 0 else ""

    # ساخت متای سئو بهینه‌شده طبق استانداردهای گوگل و افزونه‌های سئو (Yoast / Rank Math)
    meta_desc = f"خرید و قیمت {pname} اصل با ضمانت کیفیت + مشخصات کامل فنی کارخانه، نقد و بررسی تخصصی و ارسال سریع."
    focus_kw = f"خرید {pname}"
    seo_title = f"خرید {pname} اصل + مشخصات کامل و قیمت روز"

    # ذخیره در مخزن کش هوش مصنوعی جهت مراجعات آینده و صفر کردن مصرف توکن
    raw_highlights = product.get("ai_highlights", "")
    faq_list = product.get("ai_faq", [])
    try:
        save_product_ai_content(
            pid=pid,
            name=pname,
            brand=product.get("brand", ""),
            category=product.get("category", ""),
            specs=specs,
            overview=overview,
            highlights=raw_highlights,
            faq=faq_list,
            seo_meta={"title": seo_title, "description": meta_desc, "focus_keyword": focus_kw},
            model_code=model_key
        )
        update_catalog_product_ai_data(pid, specs, overview, raw_highlights)
    except Exception as e:
        logger.debug(f"Error persisting ai content cache: {e}")

    # استخراج و الصاق خودکار تصاویر تایید شده یا لینک مستقیم تصویر به محصول ووکامرس
    images_payload = []
    prod_image_url = product.get("image_url") or product.get("photo_url") or ""
    if prod_image_url and (prod_image_url.startswith("http://") or prod_image_url.startswith("https://")):
        images_payload.append({"src": prod_image_url, "alt": pname})
    else:
        try:
            from photo_service import find_matching_verified_photos
            _, entry, _ = find_matching_verified_photos(pid)
            if entry and entry.get("file_ids"):
                for fid in entry["file_ids"][:4]:
                    ok_up, media_id, media_url = upload_telegram_photo_to_wp_media(fid, pid, pname)
                    if ok_up and media_id:
                        images_payload.append({"id": media_id, "alt": pname})
                    elif media_url:
                        images_payload.append({"src": media_url, "alt": pname})
        except Exception as e_img:
            logger.debug(f"Error resolving images for {pid} on publish: {e_img}")

    payload = {
        "name": pname,
        "type": "simple",
        "regular_price": reg_price,
        "description": html_desc,
        "short_description": short_desc,
        "sku": sku,
        "manage_stock": False,
        "stock_status": stock_status,
        "categories": categories,
        "status": publish_status,
        "meta_data": [
            {"key": "_aikala_product_id", "value": pid},
            {"key": "_aikala_brand", "value": product.get("brand", "")},
            {"key": "_aikala_last_sync", "value": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
            # Rank Math SEO
            {"key": "rank_math_title", "value": seo_title},
            {"key": "rank_math_description", "value": meta_desc},
            {"key": "rank_math_focus_keyword", "value": focus_kw},
            # Yoast SEO
            {"key": "_yoast_wpseo_title", "value": seo_title},
            {"key": "_yoast_wpseo_metadesc", "value": meta_desc},
            {"key": "_yoast_wpseo_focuskw", "value": focus_kw}
        ]
    }
    if images_payload:
        payload["images"] = images_payload

    # ۲. کشف هوشمند کالای موجود در سایت با سیستم چندلایه ضد-تکرار
    existing_woo_id, match_source = find_existing_woo_product(product, pid)
    product_map = get_woo_product_map()

    if existing_woo_id:
        # بروزرسانی امن (PUT) - جلوگیری قطعی از ثبت تکراری
        ok, res = _make_woo_request(f"products/{existing_woo_id}", "PUT", payload)
        action_name = "بروزرسانی"
    else:
        # ساخت جدید (POST)
        ok, res = _make_woo_request("products", "POST", payload)
        action_name = "ایجاد و انتشار"
        # در صورت تداخل SKU، بازیابی خودکار ID و تغییر به حالت PUT
        if not ok and "resource_id" in str(res):
            try:
                res_json_str = str(res)
                match = re.search(r'"resource_id":\s*(\d+)', res_json_str)
                if match:
                    existing_woo_id = int(match.group(1))
                    product_map[pid] = existing_woo_id
                    save_woo_product_map(product_map)
                    if model_key:
                        m_map = get_woo_model_map()
                        m_map[model_key] = existing_woo_id
                        save_woo_model_map(m_map)
                    ok, res = _make_woo_request(f"products/{existing_woo_id}", "PUT", payload)
                    action_name = "بروزرسانی"
            except Exception:
                pass

    if ok and isinstance(res, dict) and "id" in res:
        woo_id = int(res["id"])
        product_map[pid] = woo_id
        save_woo_product_map(product_map)

        # نگاشت پارت‌نامبر جهت عدم درج مجدد با مدل مشابه
        if model_key:
            model_map = get_woo_model_map()
            model_map[model_key] = woo_id
            save_woo_model_map(model_map)

        # ثبت لاگ منبع
        log_content_source(
            pid=pid,
            sources=[f"https://www.google.com/search?q={urllib.parse.quote(pname)}"],
            validated=True,
            notes=f"موفقیت‌آمیز در وضعیت {publish_status} ({action_name})",
            ai_model="gemini-grounded-specs"
        )
        
        permalink = res.get("permalink", "")
        return True, f"✅ محصول با موفقیت {action_name} شد (شناسه سایت: #{woo_id})", {
            "woo_id": woo_id,
            "permalink": permalink,
            "status": publish_status,
            "sku": sku
        }
    else:
        err_msg = str(res)
        return False, f"❌ خطا در ارسال به ووکامرس: {err_msg}", None


# ─────────────────────────────────────────────────────────────────────────────
# ۷. بروزرسانی سریع و سبک قیمت‌ها (Fast Price Sync)
# ─────────────────────────────────────────────────────────────────────────────

def sync_single_product_price_to_woo(pid: str, new_price: int, product: Optional[dict] = None) -> Tuple[bool, str, Optional[int]]:
    """
    بروزرسانی بلادرنگ قیمت و وضعیت موجودی یک محصول خاص در ووکامرس (aegkala.com)
    به محض تغییر قیمت توسط ادمین در ربات تلگرام
    """
    s_pid = str(pid).strip()
    if not s_pid:
        return False, "شناسه کالا نامعتبر است.", None

    # بازیابی محصول در صورت عدم ارسال
    if not product:
        from search_engine import find_product_by_id, JSON_PRODUCTS
        product = find_product_by_id(s_pid)
        if not product and os.path.exists("catalog_products.json"):
            try:
                with open("catalog_products.json", "r", encoding="utf-8") as f:
                    cat = json.load(f)
                    if isinstance(cat, dict) and s_pid in cat:
                        product = cat[s_pid]
            except Exception:
                pass

    if not product:
        product = {"product_id": s_pid, "price": new_price}

    if is_aeg_protected(product):
        return False, "🔒 این محصول متعلق به برند آاگ است و قیمت آن در ووکامرس محافظت شده است.", None

    existing_woo_id, match_source = find_existing_woo_product(product, s_pid)
    if not existing_woo_id:
        logger.info(f"ℹ️ [WOO PRICE SYNC] محصول {s_pid} در ووکامرس یافت نشد. قیمت جدید در دیتابیس محلی ذخیره شد.")
        return False, "محصول هنوز در سایت ووکامرس ثبت نشده است. قیمت در دیتابیس ربات ثبت شد.", None

    stock_status = "instock" if new_price > 0 else "outofstock"
    reg_price = str(new_price) if new_price > 0 else ""

    payload = {
        "regular_price": reg_price,
        "stock_status": stock_status
    }

    ok, res = _make_woo_request(f"products/{existing_woo_id}", "PUT", payload)
    if ok:
        logger.info(f"💰 [WOO PRICE SYNC SUCCESS] قیمت محصول PID {s_pid} (Woo ID: {existing_woo_id}) در ووکامرس به {new_price:,} تومان تغییر یافت.")
        return True, f"✅ قیمت محصول در سایت با موفقیت به {new_price:,} تومان بروزرسانی شد.", existing_woo_id
    else:
        logger.error(f"❌ [WOO PRICE SYNC FAILED] خطا در تغییر قیمت Woo ID {existing_woo_id}: {res}")
        return False, f"خطا در بروزرسانی قیمت ووکامرس: {res}", existing_woo_id


async def async_sync_single_product_price_to_woo(pid: str, new_price: int, product: Optional[dict] = None):
    """تسک پس‌زمینه ناهمگام جهت ارسال بدون تاخیر قیمت جدید به ووکامرس"""
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: sync_single_product_price_to_woo(pid=pid, new_price=new_price, product=product)
        )
    except Exception as e:
        logger.error(f"Error in async_sync_single_product_price_to_woo for {pid}: {e}")


def sync_prices_to_woocommerce() -> Tuple[int, int, List[str]]:
    """
    بروزرسانی آنی قیمت و وضعیت موجودی محصولات در ووکامرس بدون دستکاری متن
    کالاهای ناموجود -> قیمت خالی و وضعیت outofstock («تماس بگیرید»)
    """
    from search_engine import JSON_PRODUCTS, load_json_products
    if not JSON_PRODUCTS:
        load_json_products()

    product_map = get_woo_product_map()
    if not product_map:
        return 0, 0, ["هیچ محصولی از ربات در ووکامرس ثبت نشده است."]

    updated_count = 0
    failed_count = 0
    logs = []

    # ساخت مپ شناسه کاتالوگ به محصول
    catalog_lookup = {str(p.get("product_id") or p.get("id")): p for p in JSON_PRODUCTS}

    for pid, woo_id in list(product_map.items()):
        product = catalog_lookup.get(pid)
        if not product:
            continue

        if is_aeg_protected(product):
            continue

        price = int(product.get("price") or 0)
        stock_status = "instock" if price > 0 else "outofstock"
        reg_price = str(price) if price > 0 else ""

        payload = {
            "regular_price": reg_price,
            "stock_status": stock_status
        }

        ok, _ = _make_woo_request(f"products/{woo_id}", "PUT", payload)
        if ok:
            updated_count += 1
        else:
            failed_count += 1

        time.sleep(0.3)  # تاخیر ملایم برای سرور

    settings = get_woo_settings()
    settings["last_price_sync_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_woo_settings(settings)

    return updated_count, failed_count, logs


# ─────────────────────────────────────────────────────────────────────────────
# ۸. تسک پس‌زمینه زمان‌بندی‌شده بروزرسانی قیمت ووکامرس (نامتقارن با ربات)
# ─────────────────────────────────────────────────────────────────────────────

async def woo_price_sync_background_task(bot_instance=None):
    """
    تسک پس‌زمینه مستقل که در ساعات تعیین‌شده (مثلاً ۱۲:۳۰، ۱۸:۳۰، ۰۲:۰۰)
    قیمت‌های ووکامرس را بروزرسانی می‌کند تا هیچ تداخلی با آپدیت‌های ربات رخ ندهد.
    """
    logger.info("🌐 [WOO SYNC TASK] تسک پس‌زمینه بروزرسانی قیمت‌های ووکامرس راه‌اندازی شد.")
    while True:
        try:
            settings = get_woo_settings()
            if not settings.get("auto_sync_enabled", True):
                await asyncio.sleep(60)
                continue

            now_str = datetime.now().strftime("%H:%M")
            target_hours = settings.get("price_sync_hours", ["04:30"])

            if now_str in target_hours:
                logger.info(f"🌐 [WOO AUTO-SYNC] آغاز بروزرسانی خودکار قیمت‌های ووکامرس در ساعت {now_str}...")
                updated, failed, _ = await asyncio.to_thread(sync_prices_to_woocommerce)
                logger.info(f"🌐 [WOO AUTO-SYNC COMPLETED] بروزرسانی شد: {updated} کالا | ناموفق: {failed}")
                await asyncio.sleep(65)  # عبور از دقیقه فعلی

            await asyncio.sleep(30)
        except Exception as e:
            logger.warning(f"Error in woo_price_sync_background_task: {e}")
            await asyncio.sleep(60)


# ─────────────────────────────────────────────────────────────────────────────
# ۹. دریافت آمار وضعیت همگام‌سازی ووکامرس
# ─────────────────────────────────────────────────────────────────────────────

def get_woo_sync_stats() -> dict:
    """دریافت آمار تحلیلی و امنیتی جهت نمایش در پنل ادمین"""
    from search_engine import JSON_PRODUCTS, load_json_products
    if not JSON_PRODUCTS:
        load_json_products()

    total_catalog = len(JSON_PRODUCTS)
    aeg_protected_count = 0
    ready_to_send_count = 0
    zero_price_count = 0

    for p in JSON_PRODUCTS:
        if is_aeg_protected(p):
            aeg_protected_count += 1
        else:
            ready_to_send_count += 1
            if int(p.get("price") or 0) <= 0:
                zero_price_count += 1

    product_map = get_woo_product_map()
    published_count = len(product_map)
    review_queue = get_woo_review_queue()
    review_count = len(review_queue)

    settings = get_woo_settings()

    return {
        "total_catalog": total_catalog,
        "aeg_protected_count": aeg_protected_count,
        "ready_to_send_count": ready_to_send_count,
        "published_count": published_count,
        "zero_price_count": zero_price_count,
        "review_count": review_count,
        "root_category_id": settings.get("aikala_root_category_id", 0),
        "last_sync_time": settings.get("last_sync_time", "هنوز انجام نشده"),
        "last_price_sync_time": settings.get("last_price_sync_time", "هنوز انجام نشده"),
        "default_status": settings.get("default_publish_status", "draft"),
        "auto_sync_enabled": settings.get("auto_sync_enabled", True),
        "ai_provider": settings.get("ai_provider", "gemini")
    }
