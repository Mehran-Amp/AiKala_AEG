# -*- coding: utf-8 -*-
"""
AiKala - AI Content Cache Repository (ai_content_cache.py)
===========================================================
مخزن متمرکز، پایدار و با کارایی بالای محتواهای غنی‌شده هوش مصنوعی:
۱. ذخیره دائمی مشخصات ۲۰+ ردیفه دیتاشیت (ai_specs)
۲. ذخیره نقد و بررسی تخصصی ۳ پاراگرافی (ai_overview)
۳. ذخیره ۷ ویژگی شاخص و کلیدی قالب دینا (ai_highlights)
۴. ذخیره ۳ سوال و جواب متداول سئو (ai_faq)
۵. ذخیره متادیتای افزونه‌های سئو رنک‌مث و یوست (seo_meta)
۶. نگاشت دوطرفه کد کالا (pid) و پارت‌نامبر نرمال‌شده کالا (model_key)
۷. جلوگیری ۱۰۰٪ از ارسال درخواست‌های تکراری به Gemini و صفر کردن مصرف توکن در همگام‌سازی‌های مجدد
"""

import os
import re
import json
import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

AI_CONTENT_CACHE_FILE = "ai_content_cache.json"

_MEMORY_CACHE: Optional[Dict[str, Any]] = None


def normalize_model_key(text: str) -> str:
    """استخراج و نرمال‌سازی کلید پارت‌نامبر جهت تطابق مدل‌های مشابه"""
    if not text:
        return ""
    t = str(text).lower()
    # تبدیل ارقام فارسی و عربی
    persian = "۰۱۲۳۴۵۶۷۸۹"
    arabic = "٠١٢٣٤٥٦٧٨٩"
    for i, c in enumerate(persian):
        t = t.replace(c, str(i))
    for i, c in enumerate(arabic):
        t = t.replace(c, str(i))
    
    # حذف عبارات عمومی
    t = re.sub(r'\b(مدل|model|برند|کد|پارت|part|سری|series)\b', '', t)
    # استخراج توکن‌های الفبایی-عددی اصلی
    cleaned = re.sub(r'[^a-z0-9]', '', t)
    return cleaned.strip()


