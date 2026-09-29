# -*- coding: utf-8 -*-
"""
سیستم هوشمند ارسال تصادفی درخواست تصاویر برای ادمین‌ها (Photo Request Prompter)
================================================================================
ارسال خودکار و زمان‌بندی‌شده نوتیفیکیشن درخواست عکس برای کالاهای فاقد تصویر به ادمین‌ها
دقیقاً مشابه فرمت درخواست تصویر مشتری با امکان ثبت فوری لینک/پست/عکس با یک کلیک.
"""

import os
import io
import json
import random
import logging
import asyncio
import html as html_lib
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List

from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import ContextTypes

from config import ADMIN_IDS
from keyboards import is_admin, is_owner, get_all_admin_ids, make_safe_cb, resolve_safe_cb

logger = logging.getLogger(__name__)

SETTINGS_FILE = "photo_prompter_settings.json"

DEFAULT_SETTINGS = {
    "enabled": True,
    "interval_mode": "random",  # "random" (تصادفی ۳۰ الی ۹۰ دقیقه) یا "fixed" (ثابت)
    "interval_minutes": 45,
    "next_interval_minutes": 40,
    "last_prompt_time": None,
    "last_product_name": None,
    "last_product_id": None,
    "total_prompted": 0,
    "active_hours_start": 9,
    "active_hours_end": 23,
    "prompted_product_ids": []
}


def load_prompter_settings() -> Dict[str, Any]:
    """بارگذاری تنظیمات ارسال درخواست عکس به ادمین"""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {**DEFAULT_SETTINGS, **data}
        except Exception as e:
            logger.error(f"Error loading {SETTINGS_FILE}: {e}")
    return dict(DEFAULT_SETTINGS)


def save_prompter_settings(settings: Dict[str, Any]) -> None:
    """ذخیره تنظیمات در دیسک"""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving {SETTINGS_FILE}: {e}")


def compute_next_prompt_interval(st: Dict[str, Any]) -> int:
    """محاسبه بازه زمانی بعدی جهت توزیع مناسب در طول روز"""
    mode = st.get("interval_mode", "random")
    if mode == "fixed":
        return max(10, int(st.get("interval_minutes", 45)))

    base_pool = [25, 35, 45, 60, 75, 90]
    base_choice = random.choice(base_pool)
    jitter = random.randint(-5, 5)
    return max(15, base_choice + jitter)


def toggle_prompter_enabled() -> bool:
    """فعال یا غیرفعال‌سازی دستیار ارسال درخواست تصویر"""
    st = load_prompter_settings()
    st["enabled"] = not st.get("enabled", True)
    save_prompter_settings(st)
    return st["enabled"]


def set_prompter_interval_mode(mode: str, fixed_minutes: int = 45) -> Dict[str, Any]:
    """تنظیم حالت بازه زمانی ارسال (تصادفی یا زمان مشخص)"""
    st = load_prompter_settings()
    if mode in ["random", "rand", "تصادفی"]:
        st["interval_mode"] = "random"
        st["next_interval_minutes"] = compute_next_prompt_interval(st)
    else:
        st["interval_mode"] = "fixed"
        st["interval_minutes"] = max(10, int(fixed_minutes))
        st["next_interval_minutes"] = st["interval_minutes"]
    save_prompter_settings(st)
    return st


def product_has_photo(p: Dict[str, Any]) -> bool:
    """بررسی اینکه آیا کالا دارای تصویر معتبر تاییدشده یا وب است یا خیر"""
    if not isinstance(p, dict):
        return False
    pid = str(p.get("product_id") or p.get("id") or "").strip()
    try:
        from photo_service import find_matching_verified_photos
        _, pdata, _ = find_matching_verified_photos(p or pid)
        if pdata and pdata.get("photo_urls"):
            return True
    except Exception:
        pass

    web_img = p.get("image_url")
    if web_img and isinstance(web_img, str) and web_img.startswith("http"):
        return True

    return False


