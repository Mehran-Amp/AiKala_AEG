# -*- coding: utf-8 -*-
"""
gemini_enricher.py
==================
موتور مدیریت هوشمند مشخصات فنی محصولات با قابلیت تنظیم در پنل ادمین
(Google Gemini / DeepSeek / خاموش)
کاملاً تقاضامحور (On-Demand / Lazy):
۱. فقط در صورت کلیک کاربر روی کارت یا پست محصول اجرا می‌شود.
۲. مشخصات ۱۰۰٪ منطبق با نام، برند و کد مدل دقیق کالا جهت جلوگیری از اطلاعات الکی و غیرواقعی استخراج می‌شود.
۳. مشخصات استخراج‌شده «یکبار برای همیشه» در کاتالوگ و دیتابیس ذخیره می‌شود.
۴. امکان تغییر موتور (جمینای، دیپ‌سیک یا خاموش) از طریق پنل مدیریت ربات.
"""

import os
import io
import re
import json
import sqlite3
import time
import asyncio
import logging
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, Tuple, List

logger = logging.getLogger("AIEnricher")

CATALOG_FILE = "catalog_products.json"
DB_FILE = "bot_data.db"
AI_SETTINGS_FILE = "ai_settings.json"

# تنظیمات پیش‌فرض مدل‌ها (اولویت با gemini-3.8-flash و مدل‌های نسل جدید)
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
FALLBACK_GEMINI_MODEL = "gemini-2.5-pro"
EXTRA_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
FALLBACK_DEEPSEEK_MODEL = "deepseek-reasoner"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# کلیدهای نامعتبر و آزمایشی سندباکس جهت جلوگیری از خطای ۴۰۰ کاذب
DUMMY_KEYS = {
    "AIzaSy" + "FakeKeyForTesting000000000000000000",
    "your_api_key_here",
    "YOUR_GEMINI_API_KEY",
    "YOUR_DEEPSEEK_API_KEY",
}

# ─── مدیریت تنظیمات هوش مصنوعی (Gemini / DeepSeek / Off) ───

