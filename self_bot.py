import ast
import asyncio
import json
import operator
import os
import html as htmllib
import re
import sqlite3
import sys
import time
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
from telethon import TelegramClient, events
from telethon.tl import functions, types
from telethon.errors import (AuthKeyUnregisteredError, FloodWaitError, SessionRevokedError,
                             UserDeactivatedBanError, UserDeactivatedError)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import features
import styles
from manager import setup_manager
from banner import refresh_banner
from games import setup_games
from panel import setup_panel
import extras
import more
import auto

# ================= تنظیمات =================
API_ID = int(os.getenv("API_ID", "123456"))          # از my.telegram.org
API_HASH = os.getenv("API_HASH", "your_api_hash")    # از my.telegram.org
SESSION = os.getenv("SELF_SESSION", "clock_self")
TZ = ZoneInfo("Asia/Tehran")
PREFIX = "."                 # دستورها با این علامت شروع می‌شن: .پینگ
CFG_FILE = os.getenv("SELF_CFG", "self_config.json")
OWNER_ID = int(os.getenv("OWNER_ID") or 0)            # آیدی عددی خودت (از @userinfobot)
MANAGER_TOKEN = os.getenv("MANAGER_BOT_TOKEN")        # بات مدیریت/فعالسازی (اختیاری)
HELPER_TOKEN = os.getenv("HELPER_BOT_TOKEN") or os.getenv("BOT_TOKEN")  # بات هلپر برای پنل inline
BANNER_PATH = os.getenv("BANNER_PATH", "assets/banner.jpg")  # عکس بنر خودت (اختیاری)
HUB_HELPER = os.getenv("HUB_HELPER_USERNAME")        # حالت هاب: یوزرنیم بات هلپر مشترک (پروسه‌ی کاربر)
# برای دستور هوش مصنوعی: export ANTHROPIC_API_KEY=...
# ===========================================

client = TelegramClient(SESSION, API_ID, API_HASH)
START = time.time()

DEFAULT = {
    "enabled": True,
    "clock": True, "clock_mode": "last",
    "base_first": None, "base_last": None,
    "online": False,
    "secretary": False, "secretary_text": "الان سرکارم، بعداً جواب می‌دم 🙏",
    "autoseen": False, "pvlock": False, "antilogin": False,
    "react": None, "action": None, "textmode": None,
    "autoreplies": {}, "muted": [], "filters": {},
    "gbans": [], "friends": [], "friend_words": [],
    "content_on": True, "content": {}, "voice": "زن",
    "clock_first": False, "clock_last": False, "clock_bio": False, "clock_font": "mono",
    "base_bio": None, "clock_chats": {},
    "secretary_minutes": 60, "secretary_msg": None,
    "filter_on": False, "filter_words": [], "filter_users": [], "filter_all": False,
    "act_chat_pv": False, "act_chat_gp": False, "act_game_pv": False, "act_game_gp": False,
    "act_voice_pv": False, "act_voice_gp": False, "act_video_pv": False, "act_video_gp": False,
}


def load():
    c = json.loads(json.dumps(DEFAULT))
    if os.path.exists(CFG_FILE):
        try:
            with open(CFG_FILE, encoding="utf-8") as f:
                c.update(json.load(f))
        except Exception:
            pass
    # مهاجرت از نسخه‌ی قبل: ساعت تک‌کلیدی ← سه کلید جدا؛ اکشن تک‌حالته ← حالت‌های جدا
    if c.get("clock") and not any(c.get(k) for k in ("clock_first", "clock_last", "clock_bio")):
        c["clock_first" if c.get("clock_mode") == "first" else "clock_last"] = True
    c["clock"] = False
    old_act = {"typing": "chat", "record-voice": "voice", "record-video": "video", "game": "game"}.get(c.get("action"))
    if old_act and not any(c.get(f"act_{old_act}_{w}") for w in ("pv", "gp")):
        c[f"act_{old_act}_pv"] = True
    c["action"] = None
    return c


cfg = load()


def save():
    with open(CFG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)


# ---------- ابزارهای کمکی ----------
FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_DG = re.escape(styles.all_clock_digit_chars())
CLOCK_RE = re.compile(rf"\s*[{_DG}]{{2}} : [{_DG}]{{2}}$")
COMMANDS = {}
secretary_seen = {}
autoreply_seen = {}
bot_state = {}
action_seen = {}


def cmd(*names):
    def deco(fn):
        for n in names:
            COMMANDS[n] = fn
        return fn
    return deco


async def out(e, text):
    text = text[:4000]
    try:
        await e.edit(text, parse_mode=None)
    except Exception:
        await e.respond(text, parse_mode=None)


def parse_onoff(a):
    w = a.split()[0] if a else ""
    if w in ("روشن", "on", "1"):
        return True
    if w in ("خاموش", "off", "0"):
        return False
    raise ValueError("بنویس: روشن یا خاموش")


async def target(e, arg):
    if e.is_reply:
        r = await e.get_reply_message()
        return r.sender_id
    if arg:
        a = arg.split()[0]
        ent = await client.get_entity(int(a) if a.lstrip("-").isdigit() else a)
        return ent.id
    if e.is_private:
        return e.chat_id
    raise ValueError("ریپلای کن یا آیدی بده")


def clock_text():
    return datetime.now(TZ).strftime("%H : %M").translate(styles.clock_digits(cfg.get("clock_font")))


def clock_any():
    return bool(cfg["clock_first"] or cfg["clock_last"] or cfg["clock_bio"] or cfg["clock_chats"])


# ---------- ساعت کنار اسم / فامیل / بیو / عنوان چت ----------
clock_state = {"shown": None, "chats": None}


async def snapshot_name(force=False):
    if cfg["base_first"] is not None and not force:
        return
    me = await client.get_me()
    cfg["base_first"] = CLOCK_RE.sub("", me.first_name or "")
    cfg["base_last"] = CLOCK_RE.sub("", me.last_name or "")
    try:
        full = await client(functions.users.GetFullUserRequest(me))
        cfg["base_bio"] = CLOCK_RE.sub("", full.full_user.about or "")
    except Exception:
        cfg["base_bio"] = cfg.get("base_bio") or ""
    save()


async def restore_name(bio=True):
    if cfg["base_first"] is None:
        return
    kw = {"first_name": cfg["base_first"] or "", "last_name": cfg["base_last"] or ""}
    if bio and cfg.get("base_bio") is not None:
        kw["about"] = cfg["base_bio"]
    await client(functions.account.UpdateProfileRequest(**kw))
    clock_state["shown"] = None


async def restore_chats():
    for cid, base in list(cfg["clock_chats"].items()):
        try:
            await set_chat_title(int(cid), base)
        except Exception:
            pass
    clock_state["chats"] = None


async def set_chat_title(chat_id, title):
    ent = await client.get_entity(chat_id)
    if isinstance(ent, types.Channel):
        await client(functions.channels.EditTitleRequest(ent, title[:128]))
    else:
        await client(functions.messages.EditChatTitleRequest(ent.id, title[:128]))


