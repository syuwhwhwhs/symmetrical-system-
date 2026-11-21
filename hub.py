"""
هاب چندکاربره NRT Self
=======================
یه بات واحد که هر کاربر می‌تونه توش اکانت خودش رو با شماره فعال کنه (سلف جدا، پروسه‌ی جدا)،
و ادمین از همین بات مدیریتشون می‌کنه: دیدن لیست کاربرا، افزایش/کاهش موجودی (الماس) هرکس،
الماس همگانی، پیام تکی یا همگانی. هر کاربر وقتی اولین‌بار میاد ۲ ساعت تست رایگان می‌گیره؛
بعدش موجودی الماسش (که با نرخ ثابت تبدیل به زمان می‌شه) سلفش رو روشن نگه می‌داره و با گذشت
زمان واقعی کم می‌شه؛ وقتی صفر شد سلف خودش خاموش می‌شه.

اجرا:  python hub.py
نیاز به env: API_ID, API_HASH, HUB_BOT_TOKEN (بات اصلی/مدیریت)، ADMIN_IDS (آیدی عددی ادمین/ادمین‌ها
با کاما جدا)، و اختیاری HUB_HELPER_BOT_TOKEN برای پنل inline مشترک (.پنل هر کاربر).
"""
import asyncio
import glob
import os
import sqlite3
import sys
import time
import zipfile
from html import escape

from telethon import Button, TelegramClient, errors, events
from ui import auto_btn, phone_btn, text_btn, url_btn

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from panel import setup_panel_hub
from games import setup_games

# ================= تنظیمات =================
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
HUB_BOT_TOKEN = os.getenv("HUB_BOT_TOKEN")
HELPER_BOT_TOKEN = os.getenv("HUB_HELPER_BOT_TOKEN")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
if os.getenv("OWNER_ID"):
    ADMIN_IDS.add(int(os.getenv("OWNER_ID")))

DB_PATH = os.getenv("HUB_DB", "hub.db")
os.umask(0o077)  # restrictive permissions for newly created files
SESS_DIR = os.getenv("HUB_SESSIONS_DIR", "hub_sessions")
CFG_DIR = os.getenv("HUB_CONFIGS_DIR", "hub_configs")
LOG_DIR = os.getenv("HUB_LOGS_DIR", "hub_logs")
PYTHON = sys.executable
SELF_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "self_bot.py")

# هر الماس معادل چند ثانیه از آنلاین‌بودن سلفه. پیش‌فرض: ۱۸۰۰ ثانیه = ۳۰ دقیقه، یعنی هر ساعت ۲ الماس کم می‌شه.
DIAMOND_SECONDS = float(os.getenv("DIAMOND_SECONDS", "1800"))

def diamond_seconds():
    """Seconds of service represented by one diamond; rate is stored persistently as diamonds/hour."""
    try:
        hourly = float(setting_get("diamond_hourly_rate", "") or (3600.0 / DIAMOND_SECONDS))
        return 3600.0 / max(0.01, hourly)
    except (ValueError, ZeroDivisionError):
        return DIAMOND_SECONDS
TRIAL_SECONDS = float(os.getenv("TRIAL_SECONDS", str(2 * 3600)))
TRIAL_HOURS = max(1, round(TRIAL_SECONDS / 3600))
WEB_PASSWORD = os.getenv("WEB_PASSWORD", "")          # رمز پنل وب ادمین (خالی = پنل وب خاموش)
WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
WEB_SECURE = os.getenv("WEB_SECURE", "0") == "1"      # پشت HTTPS بودی 1 بذار
BRAND = os.getenv("BRAND", "NRT Self")
HERE = os.path.dirname(os.path.abspath(__file__))
_bp = os.getenv("BANNER_PATH", "assets/banner.jpg")
BANNER = _bp if os.path.isabs(_bp) else os.path.join(HERE, _bp)
ACTIVATION_COST = float(os.getenv("ACTIVATION_COST", "32"))   # هزینه‌ی فعالسازی (الماس)؛ اولین فعالسازی با تست رایگان مجانیه
REF_REWARD = float(os.getenv("REF_REWARD", "5"))              # جایزه‌ی دعوت هر زیرمجموعه (الماس)
CHANNEL_URL = os.getenv("CHANNEL_URL", "")
SUPPORT_GROUP_URL = os.getenv("SUPPORT_GROUP_URL", "")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "").lstrip("@")
PAY_INFO = os.getenv("PAY_INFO", "")                          # متن راهنمای پرداخت (شماره کارت و ...)
PRICES = []                                                   # "الماس:قیمت تومان" مثل 142:3550,450:11250
for _p in os.getenv("PRICES", "142:3550,450:11250,620:15500").split(","):
    if ":" in _p:
        _a, _b = _p.split(":", 1)
        if _a.strip().isdigit() and _b.strip().isdigit():
            PRICES.append((int(_a), int(_b)))
TICK = 20  # ثانیه؛ هر چند وقت یه‌بار موجودی/تایمر چک و کم می‌شه

os.makedirs(SESS_DIR, mode=0o700, exist_ok=True)
os.makedirs(CFG_DIR, mode=0o700, exist_ok=True)
os.makedirs(LOG_DIR, mode=0o700, exist_ok=True)
for _private_dir in (SESS_DIR, CFG_DIR, LOG_DIR):
    try:
        os.chmod(_private_dir, 0o700)
    except OSError:
        pass

# ================= دیتابیس =================
_db = sqlite3.connect(DB_PATH)
_db.execute("""CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    phone TEXT,
    diamonds REAL DEFAULT 0,
    trial_used INTEGER DEFAULT 0,
    trial_seconds REAL DEFAULT 0,
    banned INTEGER DEFAULT 0,
    logged_in INTEGER DEFAULT 0,
    created_at REAL
)""")
_db.execute("""CREATE TABLE IF NOT EXISTS admins(
    user_id INTEGER PRIMARY KEY,
    added_by INTEGER,
    added_at REAL
)""")
_db.execute("""CREATE TABLE IF NOT EXISTS transfers(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id INTEGER,
    to_id INTEGER,
    amount REAL,
    at REAL
)""")
try:
    _db.execute("ALTER TABLE users ADD COLUMN referrer INTEGER")
except sqlite3.OperationalError:
    pass
_db.execute("CREATE TABLE IF NOT EXISTS codes(code TEXT PRIMARY KEY, amount REAL, uses INTEGER, created_at REAL)")
_db.execute("CREATE TABLE IF NOT EXISTS code_uses(code TEXT, user_id INTEGER, at REAL, PRIMARY KEY(code, user_id))")
_db.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)")
_db.execute("""CREATE TABLE IF NOT EXISTS payments(
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL, price INTEGER,
    status TEXT DEFAULT 'pending', created_at REAL)""")
_db.execute("UPDATE users SET phone=NULL WHERE phone IS NOT NULL")  # erase legacy stored phone numbers
_db.commit()
try:
    os.chmod(DB_PATH, 0o600)
except OSError:
    pass


def setting_get(key, default=""):
    row = _db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row and row[0] is not None else default