def get_ai_settings() -> dict:
    """دریافت تنظیمات فعلی هوش مصنوعی از فایل یا مقدار پیش‌فرض"""
    default_settings = {
        "provider": "gemini",  # gemini | deepseek | off
        "gemini_model": DEFAULT_GEMINI_MODEL,
        "deepseek_model": DEFAULT_DEEPSEEK_MODEL,
        "gemini_api_key": "",
        "deepseek_api_key": "",
        "updated_at": ""
    }
    if os.path.exists(AI_SETTINGS_FILE):
        try:
            with open(AI_SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                default_settings.update({k: v for k, v in saved.items() if v is not None})
        except Exception as e:
            logger.debug(f"Error loading AI settings: {e}")
    return default_settings

def set_ai_provider(provider: str) -> bool:
    """تغییر موتور فعال هوش مصنوعی (gemini, deepseek, off)"""
    clean_provider = provider.lower().strip()
    if clean_provider not in ["gemini", "deepseek", "off", "disabled"]:
        return False
    if clean_provider == "disabled":
        clean_provider = "off"

    settings = get_ai_settings()
    settings["provider"] = clean_provider
    try:
        import datetime
        settings["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(AI_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        logger.info(f"🔧 [AI SETTINGS] موتور فعال هوش مصنوعی به '{clean_provider}' تغییر یافت.")
        return True
    except Exception as e:
        logger.error(f"Error saving AI settings: {e}")
        return False

def get_active_provider_label() -> str:
    """عنوان فارسی و نشانگر موتور فعال هوش مصنوعی"""
    provider = get_ai_settings().get("provider", "gemini")
    if provider == "gemini":
        return "♊️ گوگل جمینای (Google Gemini) - فعال"
    elif provider == "deepseek":
        return "🤖 دیپ‌سیک (DeepSeek) - فعال"
    else:
        return "🛑 خاموش (غیرفعال)"

# ─── دریافت و ذخیره امن کلیدهای API ───

def _update_env_file(key_name: str, value: str):
    """ذخیره یا به‌روزرسانی متغیر در فایل .env"""
    env_path = os.path.join(os.getcwd(), ".env")
    lines = []
    found = False
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8-sig") as f:
                lines = f.readlines()
            new_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("export "):
                    stripped = stripped[7:].strip()
                if stripped.startswith(f"{key_name}=") or re.match(rf"^{key_name}\s*=", stripped):
                    new_lines.append(f'{key_name}="{value}"\n')
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f'{key_name}="{value}"\n')
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            return
        except Exception:
            pass

    try:
        with open(env_path, "a", encoding="utf-8") as f:
            f.write(f'{key_name}="{value}"\n')
    except Exception:
        pass

def save_ai_api_key(provider: str, key: str) -> bool:
    """ذخیره کلید API برای Gemini یا DeepSeek در فایل امن .env و متغیر محیطی"""
    clean_provider = provider.lower().strip()
    clean_key = key.strip().strip('"').strip("'")
    settings = get_ai_settings()

    if clean_provider == "gemini":
        if clean_key:
            os.environ["GEMINI_API_KEY"] = clean_key
        else:
            os.environ.pop("GEMINI_API_KEY", None)
        _update_env_file("GEMINI_API_KEY", clean_key)
    elif clean_provider == "deepseek":
        if clean_key:
            os.environ["DEEPSEEK_API_KEY"] = clean_key
        else:
            os.environ.pop("DEEPSEEK_API_KEY", None)
        _update_env_file("DEEPSEEK_API_KEY", clean_key)
    else:
        return False

    try:
        import datetime
        settings["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # کلیدهای امنیتی هرگز در فایل رهگیری‌شده گیت ذخیره نمی‌شوند و در .env نگهداری می‌شوند
        settings["gemini_api_key"] = ""
        settings["deepseek_api_key"] = ""
        with open(AI_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        logger.info(f"🔑 [AI KEY SAVED] کلید API برای '{clean_provider}' با موفقیت در .env ذخیره شد.")
        return True
    except Exception as e:
        logger.error(f"Error saving AI key: {e}")
        return False

def _read_key_from_env_files(key_name: str) -> str:
    """
    جستجوی هوشمند و همه‌جانبه کلید در فایل‌های .env با پشتیبانی از:
    - فاصله‌های اطراف مساوی (مانند KEY = "val")
    - پیشوندهای export
    - یونیکد BOM
    - نام‌های مستعار و متناظر (Aliases)
    - کانتینرهای Cloud Run / AI Studio (.dev.env.json)
    """
    # تعریف نام‌های مستعار برای سازگاری حداکثری
    target_names = [key_name.upper()]
    if key_name.upper() == "GEMINI_API_KEY":
        target_names.extend(["GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY", "GEMINI_KEY"])
    elif key_name.upper() == "DEEPSEEK_API_KEY":
        target_names.extend(["DEEP_SEEK_API_KEY", "DEEPSEEK_KEY"])

    candidates = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.local"),
        "/app/applet/.env",
        "/app/.env",
        ".env"
    ]

    for fp in candidates:
        if os.path.isfile(fp):
            try:
                with open(fp, "r", encoding="utf-8-sig") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if line.startswith("export "):
                            line = line[7:].strip()
                        if "=" in line:
                            k, val = line.split("=", 1)
                            k_clean = k.strip().upper()
                            if k_clean in target_names:
                                val_clean = val.strip()
                                if (val_clean.startswith('"') and val_clean.endswith('"')) or (val_clean.startswith("'") and val_clean.endswith("'")):
                                    val_clean = val_clean[1:-1].strip()
                                elif " #" in val_clean:
                                    val_clean = val_clean.split(" #", 1)[0].strip()
                                if val_clean.lower().startswith("bearer "):
                                    val_clean = val_clean[7:].strip()
                                if val_clean and not val_clean.startswith("MY_") and val_clean not in DUMMY_KEYS and len(val_clean) >= 10:
                                    os.environ[key_name] = val_clean
                                    return val_clean
            except Exception:
                pass

    # بررسی فایل پیکربندی کانتینر ابری
    dev_json_candidates = ["/app/.dev.env.json", "/app/applet/.dev.env.json"]
    for djc in dev_json_candidates:
        if os.path.isfile(djc):
            try:
                with open(djc, "r", encoding="utf-8") as f:
                    jdata = json.load(f)
                    if isinstance(jdata, dict):
                        for target_k in target_names:
                            val = jdata.get(target_k)
                            if val:
                                s_val = str(val).strip().strip('"').strip("'")
                                if s_val.lower().startswith("bearer "):
                                    s_val = s_val[7:].strip()
                                if s_val and not s_val.startswith("MY_") and s_val not in DUMMY_KEYS and len(s_val) >= 10:
                                    os.environ[key_name] = s_val
                                    return s_val
            except Exception:
                pass

    return ""

def get_gemini_api_key() -> str:
    """دریافت کلید API معتبر جمینای با آبشار چندلایه‌ای اولویت‌ها"""
    # ۱. اولویت اول: تنظیمات ذخیره شده در ai_settings.json
    settings = get_ai_settings()
    custom_key = str(settings.get("gemini_api_key") or "").strip()
    if custom_key.lower().startswith("bearer "):
        custom_key = custom_key[7:].strip()
    if custom_key and custom_key not in DUMMY_KEYS and not custom_key.startswith("MY_") and len(custom_key) >= 15:
        return custom_key

    # ۲. اولویت دوم: استخراج از فایل‌های .env و متغیرهای کانفیگ کانتینر
    file_key = _read_key_from_env_files("GEMINI_API_KEY")
    if file_key and file_key not in DUMMY_KEYS:
        return file_key

    # ۳. متغیرهای محیطی سیستم
    for env_var in ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY", "GEMINI_KEY"]:
        env_key = os.getenv(env_var, "").strip()
        if env_key.lower().startswith("bearer "):
            env_key = env_key[7:].strip()
        if env_key and env_key not in DUMMY_KEYS and not env_key.startswith("MY_") and len(env_key) >= 15:
            return env_key

    # ۴. فایل تنظیمات config.py
    try:
        import config
        c_key = getattr(config, "GEMINI_API_KEY", "").strip()
        if c_key and c_key not in DUMMY_KEYS and not c_key.startswith("MY_") and len(c_key) >= 15:
            return c_key
    except Exception:
        pass

    return ""

def get_deepseek_api_key() -> str:
    """دریافت کلید API معتبر دیپ‌سیک با آبشار چندلایه‌ای اولویت‌ها"""
    # ۱. اولویت اول: تنظیمات ذخیره شده در ai_settings.json
    settings = get_ai_settings()
    custom_key = str(settings.get("deepseek_api_key") or "").strip()
    if custom_key.lower().startswith("bearer "):
        custom_key = custom_key[7:].strip()
    if custom_key and custom_key not in DUMMY_KEYS and not custom_key.startswith("MY_") and len(custom_key) >= 15:
        return custom_key

    # ۲. اولویت دوم: استخراج از فایل‌های .env
    file_key = _read_key_from_env_files("DEEPSEEK_API_KEY")
    if file_key and file_key not in DUMMY_KEYS:
        return file_key

    # ۳. متغیرهای محیطی سیستم
    for env_var in ["DEEPSEEK_API_KEY", "DEEP_SEEK_API_KEY", "DEEPSEEK_KEY"]:
        env_key = os.getenv(env_var, "").strip()
        if env_key.lower().startswith("bearer "):
            env_key = env_key[7:].strip()
        if env_key and env_key not in DUMMY_KEYS and not env_key.startswith("MY_") and len(env_key) >= 15:
            return env_key

    try:
        import config
        c_key = getattr(config, "DEEPSEEK_API_KEY", "").strip()
        if c_key and c_key not in DUMMY_KEYS and not c_key.startswith("MY_") and len(c_key) >= 15:
            return c_key
    except Exception:
        pass

    return ""

# کلیدهایی که صرفاً اطلاعات جانبی، دسته‌بندی یا گارانتی هستند و مشخصه فنی کارخانه‌ای به شمار نمی‌روند
NON_SPEC_KEYS = {
    "زیرشاخه", "دسته‌بندی", "دسته", "امتیاز کیفی", "امتیاز",
    "ضمانت اصالت", "گارانتی", "گارانتی و مهلت تست", "مهلت تست و تعویض"
}

# ─── بررسی وجود مشخصات در کالا (Zero Delay / 0 Latency) ───

def count_product_technical_specs(p: dict) -> int:
    """
    شمارش دقیق تعداد مشخصات فنی معتبر کالا (بدون احتساب رنگ، قیمت، امتیاز و گارانتی).
    """
    if not p or not isinstance(p, dict):
        return 0

    found_keys = set()
    banned_prefixes = ("رنگ", "color", "colour", "قیمت", "price", "گارانتی", "ضمانت", "امتیاز", "دسته", "زیرشاخه", "عکس", "تصویر")

    # ۱. بررسی ai_specs
    ai_specs = p.get("ai_specs")
    if isinstance(ai_specs, str):
        try:
            ai_specs = json.loads(ai_specs)
        except Exception:
            ai_specs = {}
    if isinstance(ai_specs, dict):
        for k, v in ai_specs.items():
            k_c = str(k).strip()
            v_c = str(v).strip()
            if not k_c or not v_c:
                continue
            if k_c in NON_SPEC_KEYS:
                continue
            if any(b in k_c.lower() for b in banned_prefixes):
                continue
            if "رنگ" in v_c or "color" in v_c.lower():
                continue
            found_keys.add(k_c)

    # ۲. بررسی specs
    specs = p.get("specs")
    if isinstance(specs, str):
        try:
            specs = json.loads(specs)
        except Exception:
            specs = {}
    if isinstance(specs, dict):
        for k, v in specs.items():
            k_c = str(k).strip()
            v_c = str(v).strip()
            if not k_c or not v_c:
                continue
            if k_c in NON_SPEC_KEYS:
                continue
            if any(b in k_c.lower() for b in banned_prefixes):
                continue
            if "رنگ" in v_c or "color" in v_c.lower():
                continue
            found_keys.add(k_c)

    # ۳. فیلدهای مستقیم کاتالوگ (در صورت عدم وجود شیء مشخصات)
    if len(found_keys) == 0:
        meaningful_fields = [
            ("assembly", "کشور مونتاژ"), ("resolution", "کیفیت تصویر"), ("panel", "نوع پنل"),
            ("refresh_rate", "نرخ نوسازی"), ("os", "سیستم عامل"), ("capacity_btu", "ظرفیت کولر"),
            ("temp_range", "شرایط آب و هوایی"), ("room_size", "پوشش فضا"), ("energy_consumption", "مصرف انرژی"),
            ("plan", "طرح بدنه"), ("capacity_foot", "ظرفیت به فوت"), ("num_doors", "تعداد درب"),
            ("capacity_kg", "ظرفیت شستشو"), ("baskets", "تعداد سبد"), ("key_features", "ویژگی‌ها"),
            ("cpu", "پردازنده"), ("ram", "رم"), ("gpu", "گرافیک"), ("power", "توان مصرفی"),
            ("capacity", "ظرفیت"), ("blade", "جنس تیغه")
        ]
        for field_key, field_name in meaningful_fields:
            val = p.get(field_key)
            if val is not None and str(val).strip():
                found_keys.add(field_name)

    return len(found_keys)

def get_products_for_batch_enrich(mode: str) -> List[dict]:
    """
    دریافت لیست کالاهای واجد شرایط جهت تکمیل گروهی مشخصات فنی:
    - mode == 'no_specs': کالاهای کاملاً فاقد مشخصات فنی (0 مشخصه)
    - mode == 'under_3': کالاهای دارای مشخصات ناقص یا ناکافی (۳ مشخصه و کمتر: 0، 1، 2 و 3 مشخصه)
    """
    catalog_items = []
    if os.path.exists(CATALOG_FILE):
        try:
            with open(CATALOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                catalog_items = list(data.values())
            elif isinstance(data, list):
                catalog_items = data
        except Exception as e:
            logger.error(f"Error reading {CATALOG_FILE}: {e}")

    if not catalog_items:
        try:
            from search_engine import JSON_PRODUCTS
            catalog_items = list(JSON_PRODUCTS)
        except Exception:
            catalog_items = []

    targets = []
    for item in catalog_items:
        if not isinstance(item, dict):
            continue
        c = count_product_technical_specs(item)
        if mode == "no_specs" and c == 0:
            targets.append(item)
        elif mode == "under_3" and c <= 3:
            targets.append(item)

    return targets

def get_batch_specs_counts() -> Tuple[int, int, int]:
    """محاسبه تعداد کالاهای بدون مشخصات (0)، ناقص (۳ مشخصه و کمتر) و کل کاتالوگ"""
    catalog_items = []
    if os.path.exists(CATALOG_FILE):
        try:
            with open(CATALOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                catalog_items = list(data.values())
            elif isinstance(data, list):
                catalog_items = data
        except Exception:
            pass
    if not catalog_items:
        try:
            from search_engine import JSON_PRODUCTS
            catalog_items = list(JSON_PRODUCTS)
        except Exception:
            pass

    no_specs = 0
    under_3 = 0
    for item in catalog_items:
        if isinstance(item, dict):
            c = count_product_technical_specs(item)
            if c == 0:
                no_specs += 1
            if c <= 3:
                under_3 += 1

    return no_specs, under_3, len(catalog_items)

def product_has_specs(product: dict) -> bool:
    """
    بررسی اینکه آیا کالا از قبل مشخصات فنی واقعی، کافی و معتبر دارد یا خیر.
    نکته: مواردی مانند زیرشاخه، امتیاز کیفی، ضمانت اصالت و گارانتی جزء مشخصات فنی محصول نیستند
    و حضور آنها مانع از استعلام هوش مصنوعی نخواهد شد.
    کالاهایی که ۳ مشخصه یا کمتر دارند مشمول تکمیل مشخصات هوشمند می‌شوند (> 3 کافی در نظر گرفته می‌شود).
    """
    if not product or not isinstance(product, dict):
        return True

    return count_product_technical_specs(product) > 3

# ─── تولید پرامپت با تاکید موکد بر مدل دقیق جهت جلوگیری از مشخصات فیک و حذف قطعی رنگ ───

def build_grounded_specs_prompt(product: dict) -> str:
    """
    پرامپت تخصصی، جامع و جامع‌نگر برای استخراج حداکثر مشخصات فنی رسمی کارخانه‌ای (دیتاشیت کامل ۱۰ الی ۳۰ موردی)
    بر اساس نام کالا، برند و کد مدل دقیق با حذف قطعی رنگ و ممانعت از اطلاعات اشتباه.
    """
    name = str(product.get("name") or "").strip()
    brand = str(product.get("brand") or "").strip()
    model = str(product.get("model_number") or "").strip()
    subcat = str(product.get("subcategory") or "").strip()
    cat = str(product.get("category_name") or product.get("category_key") or "").strip()

    prompt = (
        f"تو کارشناس ارشد و متخصص فنی دیتاشیت کاتالوگ لوازم خانگی، صوتی‌تصویری و دیجیتال هستی.\n\n"
        f"کالای مورد نظر برای استخراج جدول کامل مشخصات فنی رسمی کارخانه:\n"
        f"▫️ نام کامل محصول: «{name}»\n"
        f"▫️ برند سازنده: «{brand}»\n"
        f"▫️ کد مدل دقیق: «{model}»\n"
        f"{f'▫️ نوع کالا: «{subcat}»' if subcat else ''}\n"
        f"{f'▫️ دسته‌بندی: «{cat}»' if cat else ''}\n\n"
        f"دستورات و الزامات حیاتی استخراج جامع:\n"
        f"۱. تمام مشخصات فنی رسمی و موثق موجود در دیتاشیت این کد مدل را به صورت کامل و پرجزئیات (بین ۱۰ الی ۲۵ مشخصه فنی کامل) استخراج کن.\n"
        f"۲. دسته‌بندی‌های مشخصات مدنظر شامل:\n"
        f"   - توان مصرفی، ولتاژ، رده انرژی و مشخصات الکتریکی\n"
        f"   - ظرفیت کلی و مفید، ابعاد فیزیکی، وزن دستگاه، طول کابل\n"
        f"   - جنس بدنه، جنس کاسه/مخزن و نوع پوشش داخلی\n"
        f"   - تعداد و تنوع برنامه‌های پخت/کارکرد، عملکردهای تخصصی، تایمر و زمان‌بندی\n"
        f"   - سیستم ایمنی، قفل کودک، قطع خودکار، قابلیت شستشوی قطعات در ماشین ظرفشویی\n"
        f"   - نوع صفحه نمایش و کنترل پنل، اقلام همراه جعبه و کشور سازنده/مونتاژ\n"
        f"۳. کلیدها و عناوین مشخصات کاملاً فارسی روان و بدون زیرخط (_) باشند (مثلاً 'توان مصرفی' نه 'توان_مصرفی').\n"
        f"۴. اطلاعات به‌هیچ‌وجه شامل رنگ، تنوع رنگی، قیمت، تخفیف، گارانتی یا عبارات تبلیغاتی نباشد.\n"
        f"۵. خروجی فقط و فقط یک شیء JSON استاندارد با جفت‌های کلید: مقدار متنی فارسی باشد.\n\n"
        f"نمونه فرمت خروجی:\n"
        f'{{"توان مصرفی": "۱۳۰۰ وات", "ظرفیت کاسه": "۶ لیتر", "جنس کاسه": "سرامیک نچسب چندلایه", "تعداد برنامه‌های پخت": "۱۵ برنامه", "صفحه نمایش": "دیجیتال لمسی LED", "کشور سازنده": "چین"}}'
    )
    return prompt

def _validate_and_filter_specs(raw_dict: dict) -> Optional[Dict[str, str]]:
    """فیلتر و اعتبارسنجی دقیق مشخصات برای تضمین فنی، غیرالکی بودن و حذف قطعی رنگ و قیمت"""
    if not isinstance(raw_dict, dict):
        return None

    banned_keywords = [
        "قیمت", "رنگ", "color", "colour", "خرید", "تومان", "ریال",
        "گارانتی", "ضمانت", "تخفیف", "فروش", "امتیاز", "دسته", "زیرشاخه",
        "کد کالا", "شناسه", "عکس", "تصویر", "سایز"
    ]
    color_names = [
        "مشکی", "سفید", "نقره‌ای", "نقره ای", "سیلور", "دودی", "طوسی", "خاکستری",
        "قرمز", "آبی", "زرد", "سبز", "طلایی", "رزگلد", "استیل", "تیتانیوم", "نوک مدادی",
        "black", "white", "silver", "gray", "grey", "gold", "red", "blue"
    ]

    specs = {}
    for k, v in raw_dict.items():
        k_clean = str(k).strip().lstrip("-*▫️• ").replace("_", " ")
        v_clean = str(v).strip()

        # ۱. بررسی کلمات ممنوعه در کلید (از جمله رنگ، قیمت، گارانتی)
        k_lower = k_clean.lower()
        if any(b in k_lower for b in banned_keywords):
            continue

        # ۲. بررسی اینکه آیا مقدار کلاً بیانگر رنگ است یا کلمه رنگ دارد
        v_lower = v_clean.lower()
        if "رنگ" in v_clean or "color" in v_lower:
            continue
        if v_lower in [c.lower() for c in color_names]:
            continue

        if len(k_clean) < 60 and len(v_clean) < 250:
            specs[k_clean] = v_clean

    return specs if len(specs) >= 2 else None

def _parse_ai_json_response(raw_text: str) -> Optional[Dict[str, str]]:
    """پارس امن خروجی هوش مصنوعی به صورت شیء مشخصات معتبر"""
    if not raw_text:
        return None

    cleaned_text = raw_text.strip()
    if "```" in cleaned_text:
        m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', cleaned_text)
        if m:
            cleaned_text = m.group(1).strip()

    try:
        data = json.loads(cleaned_text)
        if isinstance(data, dict):
            filtered = _validate_and_filter_specs(data)
            if filtered:
                return filtered
    except Exception:
        pass

    # روش پشتیبان خط‌به‌خط
    specs = {}
    for line in cleaned_text.split("\n"):
        line = line.strip().lstrip("-*▫️•#▪️ ")
        line = re.sub(r'^\s*[\d۰-۹]+[\.\-\)\s]+\s*', '', line)
        clean_line = line.replace("**", "").replace("__", "").strip()
        if ":" in clean_line:
            parts = clean_line.split(":", 1)
            k = parts[0].strip()
            v = parts[1].strip()
            specs[k] = v

    return _validate_and_filter_specs(specs)

# ─── فراخوانی Gemini API ───

def call_gemini_api_with_error(api_key: str, product: dict) -> Tuple[Optional[Dict[str, str]], str]:
    """فراخوانی جمینای با تنظیم دما روی 0.1 جهت بیشترین انطباق با منطق چرخش هوشمند:
    مدل اصلی: gemini-2.5-flash-lite (سرعت و مصرف بهینه سهمیه)
    مدل پشتیبان و اعتبارسنجی کیفیت: gemini-2.5-flash (در صورت ناکافی بودن یا خطا)
    سپس مدل‌های سری 3 جهت پایداری ۱۰۰ درصدی
    """
    if not api_key:
        return None, "کلید GEMINI_API_KEY تنظیم نشده است."

    prompt = build_grounded_specs_prompt(product)
    pname = product.get("name", "")
    last_error = "پاسخی از مدل دریافت نشد."

    # منطق چرخش مدل‌ها برای استخراج مشخصات فنی: اولویت با flash-lite سپس flash و سری ۳
    models_to_try = [
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
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

    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        }

        payloads = [
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "maxOutputTokens": 2500,
                    "responseMimeType": "application/json"
                }
            }
        ]

        model_exhausted = False
        for payload in payloads:
            if model_exhausted:
                break
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )

            try:
                with urllib.request.urlopen(req, timeout=14.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    candidates = data.get("candidates", [])
                    if not candidates:
                        continue
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if not parts:
                        continue
                    raw_text = parts[0].get("text", "")
                    specs = _parse_ai_json_response(raw_text)
                    if specs:
                        # کنترل کیفیت هوشمند: اگر مشخصات کمتر از ۳ مورد باشد و در مدل flash-lite باشیم، چرخش به flash
                        if len(specs) < 3 and model_name == "gemini-2.5-flash-lite":
                            logger.info(f"🔄 مشخصات '{pname}' از flash-lite ناکافی بود ({len(specs)} مورد). چرخش به gemini-2.5-flash...")
                            continue
                        logger.info(f"✅ [GEMINI AI] مشخصات دقیق '{pname}' با موفقیت از مدل {model_name} استخراج شد.")
                        return specs, ""
            except urllib.error.HTTPError as he:
                err_body = he.read().decode("utf-8", errors="ignore")
                last_error = f"HTTP {he.code}: {err_body[:180]}"
                logger.warning(f"⚠️ [GEMINI HTTP {he.code}] Model {model_name}: {err_body[:180]}")
                if he.code in [400, 403] and ("API key not valid" in err_body or "API_KEY_INVALID" in err_body):
                    return None, f"کلید API نامعتبر است (HTTP {he.code})"
                if he.code == 503:
                    last_error = f"مدل {model_name} دچار ترافیک موقت است (503 High Demand). سوییچ به مدل بعدی..."
                    model_exhausted = True
                    break
                if he.code == 429:
                    last_error = f"سقف سهمیه مدل {model_name} موقتاً تکمیل است (Rate Limit 429). استراحت ۳۰ ثانیه‌ای و سوئیچ به مدل پشتیبان..."
                    logger.warning(f"⏳ [GEMINI 429] استراحت ۳۰ ثانیه‌ای و سوئیچ به مدل پشتیبان (مانند flash-lite)...")
                    model_exhausted = True
                    time.sleep(30.0)
                    break
            except Exception as e:
                last_error = str(e)
                logger.warning(f"⚠️ [GEMINI ERROR] Model {model_name} for '{pname}': {e}")

    return None, last_error

def call_gemini_api(api_key: str, product: dict) -> Optional[Dict[str, str]]:
    """فراخوانی جمینای جهت سازگاری کامل با توابع قبلی"""
    specs, _ = call_gemini_api_with_error(api_key, product)
    return specs

# ─── فراخوانی DeepSeek API ───

def call_deepseek_api_with_error(api_key: str, product: dict) -> Tuple[Optional[Dict[str, str]], str]:
    """فراخوانی دیپ‌سیک با پرامپت دقیق منطبق بر مدل با گزارش ارور"""
    if not api_key:
        return None, "کلید DEEPSEEK_API_KEY تنظیم نشده است."

    prompt = build_grounded_specs_prompt(product)
    pname = product.get("name", "")

    endpoint = f"{DEFAULT_DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"
    models_to_try = [DEFAULT_DEEPSEEK_MODEL, FALLBACK_DEEPSEEK_MODEL]
    last_error = "پاسخی از مدل دریافت نشد."

    for model_name in models_to_try:
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": "تو متخصص فنی کاتالوگ لوازم خانگی هستی. خروجی فقط یک شیء JSON با مشخصات فنی واقعی کارخانه است."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 600,
            "temperature": 0.1,
            "stream": False
        }

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            },
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=9.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choice = data.get("choices", [{}])[0]
                content = (choice.get("message", {}).get("content") or "").strip()
                reasoning = (choice.get("message", {}).get("reasoning_content") or "").strip()
                if not content and reasoning:
                    content = reasoning
                specs = _parse_ai_json_response(content)
                if specs:
                    logger.info(f"✅ [DEEPSEEK AI] مشخصات دقیق '{pname}' با موفقیت از مدل {model_name} استخراج شد.")
                    return specs, ""
        except urllib.error.HTTPError as he:
            err_body = he.read().decode("utf-8", errors="ignore")
            last_error = f"HTTP {he.code}: {err_body[:180]}"
            logger.warning(f"⚠️ [DEEPSEEK HTTP {he.code}] Model {model_name}: {err_body[:180]}")
            if he.code in [401, 403]:
                return None, f"کلید DeepSeek نامعتبر است (HTTP {he.code})"
        except Exception as e:
            last_error = str(e)
            logger.warning(f"⚠️ [DEEPSEEK ERROR] for '{pname}': {e}")

    return None, last_error