async def apply_clock():
    if not cfg["enabled"] or not clock_any():
        return
    t = clock_text()
    key = (t, cfg["clock_first"], cfg["clock_last"], cfg["clock_bio"], cfg["clock_font"])
    if clock_state["shown"] != key and (cfg["clock_first"] or cfg["clock_last"] or cfg["clock_bio"]):
        f, l = cfg["base_first"] or "", cfg["base_last"] or ""
        kw = {}
        if cfg["clock_first"] or cfg["clock_last"]:
            kw["first_name"] = f"{f} {t}".strip() if cfg["clock_first"] else f
            kw["last_name"] = f"{l} {t}".strip() if cfg["clock_last"] else l
        if cfg["clock_bio"]:
            kw["about"] = f"{(cfg.get('base_bio') or '')[:60]} {t}".strip()
        await client(functions.account.UpdateProfileRequest(**kw))
        clock_state["shown"] = key
    if cfg["clock_chats"] and clock_state["chats"] != (t, cfg["clock_font"]):
        clock_state["chats"] = (t, cfg["clock_font"])
        for cid, base in list(cfg["clock_chats"].items()):
            try:
                await set_chat_title(int(cid), f"{base} {t}")
            except FloodWaitError:
                raise
            except Exception as ex:
                print("chat clock error:", cid, ex)
            await asyncio.sleep(1)


async def clock_loop():
    while True:
        try:
            await apply_clock()
        except FloodWaitError as ex:
            await asyncio.sleep(ex.seconds + 1)
            continue
        except Exception as ex:
            print("clock error:", ex)
        await asyncio.sleep(60 - datetime.now(TZ).second + 0.5)


async def online_loop():
    while True:
        try:
            if cfg["online"] and cfg["enabled"]:
                await client(functions.account.UpdateStatusRequest(offline=False))
        except Exception:
            pass
        await asyncio.sleep(25)


async def antilogin_loop():
    known = None
    while True:
        try:
            if cfg["antilogin"] and cfg["enabled"]:
                auths = (await client(functions.account.GetAuthorizationsRequest())).authorizations
                if known is None:
                    known = {a.hash for a in auths}
                else:
                    for a in auths:
                        if not a.current and a.hash not in known:
                            await client(functions.account.ResetAuthorizationRequest(hash=a.hash))
                            await client.send_message(
                                "me", f"🚨 نشست جدید بسته شد: {a.device_model} | {a.ip} | {a.country}")
            else:
                known = None
        except Exception as ex:
            print("antilogin error:", ex)
        await asyncio.sleep(30)


# ---------- دستورات: عمومی ----------
HELP = f"""📖 دستورات NRT Self (پیشوند: {PREFIX})
⚙️ پنل | پینگ | اطلاعات | ثبت نام
🕒 ساعت روشن/خاموش | ساعت اسم/فامیل/بیو روشن/خاموش | ساعت فونت [نام] | ساعت چت روشن/خاموش
🟢 حالت‌ها:
آنلاین | منشی | تنظیم منشی (ریپلای) | تنظیم زمان منشی 5..60 | منشی متن ...
حالت چت/بازی/ویس/ویدیو مسیج پیوی|گروه روشن/خاموش
متن [ایتالیک/بولد/اسکریپت/فراکتور/دوبل/سنس/مونو/فول ویدث/دایره‌ای/اسپویلر/کوت/خط خورده/زیر خط/رندوم/خاموش]
🛠 ابزارها:
هوا شهر | ارز 100 USD EUR | کریپتو bitcoin | ترجمه en متن | محاسبه 2+2 | هوش مصنوعی سوال
🎙 صدا: متن به ویس [مرد/زن] متن | صدای ویس مرد/زن | ویس به متن (ریپلای)
🎵 آهنگ اسم | 2 | سرچ یوتیوب متن | کیفیت (ریپلای روی عکس)
🎮 تاس | دارت | بولینگ | بسکتبال | کازینو [عدد]
🔁 تبدیل (ریپلای): عکس/ویدیو/گیف/استیکر/دایره به ... مثلا: ویدیو به دایره
👥 گروه:
تگ [تعداد] | همه | حذف [تعداد] | بن | سیک | آنبن | پین | حذف پین
بن ال | حذف بن ال | لیست بن ال
🫂 دوست: تنظیم دوست | حذف دوست | لیست دوستان | پاکسازی لیست دوستان | تنظیم لیست دوست
تنظیم کلمات دوست متن | تنظیم لیست کلمات دوست | پاکسازی لیست کلمات دوست
📦 محتوا: محتوا روشن/خاموش | محتوا جدید کلمه | ذخیره محتوا کلمه | حذف محتوا کلمه | لیست محتوا
🔒 امنیت:
قفل پیوی | بلاک | آنبلاک | سکوت | رفع سکوت | لیست سکوت | ضد لاگین | بکاپ 500 | بکاپ چت [عدد] (HTML)
فیلتر کلمات روشن/خاموش | فیلتر کلمه متن | حذف فیلتر کلمه متن | اعمال فیلتر آیدی/همه | حذف فیلتر آیدی
لیست فیلتر کلمات | لیست افراد فیلتر | پاکسازی فیلتر کلمات | پاکسازی افراد فیلتر
💎 موجودی | نشست ها | قطع نشست N
🤖 خودکار:
سین خودکار | پاسخ کلمه | جواب | حذف پاسخ کلمه | ری اکشن روشن ❤
🗡 دشمن: تنظیم دشمن | حذف دشمن | لیست دشمن | پاکسازی لیست دشمن
تنظیم فحش متن | حذف فحش متن | لیست فحش | تنظیم لیست فحش (ریپلای فایل)
📣 تبچی (بنر خودکار): تبچی روشن/خاموش | وضعیت تبچی | لیست بنر ها
تنظیم بنر فور/کپی (ریپلای) | حذف بنر N | پاکسازی لیست بنر ها
تنظیم دقیقه بنر دقیقه N | تنظیم/حذف گپ هدف بنر N | تنظیم هدف بنر N (همه)
فور بنر در تعداد (ریپلای)
💥 اسپم متن تعداد  (یا ریپلای: اسپم تعداد) — حداکثر ۳۰۰
📸 اسکرین صفحه [تعداد] | اسکرین صفحه روشن/خاموش | اسکرین صفحه تعداد N
⭐ استارزی: تنظیم عکس استارزی (ریپلای) | تنظیم زمان استارزی HH:MM | استارزی روشن/خاموش
🔴 لایو: لایو عنوان | پخش لینک/اسم (یا ریپلای) | مکث | ادامه | بعدی | صف | قطع
جلو/عقب/برو ثانیه | پنل لایو
🆕 نسخه ۵:
👁 سین خودکار پیوی|گروه|کانال|ربات روشن/خاموش
💬 پاسخ خودکار روشن/خاموش | پاسخ خودکار جدید کلمه | ذخیره پاسخ خودکار کلمه (ریپلای) | حذف پاسخ خودکار کلمه | لیست پاسخ خودکار
❤ تنظیم ری اکشن ایموجی [آیدی] (یا ریپلای) | حذف ری اکشن [آیدی] | لیست ری اکشن | پاکسازی لیست ری اکشن
🥇 تنظیم کامنت اول @ch | حذف کامنت اول @ch | تنظیم کامنت (ریپلای) | لیست کامنت | پاکسازی لیست کامنت
👮 تنظیم ادمین [آیدی/ریپلای] | حذف ادمین | لیست ادمین ها | پاکسازی لیست ادمین | تنظیم پرفیکس ادمین ! (x = بدون پرفیکس)
🐱 میو خودکار | 🐈 پیشی خودکار | 🎣 ماهی گیری خودکار  روشن/خاموش (توی گروه)
تنظیم زمان میو|پیشی|ماهی گیری دقیقه | تنظیم متن میو|پیشی|ماهی گیری متن
💎 ایموجی پریمیوم روشن/خاموش | ایموجی پریمیوم چنل روشن/خاموش | ایموجی پریمیوم پک لینک (فقط Premium)
🔣 پرفیکس [نماد|پیش‌فرض] | جوین (ریپلای روی لینک) | عضویت اجباری تنظیم @ch/روشن/خاموش
💬 کامنت اول روشن/خاموش | کامنت اول متن ... | افزودن/حذف @ch
🛡 نگهبان روشن/خاموش | نگهبان لینک/فوروارد/منشن/استیکر/گیف روشن/خاموش
🧰 کاربردی: آیدی | تاریخ | یادآوری 30 دقیقه متن | لیست یادآوری | لینک پیام | ذخیره (ریپلای)
⬇️ دانلود لینک | دانلود صدا لینک | 🌐 اسکرین سایت.com (بدون لینک = اسکرین چت)
🛠 مدیریت گروه | قفل گروه | بازکردن گروه | عنوان گروه | توضیحات گروه | لینک گروه
ترفیع | عزل | اخراج | لیست ادمین | حالت آرام ثانیه
🎯 تقلب تاس 6 | دارت | بولینگ | بسکتبال | فوتبال | کازینو عدد
🔥 چالش استارزی روشن [روز] | خاموش | ریست
🐱 بازی گربه بگیر [اسم] | غذا | بازی | خواب | اسم X | ریست
(روشن/خاموش بعد از اسم هر حالت میاد)"""