def load_ai_content_cache() -> Dict[str, Any]:
    """بارگذاری حافظه کش محتواهای هوش مصنوعی"""
    global _MEMORY_CACHE
    if _MEMORY_CACHE is not None:
        return _MEMORY_CACHE

    if os.path.exists(AI_CONTENT_CACHE_FILE):
        try:
            with open(AI_CONTENT_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    if "products" not in data:
                        data = {"products": data, "models": {}}
                    if "models" not in data:
                        data["models"] = {}
                    _MEMORY_CACHE = data
                    return _MEMORY_CACHE
        except Exception as e:
            logger.warning(f"Error loading {AI_CONTENT_CACHE_FILE}: {e}")

    _MEMORY_CACHE = {"products": {}, "models": {}}
    return _MEMORY_CACHE


def save_ai_content_cache(cache_data: Optional[Dict[str, Any]] = None) -> bool:
    """ذخیره پایدار حافظه کش روی دیسک"""
    global _MEMORY_CACHE
    if cache_data is not None:
        _MEMORY_CACHE = cache_data
    if _MEMORY_CACHE is None:
        _MEMORY_CACHE = {"products": {}, "models": {}}

    try:
        with open(AI_CONTENT_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_MEMORY_CACHE, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving {AI_CONTENT_CACHE_FILE}: {e}")
        return False


def get_cached_ai_content(pid: Any, model_name_or_code: str = "") -> Optional[Dict[str, Any]]:
    """
    بازیابی محتوای تولیدشده هوش مصنوعی:
    ۱. بر اساس کد کالا (pid)
    ۲. در صورت عدم یافتن، بر اساس پارت‌نامبر نرمال‌شده مدل (model_key)
    """
    cache = load_ai_content_cache()
    products = cache.get("products", {})
    models = cache.get("models", {})

    s_pid = str(pid).strip()
    if s_pid and s_pid in products:
        return products[s_pid]

    # جستجو بر اساس کد مدل
    norm_key = normalize_model_key(model_name_or_code)
    if norm_key and norm_key in models:
        mapped_pid = models[norm_key]
        if mapped_pid in products:
            return products[mapped_pid]

    # جستجوی فازی درون نام‌های موجود در کش
    if norm_key and len(norm_key) >= 3:
        for p_data in products.values():
            m_key = p_data.get("model_key", "")
            if m_key and (m_key == norm_key or norm_key in m_key or m_key in norm_key):
                return p_data

    return None


def save_product_ai_content(
    pid: Any,
    name: str = "",
    brand: str = "",
    category: str = "",
    specs: Optional[Dict[str, str]] = None,
    overview: str = "",
    highlights: str = "",
    faq: Optional[list] = None,
    seo_meta: Optional[Dict[str, str]] = None,
    model_code: str = ""
) -> bool:
    """ذخیره یا بروزرسانی محتوای هوش مصنوعی یک محصول در مخزن کش"""
    cache = load_ai_content_cache()
    s_pid = str(pid).strip()
    if not s_pid:
        return False

    norm_model = normalize_model_key(model_code or name)

    existing = cache["products"].get(s_pid, {})

    entry = {
        "product_id": s_pid,
        "name": name or existing.get("name", ""),
        "brand": brand or existing.get("brand", ""),
        "category": category or existing.get("category", ""),
        "model_key": norm_model or existing.get("model_key", ""),
        "ai_specs": specs if specs is not None else existing.get("ai_specs", {}),
        "ai_overview": overview if overview else existing.get("ai_overview", ""),
        "ai_highlights": highlights if highlights else existing.get("ai_highlights", ""),
        "ai_faq": faq if faq is not None else existing.get("ai_faq", []),
        "seo_meta": seo_meta if seo_meta is not None else existing.get("seo_meta", {}),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cached": True
    }

    cache["products"][s_pid] = entry
    if norm_model:
        cache["models"][norm_model] = s_pid

    return save_ai_content_cache()


def count_cached_ai_items() -> int:
    """شمارش محصولات دارای محتوای هوش مصنوعی کش‌شده"""
    cache = load_ai_content_cache()
    return len(cache.get("products", {}))


def merge_ai_content_cache_data(imported_cache: Dict[str, Any]) -> int:
    """
    ادغام هوشمند داده‌های کش هوش مصنوعی واردشده از فایل بک‌آپ با کش جاری سیستم:
    - فیلدهای غنی‌تر جایگزین فیلدهای خالی می‌شوند
    - داده‌های قبلی حفظ می‌گردند
    """
    curr = load_ai_content_cache()
    added_or_updated = 0

    imp_prods = imported_cache.get("products", {}) if isinstance(imported_cache, dict) else {}
    if not imp_prods and isinstance(imported_cache, dict):
        # اگر ساختار فلت بود
        imp_prods = {k: v for k, v in imported_cache.items() if isinstance(v, dict)}

    for pid, data in imp_prods.items():
        s_pid = str(pid).strip()
        if not s_pid or not isinstance(data, dict):
            continue

        if s_pid not in curr["products"]:
            curr["products"][s_pid] = data
            m_key = data.get("model_key") or normalize_model_key(data.get("name", ""))
            if m_key:
                curr["models"][m_key] = s_pid
            added_or_updated += 1
        else:
            # ادغام فیلدهای خالی
            cur_entry = curr["products"][s_pid]
            changed = False
            for fld in ["ai_specs", "ai_overview", "ai_highlights", "ai_faq", "seo_meta", "name", "brand", "category"]:
                if not cur_entry.get(fld) and data.get(fld):
                    cur_entry[fld] = data[fld]
                    changed = True
                elif fld == "ai_specs" and isinstance(data.get("ai_specs"), dict):
                    # اگر مشخصات در بکاپ جامع‌تر بود، ترکیب شود
                    cur_specs = cur_entry.get("ai_specs") or {}
                    if len(data["ai_specs"]) > len(cur_specs):
                        cur_specs.update(data["ai_specs"])
                        cur_entry["ai_specs"] = cur_specs
                        changed = True

            if changed:
                added_or_updated += 1

    save_ai_content_cache()
    return added_or_updated