def call_deepseek_api(api_key: str, product: dict) -> Optional[Dict[str, str]]:
    """فراخوانی دیپ‌سیک جهت سازگاری با توابع قبلی"""
    specs, _ = call_deepseek_api_with_error(api_key, product)
    return specs

# ─── تست زنده اتصال هوش مصنوعی ───

def test_ai_connection(provider: Optional[str] = None) -> Tuple[bool, str, float]:
    """تست زنده اتصال به هوش مصنوعی (Google Gemini یا DeepSeek)"""
    import time
    start_t = time.time()

    settings = get_ai_settings()
    active_p = (provider or settings.get("provider", "gemini")).lower().strip()

    if active_p in ["off", "disabled"]:
        return False, "موتور هوش مصنوعی در پنل خاموش است.", 0.0

    test_product = {
        "name": "تلویزیون 55 اینچ ال جی مدل C3",
        "brand": "ال جی",
        "model_number": "OLED55C3",
        "category_name": "تلویزیون"
    }

    if active_p == "gemini":
        key = get_gemini_api_key()
        if not key:
            ds_key = get_deepseek_api_key()
            if ds_key:
                return False, (
                    "⚠️ کلید <b>GEMINI_API_KEY</b> در تنظیمات یا فایل .env یافت نشد.\n\n"
                    f"💡 <b>نکته:</b> کلید DeepSeek با شناسه <code>{ds_key[:6]}...{ds_key[-4:]}</code> در سیستم فعال است!\n"
                    "می‌توانید با دکمه «فعالسازی دیپ‌سیک 🤖» موتور فعال را تغییر دهید یا با دکمه «🔑 ثبت / ویرایش کلید Gemini» کلید جمینای خود را وارد فرمایید."
                ), 0.0
            return False, "کلید GEMINI_API_KEY در فایل .env یا تنظیمات ربات ثبت نشده است یا نامعتبر است. لطفاً از دکمه «🔑 ثبت / ویرایش کلید Gemini» کلید معتبر را وارد فرمایید.", 0.0

        masked_key = f"{key[:6]}...{key[-4:]}"
        specs, err = call_gemini_api_with_error(key, test_product)
        elapsed = round(time.time() - start_t, 2)
        if specs:
            sample_specs = " | ".join([f"{k}: {v}" for k, v in list(specs.items())[:3]])
            return True, f"اتصال به Google Gemini با کلید (<code>{masked_key}</code>) کاملاً برقرار است! (زمان پاسخ: {elapsed} ثانیه)\nنمونه مشخصات استخراج شده:\n{sample_specs}", elapsed
        else:
            hint = ""
            if "429" in err:
                hint = (
                    "\n\n💡 <b>دلیل سهمیه (Free Tier):</b> کلید شما در پنل گوگل در پلن رایگان (Free Tier) قرار دارد که دارای سقف محدود روزانه (۲۰ درخواست) است.\n"
                    "با گذشت زمان یا فعالسازی صورتحساب (Billing) در گوگل، سهمیه این کلید نامحدود خواهد شد."
                )
            return False, f"خطا در ارتباط با Gemini (کلید: <code>{masked_key}</code>):\n{err}{hint}", elapsed

    elif active_p == "deepseek":
        key = get_deepseek_api_key()
        if not key:
            gem_key = get_gemini_api_key()
            if gem_key:
                return False, (
                    "⚠️ کلید <b>DEEPSEEK_API_KEY</b> در تنظیمات یا فایل .env یافت نشد.\n\n"
                    f"💡 <b>نکته:</b> کلید Google Gemini با شناسه <code>{gem_key[:6]}...{gem_key[-4:]}</code> در سیستم فعال است!\n"
                    "می‌توانید با دکمه «فعالسازی گوگل جمینای ♊️» موتور فعال را تغییر دهید یا با دکمه «🔑 ثبت / ویرایش کلید DeepSeek» کلید دیپ‌سیک خود را وارد فرمایید."
                ), 0.0
            return False, "کلید DEEPSEEK_API_KEY در فایل .env یا تنظیمات ربات ثبت نشده است. لطفاً از دکمه «🔑 ثبت / ویرایش کلید DeepSeek» کلید وارد فرمایید.", 0.0

        masked_key = f"{key[:6]}...{key[-4:]}"
        specs, err = call_deepseek_api_with_error(key, test_product)
        elapsed = round(time.time() - start_t, 2)
        if specs:
            sample_specs = " | ".join([f"{k}: {v}" for k, v in list(specs.items())[:3]])
            return True, f"اتصال به DeepSeek با کلید (<code>{masked_key}</code>) کاملاً برقرار است! (زمان پاسخ: {elapsed} ثانیه)\nنمونه مشخصات استخراج شده:\n{sample_specs}", elapsed
        else:
            return False, f"خطا در ارتباط با DeepSeek (کلید: <code>{masked_key}</code>):\n{err}", elapsed

    return False, f"ارائه‌دهنده نامشخص: {active_p}", 0.0