@cmd("راهنما", "help")
async def help_cmd(e, a):
    await out(e, HELP)


async def ping_text():
    t = time.time()
    await client(functions.help.GetConfigRequest())
    return f"Self is Running! [{(time.time() - t) * 1000:.2f}ms]"


def hub_balance():
    """حالت هاب: موجودی الماس این کاربر از دیتابیس هاب (فقط‌خواندنی). خروجی: متن یا None."""
    path = os.getenv("HUB_DB") or "hub.db"
    if not OWNER_ID or not os.path.exists(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3)
        try:
            admins = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()}
            try:
                admins |= {r[0] for r in con.execute("SELECT user_id FROM admins")}
            except sqlite3.Error:
                pass
            if OWNER_ID in admins:
                return "💎 موجودی: نامحدود ♾"
            row = con.execute("SELECT diamonds, trial_seconds FROM users WHERE user_id=?", (OWNER_ID,)).fetchone()
        finally:
            con.close()
    except Exception:
        return None
    if not row:
        return None
    dia, trial = row
    secs = int(dia * float(os.getenv("DIAMOND_SECONDS", "1796")) + max(0, trial))
    w, r = divmod(secs, 7 * 86400)
    d, r = divmod(r, 86400)
    h = r // 3600
    return f"💎 موجودی: {dia:.1f} الماس\n⏳ معادل: {w} هفته، {d} روز و {h} ساعت"