def get_unphotographed_products() -> List[Dict[str, Any]]:
    """دریافت تمامی کالاهای فعال و غیرپنهان کاتالوگ که هنوز فاقد عکس هستند"""
    try:
        from search_engine import JSON_PRODUCTS, load_json_products, is_product_hidden
        if not JSON_PRODUCTS:
            load_json_products()
        prods = JSON_PRODUCTS or []
    except Exception as e:
        logger.warning(f"Error fetching products for prompter: {e}")
        prods = []

    unphotographed = []
    seen = set()
    for p in prods:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("product_id") or p.get("id") or "").strip()
        if not pid or pid in seen:
            continue
        try:
            from search_engine import is_product_hidden
            if is_product_hidden(p):
                continue
        except Exception:
            pass

        if not product_has_photo(p):
            seen.add(pid)
            unphotographed.append(p)

    return unphotographed


def select_random_unphotographed_product() -> Optional[Dict[str, Any]]:
    """انتخاب تصادفی یک کالای بدون عکس با مدیریت دوره‌ای برای جلوگیری از تکرار"""
    unphotographed = get_unphotographed_products()
    if not unphotographed:
        return None

    st = load_prompter_settings()
    prompted_set = set(str(x) for x in st.get("prompted_product_ids", []))

    unprompted = [
        p for p in unphotographed
        if str(p.get("product_id") or p.get("id") or "").strip() not in prompted_set
    ]

    if not unprompted:
        st["prompted_product_ids"] = []
        save_prompter_settings(st)
        unprompted = unphotographed

    return random.choice(unprompted)


def build_photo_prompt_message(prod: Dict[str, Any]) -> Tuple[str, InlineKeyboardMarkup]:
    """
    ساخت پیام حرفه‌ای درخواست تصویر مشابه درخواست واقعی مشتری
    با دکمه مستقیم ورود به جریان ثبت تصویر کالا
    """
    pname = prod.get("name", "کالای بدون عنوان")
    pid = str(prod.get("product_id") or prod.get("id") or "").strip()
    raw_brand = prod.get("brand", "")
    try:
        from search_engine import detect_product_brand
        brand = detect_product_brand(pname, raw_brand)
    except Exception:
        brand = raw_brand if raw_brand else "اورجینال"

    category = prod.get("category") or prod.get("category_name") or "لوازم خانگی"

    raw_price = prod.get("price", 0)
    if isinstance(raw_price, (int, float)) and raw_price > 0:
        price_str = f"{int(raw_price):,} تومان"
    elif prod.get("price_formatted"):
        price_str = str(prod["price_formatted"])
    else:
        price_str = "استعلام لحظه‌ای"

    pname_esc = html_lib.escape(str(pname))
    brand_esc = html_lib.escape(str(brand))
    cat_esc = html_lib.escape(str(category))
    price_esc = html_lib.escape(price_str)

    msg_text = (
        f"🔔 <b>درخواست هوشمند تصویر محصول (تکمیل کاتالوگ)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>نام کالا:</b> <b>{pname_esc}</b>\n"
        f"🏷 <b>کد محصول:</b> <code>{pid}</code>\n"
        f"📂 <b>دسته‌بندی:</b> {cat_esc} | 🏷 <b>برند:</b> {brand_esc}\n"
        f"💰 <b>قیمت روز:</b> <code>{price_esc}</code>\n\n"
        f"🤖 <i>سیستم خودکار تکمیل تصاویر این کالا را به عنوان محصول فاقد عکس پیشنهاد می‌دهد:</i>\n"
        f"👇 <i>جهت ارسال تصاویر، دکمه زیر را لمس کرده و لینک پست، شماره پیام یا عکس‌های کانال را بفرستید:</i>"
    )

    admin_cb = make_safe_cb("adm_set_img", f"{pid}|0")
    skip_cb = make_safe_cb("adm_skip_prompt", pid)

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔗 ثبت و ارسال لینک تصاویر این کالا", callback_data=admin_cb)
        ],
        [
            InlineKeyboardButton("⏭ کالای بعدی (بدون عکس)", callback_data=skip_cb),
            InlineKeyboardButton("⚙️ تنظیمات دستیار", callback_data="adm_photo_prompter_menu")
        ]
    ])

    return msg_text, kb