def setting_set(key, value):
    _db.execute("INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value))
    _db.commit()


def parse_prices(raw):
    out = []
    for p in (raw or "").replace("،", ",").replace("\n", ",").split(","):
        if ":" in p:
            a, b = p.split(":", 1)
            a, b = a.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")), b.strip().replace(",", "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
            if a.isdigit() and b.isdigit() and int(a) > 0:
                out.append((int(a), int(b)))
    return out


def get_prices():
    return parse_prices(setting_get("prices")) or PRICES


def card_text():
    num = setting_get("card_number") or ""
    holder = setting_get("card_holder") or ""
    bank = setting_get("card_bank") or ""
    if not num:
        return ""
    t = f"💳 شماره کارت:\n<code>{escape(num)}</code>"
    if holder:
        t += f"\n👤 به نام: <b>{escape(holder)}</b>"
    if bank:
        t += f"\n🏦 بانک: {escape(bank)}"
    return t


# مالک‌ها = آیدی‌های داخل .env (ADMIN_IDS/OWNER_ID)؛ فقط اون‌ها می‌تونن ادمین اضافه/حذف کنن.
# ادمین‌هایی که از پنل «مدیریت ادمین» اضافه می‌شن توی جدول admins ذخیره و به ADMIN_IDS اضافه می‌شن
# (webpanel همین set رو می‌بینه).
OWNERS = frozenset(ADMIN_IDS)
for (_aid,) in _db.execute("SELECT user_id FROM admins").fetchall():
    ADMIN_IDS.add(_aid)


def db_get(uid, username=None):
    row = _db.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    cols = [c[0] for c in _db.execute("SELECT * FROM users LIMIT 0").description]
    if row is None:
        _db.execute("INSERT INTO users(user_id, username, created_at) VALUES(?,?,?)",
                    (uid, username, time.time()))
        _db.commit()
        return db_get(uid, username)
    u = dict(zip(cols, row))
    if username and u["username"] != username:
        _db.execute("UPDATE users SET username=? WHERE user_id=?", (username, uid))
        _db.commit()
        u["username"] = username
    return u


def db_set(uid, **kw):
    if not kw:
        return
    keys = ", ".join(f"{k}=?" for k in kw)
    _db.execute(f"UPDATE users SET {keys} WHERE user_id=?", (*kw.values(), uid))
    _db.commit()


def db_all(include_banned=True):
    rows = _db.execute("SELECT user_id FROM users" + ("" if include_banned else " WHERE banned=0")).fetchall()
    return [r[0] for r in rows]


def db_search(q):
    q = q.strip()
    like = f"%{q}%"
    rows = _db.execute(
        "SELECT user_id FROM users WHERE CAST(user_id AS TEXT)=? OR username LIKE ? LIMIT 30",
        (q, like)).fetchall()
    return [r[0] for r in rows]


def db_find_user(q):
    """آیدی عددی یا @یوزرنیم ← user_id کاربرِ ثبت‌نام‌کرده توی هاب (یا None)."""
    q = q.strip().lstrip("@")
    if not q:
        return None
    if q.isdigit():
        row = _db.execute("SELECT user_id FROM users WHERE user_id=?", (int(q),)).fetchone()
    else:
        row = _db.execute("SELECT user_id FROM users WHERE LOWER(username)=LOWER(?)", (q,)).fetchone()
    return row[0] if row else None


def fmt_duration(seconds):
    seconds = max(0, int(seconds))
    d, r = divmod(seconds, 86400)
    h, r = divmod(r, 3600)
    m, _ = divmod(r, 60)
    if d:
        return f"{d} روز و {h} ساعت"
    if h:
        return f"{h} ساعت و {m} دقیقه"
    return f"{m} دقیقه"


def fd(x):
    return str(int(round(x))) if abs(x - round(x)) < 0.05 else f"{x:.1f}"


def user_exists(uid):
    return _db.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone() is not None


def ref_count(uid):
    return _db.execute("SELECT COUNT(*) FROM users WHERE referrer=?", (uid,)).fetchone()[0]


def sess_path(uid):
    return os.path.join(SESS_DIR, f"user_{uid}")  # telethon adds .session


def cfg_path(uid):
    return os.path.join(CFG_DIR, f"user_{uid}.json")


def protect_private_file(path):
    try:
        if os.path.exists(path):
            os.chmod(path, 0o600)
    except OSError:
        pass


def protect_user_files(uid):
    for path in (sess_path(uid) + ".session", sess_path(uid) + ".session-journal", cfg_path(uid),
                 sess_path(uid) + "_tmp.session", sess_path(uid) + "_tmp.session-journal"):
        protect_private_file(path)


def is_logged_in(uid):
    return os.path.exists(sess_path(uid) + ".session")


def promote_tmp_session(uid):
    """سشن موقت ورود (user_X_tmp.session) را به سشن اصلی منتقل می‌کند تا دوباره شماره خواسته نشود."""
    src, dst = sess_path(uid) + "_tmp.session", sess_path(uid) + ".session"
    try:
        os.replace(src, dst)
    except OSError:
        pass
    try:
        os.remove(sess_path(uid) + "_tmp.session-journal")
    except OSError:
        pass
    protect_user_files(uid)


# ================= پروسه‌های سلف هر کاربر =================
running = {}   # uid -> {"proc": Process, "mode": "trial"/"paid", "last": ts}


def is_admin(uid):
    return uid in ADMIN_IDS


def runway_seconds(u):
    if is_admin(u["user_id"]):
        return float("inf"), "admin"       # ادمین: موجودی/کیف پول بی‌نهایت
    if u["trial_seconds"] > 0:
        return u["trial_seconds"], "trial"
    return u["diamonds"] * diamond_seconds(), "paid"


async def start_self(uid):
    if uid in running:
        return True, "از قبل روشنه"
    if not is_logged_in(uid):
        return False, "اول باید با شماره‌ت وارد بشی"
    u = db_get(uid)
    if u["banned"]:
        return False, "دسترسیت مسدوده"
    secs, mode = runway_seconds(u)
    if secs <= 0:
        return False, "موجودی الماس یا زمان تستت تموم شده؛ از ادمین شارژ بگیر"
    env = dict(os.environ)
    env.update({
        "SELF_SESSION": sess_path(uid),
        "SELF_CFG": cfg_path(uid),
        "API_ID": str(API_ID), "API_HASH": API_HASH,
        "OWNER_ID": str(uid),
    })
    if HELPER_BOT_TOKEN:
        me = await helper_username()
        if me:
            env["HUB_HELPER_USERNAME"] = me
    env.pop("MANAGER_BOT_TOKEN", None)
    env.pop("HELPER_BOT_TOKEN", None)
    env.pop("BOT_TOKEN", None)
    env.setdefault("HUB_DB", os.path.abspath(DB_PATH))
    # Disable persistent child logs because exceptions may contain private account data.
    proc = await asyncio.create_subprocess_exec(
        PYTHON, SELF_SCRIPT, "--child", env=env,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    protect_user_files(uid)
    running[uid] = {"proc": proc, "mode": mode, "last": time.time()}
    db_set(uid, logged_in=1)
    asyncio.create_task(_watch_exit(uid, proc))
    return True, None


async def _watch_exit(uid, proc):
    code = await proc.wait()
    info = running.pop(uid, None)
    if info is None:
        return
    if code == 3:
        db_set(uid, logged_in=0)
        await notify(uid, "⚠️ نشست اکانتت باطل/حذف شده؛ برای فعالسازی دوباره وارد شو.")


async def stop_self(uid, reason=None):
    info = running.pop(uid, None)
    if not info:
        return False
    try:
        info["proc"].terminate()
        try:
            await asyncio.wait_for(info["proc"].wait(), 10)
        except asyncio.TimeoutError:
            info["proc"].kill()
    except ProcessLookupError:
        pass
    if reason:
        await notify(uid, reason)
    return True


async def delete_self_session(uid):
    await stop_self(uid)
    for p in (sess_path(uid) + ".session", sess_path(uid) + ".session-journal", cfg_path(uid)):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    db_set(uid, logged_in=0, phone=None)
    protect_user_files(uid)


async def billing_loop():
    while True:
        await asyncio.sleep(TICK)
        now = time.time()
        for uid in list(running.keys()):
            info = running.get(uid)
            if not info:
                continue
            elapsed = now - info["last"]
            info["last"] = now
            if info["mode"] == "admin" or is_admin(uid):
                continue    # ادمین هیچ‌وقت کم نمی‌شه
            u = db_get(uid)
            if info["mode"] == "trial":
                left = max(0.0, u["trial_seconds"] - elapsed)
                over = max(0.0, elapsed - u["trial_seconds"])   # بخشی که از تست زیادی رفته از الماس کم می‌شه
                db_set(uid, trial_seconds=left)
                if left <= 0:
                    if u["diamonds"] > 0:
                        info["mode"] = "paid"
                        if over:
                            db_set(uid, diamonds=max(0.0, u["diamonds"] - over / diamond_seconds()))
                    else:
                        await stop_self(uid, f"⏰ {TRIAL_HOURS} ساعت تست رایگانت تموم شد. برای ادامه از «خرید الماس» شارژ کن.")
            else:
                left_d = max(0.0, u["diamonds"] - elapsed / diamond_seconds())
                db_set(uid, diamonds=left_d)
                if left_d <= 0:
                    await stop_self(uid, "⏰ موجودی الماست تموم شد و سلفت خاموش شد. برای ادامه شارژ کن.")


# ================= بات‌ها =================
bot = TelegramClient("hub_bot", API_ID, API_HASH)
helper_bot = TelegramClient("hub_helper_bot", API_ID, API_HASH) if HELPER_BOT_TOKEN else None
_helper_username_cache = {}


async def helper_username():
    if not helper_bot:
        return None
    if "u" not in _helper_username_cache:
        _helper_username_cache["u"] = (await helper_bot.get_me()).username
    return _helper_username_cache["u"]


async def notify(uid, text):
    try:
        await bot.send_message(uid, text)
    except Exception:
        pass


# ---------- وضعیت موقت ورود با شماره (مثل manager.py، ولی برای هرکسی) ----------
login_state = {}   # uid -> {"step", "phone", "hash", "code", "client"}
admin_state = {}   # admin_id -> {"action": ..., "target": uid or None}
xfer_state = {}    # uid -> {"step": "target"/"amount"/"confirm", "to": uid, "amount": float}


def keypad():
    rows = [[auto_btn(str(n), f"k:{n}".encode(), "blue") for n in r]
            for r in ((1, 2, 3), (4, 5, 6), (7, 8, 9))]
    rows.append([auto_btn("0", b"k:0", "blue")])
    rows.append([auto_btn("✔️ تایید کردن", b"k:ok", "green"), auto_btn("❌ پاک کردن", b"k:del", "red")])
    rows.append([auto_btn("📨 ارسال دوباره کد", b"k:re", "blue"), auto_btn("🚫 انصراف", b"k:cancel", "red")])
    return rows


def code_text(code):
    shown = " ".join(code.ljust(5, "•")) if code else "• • • • •"
    return ("🔐 <b>کد ورود تلگرام</b>\n\n"
            "کد به تلگرام شما ارسال شد.\n"
            "کد را از چت «Telegram» بگیر و با دکمه‌های زیر وارد کن.\n\n"
            f"<blockquote>کد وارد شده:  <code>{shown}</code></blockquote>\n"
            "⚠️ کد را داخل چت تایپ نکن؛ تلگرام باطلش می‌کند.")


WELCOME = (
    f"✨ <b>{BRAND}</b> ✨\n"
    "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
    "🤖 دستیار هوشمند اکانت تلگرامت؛ فقط با یه شماره، توی چند ثانیه!\n\n"
    "🔥 <b>چی گیرت میاد؟</b>\n"
    "🕒 ساعت زنده روی اسم، فامیل و بیو با فونت‌های مختلف\n"
    "💬 پاسخ خودکار و منشی هوشمند\n"
    "👁 اعلان پیام‌های ادیت و حذف‌شده\n"
    "🎮 بازی‌های گروهی (۲۱ و دوئل تاس)\n"
    "🎛 پنل هوشمند با دکمه‌های رنگی\n\n"
    f"🎁 <b>هدیه‌ی شروع:</b> {TRIAL_HOURS} ساعت تست رایگان\n"
    f"💎 <b>هزینه:</b> ساعتی {fd(3600 / diamond_seconds())} الماس\n\n"
    "🚀 <b>شروع کن:</b>\n"
    "1️⃣ «مدیریت سلف» رو بزن\n"
    "2️⃣ شمارت رو بفرست و کد رو وارد کن\n"
    "3️⃣ الماس تموم شد؟ از «خرید الماس» شارژ کن\n\n"
    "🔐 کد تایید و رمز دومرحله‌ای رو فقط توی همین ربات رسمی وارد کن و به هیچ‌کس نده.")
assert len(WELCOME) < 1000


def balance_label(u):
    if is_admin(u["user_id"]):
        return "♾ نامحدود"
    return f"{fd(u['diamonds'])} الماس | {fmt_duration(u['diamonds'] * diamond_seconds())}"


def main_kb(u):
    if u["banned"]:
        return [[auto_btn("⛔ مسدودی", b"noop", "red")]]
    rows = [[auto_btn("✅ مدیریت سلف", b"m:self", "red")],
            [auto_btn(f"💎 【 {balance_label(u)} 】", b"noop", "blue")],
            [auto_btn("🤖 حساب کاربری", b"m:account", "green"), auto_btn("💳 خرید الماس", b"m:buy", "green")],
            [auto_btn("💎 کد الماس", b"m:code", "blue")],
            [auto_btn("👥 زیر مجموعه", b"m:ref", "red"), auto_btn("🛠 پشتیبانی", b"m:support", "red")]]
    ext = []
    if CHANNEL_URL:
        ext.append(url_btn("✅ چنل ما", CHANNEL_URL, "blue"))
    if SUPPORT_GROUP_URL:
        ext.append(url_btn("✅ گپ پشتیبانی", SUPPORT_GROUP_URL, "blue"))
    if ext:
        rows.append(ext)
    return rows


user_main_kb = main_kb


def self_panel(uid):
    """(متن، دکمه‌ها) پنل «مدیریت سلف»؛ اگه هنوز وارد نشده، فقط دکمه‌ی فعالسازی."""
    u = db_get(uid)
    if not is_logged_in(uid):
        return "🎛 <b>مدیریت سلف</b>\n\nسلفت هنوز فعال نشده.", [
            [auto_btn("✅ فعالسازی سلف", b"m:act", "green")],
            [auto_btn("🔙 بازگشت", b"m:main", "red")]]
    on = uid in running
    lines = ["🎛 <b>مدیریت سلف</b>\n"]
    if is_admin(uid):
        lines.append("💎 موجودی: ♾ نامحدود (ادمین)")
    else:
        if u["trial_seconds"] > 0:
            lines.append(f"🎁 تست رایگان باقی‌مانده: {fmt_duration(u['trial_seconds'])}")
        lines.append(f"💎 موجودی: {balance_label(u)}")
    rows = [[auto_btn(f"وضعیت سلف : {'🟢 روشن' if on else '⏸ خاموش'}", b"noop", "green" if on else "red")],
            [auto_btn("❌ خاموش کردن", b"u:off", "red"), auto_btn("🗑 حذف سلف", b"u:del", "red")],
            [auto_btn("✅ فعالسازی دوباره سلف", b"u:on", "blue")],
            [auto_btn("🔑 بازیابی حساب", b"m:recover", "green")],
            [auto_btn("🔙 بازگشت", b"m:main")]]
    return "\n".join(lines), rows


def fee_for(u):
    if is_admin(u["user_id"]) or not u["trial_used"]:
        return 0.0
    return ACTIVATION_COST


def act_text(u):
    hourly = round(3600 / diamond_seconds(), 1)
    fee = fee_for(u)
    fee_txt = f"رایگان ({TRIAL_HOURS} ساعت تست هدیه)" if not u["trial_used"] and not is_admin(u["user_id"]) else fd(fee)
    return (f"💎 هزینه ماهیانه سلف: <b>{fd(hourly * 720)}</b> الماس\n"
            f"هزینه فعالسازی: <b>{fee_txt}</b>\n"
            f"مصرف ساعتی: <b>{fd(hourly)}</b>\n\n"
            "سلف روی اکانت شما ران شود؟ (هزینه فعالسازی از موجودی شما کاسته می‌شود.)")


async def send_user_main(chat_id):
    u = db_get(chat_id)
    if os.path.exists(BANNER):
        await bot.send_file(chat_id, BANNER, caption=WELCOME, buttons=main_kb(u), parse_mode="html")
    else:
        await bot.send_message(chat_id, WELCOME, buttons=main_kb(u), parse_mode="html")


async def ask_phone(uid, fee):
    login_state[uid] = {"step": "phone", "fee": fee}
    await bot.send_message(
        uid, "📱 لطفا شماره تلفن خود را از طریق دکمه زیر ارسال کنید:\n(فقط شماره‌ی خودت قبول می‌شه)",
        buttons=[[phone_btn("📱 ارسال شماره تلفن", "blue")],
                 [text_btn("❌ انصراف", "red")]])


async def after_login(uid, fee):
    """بعد از ورود موفق: کسر هزینه‌ی فعالسازی، تست رایگان (اولین بار) و روشن‌کردن سلف."""
    u = db_get(uid)
    if fee and not is_admin(uid):
        db_set(uid, diamonds=max(0.0, u["diamonds"] - fee))
    if not db_get(uid)["trial_used"] and not is_admin(uid):
        db_set(uid, trial_used=1, trial_seconds=TRIAL_SECONDS)
    return await start_self(uid)


async def redeem_code(uid, text):
    code = text.strip().upper()
    row = _db.execute("SELECT amount, uses FROM codes WHERE code=?", (code,)).fetchone()
    if not row or row[1] <= 0:
        return "❌ این کد نامعتبره یا ظرفیتش تموم شده."
    if _db.execute("SELECT 1 FROM code_uses WHERE code=? AND user_id=?", (code, uid)).fetchone():
        return "❌ قبلاً از این کد استفاده کردی."
    _db.execute("UPDATE codes SET uses=uses-1 WHERE code=?", (code,))
    _db.execute("INSERT INTO code_uses(code,user_id,at) VALUES(?,?,?)", (code, uid, time.time()))
    _db.commit()
    u = db_get(uid)
    db_set(uid, diamonds=u["diamonds"] + row[0])
    return f"✅ {fd(row[0])} الماس به حسابت اضافه شد.\n💎 موجودی فعلی: {fd(db_get(uid)['diamonds'])}"


code_state = {}      # uid -> True (منتظر کد الماس)
support_state = {}   # uid -> True (منتظر پیام پشتیبانی)
receipt_state = {}   # uid -> index بسته (منتظر رسید پرداخت)


# ---------- هندلرهای کاربر عادی ----------
@bot.on(events.NewMessage(pattern=r"^/start", func=lambda e: e.is_private))
async def h_start(ev):
    uid = ev.sender_id
    existed = user_exists(uid)
    u = db_get(uid, getattr(await ev.get_sender(), "username", None))
    login_state.pop(uid, None)
    code_state.pop(uid, None)
    support_state.pop(uid, None)
    receipt_state.pop(uid, None)
    parts = (ev.raw_text or "").split(maxsplit=1)
    if not existed and len(parts) > 1 and parts[1].startswith("ref_") and parts[1][4:].isdigit():
        r = int(parts[1][4:])
        if r != uid and user_exists(r):
            db_set(uid, referrer=r)
            ru = db_get(r)
            db_set(r, diamonds=ru["diamonds"] + REF_REWARD)
            await notify(r, f"👥 یه نفر با لینک تو عضو شد! 💎 {fd(REF_REWARD)} الماس جایزه گرفتی.")
    if uid in ADMIN_IDS:
        await send_admin_main(ev.chat_id)
        return
    await send_user_main(ev.chat_id)


@bot.on(events.NewMessage(pattern=r"^/user\b", func=lambda e: e.is_private))
async def h_user_view(ev):
    if ev.sender_id in ADMIN_IDS:
        await send_user_main(ev.chat_id)


@bot.on(events.CallbackQuery(pattern=rb"^noop$"))
async def h_noop(ev):
    await ev.answer()


@bot.on(events.NewMessage(pattern=r"^/admin", func=lambda e: e.is_private))
async def h_admin(ev):
    if ev.sender_id not in ADMIN_IDS:
        return
    await send_admin_main(ev.chat_id)


@bot.on(events.CallbackQuery(pattern=rb"^u:"))
async def h_user_cb(ev):
    uid = ev.sender_id
    action = ev.data.decode().split(":", 1)[1]
    u = db_get(uid)
    try:
        if action == "login":
            if is_logged_in(uid):
                await ev.answer("از قبل وارد شدی", alert=True)
                return
            await ev.answer()
            await ask_phone(uid, fee_for(u))
            return
        if action == "status":
            t, rows = self_panel(uid)
            await ev.edit(t, buttons=rows, parse_mode="html")
            return
        if action == "xfer":
            if is_admin(uid):
                await ev.answer("ادمین موجودی نامحدود داره؛ برای شارژ بقیه از پنل مدیریت استفاده کن.", alert=True)
                return
            if u["diamonds"] <= 0:
                await ev.answer("موجودی الماست صفره.", alert=True)
                return
            xfer_state[uid] = {"step": "target"}
            await ev.answer()
            await bot.send_message(
                uid, f"💎 موجودی تو: {u['diamonds']:.1f}\n\nآیدی عددی یا @یوزرنیمِ گیرنده رو بفرست "
                     "(گیرنده باید قبلاً توی همین بات /start زده باشه):",
                buttons=[[text_btn("❌ انصراف", "red")]])
            return
        if action in ("xok", "xno"):
            xs = xfer_state.get(uid)
            if not xs or xs.get("step") != "confirm":
                await ev.answer("⌛ این درخواست منقضی شده.", alert=True)
                return
            xfer_state.pop(uid, None)
            if action == "xno":
                await ev.edit("🚫 انتقال لغو شد.", buttons=user_main_kb(u))
                return
            to, amount = xs["to"], xs["amount"]
            u = db_get(uid)
            tu = db_get(to)
            if u["banned"] or tu["banned"] or is_admin(uid) or amount <= 0 or u["diamonds"] < amount:
                await ev.edit("❌ انتقال انجام نشد (موجودی کافی نیست یا گیرنده مجاز نیست).",
                              buttons=user_main_kb(u))
                return
            db_set(uid, diamonds=u["diamonds"] - amount)
            db_set(to, diamonds=tu["diamonds"] + amount)
            _db.execute("INSERT INTO transfers(from_id,to_id,amount,at) VALUES(?,?,?,?)",
                        (uid, to, amount, time.time()))
            _db.commit()
            u = db_get(uid)
            await ev.edit(f"✅ {amount:.1f} الماس به <code>{to}</code> منتقل شد.\n"
                          f"💎 موجودی فعلی: {u['diamonds']:.1f}",
                          buttons=user_main_kb(u), parse_mode="html")
            await notify(to, f"💎 {amount:.1f} الماس از طرف {uid} بهت منتقل شد.\n"
                             f"موجودی فعلی: {db_get(to)['diamonds']:.1f}")
            return
        if action == "on":
            if uid in running:
                await stop_self(uid)
            if not u["trial_used"] and not is_admin(uid):
                db_set(uid, trial_used=1, trial_seconds=TRIAL_SECONDS)
            ok, err = await start_self(uid)
            if not ok:
                await ev.answer(err, alert=True)
                return
            t, rows = self_panel(uid)
            await ev.edit(t, buttons=rows, parse_mode="html")
            return
        if action == "off":
            await stop_self(uid)
            t, rows = self_panel(uid)
            await ev.edit(t, buttons=rows, parse_mode="html")
            return
        if action == "del":
            await ev.edit("⏳ در حال حذف سلف...", buttons=[])
            await delete_self_session(uid)
            t, rows = self_panel(uid)
            await ev.edit("🗑 سلف حذف شد و از اکانت خارج شدی.\n\n" + t, buttons=rows, parse_mode="html")
            return
    except Exception as ex:
        if "not modified" not in str(ex).lower():
            print("user cb error:", ex)
        try:
            await ev.answer()
        except Exception:
            pass


@bot.on(events.CallbackQuery(pattern=rb"^m:"))
async def h_menu_cb(ev):
    uid = ev.sender_id
    act = ev.data.decode()[2:]
    u = db_get(uid)
    if u["banned"]:
        await ev.answer("⛔ دسترسیت مسدود شده.", alert=True)
        return
    back = [[auto_btn("🔙 بازگشت", b"m:main")]]
    try:
        if act == "main":
            await ev.edit(WELCOME, buttons=main_kb(u), parse_mode="html")
        elif act == "self":
            t, rows = self_panel(uid)
            await ev.edit(t, buttons=rows, parse_mode="html")
        elif act == "act":
            if is_logged_in(uid):
                await ev.answer("سلفت از قبل فعاله.", alert=True)
                return
            await ev.edit(act_text(u), parse_mode="html",
                          buttons=[[auto_btn("✅ بله", b"m:actyes"), auto_btn("🚫 خیر", b"m:self")]])
        elif act == "actyes":
            if is_logged_in(uid):
                await ev.answer("سلفت از قبل فعاله.", alert=True)
                return
            fee = fee_for(u)
            if fee and u["diamonds"] < fee:
                await ev.answer(f"💎 موجودیت برای هزینه‌ی فعالسازی ({fd(fee)} الماس) کافی نیست.", alert=True)
                return
            await ev.answer()
            await ask_phone(uid, fee)
        elif act == "recover":
            if uid in running:
                await ev.answer("سلفت الان روشنه؛ اگه مشکل داره اول «حذف سلف» رو بزن.", alert=True)
                return
            await ev.answer()
            await delete_self_session(uid)
            await ask_phone(uid, 0)       # بازیابی بدون هزینه‌ی فعالسازی
        elif act == "account":
            name = f"@{u['username']}" if u["username"] else "—"
            bal = "♾" if is_admin(uid) else fd(u["diamonds"])
            cell = lambda t: auto_btn(t, b"noop", "green")
            rows = [[cell(name), cell("نام اکانت")],
                    [cell(str(uid)), cell("آیدی عددی")],
                    [cell(str(ref_count(uid))), cell("تعداد رفرال")],
                    [cell(bal), cell("موجودی الماس")],
                    [auto_btn("💳 افزایش موجودی", b"m:buy", "blue"), auto_btn("💎 انتقال موجودی", b"u:xfer", "blue")],
                    [auto_btn("🔙 بازگشت", b"m:main")]]
            await ev.edit("👤 <b>اطلاعات اکانت</b>", buttons=rows, parse_mode="html")
        elif act == "buy":
            prices = get_prices()
            lines = ["💳 <b>خرید الماس</b>\n", f"⏱ مصرف سلف: ساعتی {fd(3600 / diamond_seconds())} الماس\n",
                     "یکی از بسته‌ها رو انتخاب کن 👇" if prices else "قیمت‌ها هنوز تنظیم نشده؛ به پشتیبانی پیام بده."]
            rows = [[auto_btn(f"💎 {a} الماس — {b:,} تومان", f"m:pack:{i}".encode(), "green")]
                    for i, (a, b) in enumerate(prices)]
            rows.append([auto_btn("🛠 پشتیبانی", b"m:support", "blue")])
            rows.append([auto_btn("🔙 بازگشت", b"m:main")])
            await ev.edit("\n".join(lines), parse_mode="html", buttons=rows)
        elif act.startswith("pack:"):
            prices = get_prices()
            i = int(act.split(":")[1])
            if i >= len(prices):
                await ev.answer("این بسته دیگه نیست.", alert=True)
                return
            amount, price = prices[i]
            card = card_text()
            if not card:
                await ev.edit("💳 <b>خرید الماس</b>\n\nشماره کارت هنوز تنظیم نشده؛ از «پشتیبانی» پیام بده.",
                              parse_mode="html",
                              buttons=[[auto_btn("🛠 پشتیبانی", b"m:support", "blue")],
                                       [auto_btn("🔙 بازگشت", b"m:buy")]])
                return
            await ev.edit(f"💎 <b>{fd(amount)} الماس</b> — <b>{price:,}</b> تومان\n\n{card}\n\n"
                          f"1️⃣ مبلغ رو کارت‌به‌کارت کن\n2️⃣ دکمه‌ی «ارسال رسید» رو بزن و عکس رسید رو بفرست\n"
                          f"3️⃣ بعد از تایید ادمین، الماس خودکار شارژ میشه ✅",
                          parse_mode="html",
                          buttons=[[auto_btn("📤 ارسال رسید", f"m:receipt:{i}".encode(), "green")],
                                   [auto_btn("🔙 بازگشت", b"m:buy")]])
        elif act.startswith("receipt:"):
            prices = get_prices()
            i = int(act.split(":")[1])
            if i >= len(prices):
                await ev.answer("این بسته دیگه نیست.", alert=True)
                return
            receipt_state[uid] = i
            code_state.pop(uid, None)
            support_state.pop(uid, None)
            await ev.answer()
            await bot.send_message(uid, "📤 عکس رسید پرداخت (یا شماره پیگیری) رو همین‌جا بفرست:",
                                   buttons=[[text_btn("❌ انصراف", "red")]])
        elif act == "code":
            code_state[uid] = True
            support_state.pop(uid, None)
            await ev.answer()
            await bot.send_message(uid, "💎 کد الماست رو بفرست:",
                                   buttons=[[text_btn("❌ انصراف", "red")]])
        elif act == "ref":
            me = await bot.get_me()
            link = f"https://t.me/{me.username}?start=ref_{uid}"
            await ev.edit("👥 <b>زیر مجموعه‌گیری</b>\n\n"
                          f"با هر نفری که با لینک تو عضو بشه، {fd(REF_REWARD)} الماس جایزه می‌گیری.\n\n"
                          f"👤 تعداد زیرمجموعه‌هات: <b>{ref_count(uid)}</b>\n\n"
                          f"🔗 لینک اختصاصی تو:\n<code>{link}</code>",
                          buttons=back, parse_mode="html")
        elif act == "support":
            rows = [[auto_btn("🤖 ارتباط از ربات", b"m:supmsg", "green")]]
            if SUPPORT_USERNAME:
                rows[0].append(url_btn("📞 ارتباط مستقیم", f"https://t.me/{SUPPORT_USERNAME}", "blue"))
            rows.append([auto_btn("🔙 بازگشت", b"m:main")])
            await ev.edit("🛠 جهت ارتباط مستقیم یا ارتباط از طریق ربات دکمه‌های زیر را بزنید:", buttons=rows)
        elif act == "supmsg":
            support_state[uid] = True
            code_state.pop(uid, None)
            await ev.answer()
            await bot.send_message(uid, "✍️ پیامت رو بنویس و بفرست؛ به ادمین‌ها می‌رسه:",
                                   buttons=[[text_btn("❌ انصراف", "red")]])
    except Exception as ex:
        if "not modified" not in str(ex).lower():
            print("menu cb error:", ex)
        try:
            await ev.answer()
        except Exception:
            pass


@bot.on(events.CallbackQuery(pattern=rb"^k:"))
async def h_keypad(ev):
    uid = ev.sender_id
    st = login_state.get(uid)
    key = ev.data.decode()[2:]
    if not st or st.get("step") != "code":
        await ev.answer("⌛ این کیبورد منقضی شده. دوباره از «فعالسازی» شروع کن.", alert=True)
        return
    if key == "cancel":
        tmp = st.pop("client", None)
        if tmp:
            await tmp.disconnect()
        login_state.pop(uid, None)
        await ev.edit("🚫 لغو شد.", buttons=user_main_kb(db_get(uid)))
        return
    elif key == "re":
        # ارسال دوباره‌ی کد: حتماً کد تازه به تلگرام کاربر می‌رسد
        try:
            await st["client"].send_code_request(st["phone"])
            await ev.answer("✅ کد دوباره ارسال شد.", alert=True)
        except errors.FloodWaitError as ex:
            await ev.answer(f"⏳ {ex.seconds} ثانیه صبر کن.", alert=True)
        except Exception:
            await ev.answer("❌ ارسال دوباره ناموفق بود.", alert=True)
        return
    if key.isdigit():
        if len(st["code"]) < 6:
            st["code"] += key
    elif key == "del":
        st["code"] = st["code"][:-1]
    elif key == "ok":
        if len(st["code"]) < 5:
            await ev.answer("کد حداقل ۵ رقمه", alert=True)
            return
        await submit_code(ev, uid, st)
        return
    await ev.edit(code_text(st["code"]), buttons=keypad(), parse_mode="html")


async def submit_code(ev, uid, st):
    tc = st["client"]
    try:
        await tc.sign_in(st["phone"], st["code"], phone_code_hash=st["hash"])
    except errors.SessionPasswordNeededError:
        st["step"] = "password"
        await ev.edit("🔑 رمز دومرحله‌ای (2FA) رو توی چت بنویس؛ پیامت بعدش پاک می‌شه.",
                      buttons=[[auto_btn("🚫 انصراف", b"k:cancel")]])
        return
    except (errors.PhoneCodeInvalidError, errors.PhoneCodeEmptyError):
        st["code"] = ""
        await ev.answer("❌ کد اشتباهه", alert=True)
        await ev.edit(code_text(""), buttons=keypad(), parse_mode="html")
        return
    except errors.PhoneCodeExpiredError:
        await tc.disconnect()
        login_state.pop(uid, None)
        await ev.edit("⌛ کد منقضی شد. دوباره از «فعالسازی» شروع کن.", buttons=user_main_kb(db_get(uid)))
        return
    await finish_login(ev, uid, tc)


async def finish_login(ev, uid, tc):
    me = await tc.get_me()
    if me.id != uid:
        await tc.log_out()
        login_state.pop(uid, None)
        await ev.edit("❌ این شماره مال اکانت دیگه‌ایه؛ خارج شدم.", buttons=main_kb(db_get(uid)))
        return
    phone = login_state[uid].get("phone")
    fee = login_state[uid].get("fee", 0)
    await tc.disconnect()
    login_state.pop(uid, None)
    promote_tmp_session(uid)
    db_set(uid, phone=None, logged_in=1)  # phone number is not retained
    ok, err = await after_login(uid, fee)
    t, rows = self_panel(uid)
    head = "✅ <b>وارد شدی و سلف روشن شد!</b>\n\n" if ok else f"✅ وارد شدی ولی سلف روشن نشد: {err}\n\n"
    await ev.edit(head + t, buttons=rows, parse_mode="html")


@bot.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
async def h_text(ev):
    uid = ev.sender_id
    m = ev.message
    text = (m.raw_text or "").strip()

    # --- ادمین: منتظر ورودی متنی (مبلغ/پیام) ---
    ast = admin_state.get(uid)
    if uid in ADMIN_IDS and ast:
        await handle_admin_input(ev, ast)
        return

    # --- جستجوی کاربر توسط ادمین ---
    if uid in ADMIN_IDS and text.startswith("جستجو"):
        q = text.split(None, 1)[1] if len(text.split(None, 1)) > 1 else ""
        await admin_search(ev.chat_id, q)
        return

    st = login_state.get(uid)
    if text in ("❌ انصراف", "/cancel"):
        if st and st.get("client"):
            await st["client"].disconnect()
        login_state.pop(uid, None)
        xfer_state.pop(uid, None)
        code_state.pop(uid, None)
        support_state.pop(uid, None)
        receipt_state.pop(uid, None)
        await bot.send_message(uid, "🚫 لغو شد.", buttons=Button.clear())
        await send_user_main(uid)
        return

    if uid in receipt_state and (m.photo or (text and not text.startswith("/"))):
        prices = get_prices()
        i = receipt_state.pop(uid)
        if i >= len(prices):
            await ev.respond("❌ این بسته دیگه نیست.", buttons=Button.clear())
            await send_user_main(uid)
            return
        amount, price = prices[i]
        cur = _db.execute("INSERT INTO payments(user_id, amount, price, created_at) VALUES(?,?,?,?)",
                          (uid, amount, price, time.time()))
        _db.commit()
        pid = cur.lastrowid
        sender = await ev.get_sender()
        un = f"@{sender.username}" if getattr(sender, "username", None) else "—"
        cap = (f"🧾 <b>رسید پرداخت #{pid}</b>\n👤 <code>{uid}</code> {un}\n"
               f"💎 {fd(amount)} الماس — {price:,} تومان" + (f"\n\n{escape(text)}" if text else ""))
        kb = [[auto_btn("✅ تایید و شارژ", f"a:payok:{pid}".encode(), "green"),
               auto_btn("❌ رد", f"a:payno:{pid}".encode(), "red")]]
        for aid in ADMIN_IDS:
            try:
                if m.photo:
                    await bot.send_file(aid, m.photo, caption=cap, buttons=kb, parse_mode="html")
                else:
                    await bot.send_message(aid, cap, buttons=kb, parse_mode="html")
            except Exception:
                pass
        await ev.respond("✅ رسیدت برای ادمین ارسال شد؛ بعد از تایید، الماست شارژ میشه.", buttons=Button.clear())
        await send_user_main(uid)
        return

    if uid in ADMIN_IDS and text.startswith("/code"):
        import random
        import string
        args = text.split()[1:]
        try:
            amount, uses = float(args[0]), int(args[1]) if len(args) > 1 else 1
        except (IndexError, ValueError):
            await ev.respond("فرمت: <code>/code مقدار_الماس [تعداد_استفاده]</code>\nمثال: <code>/code 50 10</code>",
                             parse_mode="html")
            return
        code = "".join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(8))
        _db.execute("INSERT INTO codes(code, amount, uses, created_at) VALUES(?,?,?,?)",
                    (code, amount, uses, time.time()))
        _db.commit()
        await ev.respond(f"✅ کد ساخته شد:\n<code>{code}</code>\n💎 {fd(amount)} الماس | {uses} بار استفاده",
                         parse_mode="html")
        return

    if uid in code_state and text and not text.startswith("/"):
        code_state.pop(uid, None)
        res = await redeem_code(uid, text)
        await ev.respond(res, buttons=Button.clear())
        await send_user_main(uid)
        return

    if uid in support_state and text and not text.startswith("/"):
        support_state.pop(uid, None)
        sender = await ev.get_sender()
        un = f"@{sender.username}" if getattr(sender, "username", None) else "—"
        for aid in ADMIN_IDS:
            try:
                await bot.send_message(aid, f"📩 <b>پیام پشتیبانی</b>\n👤 <code>{uid}</code> {un}\n\n{escape(text)}",
                                       parse_mode="html",
                                       buttons=[[auto_btn("📨 پاسخ", f"a:msg:{uid}".encode())]])
            except Exception:
                pass
        await ev.respond("✅ پیامت برای پشتیبانی ارسال شد؛ منتظر پاسخ باش.", buttons=Button.clear())
        await send_user_main(uid)
        return

    xs = xfer_state.get(uid)
    if xs and text:
        u = db_get(uid)
        if xs["step"] == "target":
            to = db_find_user(text)
            if to is None:
                await ev.respond("❌ این کاربر توی بات ثبت‌نام نکرده. آیدی/یوزرنیم درست بفرست:")
                return
            if to == uid:
                await ev.respond("❌ نمی‌تونی به خودت منتقل کنی.")
                return
            if db_get(to)["banned"]:
                await ev.respond("❌ این کاربر مسدوده.")
                return
            xs.update(step="amount", to=to)
            await ev.respond(f"چند الماس به <code>{to}</code> منتقل بشه؟ (حداکثر {u['diamonds']:.1f})",
                             parse_mode="html")
            return
        if xs["step"] == "amount":
            try:
                amount = round(float(text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٫", "0123456789.")).replace(",", ".")), 2)
            except ValueError:
                amount = 0
            if amount < 0.1:
                await ev.respond("❌ یه عدد (حداقل ۰.۱) بفرست.")
                return
            if amount > u["diamonds"]:
                await ev.respond(f"❌ موجودیت کافی نیست ({u['diamonds']:.1f}).")
                return
            xs.update(step="confirm", amount=amount)
            await bot.send_message(uid, "⌨️", buttons=Button.clear())
            await ev.respond(f"⚠️ تایید می‌کنی {amount:.1f} الماس به <code>{xs['to']}</code> منتقل بشه؟\n"
                             "(برگشت‌ناپذیره)", parse_mode="html",
                             buttons=[[auto_btn("✅ تایید", b"u:xok"), auto_btn("🚫 لغو", b"u:xno")]])
            return

    if st and st.get("step") == "phone" and m.contact:
        if m.contact.user_id != uid:
            await ev.respond("❌ فقط شماره‌ی خودت (با دکمه‌ی پایین) قبول می‌شه.")
            return
        phone = "+" + m.contact.phone_number.lstrip("+")
        try:
            await m.delete()  # remove the shared contact message from the chat history
        except Exception:
            pass
        tc = TelegramClient(sess_path(uid) + "_tmp", API_ID, API_HASH)
        await tc.connect()
        if not await tc.is_user_authorized():
            try:
                sent = await tc.send_code_request(phone)
            except errors.FloodWaitError as ex:
                await ev.respond(f"⏳ تلگرام محدود کرد؛ {ex.seconds} ثانیه صبر کن.")
                await tc.disconnect()
                return
            except Exception as ex:
                await ev.respond("❌ درخواست ورود ناموفق بود. جزئیات خطا نمایش داده نمی‌شود.")
                await tc.disconnect()
                return
            code_hash = sent.phone_code_hash
        else:
            code_hash = None   # اکانت از قبل با کلید (سشن) وارد شده؛ نیازی به کد نیست
        protect_user_files(uid)
        login_state[uid] = {"step": "code" if code_hash else "done", "phone": phone, "hash": code_hash,
                             "code": "", "client": tc, "fee": (st or {}).get("fee", 0)}
        if code_hash:
            await ev.respond("✅ کد به تلگرامت ارسال شد.", buttons=Button.clear())
            await ev.respond(code_text(""), buttons=keypad(), parse_mode="html")
        else:
            # با کلید (سشن موجود) وارد شد؛ بدون کد مستقیم سلف روشن می‌شود
            login_state.pop(uid, None)
            promote_tmp_session(uid)
            db_set(uid, phone=None, logged_in=1)  # phone number is not retained
            await ev.respond("🔑 با کلید ذخیره‌شده وارد شدی (بدون نیاز به کد).", buttons=Button.clear())
            ok, err = await after_login(uid, (st or {}).get("fee", 0))
            t, rows = self_panel(uid)
            head = "✅ <b>سلف روشن شد!</b>\n\n" if ok else f"⚠️ سلف روشن نشد: {err}\n\n"
            await bot.send_message(uid, head + t, buttons=rows, parse_mode="html")
        return

    if st and st.get("step") == "password" and text:
        try:
            await m.delete()
        except Exception:
            pass
        tc = st["client"]
        try:
            await tc.sign_in(password=text)
        except errors.PasswordHashInvalidError:
            await bot.send_message(uid, "❌ رمز اشتباهه. دوباره بنویس.")
            return
        except Exception as ex:
            await bot.send_message(uid, "❌ ورود ناموفق بود. جزئیات خطا نمایش داده نمی‌شود.")
            return
        me = await tc.get_me()
        if me.id != uid:
            await tc.log_out()
            login_state.pop(uid, None)
            await bot.send_message(uid, "❌ این شماره مال اکانت دیگه‌ایه؛ خارج شدم.")
            return
        phone = st.get("phone")
        fee = st.get("fee", 0)
        await tc.disconnect()
        login_state.pop(uid, None)
        promote_tmp_session(uid)
        db_set(uid, phone=None, logged_in=1)  # phone number is not retained
        ok, err = await after_login(uid, fee)
        t, rows = self_panel(uid)
        head = "✅ <b>وارد شدی و سلف روشن شد!</b>\n\n" if ok else f"✅ وارد شدی ولی سلف روشن نشد: {err}\n\n"
        await bot.send_message(uid, head + t, buttons=rows, parse_mode="html")
        return


# ================= پنل ادمین =================
def pay_settings_text():
    prices = get_prices()
    return ("💳 <b>تنظیم کارت و قیمت‌ها</b>\n\n"
            f"💳 شماره کارت: <code>{escape(setting_get('card_number') or '—')}</code>\n"
            f"👤 صاحب کارت: {escape(setting_get('card_holder') or '—')}\n"
            f"🏦 بانک: {escape(setting_get('card_bank') or '—')}\n\n"
            "💰 <b>قیمت‌ها:</b>\n" + ("\n".join(f"💎 {a} الماس — {b:,} تومان" for a, b in prices) or "—"))


def pay_settings_kb():
    return [[auto_btn("💳 شماره کارت", b"a:setcard", "green"), auto_btn("👤 نام صاحب کارت", b"a:setholder", "green")],
            [auto_btn("🏦 بانک", b"a:setbank", "blue"), auto_btn("💰 قیمت‌ها", b"a:setprices", "blue")],
            [auto_btn("🔙 بازگشت", b"a:main", "red")]]


def admin_main_kb():
    return [
        [auto_btn("👥 لیست کاربران", b"a:list:0")],
        [auto_btn("🔎 جستجو با آیدی", b"a:searchhelp")],
        [auto_btn("🤖 سلف خودم (نامحدود)", b"a:me")],
        [auto_btn("💎 الماس همگانی", b"a:bdiamond"), auto_btn("📢 پیام همگانی", b"a:bmsg")],
        [auto_btn("⏱ نرخ مصرف ساعتی", b"a:setrate", "green")],
        [auto_btn("💳 تنظیم کارت و قیمت‌ها", b"a:pay", "green")],
        [auto_btn("👮 مدیریت ادمین", b"a:admins")],
    ]


async def send_admin_main(chat_id):
    total = len(db_all())
    on = len(running)
    await bot.send_message(
        chat_id,
        f"🛠 <b>پنل مدیریت</b>\n👥 کل کاربرا: {total}\n🟢 سلف روشن الان: {on}\n💎 نرخ مصرف: {fd(3600 / diamond_seconds())} الماس/ساعت\n\n"
        "برای دیدن یه کاربر خاص بنویس:\n<code>جستجو آیدی_یا_یوزرنیم</code>",
        buttons=admin_main_kb(), parse_mode="html")


def admins_view(viewer):
    owners = sorted(OWNERS)
    extra = sorted(ADMIN_IDS - OWNERS)
    lines = ["👮 <b>مدیریت ادمین</b>\n",
             "👑 مالک‌ها: " + (" ".join(f"<code>{i}</code>" for i in owners) or "—"),
             "👮 ادمین‌ها: " + (" ".join(f"<code>{i}</code>" for i in extra) or "—")]
    rows = []
    if viewer in OWNERS:
        rows.append([auto_btn("➕ افزودن ادمین", b"a:addadmin")])
        rows += [[auto_btn(f"❌ حذف {i}", f"a:rmadmin:{i}".encode())] for i in extra]
    else:
        lines.append("\nℹ️ فقط مالک‌ها می‌تونن ادمین اضافه/حذف کنن.")
    rows.append([auto_btn("🔙 بازگشت", b"a:main")])
    return "\n".join(lines), rows


def user_detail_text(u):
    uid = u["user_id"]
    lines = [f"👤 <b>کاربر</b> <code>{uid}</code>" + (f" (@{escape(u['username'])})" if u["username"] else "")]
    lines.append("📱 شماره: ذخیره نمی‌شود (حفاظت حریم خصوصی)")
    lines.append(f"🔑 ورود: {'✅' if is_logged_in(uid) else '🔒'}")
    lines.append(f"📶 سلف: {'🟢 روشن' if uid in running else '⏸ خاموش'}")
    if is_admin(uid):
        lines.append("💎 موجودی: ♾ نامحدود (ادمین)")
    else:
        lines.append(f"💎 موجودی: {u['diamonds']:.1f} الماس (≈ {fmt_duration(u['diamonds']*diamond_seconds())})")
    if not u["trial_used"]:
        lines.append("🎁 تست رایگان: هنوز نگرفته")
    else:
        lines.append(f"🎁 باقی‌مونده‌ی تست: {fmt_duration(u['trial_seconds'])}")
    lines.append(f"⛔ بن: {'بله' if u['banned'] else 'خیر'}")
    return "\n".join(lines)


def user_detail_kb(uid):
    u = db_get(uid)
    rows = [
        [auto_btn("➕ افزایش الماس", f"a:add:{uid}".encode()),
         auto_btn("➖ کاهش الماس", f"a:sub:{uid}".encode())],
        [auto_btn(f"🎁 {TRIAL_HOURS} ساعت تست هدیه", f"a:trial:{uid}".encode(), "blue")],
        [auto_btn("📨 ارسال پیام", f"a:msg:{uid}".encode())],
        [auto_btn("🔓 رفع بن" if u["banned"] else "⛔ بن کردن", f"a:ban:{uid}".encode())],
        [auto_btn("⏸ خاموش‌کردن سلفش", f"a:stop:{uid}".encode())] if uid in running else [],
        [auto_btn("🔙 بازگشت", b"a:main")],
    ]
    return [r for r in rows if r]


async def admin_search(chat_id, q):
    if not q:
        await bot.send_message(chat_id, "بنویس: جستجو آیدی_یا_یوزرنیم")
        return
    found = db_search(q)
    if not found:
        await bot.send_message(chat_id, "چیزی پیدا نشد.")
        return
    if len(found) == 1:
        uid = found[0]
        await bot.send_message(chat_id, user_detail_text(db_get(uid)),
                               buttons=user_detail_kb(uid), parse_mode="html")
        return
    rows = [[auto_btn(f"{uid}", f"a:view:{uid}".encode())] for uid in found]
    rows.append([auto_btn("🔙 بازگشت", b"a:main")])
    await bot.send_message(chat_id, f"🔎 {len(found)} نتیجه:", buttons=rows)


PAGE_SIZE = 10


def users_page_kb(page):
    ids = db_all()
    total_pages = max(1, (len(ids) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    chunk = ids[page * PAGE_SIZE: (page + 1) * PAGE_SIZE]
    rows = []
    for uid in chunk:
        tag = "🟢" if uid in running else "⚪️"
        rows.append([auto_btn(f"{tag} {uid}", f"a:view:{uid}".encode())])
    nav = []
    if page > 0:
        nav.append(auto_btn("◀️ قبلی", f"a:list:{page-1}".encode()))
    if page < total_pages - 1:
        nav.append(auto_btn("بعدی ▶️", f"a:list:{page+1}".encode()))
    if nav:
        rows.append(nav)
    rows.append([auto_btn("🔙 بازگشت", b"a:main")])
    return f"👥 کاربران ({page+1}/{total_pages})", rows


@bot.on(events.CallbackQuery(pattern=rb"^a:"))
async def h_admin_cb(ev):
    if ev.sender_id not in ADMIN_IDS:
        await ev.answer("این پنل مال تو نیست", alert=True)
        return
    parts = ev.data.decode().split(":")
    d = parts[1]
    try:
        if d == "main":
            total, on = len(db_all()), len(running)
            await ev.edit(f"🛠 <b>پنل مدیریت</b>\n👥 کل کاربرا: {total}\n🟢 سلف روشن الان: {on}\n💎 نرخ مصرف: {fd(3600 / diamond_seconds())} الماس/ساعت\n\n"
                          "برای دیدن یه کاربر خاص بنویس:\n<code>جستجو آیدی_یا_یوزرنیم</code>",
                          buttons=admin_main_kb(), parse_mode="html")
            return
        if d == "me":
            await ev.answer()
            await send_user_main(ev.sender_id)
            return
        if d == "setrate":
            current = float(setting_get("diamond_hourly_rate", "") or (3600.0 / DIAMOND_SECONDS))
            admin_state[ev.sender_id] = {"action": "setrate", "target": None}
            await ev.answer()
            await bot.send_message(ev.sender_id, f"نرخ فعلی: ساعتی {fd(current)} الماس\nنرخ جدید مصرف ساعتی برای همه کاربران را بفرست (مثلاً 2.5):",
                                   buttons=[[text_btn("❌ انصراف", "red")]])
            return
        if d == "pay":
            await ev.edit(pay_settings_text(), parse_mode="html", buttons=pay_settings_kb())
            return
        if d in ("setcard", "setholder", "setbank", "setprices"):
            admin_state[ev.sender_id] = {"action": d, "target": None}
            prompt = {"setcard": "💳 شماره کارت رو بفرست (مثلاً 6037-9911-2233-4455):",
                      "setholder": "👤 نام صاحب کارت رو بفرست:",
                      "setbank": "🏦 اسم بانک رو بفرست (یا - برای خالی کردن):",
                      "setprices": "💰 قیمت‌ها رو به شکل «الماس:تومان» با کاما بفرست.\nمثال:\n<code>60:15000,142:35500,450:112500</code>"}[d]
            await ev.answer()
            await bot.send_message(ev.sender_id, prompt, parse_mode="html",
                                   buttons=[[text_btn("❌ انصراف", "red")]])
            return
        if d in ("payok", "payno"):
            pid = int(parts[2])
            row = _db.execute("SELECT user_id, amount, price FROM payments WHERE id=? AND status='pending'", (pid,)).fetchone()
            if not row:
                await ev.answer("این رسید قبلاً بررسی شده.", alert=True)
                return
            tuid, amount, price = row
            if d == "payok":
                cur = _db.execute("UPDATE payments SET status='paid' WHERE id=? AND status='pending'", (pid,))
                _db.commit()
                if cur.rowcount:
                    tu = db_get(tuid)
                    db_set(tuid, diamonds=tu["diamonds"] + amount)
                    await notify(tuid, f"✅ پرداختت تایید شد! 💎 {fd(amount)} الماس به حسابت اضافه شد.\n"
                                       f"موجودی فعلی: {fd(db_get(tuid)['diamonds'])}")
                await ev.edit(f"✅ رسید #{pid} تایید شد؛ {fd(amount)} الماس به <code>{tuid}</code> داده شد.",
                              parse_mode="html", buttons=[[auto_btn("✅ تایید شد", b"noop", "green")]])
            else:
                _db.execute("UPDATE payments SET status='rejected' WHERE id=? AND status='pending'", (pid,))
                _db.commit()
                await notify(tuid, "❌ رسید پرداختت تایید نشد. اگه اشتباهی شده از «پشتیبانی» پیام بده.")
                await ev.edit(f"❌ رسید #{pid} رد شد.", buttons=[[auto_btn("❌ رد شد", b"noop", "red")]])
            return
        if d == "admins":
            await ev.edit(admins_view(ev.sender_id)[0], buttons=admins_view(ev.sender_id)[1], parse_mode="html")
            return
        if d == "addadmin":
            if ev.sender_id not in OWNERS:
                await ev.answer("فقط مالک‌ها می‌تونن ادمین اضافه کنن.", alert=True)
                return
            admin_state[ev.sender_id] = {"action": "addadmin", "target": None}
            await ev.answer()
            await bot.send_message(ev.sender_id, "آیدی عددی یا @یوزرنیمِ ادمین جدید رو بفرست "
                                   "(باید قبلاً توی همین بات /start زده باشه):",
                                   buttons=[[text_btn("❌ انصراف", "red")]])
            return
        if d == "rmadmin":
            if ev.sender_id not in OWNERS:
                await ev.answer("فقط مالک‌ها می‌تونن ادمین حذف کنن.", alert=True)
                return
            rid = int(parts[2])
            if rid in OWNERS:
                await ev.answer("مالک رو نمی‌شه حذف کرد.", alert=True)
                return
            _db.execute("DELETE FROM admins WHERE user_id=?", (rid,))
            _db.commit()
            ADMIN_IDS.discard(rid)
            if rid in running:   # دیگه نامحدود نیست؛ از الان طبق موجودی حساب می‌شه
                secs, mode = runway_seconds(db_get(rid))
                if secs <= 0:
                    await stop_self(rid, "⏰ دسترسی ادمینی‌ت برداشته شد و موجودی نداری؛ سلفت خاموش شد.")
                else:
                    running[rid]["mode"] = mode
            await notify(rid, "ℹ️ دسترسی ادمینی‌ت برداشته شد.")
            await ev.answer("حذف شد", alert=True)
            await ev.edit(admins_view(ev.sender_id)[0], buttons=admins_view(ev.sender_id)[1], parse_mode="html")
            return
        if d == "searchhelp":
            await ev.answer("بنویس: جستجو آیدی_یا_یوزرنیم", alert=True)
            return
        if d == "list":
            text, rows = users_page_kb(int(parts[2]))
            await ev.edit(text, buttons=rows)
            return
        if d == "view":
            uid = int(parts[2])
            await ev.edit(user_detail_text(db_get(uid)), buttons=user_detail_kb(uid), parse_mode="html")
            return
        if d in ("add", "sub", "msg"):
            uid = int(parts[2])
            admin_state[ev.sender_id] = {"action": d, "target": uid}
            prompt = {"add": "چند الماس اضافه بشه؟ (عدد بفرست)",
                      "sub": "چند الماس کم بشه؟ (عدد بفرست)",
                      "msg": "متن پیام رو بفرست تا براش ارسال بشه:"}[d]
            await ev.answer()
            await bot.send_message(ev.sender_id, prompt, buttons=[[text_btn("❌ انصراف", "red")]])
            return
        if d == "trial":
            uid = int(parts[2])
            db_set(uid, trial_used=1, trial_seconds=TRIAL_SECONDS)
            await notify(uid, f"🎁 ادمین {fmt_duration(TRIAL_SECONDS)} تست رایگان بهت هدیه داد!")
            await ev.answer("انجام شد", alert=True)
            await ev.edit(user_detail_text(db_get(uid)), buttons=user_detail_kb(uid), parse_mode="html")
            return
        if d == "ban":
            uid = int(parts[2])
            u = db_get(uid)
            db_set(uid, banned=0 if u["banned"] else 1)
            if not u["banned"]:
                await stop_self(uid, "⛔ دسترسیت توسط ادمین مسدود شد.")
            await ev.edit(user_detail_text(db_get(uid)), buttons=user_detail_kb(uid), parse_mode="html")
            return
        if d == "stop":
            uid = int(parts[2])
            await stop_self(uid, "⏸ ادمین سلفت رو خاموش کرد.")
            await ev.edit(user_detail_text(db_get(uid)), buttons=user_detail_kb(uid), parse_mode="html")
            return
        if d in ("bdiamond", "bmsg"):
            admin_state[ev.sender_id] = {"action": d, "target": None}
            prompt = ("چند الماس به همه‌ی کاربرا اضافه بشه؟ (عدد بفرست)" if d == "bdiamond"
                      else "متن پیام همگانی رو بفرست:")
            await ev.answer()
            await bot.send_message(ev.sender_id, prompt, buttons=[[text_btn("❌ انصراف", "red")]])
            return
    except Exception as ex:
        if "not modified" not in str(ex).lower():
            print("admin cb error:", ex)
        try:
            await ev.answer()
        except Exception:
            pass


async def handle_admin_input(ev, ast):
    admin_id = ev.sender_id
    text = (ev.raw_text or "").strip()
    if text in ("❌ انصراف", "/cancel"):
        admin_state.pop(admin_id, None)
        await bot.send_message(admin_id, "🚫 لغو شد.", buttons=Button.clear())
        await send_admin_main(admin_id)
        return
    action, target = ast["action"], ast["target"]
    if action == "setrate":
        try:
            rate = float(text.replace(",", "."))
            if rate <= 0 or rate > 100000:
                raise ValueError
        except ValueError:
            await ev.respond("❌ نرخ باید عدد مثبت باشد. نمونه: 2.5")
            return
        setting_set("diamond_hourly_rate", str(rate))
        admin_state.pop(admin_id, None)
        await bot.send_message(admin_id, f"✅ نرخ مصرف ساعتی برای همه کاربران ذخیره شد: {fd(rate)} الماس/ساعت", buttons=Button.clear())
        await send_admin_main(admin_id)
        return
    if action in ("setcard", "setholder", "setbank", "setprices"):
        if action == "setprices":
            if not parse_prices(text):
                await ev.respond("❌ فرمت اشتباهه. مثال: <code>60:15000,142:35500</code>", parse_mode="html")
                return
            setting_set("prices", text)
        elif action == "setcard":
            setting_set("card_number", text)
        elif action == "setholder":
            setting_set("card_holder", text)
        else:
            setting_set("card_bank", "" if text == "-" else text)
        admin_state.pop(admin_id, None)
        await bot.send_message(admin_id, "✅ ذخیره شد.", buttons=Button.clear())
        await bot.send_message(admin_id, pay_settings_text(), parse_mode="html", buttons=pay_settings_kb())
        return
    if action == "addadmin":
        if admin_id not in OWNERS:
            admin_state.pop(admin_id, None)
            return
        new = db_find_user(text)
        if new is None:
            await ev.respond("❌ این کاربر توی بات ثبت‌نام نکرده (باید /start زده باشه). دوباره بفرست:")
            return
        if new in ADMIN_IDS:
            await ev.respond("ℹ️ این کاربر از قبل ادمینه.")
            return
        _db.execute("INSERT OR IGNORE INTO admins(user_id, added_by, added_at) VALUES(?,?,?)",
                    (new, admin_id, time.time()))
        _db.commit()
        ADMIN_IDS.add(new)
        admin_state.pop(admin_id, None)
        await notify(new, "👮 تو ادمین بات شدی! برای ورود به پنل مدیریت /admin بزن.")
        await bot.send_message(admin_id, f"✅ {new} ادمین شد.", buttons=Button.clear())
        t, rows = admins_view(admin_id)
        await bot.send_message(admin_id, t, buttons=rows, parse_mode="html")
        return
    if action in ("add", "sub", "bdiamond"):
        try:
            amount = float(text.replace(",", "."))
            if amount <= 0:
                raise ValueError
        except ValueError:
            await ev.respond("❌ یه عدد مثبت بفرست.")
            return
        if action == "add":
            u = db_get(target)
            db_set(target, diamonds=u["diamonds"] + amount)
            if target in running and running[target]["mode"] == "paid":
                pass  # تیک بعدی billing_loop موجودی جدید رو می‌خونه
            await notify(target, f"💎 {amount:.1f} الماس به حسابت اضافه شد. موجودی فعلی: "
                                  f"{db_get(target)['diamonds']:.1f}")
            admin_state.pop(admin_id, None)
            await bot.send_message(admin_id, "✅ انجام شد.", buttons=Button.clear())
            await bot.send_message(admin_id, user_detail_text(db_get(target)),
                                   buttons=user_detail_kb(target), parse_mode="html")
            return
        if action == "sub":
            u = db_get(target)
            new_bal = max(0.0, u["diamonds"] - amount)
            db_set(target, diamonds=new_bal)
            if new_bal <= 0 and target in running and running[target]["mode"] == "paid":
                await stop_self(target, "⏰ موجودی الماست توسط ادمین صفر شد و سلفت خاموش شد.")
            await notify(target, f"💎 {amount:.1f} الماس از حسابت کم شد. موجودی فعلی: {new_bal:.1f}")
            admin_state.pop(admin_id, None)
            await bot.send_message(admin_id, "✅ انجام شد.", buttons=Button.clear())
            await bot.send_message(admin_id, user_detail_text(db_get(target)),
                                   buttons=user_detail_kb(target), parse_mode="html")
            return
        if action == "bdiamond":
            ids = db_all(include_banned=False)
            for uid in ids:
                if is_admin(uid):
                    continue
                u = db_get(uid)
                db_set(uid, diamonds=u["diamonds"] + amount)
                await notify(uid, f"🎁 ادمین {amount:.1f} الماس به همه‌ی کاربرا هدیه داد! موجودی فعلیت: "
                                   f"{db_get(uid)['diamonds']:.1f}")
            admin_state.pop(admin_id, None)
            await bot.send_message(admin_id, f"✅ به {len(ids)} کاربر {amount:.1f} الماس داده شد.",
                                   buttons=Button.clear())
            await send_admin_main(admin_id)
            return
    if action in ("msg", "bmsg"):
        if not text:
            await ev.respond("❌ متن خالیه.")
            return
        if action == "msg":
            ok = True
            try:
                await bot.send_message(target, f"📨 <b>پیام از ادمین:</b>\n\n{text}", parse_mode="html")
            except Exception:
                ok = False
            admin_state.pop(admin_id, None)
            await bot.send_message(admin_id, "✅ ارسال شد." if ok else "❌ ارسال نشد (شاید بات رو بلاک کرده).",
                                   buttons=Button.clear())
            await send_admin_main(admin_id)
            return
        if action == "bmsg":
            ids = db_all(include_banned=False)
            sent = 0
            for uid in ids:
                try:
                    await bot.send_message(uid, f"📢 <b>پیام همگانی:</b>\n\n{text}", parse_mode="html")
                    sent += 1
                except Exception:
                    pass
                await asyncio.sleep(0.05)
            admin_state.pop(admin_id, None)
            await bot.send_message(admin_id, f"✅ برای {sent} از {len(ids)} کاربر ارسال شد.",
                                   buttons=Button.clear())
            await send_admin_main(admin_id)
            return


# ================= پنل هلپر مشترک (.پنل هر کاربر) =================
def hub_get_ctx(uid):
    if not is_logged_in(uid) or uid not in running:
        return None
    u = db_get(uid)
    if u["banned"]:
        return None
    path = cfg_path(uid)
    if not os.path.exists(path):
        return None
    import json

    def load():
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def save_back(c):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)

    cfg = load()

    class LazyCfg(dict):
        def __setitem__(self, k, v):
            super().__setitem__(k, v)

    lc = LazyCfg(cfg)

    def do_save():
        save_back(dict(lc))

    async def info():
        u = db_get(uid)
        secs, mode = runway_seconds(u)
        if mode == "admin":
            bal = "💎 موجودی: نامحدود ♾"
        else:
            bal = f"💎 الماس: {fd(u['diamonds'])}\n⏳ زمان باقی‌مانده: {fmt_duration(secs)}" + (" (تست)" if mode == "trial" else "")
        return f"🆔 {uid}\n{bal}\nوضعیت: {'روشن' if running.get(uid) else 'خاموش'}"

    async def ping():
        return "🏓 پنل آنلاین است"

    return lc, do_save, {"info": info, "ping": ping}


BACKUP_HOURS = float(os.getenv("BACKUP_HOURS", "6"))
BACKUP_KEEP = int(os.getenv("BACKUP_KEEP", "10"))


async def backup_loop():
    """بکاپ خودکار دیتابیس، سشن‌ها و تنظیمات هر کاربر — نگه‌داشتن BACKUP_KEEP نسخه‌ی آخر."""
    os.makedirs("backups", exist_ok=True)
    while True:
        try:
            stamp = time.strftime("%Y%m%d_%H%M")
            tmp = f"backups/backup_{stamp}.zip"
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
                for base in (DB_PATH, os.getenv("HUB_GAMES_DB", "hub_games.db"), SESS_DIR, CFG_DIR):
                    if os.path.isfile(base):
                        z.write(base)
                    elif os.path.isdir(base):
                        for root, _, files in os.walk(base):
                            for f in files:
                                z.write(os.path.join(root, f))
            olds = sorted(glob.glob("backups/backup_*.zip"))
            for p in olds[:-BACKUP_KEEP] if BACKUP_KEEP > 0 else olds:
                try:
                    os.remove(p)
                except OSError:
                    pass
            print("backup saved:", tmp)
        except Exception as ex:
            print("backup error:", ex)
        await asyncio.sleep(BACKUP_HOURS * 3600)


async def main():
    if not HUB_BOT_TOKEN:
        print("❌ HUB_BOT_TOKEN تنظیم نشده")
        return
    if not ADMIN_IDS:
        print("⚠️ ADMIN_IDS تنظیم نشده؛ هیچ‌کس دسترسی پنل مدیریت نداره")
    await bot.start(bot_token=HUB_BOT_TOKEN)
    print("Hub bot: @" + (await bot.get_me()).username)
    if helper_bot:
        await helper_bot.start(bot_token=HELPER_BOT_TOKEN)
        setup_panel_hub(helper_bot, hub_get_ctx)
        setup_games(helper_bot, os.getenv("HUB_GAMES_DB", "hub_games.db"), admin_ids=ADMIN_IDS)   # توی گروه /gameon بزن
        print("Hub helper bot: @" + (await helper_username()))
    asyncio.create_task(billing_loop())
    asyncio.create_task(backup_loop())
    if WEB_PASSWORD:
        from webpanel import WebPanel

        async def send_html(uid, text):
            await bot.send_message(uid, text, parse_mode="html")
        web = WebPanel({
            "db_get": db_get, "db_set": db_set, "db_all": db_all, "db_search": db_search,
            "running": running, "admins": ADMIN_IDS, "is_logged_in": is_logged_in,
            "stop_self": stop_self, "notify": notify, "send_html": send_html,
            "fmt_duration": fmt_duration, "TRIAL_SECONDS": TRIAL_SECONDS,
            "db": _db, "owners": OWNERS, "start_self": start_self, "delete_self": delete_self_session,
            "cfg_path": cfg_path, "log_dir": LOG_DIR, "runway_seconds": runway_seconds, "ref_count": ref_count,
            "db_find_user": db_find_user, "BRAND": BRAND, "start_time": time.time(),
            "restart": lambda: os._exit(0),   # systemd با Restart=always دوباره بالاش میاره
        }, WEB_PASSWORD, WEB_HOST, WEB_PORT, WEB_SECURE)
        await web.start()
    else:
        print("ℹ️ WEB_PASSWORD تنظیم نشده؛ پنل وب خاموشه")
    clients = [bot] + ([helper_bot] if helper_bot else [])
    await asyncio.gather(*(c.run_until_disconnected() for c in clients))


if __name__ == "__main__":
    asyncio.run(main())