async def info_text():
    me = await client.get_me()
    flags = {"ساعت": clock_any(), "آنلاین": cfg["online"], "منشی": cfg["secretary"],
             "سین": cfg["autoseen"], "قفل پیوی": cfg["pvlock"], "ضدلاگین": cfg["antilogin"]}
    st = " | ".join(f"{k}:{'✅' if v else '⛔'}" for k, v in flags.items())
    up = int((time.time() - START) // 60)
    bal = hub_balance()
    return f"👤 {me.first_name} | id: {me.id}\n⏱ آپتایم: {up} دقیقه\n{st}" + (f"\n{bal}" if bal else "")


@cmd("موجودی")
async def balance_cmd(e, a):
    bal = hub_balance()
    if not bal:
        raise ValueError("موجودی الماس فقط توی حالت هاب (hub.py) وجود داره")
    await out(e, bal)


@cmd("پینگ", "ping")
async def ping(e, a):
    text = await ping_text()
    try:   # داخل کوت نمایش داده می‌شه
        await e.edit(text, parse_mode=None,
                     formatting_entities=[types.MessageEntityBlockquote(offset=0, length=len(text.encode("utf-16-le")) // 2)])
    except Exception:
        await out(e, text)


@cmd("اطلاعات")
async def info(e, a):
    await out(e, await info_text())


BOT_TOKEN_RE = re.compile(r"\d{6,12}:[A-Za-z0-9_-]{30,}")
_helper_lock = asyncio.Lock()


async def start_helper(token):
    """بات هلپر (پنل inline + بازی‌ها) رو با توکن بالا میاره."""
    me = await client.get_me()
    helper = TelegramClient("panel_bot", API_ID, API_HASH)
    await helper.start(bot_token=token)
    bot_state["client"] = helper
    bot_state["username"] = (await helper.get_me()).username
    setup_panel(helper, me.id, cfg, save, on_change, {"info": info_text, "ping": ping_text})
    setup_games(helper)   # بازی‌های گروهی روی همین بات هلپر
    extra_hooks["after_helper"]()   # پنل کنترل لایو روی همین بات هلپر


async def create_helper_bot():
    """خودکار از @BotFather یه بات هلپر می‌سازه (inline روشن) و توکنش رو تو کانفیگ نگه می‌داره؛
    یعنی بدون دادن هیچ توکنی، فقط با لاگین شماره، .پنل کار می‌کنه."""
    import random
    import string
    uname = token = None
    last = ""
    try:
        async with client.conversation("@BotFather", timeout=40, total_timeout=300) as conv:
            async def say(text):
                await conv.send_message(text)
                r = await conv.get_response()
                return (r.raw_text or "")

            await say("/newbot")
            await say("NRT Self Panel")
            for _ in range(6):
                cand = "nrt_" + "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8)) + "_bot"
                last = await say(cand)
                m = BOT_TOKEN_RE.search(last)
                if m:
                    token, uname = m.group(0), cand
                    break
                w = re.search(r"in (\d+) seconds", last)
                if w:
                    await asyncio.sleep(min(int(w.group(1)) + 1, 60))
            if not token:
                raise ValueError("BotFather بات نساخت: " + last[:180])
            cfg["helper_token"], cfg["helper_username"] = token, uname
            save()
            r = await say("/setinline")
            r = await say("@" + uname)
            r = await say("panel")
            if "success" not in r.lower():
                raise ValueError(f"بات ساخته شد (@{uname}) ولی روشن کردن inline شکست خورد؛ تو BotFather برای @{uname} دستور /setinline بزن. ({r[:120]})")
            try:   # برای کار بازی‌ها توی گروه (خوندن پیام‌های بدون اسلش)
                await say("/setprivacy")
                await say("@" + uname)
                await say("Disable")
            except Exception:
                pass
    except asyncio.TimeoutError:
        raise ValueError("BotFather جواب نداد؛ چند دقیقه دیگه دوباره .پنل بزن")
    await start_helper(token)
    try:
        await client.send_message(uname, "/start")
    except Exception:
        pass
    return uname


async def ensure_helper():
    async with _helper_lock:
        current = bot_state.get("client")
        # اگر کلاینت هلپر قبلی قطع شده باشد، دوباره آن را بالا بیاور.
        if current and hasattr(current, "is_connected") and current.is_connected():
            return
        if current and hasattr(current, "is_connected"):
            bot_state.pop("client", None)
            bot_state.pop("username", None)
        tok = HELPER_TOKEN or cfg.get("helper_token")
        if tok:
            await start_helper(tok)
        else:
            await create_helper_bot()


@cmd("پنل")
async def panel_cmd(e, a):
    if e.sender_id != OWNER_ID:
        raise ValueError("فقط مالک سلف می‌تونه پنل رو باز کنه")
    if not bot_state.get("client") or not bot_state.get("username"):
        await out(e, "⏳ دارم بات پنل رو آماده می‌کنم؛ بار اول ممکنه حدود ۳۰ تا ۶۰ ثانیه طول بکشه…")
        await ensure_helper()
        await asyncio.sleep(2)
    username = bot_state.get("username")
    if not username:
        raise ValueError("بات هلپر آماده نشد. لاگ سرویس رو بررسی کن و دوباره .پنل بزن")
    res = None
    last_error = None
    for i in range(3):
        try:
            res = await client.inline_query(username, "panel")
            if res:
                break
        except Exception as ex:
            last_error = ex
        await asyncio.sleep(2)
    if not res:
        detail = f" ({last_error})" if last_error else ""
        raise ValueError(
            "پنل از بات هلپر پاسخ نگرفت" + detail +
            ". در BotFather برای بات هلپر /setinline را فعال کن، "
            "متن placeholder را panel بگذار و سپس در خود بات /start بزن."
        )
    try:
        await res[0].click(e.chat_id, reply_to=e.reply_to_msg_id)
        await e.delete()
    except Exception as ex:
        raise ValueError(f"نتونستم پنل رو داخل این گفتگو بفرستم: {ex}")


@cmd("ثبت نام")
async def snap(e, a):
    await snapshot_name(force=True)
    await out(e, f"✅ اسم اصلی ثبت شد: {cfg['base_first']} {cfg['base_last'] or ''}")


@cmd("ساعت")
async def clock_cmd(e, a):
    p = a.split()
    w = p[0] if p else ""
    arg = p[1] if len(p) > 1 else ""
    parts = {"اسم": "clock_first", "فامیل": "clock_last", "بیو": "clock_bio"}
    if w in parts:
        cfg[parts[w]] = parse_onoff(arg)
        msg = f"🕒 ساعت {w}: {'✅ روشن' if cfg[parts[w]] else '⛔ خاموش'}"
    elif w == "فونت":
        name = styles.CLOCK_FONT_FA
        rev = {v: k for k, v in name.items()}
        key = arg if arg in styles.CLOCK_FONTS else rev.get(arg)
        if not key:
            raise ValueError("فونت‌ها: " + " | ".join(name.values()))
        cfg["clock_font"] = key
        msg = f"🔤 فونت ساعت: {name[key]} {clock_text()}"
    elif w == "چت":
        if e.is_private:
            raise ValueError("این دستور رو توی گروه یا کانالی که ادمینی بزن")
        key = str(e.chat_id)
        if parse_onoff(arg):
            chat = await e.get_chat()
            if len(cfg["clock_chats"]) >= 5 and key not in cfg["clock_chats"]:
                raise ValueError("حداکثر ۵ چت")
            cfg["clock_chats"][key] = CLOCK_RE.sub("", getattr(chat, "title", "") or "")
            msg = "🕒 ساعت عنوان این چت روشن شد (باید دسترسی تغییر اطلاعات داشته باشی)"
        else:
            base = cfg["clock_chats"].pop(key, None)
            if base is not None:
                try:
                    await set_chat_title(e.chat_id, base)
                except Exception:
                    pass
            msg = "🕒 ساعت عنوان این چت خاموش شد"
    elif w in ("اول", "first"):
        cfg["clock_first"], cfg["clock_last"] = True, False
        msg = "🕒 ساعت کنار اسم"
    elif w in ("آخر", "last"):
        cfg["clock_first"], cfg["clock_last"] = False, True
        msg = "🕒 ساعت کنار فامیل"
    else:
        on = parse_onoff(a)
        cfg["clock_first"] = False
        cfg["clock_last"] = on
        cfg["clock_bio"] = False if not on else cfg["clock_bio"]
        msg = f"🕒 ساعت: {'✅ روشن' if on else '⛔ خاموش'}"
    save()
    await restore_name()
    await apply_clock()
    await out(e, msg)


async def reload_clock():
    """بعد از تغییر ساعت: اسم/بیو اصلی برگرده و ساعت جدید اعمال بشه."""
    await restore_name()
    await apply_clock()


def make_toggle(name, key, label):
    @cmd(name)
    async def _(e, a):
        cfg[key] = parse_onoff(a)
        save()
        await out(e, f"{label}: {'✅ روشن' if cfg[key] else '⛔ خاموش'}")


make_toggle("آنلاین", "online", "🟢 حالت آنلاین")
make_toggle("منشی", "secretary", "🗂 منشی")
make_toggle("سین خودکار", "autoseen", "👁 سین خودکار")
make_toggle("قفل پیوی", "pvlock", "🔒 قفل پیوی (پیام غریبه‌ها پاک می‌شه)")
make_toggle("ضد لاگین", "antilogin", "🛡 ضد لاگین")


@cmd("منشی متن")
async def sec_text(e, a):
    if not a:
        raise ValueError("متن منشی رو بنویس")
    cfg["secretary_text"] = a
    cfg["secretary_msg"] = None
    save()
    await out(e, "✅ متن منشی تنظیم شد")


@cmd("تنظیم منشی")
async def sec_set(e, a):
    if not e.is_reply:
        raise ValueError("روی پیامی که می‌خوای پاسخ خودکار باشه ریپلای کن")
    r = await e.get_reply_message()
    saved = await client.send_message("me", r)    # کپی توی Saved Messages (متن یا مدیا)
    cfg["secretary_msg"] = saved.id
    if r.raw_text:
        cfg["secretary_text"] = r.raw_text
    save()
    await out(e, "✅ پیام منشی تنظیم شد؛ با «.منشی روشن» فعالش کن")


@cmd("تنظیم زمان منشی")
async def sec_time(e, a):
    n = a.translate(FA_DIGITS).strip()
    if not n.isdigit() or not 5 <= int(n) <= 60:
        raise ValueError("عدد بین ۵ تا ۶۰ (دقیقه)")
    cfg["secretary_minutes"] = int(n)
    save()
    await out(e, f"⏱ منشی هر {n} دقیقه یک بار به هر کاربر جواب می‌ده")


ACTION_NAMES = {"چت": "chat", "بازی": "game", "ویس": "voice", "ویدیو مسیج": "video"}
ACTION_TG = {"chat": "typing", "game": "game", "voice": "record-voice", "video": "record-round"}


def make_action(kind_fa, kind, where_fa, where):
    @cmd(f"حالت {kind_fa} {where_fa}")
    async def _(e, a):
        key = f"act_{kind}_{where}"
        cfg[key] = parse_onoff(a)
        save()
        await out(e, f"🎭 حالت {kind_fa} {where_fa}: {'✅ روشن' if cfg[key] else '⛔ خاموش'}")


for _kf, _k in ACTION_NAMES.items():
    for _wf, _w in (("پیوی", "pv"), ("گروه", "gp")):
        make_action(_kf, _k, _wf, _w)


@cmd("اکشن")
async def action_cmd(e, a):    # سازگاری با نسخه‌ی قبل
    m = {"typing": "chat", "تایپ": "chat", "voice": "voice", "ویس": "voice",
         "video": "video", "ویدیو": "video", "game": "game", "بازی": "game"}
    for k in ACTION_NAMES.values():
        cfg[f"act_{k}_pv"] = False
    if a in m:
        cfg[f"act_{m[a]}_pv"] = True
    elif a not in ("خاموش", "off"):
        raise ValueError("typing / voice / video / game / خاموش  (یا: .حالت چت پیوی روشن)")
    save()
    await out(e, "🎭 حالت اکشن پیوی: " + (a if a not in ("خاموش", "off") else "⛔ خاموش"))


@cmd("متن")
async def text_mode(e, a):
    a = a.strip()
    if a in ("خاموش", "off", ""):
        cfg["textmode"] = None
        save()
        return await out(e, "✍️ حالت متن: ⛔ خاموش")
    key = styles.resolve(a)
    if not key:
        raise ValueError("سبک‌ها: " + " | ".join(fa for _, fa in styles.STYLE_ORDER) + " | خاموش")
    cfg["textmode"] = key
    save()
    await out(e, f"✍️ حالت متن: {styles.STYLE_FA[key]}  {styles.preview(key)}")


_ENT = {"bold": types.MessageEntityBold, "italic": types.MessageEntityItalic,
        "code": types.MessageEntityCode, "spoiler": types.MessageEntitySpoiler,
        "quote": types.MessageEntityBlockquote, "strike": types.MessageEntityStrike,
        "underline": types.MessageEntityUnderline}


async def style_text(e, text):
    m = cfg["textmode"]
    m = styles.LEGACY.get(m, m)
    msg = e.message
    # پیام‌های فوروارد/ساخته‌شده با بات (پنل) دست‌نخورده می‌مونن
    if msg.fwd_from or getattr(msg, "via_bot_id", None):
        return
    # حالت متن: فقط روی پیام ساده (بدون مدیا و فرمت)
    styled = bool(m) and not msg.media and not msg.entities
    new, ents = styles.apply(text, m) if styled else (msg.message or text, [])   # offset entityها نسبت به متن خام
    ent_objs = [_ENT["code" if k == "code" else k](offset=o, length=n) for k, o, n in ents]
    # ایموجی پریمیوم (روی متن نهایی؛ فقط اگه روشن باشه)
    try:
        prem = await auto_hooks["premium"](e, new)
    except Exception as ex:
        print("premium emoji error:", ex)
        prem = []
    if not styled and not prem:
        return
    entities = (ent_objs if styled else list(msg.entities or [])) + prem
    try:
        await e.edit(new, parse_mode=None, formatting_entities=entities or None)
    except Exception:
        pass


# ---------- ابزارها ----------
@cmd("هوا")
async def weather(e, a):
    city = a or "Tehran"
    r = await asyncio.to_thread(
        requests.get, f"https://wttr.in/{quote(city)}?format=3&lang=fa", timeout=10)
    await out(e, "🌤 " + r.text.strip())


@cmd("ارز")
async def fx(e, a):
    p = a.translate(FA_DIGITS).upper().split()
    if len(p) == 3:
        amt, fr, to = float(p[0]), p[1], p[2]
    elif len(p) == 2:
        amt, fr, to = 1.0, p[0], p[1]
    else:
        raise ValueError("مثال: .ارز 100 USD EUR")
    j = await asyncio.to_thread(
        lambda: requests.get(f"https://open.er-api.com/v6/latest/{fr}", timeout=10).json())
    rate = j.get("rates", {}).get(to)
    if rate is None:
        raise ValueError("ارز نامعتبر")
    await out(e, f"💱 {amt:g} {fr} = {amt * rate:,.4f} {to}")


@cmd("کریپتو")
async def crypto(e, a):
    cid = (a or "bitcoin").lower()
    j = await asyncio.to_thread(lambda: requests.get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": cid, "vs_currencies": "usd", "include_24hr_change": "true"},
        timeout=10).json())
    if cid not in j:
        raise ValueError("اسم ارز درست نیست (مثلا bitcoin)")
    d = j[cid]
    await out(e, f"🪙 {cid}: ${d['usd']:,} ({d.get('usd_24h_change', 0):+.2f}%)")


@cmd("ترجمه")
async def translate(e, a):
    from deep_translator import GoogleTranslator
    lang, text = "fa", a
    parts = a.split(None, 1)
    if parts and re.fullmatch(r"[a-z]{2}(-[A-Za-z]{2})?", parts[0]):
        lang = parts[0]
        text = parts[1] if len(parts) > 1 else ""
    if not text and e.is_reply:
        text = (await e.get_reply_message()).raw_text or ""
    if not text:
        raise ValueError("متن بده یا ریپلای کن. مثال: .ترجمه en سلام")
    res = await asyncio.to_thread(
        lambda: GoogleTranslator(source="auto", target=lang).translate(text))
    await out(e, f"🌐 {res}")


OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
       ast.FloorDiv: operator.floordiv, ast.USub: operator.neg}


def calc_node(n):
    if isinstance(n, ast.Expression):
        return calc_node(n.body)
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
        return n.value
    if isinstance(n, ast.BinOp) and type(n.op) in OPS:
        l, r = calc_node(n.left), calc_node(n.right)
        if isinstance(n.op, ast.Pow) and abs(r) > 100:
            raise ValueError("توان خیلی بزرگه")
        return OPS[type(n.op)](l, r)
    if isinstance(n, ast.UnaryOp) and type(n.op) in OPS:
        return OPS[type(n.op)](calc_node(n.operand))
    raise ValueError("عبارت نامعتبر")


@cmd("محاسبه")
async def calc(e, a):
    expr = a.translate(FA_DIGITS).replace("×", "*").replace("÷", "/").replace("^", "**")
    res = calc_node(ast.parse(expr, mode="eval"))
    await out(e, f"🧮 {a} = {res:g}" if isinstance(res, float) else f"🧮 {a} = {res}")


@cmd("هوش مصنوعی")
async def ai(e, a):
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("متغیر ANTHROPIC_API_KEY تنظیم نشده")
    q = a or ((await e.get_reply_message()).raw_text if e.is_reply else "")
    if not q:
        raise ValueError("سوالت رو بنویس")

    def ask():
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-5-5", "max_tokens": 800,
                  "messages": [{"role": "user", "content": q}]},
            timeout=60)
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"])

    await out(e, "🤖 " + await asyncio.to_thread(ask))