async def send_photo_prompt_to_admins(
    bot: Bot,
    product: Optional[Dict[str, Any]] = None,
    target_admin_id: Optional[int] = None
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    ارسال پیام نوتیفیکیشن درخواست عکس به ادمین(ها)
    """
    if not product:
        product = select_random_unphotographed_product()

    if not product:
        return False, "هیچ محصول بدون عکسی در کاتالوگ یافت نشد. تمامی کالاها دارای تصویر هستند! 🎉", None

    msg_text, kb = build_photo_prompt_message(product)
    pid = str(product.get("product_id") or product.get("id") or "").strip()
    pname = product.get("name", pid)

    recipients = [target_admin_id] if target_admin_id else get_all_admin_ids()
    sent_count = 0

    for adm_id in recipients:
        try:
            await bot.send_message(
                chat_id=adm_id,
                text=msg_text,
                reply_markup=kb,
                parse_mode="HTML"
            )
            sent_count += 1
        except Exception as e:
            logger.warning(f"Could not send photo prompt to admin {adm_id}: {e}")

    if sent_count > 0:
        st = load_prompter_settings()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        st["last_prompt_time"] = now_str
        st["last_product_name"] = pname
        st["last_product_id"] = pid
        st["total_prompted"] = st.get("total_prompted", 0) + 1

        prompted_list = st.get("prompted_product_ids", [])
        if pid and pid not in prompted_list:
            prompted_list.append(pid)
        st["prompted_product_ids"] = prompted_list
        st["next_interval_minutes"] = compute_next_prompt_interval(st)

        save_prompter_settings(st)
        logger.info(f"📸 [PHOTO PROMPTER] Sent photo prompt for '{pname}' ({pid}) to {sent_count} admins.")
        return True, f"درخواست عکس برای کالا «{pname}» با موفقیت به {sent_count} ادمین ارسال گردید.", product

    return False, "ارسال پیام به ادمین‌ها با خطا مواجه شد.", product


async def admin_photo_prompter_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی کنترل و تنظیمات دستیار درخواست تصاویر ادمین"""
    query = update.callback_query
    if query:
        await query.answer()

    st = load_prompter_settings()
    is_en = st.get("enabled", True)
    mode = st.get("interval_mode", "random")
    next_min = st.get("next_interval_minutes", 40)
    total_prompted = st.get("total_prompted", 0)
    last_time = st.get("last_prompt_time") or "تاکنون ارسالی ثبت نشده"
    last_prod = st.get("last_product_name") or "-"

    unphotographed_list = get_unphotographed_products()
    unphoto_count = len(unphotographed_list)

    try:
        from search_engine import JSON_PRODUCTS
        total_prods = len(JSON_PRODUCTS) if JSON_PRODUCTS else 0
    except Exception:
        total_prods = 0

    status_icon = "🟢 <b>فعال و خودکار</b>" if is_en else "🔴 <b>غیرفعال (متوقف)</b>"
    mode_desc = f"تصادفی ضد اسپم (~{next_min} دقیقه دیگر)" if mode == "random" else f"ثابت (هر {st.get('interval_minutes', 45)} دقیقه)"

    menu_text = (
        f"📸 <b>دستیار هوشمند ارسال درخواست تصاویر به ادمین‌ها</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"▫️ وضعیت دستیار: {status_icon}\n"
        f"▫️ شیوه زمان‌بندی: <b>{mode_desc}</b>\n"
        f"▫️ ساعات فعالیت: <b>{st.get('active_hours_start', 9)} الی {st.get('active_hours_end', 23)}</b>\n\n"
        f"📊 <b>آمار تصاویر کاتالوگ:</b>\n"
        f"▫️ کالاهای فاقد عکس: <b>{unphoto_count:,} کالا</b> (از مجموع {total_prods:,})\n"
        f"▫️ کل درخواست‌های ارسالی تاکنون: <b>{total_prompted:,} عدد</b>\n"
        f"▫️ آخرین کالا ارسالی: <b>{last_prod}</b> (<code>{last_time}</code>)\n\n"
        f"👇 <i>با انتخاب دکمه‌های زیر می‌توانید وضعیت ارسال را مدیریت نمایید:</i>"
    )

    toggle_btn_text = "🔴 خاموش کردن ارسال خودکار" if is_en else "🟢 روشن کردن ارسال خودکار"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎲 ارسال یک کالا همین الان (تست آنی)", callback_data="adm_prompt_now")
        ],
        [
            InlineKeyboardButton(toggle_btn_text, callback_data="adm_prompt_toggle")
        ],
        [
            InlineKeyboardButton("⏱ زمان‌بندی: تصادفی (۳۰-۹۰ دقیقه)", callback_data="adm_prompt_set_rand"),
            InlineKeyboardButton("⏱ زمان‌بندی: هر ۳۰ دقیقه", callback_data="adm_prompt_set_30")
        ],
        [
            InlineKeyboardButton("⏱ زمان‌بندی: هر ۶۰ دقیقه", callback_data="adm_prompt_set_60"),
            InlineKeyboardButton("⏱ زمان‌بندی: هر ۱۵ دقیقه", callback_data="adm_prompt_set_15")
        ],
        [
            InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="adm_back_panel")
        ]
    ])

    if query and query.message:
        try:
            await query.edit_message_text(menu_text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await query.message.reply_text(menu_text, reply_markup=kb, parse_mode="HTML")
    elif update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=menu_text,
            reply_markup=kb,
            parse_mode="HTML"
        )