# ─── ذخیره‌سازی دائمی یکبار برای همیشه ───

def sync_save_ai_specs(pid: str, specs: dict):
    """ذخیره دائمی مشخصات در catalog_products.json و bot_data.db"""
    if not pid or not specs:
        return

    spec_str = " | ".join([f"{k}: {v}" for k, v in specs.items()])

    # ۱. ذخیره در کاتالوگ JSON
    try:
        if os.path.exists(CATALOG_FILE):
            with open(CATALOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            updated = False
            if isinstance(data, dict):
                if pid in data:
                    data[pid]["ai_specs"] = specs
                    data[pid]["more_details"] = spec_str
                    updated = True
                else:
                    for _, v in data.items():
                        if str(v.get("product_id")) == str(pid):
                            v["ai_specs"] = specs
                            v["more_details"] = spec_str
                            updated = True
                            break
            elif isinstance(data, list):
                for item in data:
                    if str(item.get("product_id")) == str(pid):
                        item["ai_specs"] = specs
                        item["more_details"] = spec_str
                        updated = True
                        break

            if updated:
                with open(CATALOG_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                logger.info(f"💾 [AI DISK SAVED] مشخصات کالا {pid} برای همیشه در کاتالوگ ذخیره شد.")
    except Exception as e:
        logger.error(f"Error saving AI specs for {pid} to JSON: {e}")

    # ۲. ذخیره در جدول SQLite
    try:
        if os.path.exists(DB_FILE):
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            specs_json = json.dumps(specs, ensure_ascii=False)
            cursor.execute("""
                UPDATE products
                SET specs_json = ?, more_details = ?, updated_at = CURRENT_TIMESTAMP
                WHERE product_id = ?
            """, (specs_json, spec_str, pid))
            conn.commit()
            conn.close()
            logger.info(f"💾 [AI DB SAVED] مشخصات کالا {pid} در جدول دیتابیس SQLite ثبت شد.")
    except Exception as e:
        logger.error(f"Error saving AI specs for {pid} to SQLite: {e}")

# ─── روال اصلی On-Demand با مدیریت ارائه‌دهنده فعال ───

async def async_enrich_product_with_gemini_on_demand(
    product: dict,
    force: bool = False,
    return_error: bool = False
) -> Any:
    """
    روال آن‌دیمند یکپارچه:
    ۱. بررسی وضعیت هوش مصنوعی (خاموش/روشن، جمینای یا دیپ‌سیک)
    ۲. بررسی اینکه آیا کالا از قبل مشخصات دارد؟ (در صورت داشتن مشخصات ۰ معطلی، مگر اینکه force=True باشد)
    ۳. استخراج منحصراً مشخصات واقعی کارخانه‌ای مدل
    ۴. ذخیره‌سازی دائمی یکبار برای همیشه
    """
    if not product or not isinstance(product, dict):
        return (False, "اطلاعات کالا معتبر نیست") if return_error else False

    # بررسی تنظیمات فعال ادمین
    ai_settings = get_ai_settings()
    provider = ai_settings.get("provider", "gemini")

    if provider in ["off", "disabled"]:
        logger.debug("AI specs enrichment is currently disabled by admin.")
        return (False, "هوش مصنوعی در تنظیمات پنل ادمین خاموش است.") if return_error else False

    # بررسی اولیه مشخصات کالا (در صورت force بودن بازنویسی می‌شود)
    if not force and product_has_specs(product):
        return (False, "کالا از قبل دارای مشخصات فنی کامل است.") if return_error else False

    pname = product.get("name", "")
    if not pname:
        return (False, "نام کالا خالی است.") if return_error else False

    specs = None
    err_detail = ""

    if provider == "gemini":
        api_key = get_gemini_api_key()
        if not api_key:
            err_msg = "کلید GEMINI_API_KEY تنظیم نشده یا نامعتبر است."
            logger.debug(err_msg)
            return (False, err_msg) if return_error else False
        logger.info(f"🤖 [GEMINI LAZY] استعلام مشخصات موثق برای: '{pname}'...")
        try:
            specs, err_detail = await asyncio.wait_for(
                asyncio.to_thread(call_gemini_api_with_error, api_key, product),
                timeout=8.5
            )
        except Exception as e:
            logger.warning(f"Gemini on-demand note for '{pname}': {e}")
            return (False, f"تایم‌اوت یا خطای شبکه: {e}") if return_error else False

    elif provider == "deepseek":
        api_key = get_deepseek_api_key()
        if not api_key:
            err_msg = "کلید DEEPSEEK_API_KEY تنظیم نشده است."
            logger.debug(err_msg)
            return (False, err_msg) if return_error else False
        logger.info(f"🤖 [DEEPSEEK LAZY] استعلام مشخصات موثق برای: '{pname}'...")
        try:
            specs, err_detail = await asyncio.wait_for(
                asyncio.to_thread(call_deepseek_api_with_error, api_key, product),
                timeout=10.0
            )
        except Exception as e:
            logger.warning(f"DeepSeek on-demand note for '{pname}': {e}")
            return (False, f"تایم‌اوت یا خطای شبکه: {e}") if return_error else False

    if specs and isinstance(specs, dict):
        product["ai_specs"] = specs
        if not isinstance(product.get("specs"), dict):
            product["specs"] = {}
        for k, v in specs.items():
            product["specs"][k] = v
        product["more_details"] = " | ".join([f"{k}: {v}" for k, v in specs.items()])

        pid = str(product.get("product_id") or "").strip()

        # به‌روزرسانی کش درون‌حافظه‌ای ربات
        try:
            from search_engine import JSON_PRODUCTS
            for p in JSON_PRODUCTS:
                if str(p.get("product_id")) == pid:
                    p["ai_specs"] = specs
                    if not isinstance(p.get("specs"), dict):
                        p["specs"] = {}
                    for k, v in specs.items():
                        p["specs"][k] = v
                    p["more_details"] = product["more_details"]
                    break
        except Exception:
            pass

        # ذخیره‌سازی دائمی یکبار برای همیشه در پس‌زمینه
        if pid:
            asyncio.create_task(asyncio.to_thread(sync_save_ai_specs, pid, specs))

        logger.info(f"🎉 [AI APPLIED] مشخصات کالا '{pname}' با موفقیت روی کارت اعمال و ذخیره شد.")
        return (True, "") if return_error else True

    return (False, err_detail or "مدل هوش مصنوعی مشخصاتی برای این مدل استخراج نکرد.") if return_error else False


# ─── سیستم تکمیل گروهی و دسته‌ای مشخصات با گوگل جمینای ───

_BATCH_STATUS = {
    "is_running": False,
    "mode": None,
    "total": 0,
    "current": 0,
    "success": 0,
    "failed": 0,
    "stop_requested": False,
    "start_time": 0.0,
    "current_product": ""
}

def get_batch_enrichment_status() -> dict:
    return dict(_BATCH_STATUS)

def stop_gemini_batch_enrichment() -> bool:
    if _BATCH_STATUS["is_running"]:
        _BATCH_STATUS["stop_requested"] = True
        return True
    return False

async def run_gemini_batch_enrichment(mode: str, bot, chat_id: int, message_id: int):
    """
    پردازش پس‌زمینه تکمیل دسته‌ای مشخصات کالاها منحصراً با Google Gemini.
    - mode == 'no_specs': کالاهای کاملاً فاقد مشخصات (۰ مورد)
    - mode == 'under_3': کالاهای با مشخصات کمتر از ۳ مورد
    """
    global _BATCH_STATUS
    if _BATCH_STATUS["is_running"]:
        return

    _BATCH_STATUS["is_running"] = True
    _BATCH_STATUS["mode"] = mode
    _BATCH_STATUS["total"] = 0
    _BATCH_STATUS["current"] = 0
    _BATCH_STATUS["success"] = 0
    _BATCH_STATUS["failed"] = 0
    _BATCH_STATUS["stop_requested"] = False
    _BATCH_STATUS["start_time"] = time.time()
    _BATCH_STATUS["current_product"] = ""

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    mode_title = (
        "کالاهای کاملاً فاقد مشخصات فنی (۰ مشخصه)"
        if mode == "no_specs"
        else "کالاهای با مشخصات ناقص (۳ مشخصه و کمتر)"
    )

    btn_stop = InlineKeyboardButton("🛑 توقف عملیات", callback_data="adm_ai_batch_stop")
    kb_running = InlineKeyboardMarkup([[btn_stop]])

    api_key = get_gemini_api_key()
    if not api_key:
        _BATCH_STATUS["is_running"] = False
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=(
                    "❌ <b>خطا در دسترسی به کلید API جمینای!</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "کلید اختصاصی Google Gemini یافت نشد. لطفاً ابتدا از منوی هوش مصنوعی کلید خود را ثبت فرمایید."
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به تنظیمات هوش مصنوعی", callback_data="adm_ai_settings")]])
            )
        except Exception:
            pass
        return

    targets = get_products_for_batch_enrich(mode)
    _BATCH_STATUS["total"] = len(targets)

    if not targets:
        _BATCH_STATUS["is_running"] = False
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=(
                    f"🎉 <b>تمام کالاهای این بخش دارای مشخصات فنی کامل هستند!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"▫️ بخش انتخابی: <b>{mode_title}</b>\n"
                    f"▫️ هیچ کالایی نیازمند پردازش و استخراج مشخصات جدید یافت نشد."
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به تنظیمات هوش مصنوعی", callback_data="adm_ai_settings")]])
            )
        except Exception:
            pass
        return

    last_edit_time = 0.0

    for idx, product in enumerate(targets):
        if _BATCH_STATUS["stop_requested"]:
            logger.info("🛑 عملیات تکمیل مشخصات توسط ادمین متوقف شد.")
            break

        _BATCH_STATUS["current"] = idx + 1
        pid = str(product.get("product_id") or "")
        pname = str(product.get("name") or f"کد {pid}")
        _BATCH_STATUS["current_product"] = pname

        now = time.time()
        # بروزرسانی وضعیت تلگرام (حداکثر هر ۴.۵ ثانیه یکبار برای رعایت محدودیت Rate Limit تلگرام)
        if (now - last_edit_time > 4.5) or idx == 0:
            elapsed_sec = int(now - _BATCH_STATUS["start_time"])
            mins, secs = divmod(elapsed_sec, 60)
            pct = int((idx / len(targets)) * 100) if len(targets) > 0 else 0
            filled_bars = min(10, pct // 10)
            progress_bar = "▓" * filled_bars + "░" * (10 - filled_bars)

            status_text = (
                f"⚙️ <b>در حال استخراج مشخصات فنی با Google Gemini...</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"▫️ دسته پردازش: <b>{mode_title}</b>\n"
                f"▫️ پیشرفت: <b>{idx + 1} از {len(targets)}</b> ({pct}%)\n"
                f"<code>[{progress_bar}]</code>\n\n"
                f"▫️ کالای در حال بررسی: <code>{pname[:38]}</code>\n"
                f"▫️ ✅ ثبت موفق: <b>{_BATCH_STATUS['success']}</b> کالا\n"
                f"▫️ ⏭ نامشخص / ردشده: <b>{_BATCH_STATUS['failed']}</b> کالا\n"
                f"▫️ ⏱ زمان سپری‌شده: <b>{mins:02d}:{secs:02d}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 <i>مشخصات ۱۰۰٪ بر اساس کد مدل کارخانه استخراج شده و فاقد هرگونه رنگ هستند.</i>"
            )
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=status_text,
                    parse_mode="HTML",
                    reply_markup=kb_running
                )
                last_edit_time = now
            except Exception:
                pass

        # فراخوانی API جمینای
        try:
            specs, err = await asyncio.wait_for(
                asyncio.to_thread(call_gemini_api_with_error, api_key, product),
                timeout=18.0
            )
        except Exception as e:
            specs, err = None, str(e)

        if specs and isinstance(specs, dict) and len(specs) >= 2:
            # اعمال روی شیء کالا
            product["ai_specs"] = specs
            if not isinstance(product.get("specs"), dict):
                product["specs"] = {}
            for k, v in specs.items():
                product["specs"][k] = v
            product["more_details"] = " | ".join([f"{k}: {v}" for k, v in specs.items()])

            # اعمال در کش حافظه
            try:
                from search_engine import JSON_PRODUCTS
                for p in JSON_PRODUCTS:
                    if str(p.get("product_id")) == pid:
                        p["ai_specs"] = specs
                        if not isinstance(p.get("specs"), dict):
                            p["specs"] = {}
                        for k, v in specs.items():
                            p["specs"][k] = v
                        p["more_details"] = product["more_details"]
                        break
            except Exception:
                pass

            # ذخیره‌سازی دائمی دیسک و SQLite
            if pid:
                await asyncio.to_thread(sync_save_ai_specs, pid, specs)

            _BATCH_STATUS["success"] += 1
            logger.info(f"✅ [BATCH GEMINI] ({idx+1}/{len(targets)}) '{pname}' با {len(specs)} مشخصه فنی ذخیره شد.")
        else:
            _BATCH_STATUS["failed"] += 1
            logger.info(f"⏭ [BATCH GEMINI] ({idx+1}/{len(targets)}) '{pname}': مشخصاتی دریافت نشد ({err[:80]})")

        # فاصله کوتاه برای جلوگیری از Rate Limit
        await asyncio.sleep(1.8)

    # پایان عملیات و ارسال گزارش نهایی
    total_time = int(time.time() - _BATCH_STATUS["start_time"])
    mins, secs = divmod(total_time, 60)
    was_stopped = _BATCH_STATUS["stop_requested"]
    success_count = _BATCH_STATUS["success"]
    failed_count = _BATCH_STATUS["failed"]
    processed_count = _BATCH_STATUS["current"]
    total_count = len(targets)

    _BATCH_STATUS["is_running"] = False
    _BATCH_STATUS["stop_requested"] = False

    kb_done = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت به تنظیمات هوش مصنوعی", callback_data="adm_ai_settings")]
    ])

    title = "🛑 <b>عملیات تکمیل مشخصات توسط ادمین متوقف شد.</b>" if was_stopped else "🏁 <b>عملیات تکمیل مشخصات با موفقیت به پایان رسید!</b>"
    final_text = (
        f"{title}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"▫️ بخش: <b>{mode_title}</b>\n"
        f"▫️ موتور هوش مصنوعی: <b>گوگل جمینای (Google Gemini ♊️)</b>\n"
        f"▫️ کل اقلام بررسی‌شده: <b>{processed_count} از {total_count} کالا</b>\n"
        f"▫️ ✅ تکمیل موفق مشخصات فنی: <b>{success_count} کالا</b>\n"
        f"▫️ ⏭ اقلام فاقد مدارک رسمی کارخانه: <b>{failed_count} کالا</b>\n"
        f"▫️ ⏱ مدت زمان عملیات: <b>{mins:02d}:{secs:02d}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💾 تمامی مشخصات جدید در کاتالوگ و پایگاه داده به‌صورت دائمی ذخیره شدند."
    )

    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=final_text,
            parse_mode="HTML",
            reply_markup=kb_done
        )
    except Exception:
        try:
            await bot.send_message(chat_id=chat_id, text=final_text, parse_mode="HTML", reply_markup=kb_done)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# 🌟 بخش تولید هوشمند توضیحات تکمیلی محصولات (AI Generated Description)