# ---------- گروه ----------
async def do_tag(e, text, limit):
    if e.is_private:
        raise ValueError("فقط توی گروه")
    users = [u async for u in client.iter_participants(e.chat_id, limit=limit)
             if not u.bot and not u.deleted]
    reply_to = e.reply_to_msg_id
    await e.delete()
    for i in range(0, len(users), 5):
        names = " ".join(
            f"[{re.sub(r'[][()*_`~|]', '', (u.first_name or 'user'))[:15] or 'user'}](tg://user?id={u.id})"
            for u in users[i:i + 5])
        await client.send_message(e.chat_id, f"{text}\n{names}".strip(), reply_to=reply_to)
        await asyncio.sleep(2)


@cmd("تگ")
async def tag(e, a):
    if a.isdigit():                     # .تگ 20 ← ۲۰ نفر
        await do_tag(e, "", min(int(a), 500))
    else:                               # .تگ متن ← ۱۰۰ نفر با متن
        await do_tag(e, a, 100)


@cmd("همه")
async def tag_all(e, a):
    await do_tag(e, a, 1000)


@cmd("حذف")
async def delete_mine(e, a):
    if e.is_reply and not a.isdigit():  # .حذف با ریپلای ← همون پیام + دستور
        r = await e.get_reply_message()
        await client.delete_messages(e.chat_id, [r.id, e.id])
        return
    n = int(a) if a.isdigit() else 1
    ids = [m.id async for m in client.iter_messages(e.chat_id, from_user="me", limit=n + 1)]
    await client.delete_messages(e.chat_id, ids)


@cmd("بن")
async def ban(e, a):
    uid = await target(e, a)
    await client.edit_permissions(e.chat_id, uid, view_messages=False)
    await out(e, "⛔ بن شد")