async def photo_prompter_background_task(bot: Bot):
    """
    تسک پس‌زمینه که طبق زمان‌بندی برای ادمین‌ها درخواست تصویر کالاهای بدون عکس را ارسال می‌کند.
    """
    logger.info("🚀 [PHOTO PROMPTER] Background task started.")
    # تاخیر اولیه ۵۰ ثانیه‌ای هنگام روشن شدن ربات
    await asyncio.sleep(50)

    while True:
        try:
            st = load_prompter_settings()
            enabled = st.get("enabled", True)

            if not enabled:
                await asyncio.sleep(60)
                continue

            now = datetime.now()
            start_h = st.get("active_hours_start", 9)
            end_h = st.get("active_hours_end", 23)

            # بررسی ساعات مجاز فعالیت
            if not (start_h <= now.hour <= end_h):
                await asyncio.sleep(180)
                continue

            last_time_str = st.get("last_prompt_time")
            interval_min = st.get("next_interval_minutes") or st.get("interval_minutes", 45)

            should_prompt = False
            if not last_time_str:
                should_prompt = True
            else:
                try:
                    last_dt = datetime.strptime(last_time_str, "%Y-%m-%d %H:%M")
                    elapsed_seconds = (now - last_dt).total_seconds()
                    if elapsed_seconds >= (interval_min * 60):
                        should_prompt = True
                except Exception:
                    should_prompt = True

            if should_prompt:
                logger.info("⏱ [PHOTO PROMPTER] Interval reached. Selecting unphotographed product to prompt...")
                success, msg, _ = await send_photo_prompt_to_admins(bot)
                if not success:
                    logger.info(f"ℹ️ [PHOTO PROMPTER] Prompt skipped: {msg}")
                # پس از هر اقدام، حداقل ۴۵ ثانیه مکث
                await asyncio.sleep(45)

        except Exception as e:
            logger.error(f"Error in photo_prompter_background_task: {e}", exc_info=True)

        await asyncio.sleep(60)