# ═══════════════════════════════════════════════════════════════════════════

def sync_save_ai_description(pid: str, description: str):
    """ذخیره دائمی فیلد ai_generated_description در کاتالوگ دیسک، حافظه و دیتابیس SQLite برای تمامی دسته‌ها (اصلی، آاگ، صوتی، لپ‌تاپ)"""
    if not pid or not description:
        return

    clean_pid = str(pid).strip()
    clean_desc = str(description).strip()

    # ۱. ذخیره در کش حافظه موتور جستجو
    try:
        from search_engine import JSON_PRODUCTS
        for p in JSON_PRODUCTS:
            p_id = str(p.get("product_id") or p.get("id") or "").strip()
            if p_id == clean_pid or p_id.lower() == clean_pid.lower():
                p["ai_generated_description"] = clean_desc
    except Exception as e:
        logger.debug(f"Error updating JSON_PRODUCTS memory with AI description: {e}")

    # ۲. ذخیره در کاتالوگ‌های JSON دیسک (کاتالوگ اصلی، محصولات آاگ، سیستم‌های صوتی، لپ‌تاپ‌ها)
    target_files = [
        CATALOG_FILE,
        "momtazkalla_all_products.json",
        "aeg_products.json",
        "audio_catalog.json",
        "laptops_catalog.json"
    ]
    for cat_f in target_files:
        try:
            if os.path.exists(cat_f):
                with open(cat_f, "r", encoding="utf-8") as f:
                    data = json.load(f)
                updated = False
                if isinstance(data, dict):
                    if clean_pid in data:
                        data[clean_pid]["ai_generated_description"] = clean_desc
                        updated = True
                    else:
                        for _, v in data.items():
                            if str(v.get("product_id") or v.get("id", "")) == clean_pid:
                                v["ai_generated_description"] = clean_desc
                                updated = True
                                break
                elif isinstance(data, list):
                    for item in data:
                        if str(item.get("product_id") or item.get("id", "")) == clean_pid:
                            item["ai_generated_description"] = clean_desc
                            updated = True
                            break
                if updated:
                    with open(cat_f, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    logger.info(f"💾 [AI DESC DISK SAVED] توضیحات تکمیلی کالا {clean_pid} در {cat_f} ثبت شد.")
        except Exception as e:
            logger.error(f"Error saving AI description to {cat_f} for {clean_pid}: {e}")

    # ۳. ذخیره در جدول SQLite
    try:
        if os.path.exists(DB_FILE):
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE products
                SET ai_generated_description = ?, updated_at = CURRENT_TIMESTAMP
                WHERE product_id = ?
            """, (clean_desc, clean_pid))
            conn.commit()
            conn.close()
    except Exception as e:
        logger.error(f"Error saving AI description to SQLite for {clean_pid}: {e}")


def generate_product_description_with_deepseek(api_key: str, product: dict) -> Tuple[Optional[str], str]:
    """تولید توضیحات تکمیلی و معرفی تخصصی با DeepSeek"""
    if not api_key:
        return None, "کلید DEEPSEEK_API_KEY تنظیم نشده است."

    pname = str(product.get("name", "")).strip()
    brand = str(product.get("brand", "")).strip()
    category = str(product.get("category") or product.get("category_name") or product.get("category_key") or "لوازم خانگی").strip()
    subcategory = str(product.get("subcategory") or "").strip()
    specs = product.get("specs", {})
    if isinstance(specs, str):
        try:
            specs = json.loads(specs)
        except Exception:
            specs = {}
    specs_summary = ""
    if isinstance(specs, dict):
        specs_summary = "\n".join([f"- {k}: {v}" for k, v in specs.items() if v])

    prompt = f"""شما کارشناس بازاریابی و کپی‌رایتر فنی فروشگاه اینترنتی لوازم خانگی و دیجیتال هستید.
برای محصول زیر ۳ تا ۵ ویژگی برجسته، کاملاً واقعی، جذاب و ترغیب‌کننده به زبان فارسی روان بنویسید:

نام محصول: {pname}
برند: {brand}
دسته‌بندی: {category} {f'({subcategory})' if subcategory else ''}
مشخصات فنی:
{specs_summary if specs_summary else '- مشخصات استاندارد کارخانه'}

قوانین مهم:
۱. هر خط حتماً با علامت «▫️ » شروع شود.
۲. روی فناوری‌های کلیدی، راندمان انرژی، کیفیت ساخت و مزیت‌های کاربردی واقعی تمرکز کنید.
۳. از ادعاهای اغراق‌آمیز زرد و گارانتی‌های خیالی پرهیز کنید.
۴. خروجی فقط و فقط خطوط بالت‌پوینت باشد (بدون تیتر، بدون مقدمه، بدون مارک‌داون اضافی)."""

    endpoint = f"{DEFAULT_DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"
    models_to_try = [DEFAULT_DEEPSEEK_MODEL, FALLBACK_DEEPSEEK_MODEL]
    last_error = "پاسخی از DeepSeek دریافت نشد."

    for model_name in models_to_try:
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": "تو کپی‌رایتر ارشد فنی فروشگاهی هستی."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 700,
            "temperature": 0.2,
            "stream": False
        }

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            },
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=12.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choice = data.get("choices", [{}])[0]
                content = (choice.get("message", {}).get("content") or "").strip()
                if content and len(content) > 20:
                    clean_lines = []
                    for line in content.splitlines():
                        l = line.strip().lstrip("*-• ").strip()
                        if l and not l.startswith("```"):
                            if not l.startswith("▫️"):
                                l = f"▫️ {l}"
                            clean_lines.append(l)
                    if clean_lines:
                        res = "\n".join(clean_lines)
                        logger.info(f"✨ [DEEPSEEK DESC] توضیحات تکمیلی '{pname}' از مدل {model_name} با موفقیت تولید شد.")
                        return res, ""
        except urllib.error.HTTPError as he:
            err_body = he.read().decode("utf-8", errors="ignore")
            last_error = f"HTTP {he.code}: {err_body[:180]}"
        except Exception as e:
            last_error = str(e)

    return None, last_error


def generate_product_description_with_gemini(api_key: str, product: dict) -> Tuple[Optional[str], str]:
    """تولید توضیحات تکمیلی و معرفی تخصصی با هوش مصنوعی (پشتیبانی هوشمند از Gemini و DeepSeek)"""
    settings = get_ai_settings()
    active_p = settings.get("provider", "gemini")

    if active_p == "deepseek":
        ds_key = get_deepseek_api_key() or api_key
        if ds_key:
            return generate_product_description_with_deepseek(ds_key, product)

    if not api_key:
        return None, "کلید GEMINI_API_KEY تنظیم نشده است."

    pname = str(product.get("name", "")).strip()
    brand = str(product.get("brand", "")).strip()
    category = str(product.get("category") or product.get("category_name") or product.get("category_key") or "لوازم خانگی").strip()
    subcategory = str(product.get("subcategory") or "").strip()
    specs = product.get("specs", {})
    if isinstance(specs, str):
        try:
            specs = json.loads(specs)
        except Exception:
            specs = {}
    specs_summary = ""
    if isinstance(specs, dict):
        specs_summary = "\n".join([f"- {k}: {v}" for k, v in specs.items() if v])

    # راهنمای تخصصی دسته‌بندی برای افزایش دقت و کیفیت خروجی مدل
    is_aeg = "aeg" in (brand + " " + category + " " + pname).lower() or "آاگ" in (brand + " " + category + " " + pname) or str(product.get("product_id", "")).startswith("AEG")
    is_audio = any(w in (category + " " + subcategory + " " + pname).lower() for w in ["audio", "صوتی", "speaker", "soundbar", "partybox", "اسپیکر", "ساندبار", "پارتی باکس", "هدفون", "jbl"]) or str(product.get("product_id", "")).startswith("AUD")
    is_laptop = any(w in (category + " " + subcategory + " " + pname).lower() for w in ["laptop", "لپ‌تاپ", "لپ تاپ", "لپتاپ"]) or str(product.get("product_id", "")).startswith("LAP")

    category_guideline = ""
    if is_aeg:
        category_guideline = """
- This is an authentic German AEG luxury appliance (یخچال، ماشین لباسشویی، ظرفشویی، فر توکار/مایکرویو یا جاروبرقی آاگ).
- Emphasize German engineering, ProSense smart sensors, ProSteam steam care, AirDry/AutoDoor, Steamify oven steam, ÖKOMix pre-mixing, quiet decibel operation, and energy-saving EcoInverter.
"""
    elif is_audio:
        category_guideline = """
- This is a high-performance Audio System / PartyBox Speaker / Soundbar / Headphones (سیستم صوتی / اسپیکر پارتی‌باکس / ساندبار).
- Emphasize total acoustic power & RMS wattage, punchy bass (Bass Boost / Deep Bass), crystal-clear highs, connectivity (Bluetooth 5.x, TWS stereo pairing, Optical / HDMI eARC, AUX), battery life & charging (for portable models), dynamic light show (رقص نور هوشمند), and water resistance (IPX4/IPX7/IP67).
"""
    elif is_laptop:
        category_guideline = """
- This is a laptop / workstation computer (لپ‌تاپ).
- Emphasize CPU speed & multitasking, RAM/SSD responsiveness, display color accuracy & refresh rate, ergonomics, and cooling.
"""

    prompt = f"""You are a professional Persian technical copywriter and consumer electronics specialist for the AiKala store.
Generate a concise, elegant, highly persuasive, and accurate Persian complementary description (معرفی و نکات برجسته محصول) for this item:

Product: {pname}
Brand: {brand}
Category: {category} {f'({subcategory})' if subcategory else ''}
Technical Highlights:
{specs_summary}
{category_guideline}

Rules:
1. Write 3 to 5 structured, high-value Persian bullet points.
2. Each bullet point MUST start with '▫️ ' (e.g. '▫️ موتور قدرتمند اینورتر دیجیتال با مصرف بهینه A+++ و طول عمر بسیار بالا').
3. Focus on real technologies, build materials, energy efficiency, user convenience, and key selling advantages.
4. DO NOT invent fake warranties or fictional details. Keep it realistic and brand-accurate.
5. Return ONLY the bullet points, one per line. No introduction, no markdown headings, no JSON.
"""

    # برای تولید محتوا و کپی‌رایتینگ، اولویت با flash (لحن غنی‌تر و ادبیات جذاب‌تر) است
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

    last_error = "پاسخی از مدل دریافت نشد."

    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 700
            }
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=12.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                candidates = data.get("candidates", [])
                if not candidates:
                    continue
                parts = candidates[0].get("content", {}).get("parts", [])
                if not parts:
                    continue
                raw_text = parts[0].get("text", "").strip()
                if raw_text and len(raw_text) > 20:
                    clean_lines = []
                    for line in raw_text.splitlines():
                        l = line.strip().lstrip("*-• ").strip()
                        if l and not l.startswith("```"):
                            if not l.startswith("▫️"):
                                l = f"▫️ {l}"
                            clean_lines.append(l)
                    if clean_lines:
                        res = "\n".join(clean_lines)
                        logger.info(f"✨ [GEMINI DESC] توضیحات تکمیلی '{pname}' از مدل {model_name} با موفقیت تولید شد.")
                        return res, ""
        except urllib.error.HTTPError as he:
            err_body = he.read().decode("utf-8", errors="ignore")
            last_error = f"HTTP {he.code}: {err_body[:180]}"
            if he.code in [400, 403] and ("API key not valid" in err_body or "API_KEY_INVALID" in err_body):
                return None, f"کلید API نامعتبر است (HTTP {he.code})"
            if he.code == 429:
                last_error = f"سهمیه مدل {model_name} تکمیل است (Rate Limit 429)."
                continue
        except Exception as e:
            last_error = str(e)

    return None, last_error


class BatchDescCounts(dict):
    """دیکشنری هوشمند شمارش وضعیت توضیحات با سازگاری دوگانه: دسترسی دیکشنری و بازگشایی ۲ مقداری (no_desc, total)"""
    def __iter__(self):
        yield self.get("all", {}).get("no_desc", 0)
        yield self.get("all", {}).get("total", 0)


def get_batch_description_counts() -> BatchDescCounts:
    """تعداد کل محصولات و تعداد کالاهای فاقد توضیحات تکمیلی هوش مصنوعی به تفکیک دسته‌ها"""
    from search_engine import JSON_PRODUCTS, load_json_products
    if not JSON_PRODUCTS:
        load_json_products()

    counts = BatchDescCounts({
        "all": {"total": 0, "no_desc": 0},
        "aeg": {"total": 0, "no_desc": 0},
        "audio": {"total": 0, "no_desc": 0},
        "laptop": {"total": 0, "no_desc": 0},
        "main": {"total": 0, "no_desc": 0}
    })

    for p in JSON_PRODUCTS:
        pid = str(p.get("product_id") or p.get("id") or "").strip()
        cat = str(p.get("category") or p.get("category_name") or p.get("category_key") or "").lower()
        subcat = str(p.get("subcategory") or "").lower()
        brand = str(p.get("brand") or "").lower()
        pname = str(p.get("name") or "").lower()

        has_desc = bool(str(p.get("ai_generated_description") or "").strip())

        counts["all"]["total"] += 1
        if not has_desc:
            counts["all"]["no_desc"] += 1

        is_aeg = "aeg" in (brand + " " + cat + " " + pname) or "آاگ" in (brand + " " + cat + " " + pname) or pid.startswith("AEG")
        is_audio = "audio" in (cat + " " + subcat + " " + pname) or "صوتی" in (cat + " " + subcat + " " + pname) or pid.startswith("AUD")
        is_laptop = "laptop" in (cat + " " + subcat + " " + pname) or "لپ" in (cat + " " + subcat + " " + pname) or pid.startswith("LAP")

        if is_aeg:
            counts["aeg"]["total"] += 1
            if not has_desc:
                counts["aeg"]["no_desc"] += 1
        elif is_audio:
            counts["audio"]["total"] += 1
            if not has_desc:
                counts["audio"]["no_desc"] += 1
        elif is_laptop:
            counts["laptop"]["total"] += 1
            if not has_desc:
                counts["laptop"]["no_desc"] += 1
        else:
            counts["main"]["total"] += 1
            if not has_desc:
                counts["main"]["no_desc"] += 1

    return counts


def get_products_for_description_batch(mode: str = "missing") -> List[dict]:
    """
    لیست محصولات جهت تولید توضیحات تکمیلی بر اساس مود انتخابی:
    - 'missing': کلیه کالاهای فاقد توضیحات در تمام کاتالوگ
    - 'all': تمام کالاهای کاتالوگ
    - 'aeg' / 'aeg_missing': محصولات آاگ (کل یا فاقد توضیحات)
    - 'audio' / 'audio_missing': سیستم‌های صوتی (کل یا فاقد توضیحات)
    - 'laptop' / 'laptop_missing': لپ‌تاپ‌ها (کل یا فاقد توضیحات)
    """
    from search_engine import JSON_PRODUCTS, load_json_products
    if not JSON_PRODUCTS:
        load_json_products()

    prods = list(JSON_PRODUCTS)
    filtered = []

    for p in prods:
        pid = str(p.get("product_id") or p.get("id") or "").strip()
        cat = str(p.get("category") or p.get("category_name") or p.get("category_key") or "").lower()
        subcat = str(p.get("subcategory") or "").lower()
        brand = str(p.get("brand") or "").lower()
        pname = str(p.get("name") or "").lower()
        has_desc = bool(str(p.get("ai_generated_description") or "").strip())

        is_aeg = "aeg" in (brand + " " + cat + " " + pname) or "آاگ" in (brand + " " + cat + " " + pname) or pid.startswith("AEG")
        is_audio = "audio" in (cat + " " + subcat + " " + pname) or "صوتی" in (cat + " " + subcat + " " + pname) or pid.startswith("AUD")
        is_laptop = "laptop" in (cat + " " + subcat + " " + pname) or "لپ" in (cat + " " + subcat + " " + pname) or pid.startswith("LAP")

        if mode == "missing":
            if not has_desc:
                filtered.append(p)
        elif mode == "all":
            filtered.append(p)
        elif mode == "aeg_missing":
            if is_aeg and not has_desc:
                filtered.append(p)
        elif mode == "aeg":
            if is_aeg:
                filtered.append(p)
        elif mode == "audio_missing":
            if is_audio and not has_desc:
                filtered.append(p)
        elif mode == "audio":
            if is_audio:
                filtered.append(p)
        elif mode == "laptop_missing":
            if is_laptop and not has_desc:
                filtered.append(p)
        elif mode == "laptop":
            if is_laptop:
                filtered.append(p)
        else:
            if not has_desc:
                filtered.append(p)

    return filtered


_DESC_BATCH_STATUS = {
    "is_running": False,
    "total": 0,
    "current": 0,
    "success": 0,
    "failed": 0,
    "stop_requested": False,
    "start_time": 0.0,
    "current_product": "",
    "mode_title": ""
}

def get_description_batch_status() -> dict:
    return dict(_DESC_BATCH_STATUS)

def stop_description_batch() -> bool:
    if _DESC_BATCH_STATUS["is_running"]:
        _DESC_BATCH_STATUS["stop_requested"] = True
        return True
    return False

async def run_gemini_description_batch(bot, chat_id: int, message_id: int, mode: str = "missing"):
    """
    پردازش صف با Rate Limit دقیق ۱۵ درخواست در دقیقه (۴ ثانیه تاخیر بین هر درخواست)
    تولید توضیحات تکمیلی با Gemini API و ذخیره در ai_generated_description
    نمایش Progress Bar و گزارش نهایی به ادمین با parse_mode="HTML"
    """
    global _DESC_BATCH_STATUS
    if _DESC_BATCH_STATUS["is_running"]:
        return

    mode_titles = {
        "missing": "کالاهای فاقد توضیحات (کل کاتالوگ)",
        "all": "تمام محصولات کاتالوگ",
        "aeg_missing": "محصولات آاگ (AEG) فاقد توضیحات",
        "aeg": "کلیه محصولات آاگ (AEG)",
        "audio_missing": "سیستم‌های صوتی فاقد توضیحات",
        "audio": "کلیه سیستم‌های صوتی و اسپیکر",
        "laptop_missing": "لپ‌تاپ‌های فاقد توضیحات",
        "laptop": "کلیه لپ‌تاپ‌ها"
    }
    mode_label = mode_titles.get(mode, "تکمیل هوشمند توضیحات کالاها")

    _DESC_BATCH_STATUS["is_running"] = True
    _DESC_BATCH_STATUS["total"] = 0
    _DESC_BATCH_STATUS["current"] = 0
    _DESC_BATCH_STATUS["success"] = 0
    _DESC_BATCH_STATUS["failed"] = 0
    _DESC_BATCH_STATUS["stop_requested"] = False
    _DESC_BATCH_STATUS["start_time"] = time.time()
    _DESC_BATCH_STATUS["current_product"] = ""
    _DESC_BATCH_STATUS["mode_title"] = mode_label

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    btn_stop = InlineKeyboardButton("🛑 توقف عملیات", callback_data="adm_ai_desc_stop")
    kb_running = InlineKeyboardMarkup([[btn_stop]])

    api_key = get_gemini_api_key()
    if not api_key:
        _DESC_BATCH_STATUS["is_running"] = False
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=(
                    "❌ <b>خطا در دسترسی به کلید API جمینای!</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "کلید اختصاصی Google Gemini یافت نشد. لطفاً ابتدا از منوی هوش مصنوعی کلید خود را ثبت فرمایید."
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به تنظیمات هوش مصنوعی", callback_data="adm_ai_settings")]])
            )
        except Exception:
            pass
        return

    targets = get_products_for_description_batch(mode=mode)
    _DESC_BATCH_STATUS["total"] = len(targets)

    if not targets:
        _DESC_BATCH_STATUS["is_running"] = False
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=(
                    f"🎉 <b>تمامی کالاهای دسته «{mode_label}» دارای توضیحات تکمیلی هوش مصنوعی هستند!</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "▫️ هیچ کالایی نیازمند تولید توضیحات تکمیلی جدید یافت نشد."
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به تنظیمات هوش مصنوعی", callback_data="adm_ai_settings")]])
            )
        except Exception:
            pass
        return

    last_edit_time = 0.0

    for idx, product in enumerate(targets):
        if _DESC_BATCH_STATUS["stop_requested"]:
            logger.info("🛑 عملیات تولید توضیحات تکمیلی توسط ادمین متوقف شد.")
            break

        _DESC_BATCH_STATUS["current"] = idx + 1
        pid = str(product.get("product_id") or product.get("id") or "")
        pname = str(product.get("name") or f"کد {pid}")
        _DESC_BATCH_STATUS["current_product"] = pname

        now = time.time()
        # به‌روزرسانی نوار پیشرفت زنده تلگرام هر ۴.۵ ثانیه
        if (now - last_edit_time > 4.5) or idx == 0:
            elapsed_sec = int(now - _DESC_BATCH_STATUS["start_time"])
            mins, secs = divmod(elapsed_sec, 60)
            pct = int((idx / len(targets)) * 100) if len(targets) > 0 else 0
            filled_bars = min(10, pct // 10)
            progress_bar = "▓" * filled_bars + "░" * (10 - filled_bars)

            status_text = (
                f"✨ <b>در حال تولید توضیحات تکمیلی با Google Gemini...</b>\n"
                f"🏷 <b>بخش در حال پردازش:</b> {mode_label}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"▫️ صف پردازش: <b>Rate Limit استاندارد (۱۵ درخواست در دقیقه)</b>\n"
                f"▫️ پیشرفت: <b>{idx + 1} از {len(targets)}</b> ({pct}%)\n"
                f"<code>[{progress_bar}]</code>\n\n"
                f"▫️ کالای جاری: <code>{pname[:38]}</code>\n"
                f"▫️ ✅ تولید موفق: <b>{_DESC_BATCH_STATUS['success']}</b> کالا\n"
                f"▫️ ⏭ ناموفق/خطا: <b>{_DESC_BATCH_STATUS['failed']}</b> کالا\n"
                f"▫️ ⏱ زمان سپری‌شده: <b>{mins:02d}:{secs:02d}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 <i>توضیحات تکمیلی به صورت کشویی (&lt;blockquote expandable&gt;) در کارت کالا نمایش داده می‌شوند.</i>"
            )
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=status_text,
                    parse_mode="HTML",
                    reply_markup=kb_running
                )
                last_edit_time = now
            except Exception as e_edit:
                logger.debug(f"Progress bar edit note: {e_edit}")

        # تولید متن با جمینای
        desc_text, err = generate_product_description_with_gemini(api_key, product)
        if desc_text:
            sync_save_ai_description(pid, desc_text)
            product["ai_generated_description"] = desc_text
            _DESC_BATCH_STATUS["success"] += 1
        else:
            _DESC_BATCH_STATUS["failed"] += 1
            logger.warning(f"Failed to generate AI description for {pname}: {err}")

        # اعمال دقیق Rate Limit (۱۵ درخواست در دقیقه -> ۴.۰ ثانیه وقفه بین هر درخواست)
        await asyncio.sleep(4.0)

    # پایان عملیات و ارسال گزارش نهایی به ادمین
    total_time = int(time.time() - _DESC_BATCH_STATUS["start_time"])
    tot_mins, tot_secs = divmod(total_time, 60)
    was_stopped = _DESC_BATCH_STATUS["stop_requested"]

    final_header = "🛑 <b>عملیات تولید توضیحات تکمیلی متوقف شد</b>" if was_stopped else "🎉 <b>تکمیل هوشمند توضیحات کاتالوگ با موفقیت پایان یافت!</b>"

    final_report = (
        f"{final_header}\n"
        f"🏷 <b>بخش پردازش‌شده:</b> {mode_label}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>گزارش نهایی پردازش هوش مصنوعی (Google Gemini):</b>\n\n"
        f"▫️ کل کالاهای بررسی‌شده: <b>{_DESC_BATCH_STATUS['current']} از {_DESC_BATCH_STATUS['total']}</b>\n"
        f"▫️ ✅ تولید و ثبت موفق در کاتالوگ: <b>{_DESC_BATCH_STATUS['success']} کالا</b>\n"
        f"▫️ ⚠️ موارد ناموفق یا ردشده: <b>{_DESC_BATCH_STATUS['failed']} کالا</b>\n"
        f"▫️ ⏱ مدت زمان کل عملیات: <b>{tot_mins:02d}:{tot_secs:02d}</b>\n"
        f"▫️ ⚡️ نرخ پردازش: <b>۱۵ درخواست در دقیقه (کنترل‌شده)</b>\n"
        f"▫️ 📦 فرمت نمایش: <b>کشویی با تگ <code>&lt;blockquote expandable&gt;</code></b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"کارت محصولات هم‌اکنون با توضیحات جامع و معرفی حرفه‌ای به‌روزرسانی شدند."
    )

    kb_final = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت به تنظیمات هوش مصنوعی", callback_data="adm_ai_settings")]
    ])

    _DESC_BATCH_STATUS["is_running"] = False

    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=final_report,
            parse_mode="HTML",
            reply_markup=kb_final
        )
    except Exception as e_final:
        logger.warning(f"Could not send final description batch report: {e_final}")
        try:
            await bot.send_message(chat_id=chat_id, text=final_report, parse_mode="HTML", reply_markup=kb_final)
        except Exception:
            pass