@cmd("سیک")
async def kick_user(e, a):
    uid = await target(e, a)
    await client.kick_participant(e.chat_id, uid)
    await out(e, "👢 اخراج شد (می‌تونه دوباره بیاد)")


@cmd("آنبن", "آن بن")
async def unban(e, a):
    uid = await target(e, a)
    await client.edit_permissions(e.chat_id, uid, view_messages=True)
    await out(e, "✅ آنبن شد")


@cmd("پین")
async def pin(e, a):
    if not e.is_reply:
        raise ValueError("روی یه پیام ریپلای کن")
    await client.pin_message(e.chat_id, e.reply_to_msg_id)
    await e.delete()


@cmd("حذف پین")
async def unpin(e, a):
    if not e.is_reply:
        raise ValueError("روی یه پیام ریپلای کن")
    await client.unpin_message(e.chat_id, e.reply_to_msg_id)
    await e.delete()


# ---------- امنیت ----------
@cmd("بلاک")
async def block(e, a):
    uid = await target(e, a)
    await client(functions.contacts.BlockRequest(id=await client.get_input_entity(uid)))
    await out(e, "⛔ بلاک شد")


@cmd("آنبلاک")
async def unblock(e, a):
    uid = await target(e, a)
    await client(functions.contacts.UnblockRequest(id=await client.get_input_entity(uid)))
    await out(e, "✅ آنبلاک شد")


@cmd("سکوت")
async def mute(e, a):
    uid = await target(e, a)
    k = f"{e.chat_id}:{uid}"
    if k not in cfg["muted"]:
        cfg["muted"].append(k)
    save()
    await out(e, "🔇 سکوت شد (پیام‌هاش پاک می‌شه؛ توی گروه باید ادمین باشی)")


@cmd("لیست سکوت")
async def mute_list(e, a):
    await out(e, "🔇 سکوت‌شده‌ها:\n" + ("\n".join(cfg["muted"]) or "خالی"))


@cmd("رفع سکوت")
async def unmute(e, a):
    uid = await target(e, a)
    k = f"{e.chat_id}:{uid}"
    if k in cfg["muted"]:
        cfg["muted"].remove(k)
    save()
    await out(e, "🔊 سکوت برداشته شد")


@cmd("فیلتر کلمات")
async def filter_toggle(e, a):
    cfg["filter_on"] = parse_onoff(a)
    save()
    await out(e, f"🚫 فیلتر کلمات: {'✅ روشن' if cfg['filter_on'] else '⛔ خاموش'} (فقط توی پیوی)")


@cmd("فیلتر کلمه")
async def add_filter(e, a):
    word = a.strip() or ((await e.get_reply_message()).raw_text.strip() if e.is_reply else "")
    if not word:
        raise ValueError("کلمه رو بنویس یا روی پیام ریپلای کن")
    if word not in cfg["filter_words"]:
        cfg["filter_words"].append(word)
    save()
    await out(e, f"🚫 به لیست فیلتر اضافه شد: {word}")


@cmd("حذف فیلتر کلمه")
async def del_filter_word(e, a):
    if a.strip() in cfg["filter_words"]:
        cfg["filter_words"].remove(a.strip())
        save()
    await out(e, f"✅ از لیست فیلتر حذف شد: {a.strip()}")


@cmd("اعمال فیلتر")
async def apply_filter(e, a):
    if a.strip() == "همه":
        cfg["filter_all"] = True
        save()
        return await out(e, "🚫 فیلتر روی همه‌ی پیوی‌ها اعمال شد")
    uid = await target(e, a)
    if uid not in cfg["filter_users"]:
        cfg["filter_users"].append(uid)
    save()
    await out(e, f"🚫 فیلتر روی کاربر اعمال شد: {uid}")


@cmd("حذف فیلتر")
async def remove_filter(e, a):
    if a.strip() == "همه":
        cfg["filter_all"] = False
        save()
        return await out(e, "✅ فیلتر همگانی برداشته شد")
    uid = await target(e, a)
    if uid in cfg["filter_users"]:
        cfg["filter_users"].remove(uid)
    save()
    await out(e, f"✅ فیلتر از کاربر برداشته شد: {uid}")


@cmd("لیست فیلتر کلمات")
async def filter_words_list(e, a):
    await out(e, "🚫 کلمات فیلتر:\n" + ("، ".join(cfg["filter_words"]) or "خالی"))


@cmd("لیست افراد فیلتر")
async def filter_users_list(e, a):
    rows = [str(x) for x in cfg["filter_users"]]
    await out(e, f"🚫 افراد فیلتر{' (همه‌ی پیوی‌ها هم فعاله)' if cfg['filter_all'] else ''}:\n" + ("\n".join(rows) or "خالی"))


@cmd("پاکسازی فیلتر کلمات")
async def filter_words_clear(e, a):
    cfg["filter_words"] = []
    save()
    await out(e, "🧹 لیست کلمات فیلتر پاک شد")


@cmd("پاکسازی افراد فیلتر")
async def filter_users_clear(e, a):
    cfg["filter_users"], cfg["filter_all"] = [], False
    save()
    await out(e, "🧹 لیست افراد فیلتر پاک شد")


@cmd("بکاپ")
async def backup(e, a):
    n = int(a) if a.isdigit() else 1000
    path = f"backup_{abs(e.chat_id)}.txt"
    try:
        with open(path, "w", encoding="utf-8") as f:
            async for m in client.iter_messages(e.chat_id, limit=n):
                body = m.text or (f"<{type(m.media).__name__}>" if m.media else "")
                f.write(f"[{m.date:%Y-%m-%d %H:%M}] {m.sender_id}: {body}\n")
        await client.send_file("me", path, caption=f"بکاپ چت {e.chat_id}")
    finally:
        if os.path.exists(path):
            os.remove(path)
    await out(e, "✅ بکاپ به Saved Messages فرستاده شد")


def media_label(m):
    if m.photo:
        return "🖼 عکس"
    if m.sticker:
        return "🏷 استیکر"
    if m.voice:
        return "🎙 ویس"
    if m.video_note:
        return "⭕ ویدیو مسیج"
    if m.video or m.gif:
        return "🎬 ویدیو"
    if m.audio:
        return "🎵 موزیک"
    if m.document:
        return "📎 فایل"
    return "📦 مدیا" if m.media else ""


def build_backup_html(title, msgs, me_id):
    rows = []
    for m in msgs:
        mine = m.sender_id == me_id
        when = m.date.astimezone(TZ).strftime("%Y-%m-%d %H:%M")
        body = htmllib.escape(m.text or "").replace("\n", "<br>")
        lab = media_label(m)
        if lab:
            body = f"<i>{lab}</i><br>{body}" if body else f"<i>{lab}</i>"
        rows.append(f'<div class="m {"me" if mine else "ot"}"><div class="b">{body or "&nbsp;"}</div>'
                    f'<div class="t">{when}</div></div>')
    return ("<!DOCTYPE html><html lang=\"fa\" dir=\"rtl\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{htmllib.escape(title)}</title><style>"
            "body{background:#0e1621;color:#e8eef5;font-family:Tahoma,sans-serif;margin:0;padding:12px}"
            "h2{text-align:center}.m{max-width:78%;margin:6px 0;padding:8px 12px;border-radius:14px;clear:both}"
            ".me{background:#2b5278;float:left}.ot{background:#182533;float:right}"
            ".t{font-size:11px;opacity:.6;margin-top:4px}.b{word-wrap:break-word}</style></head><body>"
            f"<h2>{htmllib.escape(title)} — {len(msgs)} پیام</h2>" + "".join(rows) + "</body></html>")


@cmd("بکاپ چت")
async def backup_chat(e, a):
    if not e.is_private:
        raise ValueError("بکاپ HTML فقط توی چت پیوی کار می‌کنه")
    n = a.translate(FA_DIGITS).strip()
    limit = int(n) if n.isdigit() else 20000
    await out(e, "⏳ در حال ساخت بکاپ...")
    me = await client.get_me()
    chat = await e.get_chat()
    title = " ".join(x for x in (getattr(chat, "first_name", None), getattr(chat, "last_name", None)) if x) or str(e.chat_id)
    msgs = [m async for m in client.iter_messages(e.chat_id, limit=limit)]
    msgs.reverse()
    data = build_backup_html(f"چت با {title}", msgs, me.id).encode("utf-8")
    import io
    buf = io.BytesIO(data)
    buf.name = f"backup_{abs(e.chat_id)}.html"
    await client.send_file("me", buf, caption=f"💾 بکاپ چت با {title} ({len(msgs)} پیام)")
    await out(e, f"✅ بکاپ {len(msgs)} پیام به Saved Messages فرستاده شد")


@cmd("نشست ها", "نشستها")
async def sessions_cmd(e, a):
    auths = (await client(functions.account.GetAuthorizationsRequest())).authorizations
    bot_state["sessions"] = {}
    lines = ["🔐 نشست‌های فعال:"]
    for i, x in enumerate(auths, 1):
        bot_state["sessions"][i] = None if x.current else x.hash
        last = datetime.fromtimestamp(x.date_active.timestamp(), TZ).strftime("%m-%d %H:%M")
        lines.append(f"{i}. {x.device_model} | {x.platform} | {x.country} | {last}" + (" ← این دستگاه" if x.current else ""))
    lines.append("\nقطع: .قطع نشست [شماره]")
    await out(e, "\n".join(lines))


@cmd("قطع نشست")
async def kill_session(e, a):
    n = a.translate(FA_DIGITS).strip()
    sess = bot_state.get("sessions")
    if not sess:
        raise ValueError("اول «.نشست ها» رو بفرست تا لیست به‌روز بشه")
    if not n.isdigit() or int(n) not in sess:
        raise ValueError("شماره‌ی نشست نامعتبره")
    h = sess[int(n)]
    if h is None:
        raise ValueError("نشست فعلی رو نمی‌شه قطع کرد")
    await client(functions.account.ResetAuthorizationRequest(hash=h))
    bot_state.pop("sessions", None)
    await out(e, f"✅ نشست {n} قطع شد. برای لیست جدید: .نشست ها")


# ---------- خودکارها ----------
@cmd("پاسخ")
async def add_reply(e, a):
    if "|" not in a:
        raise ValueError("مثال: .پاسخ سلام | سلام عزیزم")
    k, v = (x.strip() for x in a.split("|", 1))
    cfg["autoreplies"][k] = v
    save()
    await out(e, f"✅ پاسخ خودکار ثبت شد: {k}")


@cmd("حذف پاسخ")
async def del_reply(e, a):
    cfg["autoreplies"].pop(a, None)
    save()
    await out(e, f"✅ پاسخ حذف شد: {a}")


@cmd("ری اکشن")
async def react_cmd(e, a):
    p = a.split()
    on = parse_onoff(a)
    cfg["react"] = (p[1] if len(p) > 1 else "❤") if on else None
    save()
    await out(e, f"❤ ری‌اکشن خودکار: {cfg['react'] or '⛔ خاموش'}")


# ---------- هندلرها ----------
hooks = features.setup(client, cfg, save, cmd, out, target)
extra_hooks = extras.setup_extras(client, cfg, save, cmd, out, target, bot_state)
more_hooks = more.setup_more(client, cfg, save, cmd, out, target, bot_state, COMMANDS, PREFIX)
auto_hooks = auto.setup_auto(client, cfg, save, cmd, out, target, COMMANDS)


def match_command(body):
    """طولانی‌ترین نام دستور (تا ۴ کلمه) رو پیدا می‌کنه. خروجی: (تابع، آرگومان)."""
    words = body.split()
    for n in (4, 3, 2, 1):
        if len(words) >= n:
            name = " ".join(words[:n])
            if name in COMMANDS:
                pieces = body.split(None, n)
                return COMMANDS[name], (pieces[n] if len(pieces) > n else "")
    return None, ""


@client.on(events.NewMessage(outgoing=True))
async def router(e):
    if not cfg["enabled"]:
        return
    text = (e.raw_text or "").strip()
    if not text:
        return
    prefix = cfg.get("prefix") or PREFIX
    if not text.startswith(prefix):
        # فرمان‌های بازیابی و بازکردن پنل همیشه با نقطه کار می‌کنند،
        # حتی اگر کاربر پیشوند عمومی دستورها را به چیز دیگری تغییر داده باشد.
        if (text.startswith(PREFIX + "پرفیکس")
                or text == PREFIX + "panel"
                or text.startswith(PREFIX + "panel ")
                or text == PREFIX + "پنل"
                or text.startswith(PREFIX + "پنل ")):
            prefix = PREFIX
        else:
            prefix = None
    if prefix is None:
        try:
            if await hooks["outgoing"](e, text):   # جایگزینی «محتوا»
                return
        except Exception as ex:
            print("content error:", ex)
        await style_text(e, text)
        return
    fn, arg = match_command(text[len(prefix):].strip())
    if not fn:
        return
    try:
        await fn(e, arg)
    except Exception as ex:
        await out(e, f"❌ {ex}")


async def fake_action(chat, act):
    try:
        async with client.action(chat, act):
            await asyncio.sleep(6)
    except Exception:
        pass


def schedule_actions(chat_id, where):
    """«در حال تایپ/ضبط...» برای حالت‌های روشنِ پیوی یا گروه (چندتا همزمان ممکنه)."""
    now = time.time()
    for kind, tg in ACTION_TG.items():
        if cfg.get(f"act_{kind}_{where}") and now - action_seen.get((chat_id, kind), 0) > 5:
            action_seen[(chat_id, kind)] = now
            asyncio.create_task(fake_action(chat_id, tg))


async def on_incoming(e):
    if not cfg["enabled"]:
        return
    if await hooks["incoming"](e):   # بن سراسری / پاسخ به دوستان
        return
    if f"{e.chat_id}:{e.sender_id}" in cfg["muted"]:
        await e.delete()
        return
    words = cfg["filters"].get(str(e.chat_id))    # فیلتر قدیمیِ هر چت (سازگاری)
    if words and e.raw_text and any(w in e.raw_text for w in words):
        await e.delete()
        return
    if (cfg["filter_on"] and e.is_private and e.raw_text and cfg["filter_words"]
            and (cfg["filter_all"] or e.sender_id in cfg["filter_users"])
            and any(w in e.raw_text for w in cfg["filter_words"])):
        await e.delete()
        return
    for h in (auto_hooks["incoming"], extra_hooks["incoming"], more_hooks["incoming"]):   # ادمین‌ها/سین/ری‌اکشن، دشمن/اسکرین خودکار، نگهبان، عضویت اجباری
        try:
            if await h(e):
                return
        except Exception as ex:
            print("hook error:", ex)
    if not e.is_private:
        schedule_actions(e.chat_id, "gp")
        return
    sender = await e.get_sender()
    if getattr(sender, "bot", False):
        return
    # پیام‌های رسمی تلگرام (۷۷۷۰۰۰ = کد ورود) نباید پاک بشن
    if cfg["pvlock"] and e.sender_id != 777000 and not getattr(sender, "contact", False):
        await e.delete()
        return
    if cfg["autoseen"]:
        await e.message.mark_read()
    schedule_actions(e.chat_id, "pv")
    if cfg["react"]:
        try:
            await client(functions.messages.SendReactionRequest(
                peer=await e.get_input_chat(), msg_id=e.id,
                reaction=[types.ReactionEmoji(emoticon=cfg["react"])]))
        except Exception:
            pass
    text = e.raw_text or ""
    for k, v in (cfg["autoreplies"].items() if cfg.get("autoreply_on", True) else ()):
        if k in text:
            key = (e.sender_id, k)   # کول‌داون ۳۰ ثانیه؛ جلوی حلقه‌ی پاسخ با بات‌های دیگه
            if time.time() - autoreply_seen.get(key, 0) > 30:
                autoreply_seen[key] = time.time()
                await e.reply(v)
            return
    gap = max(5, min(60, int(cfg.get("secretary_minutes") or 60))) * 60
    if cfg["secretary"] and time.time() - secretary_seen.get(e.sender_id, 0) > gap:
        secretary_seen[e.sender_id] = time.time()
        sent = False
        if cfg.get("secretary_msg"):
            try:
                src = await client.get_messages("me", ids=cfg["secretary_msg"])
                if src:
                    await client.send_message(e.chat_id, src, reply_to=e.id)
                    sent = True
            except Exception as ex:
                print("secretary error:", ex)
        if not sent:
            await e.reply(cfg["secretary_text"])


@client.on(events.NewMessage(incoming=True))
async def incoming(e):
    try:
        await on_incoming(e)
    except Exception as ex:
        print("incoming error:", ex)


active = {"on": False, "tasks": []}


async def cfg_watch_loop():
    """پنل مشترک (بات هلپر توی هاب) فایل کانفیگ رو عوض می‌کنه؛ اینجا تغییرها رو اعمال می‌کنیم."""
    last = os.path.getmtime(CFG_FILE) if os.path.exists(CFG_FILE) else 0
    while True:
        await asyncio.sleep(2)
        try:
            m = os.path.getmtime(CFG_FILE)
            if m == last:
                continue
            last = m
            with open(CFG_FILE, encoding="utf-8") as f:
                new = json.load(f)
            changed = [k for k, v in new.items() if k in cfg and cfg[k] != v]
            cfg.update({k: new[k] for k in changed})
            for k in changed:
                await on_change(k)
        except Exception as ex:
            print("cfg watch error:", ex)


async def set_enabled(v):
    cfg["enabled"] = v
    save()
    try:
        if v:
            clock_state["shown"] = None
            await apply_clock()
        else:
            await restore_name()
            await restore_chats()
    except Exception as ex:
        print("set_enabled error:", ex)


async def on_change(key):
    try:
        if key == "enabled":
            await set_enabled(cfg["enabled"])
            return
        if key.startswith("clock_"):
            await restore_name()
        await apply_clock()
    except FloodWaitError as ex:
        print("flood wait:", ex.seconds)
    except Exception as ex:
        print("on_change error:", ex)


async def account_info():
    me = await client.get_me()
    if not me:
        return None
    name = f"{cfg['base_first'] or me.first_name or ''} {cfg['base_last'] or me.last_name or ''}".strip()
    return {"name": name or "-", "username": me.username, "id": me.id,
            "uptime": int((time.time() - START) // 60)}


async def restart_process():
    await asyncio.sleep(1.5)
    try:
        await client.disconnect()
    except Exception:
        pass
    os.execv(sys.executable, [sys.executable] + sys.argv)


async def delete_self():
    try:
        await restore_name()
    except Exception:
        pass
    await client.log_out()
    cfg["base_first"] = cfg["base_last"] = None
    save()
    asyncio.create_task(restart_process())


BANNER_DIR = os.getenv("BANNER_DIR", "banners")


async def update_banner():
    """بنر «NRT self» با عکس پروفایل فعلی خودت (وسط دایره) برای پنل می‌سازه."""
    me = await client.get_me()
    await refresh_banner(client, os.path.join(BANNER_DIR, f"user_{me.id}.jpg"))


async def banner_loop():
    while True:
        try:
            await update_banner()
        except Exception as ex:
            print("banner error:", ex)
        await asyncio.sleep(600)   # هر ۱۰ دقیقه؛ اگه عکس پروفایلت عوض شد بنر هم عوض می‌شه


async def activate():
    if active["on"]:
        return
    active["on"] = True
    await snapshot_name()
    me = await client.get_me()
    try:
        await update_banner()   # قبل از ساخت پنل، بنر آماده باشه
    except Exception as ex:
        print("banner error:", ex)
    if HUB_HELPER:
        bot_state["client"] = True
        bot_state["username"] = HUB_HELPER
    _tok = HELPER_TOKEN or cfg.get("helper_token")
    if _tok and not HUB_HELPER and not bot_state.get("client"):
        await start_helper(_tok)
    loops = [clock_loop, online_loop, antilogin_loop, banner_loop] + ([cfg_watch_loop] if HUB_HELPER else [])
    loops += extra_hooks["loops"] + more_hooks["loops"] + auto_hooks["loops"]
    active["tasks"] = [asyncio.create_task(f()) for f in loops]
    print("NRT Self is active. Send .راهنما or .پنل in any chat.")


async def main_child():
    """پروسه‌ی سلف یک کاربر (توسط hub.py اجرا می‌شه). با SIGTERM اسم رو برمی‌گردونه و خارج می‌شه."""
    import signal
    await client.connect()
    if not await client.is_user_authorized():
        print("child: session not authorized")
        sys.exit(3)
    loop = asyncio.get_running_loop()

    async def shutdown():
        try:
            await asyncio.wait_for(restore_name(), 10)
        except Exception:
            pass
        await client.disconnect()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
    await activate()
    try:
        await client.run_until_disconnected()
    except (AuthKeyUnregisteredError, SessionRevokedError, UserDeactivatedError, UserDeactivatedBanError):
        print("child: session revoked")
        sys.exit(3)


async def main():
    if "--child" in sys.argv:
        await main_child()
        return
    if "--login" in sys.argv:  # لاگین از ترمینال (اگه بات مدیریت نمی‌خوای)
        await client.start()
        print("✅ لاگین انجام شد")
        await client.disconnect()
        return
    await client.connect()
    manager_ready = False
    if MANAGER_TOKEN and OWNER_ID:
        mgr = TelegramClient("manager_bot", API_ID, API_HASH)
        await mgr.start(bot_token=MANAGER_TOKEN)
        setup_manager(mgr, OWNER_ID, client, cfg, {
            "activate": activate, "info": account_info, "set_enabled": set_enabled,
            "delete": delete_self, "restart": restart_process}, BANNER_PATH)
        manager_ready = True
        print("Manager bot: @" + (await mgr.get_me()).username)
    elif MANAGER_TOKEN:
        print("⚠️ OWNER_ID تنظیم نشده؛ بات مدیریت غیرفعاله")
    if await client.is_user_authorized():
        await activate()
    elif manager_ready:
        print("لاگین نیستی؛ توی بات مدیریت /start بزن و «فعالسازی سلف» رو بزن.")
    else:
        print("لاگین نیستی: یا MANAGER_BOT_TOKEN + OWNER_ID بذار، یا بزن: python self_bot.py --login")
        return
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
