"""پنل دکمه‌ای (inline) برای NRT Self — از طریق بات هلپر (inline mode) بالا میاد.

ظاهر مثل LTM Self:
  • پیام اصلی: بنر + «› Panel @هلپر» + دکمه‌های «مدیریت سلف | حساب کاربری | بستن پنل»
  • هر بخش: عنوان + بلاک‌کوت دستورها + «بازگشت به دستورات»
  • دکمه‌های رنگی (سبز/آبی/قرمز) وقتی نسخه‌ی Telethon پشتیبانی کنه؛ وگرنه دکمه‌ی معمولی.
  • صفحه‌های ویژه: حالت متن (۲۰ سبک)، حالت اکشن (پیوی/گروه)، بخش ساعت، مدیریت سلف، حساب کاربری.

منطق نمایش توی process() هست و فقط به cfg/save/on_change/actions وابسته‌ست؛ هم برای سلف تکی
(setup_panel) و هم برای هاب چندکاربره (setup_panel_hub) استفاده می‌شه.
"""
import html
import os
import re

from telethon import Button, events
from telethon.tl import types

import styles
from ui import btn, switch_btn
from details import detail_text

BANNER_DIR = os.getenv("BANNER_DIR", "banners")
BRAND = os.getenv("BRAND", "NRT Self")
CAPTION_MAX = 1000   # کپشن عکس inline حداکثر ۱۰۲۴ کاراکتره

CYCLES = {
    "react": [None, "❤", "👍", "🔥", "😂"],
}

# کلیدهای حالت اکشن: (نوع، اسم فارسی، نوع اکشن تلگرام، متن نمایش)
ACTION_KINDS = [
    ("chat", "چت", "typing", "«در حال تایپ...»"),
    ("game", "بازی", "game", "«در حال بازی...»"),
    ("voice", "ویس", "record-voice", "«در حال ضبط ویس...»"),
    ("video", "ویدیو مسیج", "record-round", "«در حال ضبط ویدیو مسیج...»"),
]
ACTION_KEYS = [f"act_{k}_{w}" for k, *_ in ACTION_KINDS for w in ("pv", "gp")]


def esc(s):
    return html.escape(str(s), quote=False)


def alert_text(s):
    return str(s)[:190]    # حد تلگرام برای alert: ۲۰۰ کاراکتر


def fit_caption(text):
    """کپشن عکس بیشتر از ۱۰۲۴ کاراکتر نمی‌شه؛ اگه بلندتر بود تگ‌ها رو برمی‌داریم و کوتاه می‌کنیم."""
    if len(text) <= CAPTION_MAX:
        return text
    return re.sub(r"<[^>]+>", "", text)[:CAPTION_MAX - 1] + "…"


def blockquote(first, bold=None):
    t = f"<blockquote>{esc(first)}"
    if bold:
        t += f"\n<b>{esc(bold)}</b>"
    return t + "</blockquote>"


def banner_file(uid):
    """مسیر بنر اختصاصی هر کاربر (با عکس پروفایل خودش)؛ اگه نبود بنر پیش‌فرض."""
    for path in (os.path.join(BANNER_DIR, f"user_{uid}.jpg"),
                 os.getenv("BANNER_PATH", "assets/banner.jpg")):
        if os.path.exists(path):
            return path
    return None


def panel_article(ev, uid, title, text, rows):
    text = fit_caption(text)
    path = banner_file(uid)
    if path:
        return ev.builder.photo(path, text=text, buttons=rows, id="panel", parse_mode="html")
    return ev.builder.article(title, text=text, buttons=rows, parse_mode="html")


# kind: t=روشن/خاموش | c=چرخشی | a=نمایش مستقیم | h=راهنمای دستور | v=صفحه‌ی ویژه
# ۸ صفحه، هم‌ترتیب با منوی LTM Self
PAGES = {
    1: ("🛠 مدیریت سلف", [
        ("t", "enabled", "⚡ مدیریت سلف"),
        ("a", "info", "ℹ️ اطلاعات"), ("a", "ping", "🏓 پینگ"),
        ("h", "موجودی الماس: .موجودی  |  نشست‌ها: .نشست ها  |  قطع نشست: .قطع نشست 2", "💎 موجودی و نشست‌ها"),
        ("h", "داخل بات هاب: /start ← 💎 انتقال الماس (به آیدی یا یوزرنیم کاربر هاب)", "💎 انتقال الماس"),
        ("v", "ad", "👮 مدیریت ادمین"),
        ("h", ".پرفیکس /  ← تغییر پیشوند دستورها  |  .پرفیکس پیش‌فرض", "🔣 پرفیکس"),
        ("h", ".عضویت اجباری تنظیم @ch  ←  بعد توی گروه: .عضویت اجباری روشن", "📢 عضویت اجباری"),
        ("h", ".جوین  ← ریپلای روی پیامی که لینک/یوزرنیم گروه یا کانال داره", "🔗 جوین از پیام"),
        ("h", ".راهنما  ← لیست همه دستورها", "📖 راهنما"),
        ("h", ".ثبت نام  ← ثبت اسم فعلی به‌عنوان اسم اصلی", "💾 ثبت نام"),
    ]),
    2: ("⚡ قابلیت‌های خودکار", [
        ("v", "sn", "👁 سین خودکار"), ("v", "ar", "💬 پاسخ خودکار"),
        ("h", ".تنظیم ری اکشن 🔥 (ریپلای)  |  .لیست ری اکشن", "❤ ری‌اکشن خودکار"),
        ("v", "fc", "🥇 کامنت اول خودکار"),
        ("v", "mw", "🐱 میو خودکار"), ("v", "ps", "🐈 پیشی خودکار"),
        ("v", "fs", "🎣 ماهی‌گیری خودکار"),
        ("c", "react", "❤ ری‌اکشن پیوی (همه)"),
    ]),
    3: ("🔒 امنیت و حریم خصوصی", [
        ("h", ".نگهبان روشن  |  .نگهبان لینک/فوروارد/منشن/استیکر/گیف روشن  (توی گروه، ادمین باش)", "🛡 نگهبان چت"),
        ("t", "pvlock", "🔒 قفل پیوی"), ("t", "antilogin", "🛡 ضد لاگین"),
        ("h", ".بلاک / .آنبلاک  (ریپلای یا آیدی)", "⛔ بلاک"),
        ("h", ".سکوت / .رفع سکوت  (ریپلای)", "🔇 سکوت"),
        ("t", "filter_on", "🚫 فیلتر کلمات"),
        ("h", ".فیلتر کلمه متن  |  .اعمال فیلتر آیدی/همه  |  .لیست فیلتر کلمات", "⚙️ تنظیم فیلتر"),
        ("h", ".بکاپ چت  ← کل چت پیوی به‌صورت HTML توی Saved Messages", "💾 بکاپ چت"),
    ]),
    4: ("🎭 حالت‌ها و ظاهر", [
        ("t", "online", "🟢 حالت آنلاین"), ("t", "secretary", "🗂 حالت منشی"),
        ("h", ".تنظیم منشی (ریپلای)  |  .تنظیم زمان منشی 30", "⚙️ تنظیم منشی"),
        ("v", "ts", "✍️ حالت متن"), ("v", "ax", "🎭 حالت اکشن"),
        ("v", "ck", "🕒 بخش ساعت"),
        ("h", ".هوا تهران", "🌤 آب و هوا"),
        ("v", "pe", "💎 ایموجی پریمیوم"), ("v", "pc", "📢 ایموجی پریمیوم چنل"),
    ]),
    5: ("🧰 ابزارها (1)", [
        ("h", ".آیدی | .تاریخ | .یادآوری 30 دقیقه متن | .لینک پیام | .ذخیره  (ریپلای)", "🧰 کاربردی"),
        ("h", ".محاسبه 2+2*3", "🧮 محاسبات"),
        ("h", ".ارز 100 USD EUR", "💱 قیمت ارز"), ("h", ".کریپتو bitcoin", "🪙 کریپتو"),
        ("h", ".دانلود لینک  |  .دانلود صدا لینک  (یا ریپلای روی لینک)", "⬇️ دانلود"),
        ("h", ".ترجمه en سلام  (یا ریپلای)", "🌐 ترجمه"),
        ("h", ".هوش مصنوعی سوالت", "🤖 هوش مصنوعی"),
        ("h", ".کیفیت  (ریپلای روی عکس)", "🖼 کیفیت عکس"),
        ("h", "ریپلای: .عکس/ویدیو/گیف/استیکر/دایره به ...  مثلا .ویدیو به دایره", "🔁 ابزار تبدیل"),
    ]),
    6: ("🎵 ابزارها (2)", [
        ("h", ".آهنگ اسم  |  .آهنگ اسم | 2", "🎵 سرچ آهنگ"),
        ("h", ".سرچ یوتیوب متن  |  .سرچ یوتیوب متن | 3", "▶️ سرچ یوتیوب"),
    ]),
    7: ("👥 گروه و پیام", [
        ("h", ".مدیریت گروه ← لیست دستورها (قفل گروه، عنوان، لینک، ترفیع، عزل، اخراج، حالت آرام)", "🛠 مدیریت گروه"),
        ("h", ".تگ 20  |  .همه  ← تگ ۲۰ نفر / همه", "📣 تگ اعضا"),
        ("h", ".اسپم متن 10  (یا ریپلای: .اسپم 10)", "💥 اسپم"),
        ("h", ".حذف 10  ← ۱۰ پیام آخر خودت", "🗑 حذف پیام"),
        ("h", ".اسکرین google.com  ← اسکرین سایت", "🌐 اسکرین"),
        ("h", ".متن به ویس متن  |  .متن به ویس مرد متن  (یا ریپلای)", "🎙 متن به ویس"),
        ("h", ".ویس به متن  (ریپلای روی ویس)", "📝 ویس به متن"),
        ("h", ".اسکرین صفحه 5  ← عکس از آخرین پیام‌های چت", "📸 اسکرین صفحه"),
        ("t", "screen_on", "🤖 اسکرین خودکار"),
        ("h", ".لایو عنوان  |  .پخش لینک  |  .پنل لایو", "🔴 لایو"),
        ("h", ".بن / .سیک / .آنبن  (ریپلای)", "⛔ بن"), ("h", ".پین / .حذف پین  (ریپلای)", "📌 پین"),
        ("h", ".بن ال / .حذف بن ال / .لیست بن ال  ← بن سراسری", "🌐 بن سراسری"),
    ]),
    8: ("🎮 بازی و سرگرمی", [
        ("h", ".تقلب تاس 6  |  دارت | بولینگ | بسکتبال | فوتبال | کازینو 64", "🎯 تقلب"),
        ("h", ".چالش استارزی روشن 30  (اول استارزی رو تنظیم کن)", "🔥 چالش استارزی"),
        ("h", ".تنظیم عکس استارزی (ریپلای)  |  .تنظیم زمان استارزی 20:00  |  .استارزی روشن", "⭐ استارزی"),
        ("h", ".تنظیم دوست / .حذف دوست  |  .لیست دوستان  |  .تنظیم کلمات دوست متن", "🫂 دوست"),
        ("h", ".تنظیم دشمن / .حذف دشمن  |  .لیست دشمن  |  .تنظیم فحش متن", "🗡 دشمن"),
        ("h", ".بازی گربه بگیر  |  غذا | بازی | خواب | اسم X", "🐱 بازی گربه"),
        ("t", "tabchi_on", "📣 تبچی"),
        ("h", ".تنظیم بنر فور (ریپلای)  |  .تنظیم دقیقه بنر 30 1  |  .تنظیم هدف بنر 1", "⚙️ تنظیم تبچی"),
        ("t", "content_on", "📦 محتوا"),
        ("h", ".محتوا جدید کلمه ← بعد: .ذخیره محتوا کلمه (ریپلای)  |  .لیست محتوا", "🗂 مدیریت محتوا"),
        ("h", ".تاس  .دارت  .بولینگ  .بسکتبال", "🎲 تاس و بازی‌ها"),
        ("h", ".کازینو  یا  .کازینو 64  ← اسلات تا رسیدن به عدد", "🎰 کازینو"),
    ]),
    9: ("🧩 مدیریت گروه‌های مقصد", [
        ("h", ".گروه ها ← راهنمای تنظیم گروه بازی و گروه گزارش", "📍 گروه‌ها"),
        ("h", ".گروه بازی تنظیم -1001234567890 ← تنظیم گروه بازی (چند آیدی با کاما)", "🎮 گروه بازی"),
        ("h", ".گزارش انجمن تنظیم -1001234567890 ← تنظیم گروه Forum گزارش", "📊 گروه گزارش"),
        ("h", ".گزارش انجمن ایجاد ← ساخت موضوع‌های گزارش در گروه Forum", "🗂 موضوع‌های گزارش"),
        ("h", "گروه بازی و گروه گزارش مستقل هستند؛ آیدی یکسان استفاده نکن.", "⚠️ جداسازی مقصدها"),
    ]),
}


# ================= نمای صفحه‌ها =================
def detail_view(n, idx):
    """صفحه‌ی توضیح یک قابلیت + دکمه‌ی بازگشت به همون صفحه."""
    label = PAGES[n][1][idx][2]
    text = detail_text(label)
    if text is None:
        return None
    return text, [[btn("🔙 بازگشت به دستورات", f"p:{n}", "red")]]


def mark(on):
    return "〈 ✓ 〉" if on else "〈 ✗ 〉"


def item_button(n, i, item, cfg):
    kind, key, text = item
    data = f"i:{n}:{i}"
    if kind == "t":
        on = bool(cfg.get(key))
        return btn(f"{mark(on)} {text}", data, "green" if on else "red")
    if kind == "c":
        cur = cfg.get(key)
        return btn(f"{text}: {cur or '⛔'}", data, "green" if cur else "blue")
    return btn(text, data, "blue")


def main_view(tag=""):
    text = f"🎛 <b>پنل {esc(BRAND)}</b>\nیه بخش رو انتخاب کن:"
    if tag:
        text += f"\n\n› {esc(tag)}"
    rows = [[btn("مدیریت سلف", "v:mg:0", "blue"), btn("حساب کاربری", "v:ac:0", "blue")]]
    cats = [btn(PAGES[n][0], f"p:{n}", "blue") for n in sorted(PAGES)]
    rows += [cats[i:i + 2] for i in range(0, len(cats), 2)]
    rows.append([btn("بستن پنل", "x", "red")])
    return text, rows


def page_view(n, cfg):
    title, items = PAGES[n]
    btns = [item_button(n, i, it, cfg) for i, it in enumerate(items)]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    nav = [btn(f"「{k}」" if k == n else str(k), f"p:{k}", "blue") for k in sorted(PAGES)]
    rows.extend(nav[i:i + 5] for i in range(0, len(nav), 5))   # مثل منوی اصلی: ۵ تا در هر ردیف
    rows.append([btn("🔙 بازگشت به منوی اصلی", "m", "red")])
    return f"<b>{esc(title)}</b>  ({n}/{len(PAGES)})", rows


def back_row(n, label="🔙 بازگشت به دستورات"):
    return [btn(label, f"p:{n}" if n else "m", "red")]


# صفحه‌ی توضیح + دکمه‌ی روشن/خاموش: کلید صفحه ← (برچسب توضیح در details.py، [(کلید cfg، متن دکمه)])
DETAIL_TOGGLES = {
    "sn": ("👁 سین خودکار", [("autoseen", "پیوی"), ("seen_gp", "گروه"), ("seen_ch", "کانال"), ("seen_bot", "ربات")]),
    "ar": ("💬 پاسخ خودکار", [("autoreply_on", "پاسخ خودکار")]),
    "fc": ("🥇 کامنت اول خودکار", [("fc_on", "کامنت اول")]),
    "mw": ("🐱 میو خودکار", [("meow_on", "میو خودکار")]),
    "ps": ("🐈 پیشی خودکار", [("pishi_on", "پیشی خودکار")]),
    "fs": ("🎣 ماهی‌گیری خودکار", [("fish_on", "ماهی‌گیری خودکار")]),
    "pe": ("💎 ایموجی پریمیوم", [("pe_on", "ایموجی پریمیوم")]),
    "pc": ("📢 ایموجی پریمیوم چنل", [("pe_chan", "ایموجی پریمیوم چنل")]),
}


def view_detail_toggle(key, cfg, n):
    label, toggles = DETAIL_TOGGLES[key]
    text = detail_text(label) or f"<b>{esc(label)}</b>"
    btns = []
    for ck, fa in toggles:
        on = bool(cfg.get(ck, ck == "autoreply_on"))
        btns.append(btn(f"{mark(on)} {fa}", f"s:{key}:{ck}:{n}", "green" if on else "red"))
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append(back_row(n))
    return text, rows


def view_admin(cfg, n):
    admins = cfg.get("self_admins") or []
    prefix = cfg.get("admin_prefix") or ""
    text = ((detail_text("👮 مدیریت ادمین") or "")
            + f"\n\n<b>تعداد ادمین‌ها: {len(admins)}</b>\n<b>پرفیکس ادمین: {esc(prefix) if prefix else 'پیش‌فرض (بدون پرفیکس)'}</b>")
    rows = [[btn("لیست ادمین‌ها", f"s:ad:list:{n}", "blue"), btn("پرفیکس ادمین", f"s:ad:prefix:{n}", "blue")],
            back_row(n)]
    return text, rows


def admin_item_data():
    """data دکمه‌ی «مدیریت ادمین» توی صفحه‌ی ۱ (ادمین‌های سلف بهش دسترسی ندارن)."""
    for i, (kind, key, _) in enumerate(PAGES[1][1]):
        if kind == "v" and key == "ad":
            return f"i:1:{i}"
    return None


def callback_allowed_for_admin(data):
    return not (data.startswith("v:ad:") or data.startswith("s:ad:") or data == admin_item_data())


def view_manage(cfg, n):
    on = cfg.get("enabled", True)
    text = ("⚙️ <b>مدیریت سلف</b>\n\n"
            + blockquote("با دکمه‌ی زیر می‌تونی بدون نوشتن دستور، همینجا سلف رو خاموش یا روشن کنی.") + "\n"
            + blockquote("خاموش کردن، همه‌ی قابلیت‌های خودکار (ساعت، منشی، تبچی، استارزی و ...) رو متوقف می‌کنه؛ "
                         "روشن کردن دوباره، دقیقاً همون‌ها رو از سر می‌گیره."))
    rows = [[btn(f"{mark(on)} {'روشن' if on else 'خاموش'}", f"s:mg:toggle:{n}", "green" if on else "red")],
            back_row(n)]
    return text, rows


def view_textmode(cfg, n):
    cur = cfg.get("textmode")
    cur = styles.LEGACY.get(cur, cur)
    text = ("<b>بخش حالت متن</b>\n\n"
            + blockquote(".متن [سبک]  یا  .متن خاموش",
                         "هر پیامی که می‌فرستی خودکار با سبک انتخابی ویرایش می‌شه")
            + "\n<b>نکته:</b> فونت‌های یونیکدی فقط روی حروف لاتین و عدد اثر دارن؛ بولد/ایتالیک/کوت/... روی فارسی هم کار می‌کنن.")
    btns = [btn(f"{mark(key == cur)} {fa}", f"s:ts:{key}:{n}", "green" if key == cur else "red")
            for key, fa in styles.STYLE_ORDER]
    pairs = btns[:18]
    rows = [pairs[i:i + 2] for i in range(0, len(pairs), 2)]
    rows += [[b] for b in btns[18:]]
    rows.append(back_row(n, "بازگشت"))
    return text, rows


def view_action(cfg, n):
    parts = ["<b>حالت اکشن</b>\n"]
    for k, fa, _, shown in ACTION_KINDS:
        parts.append(blockquote(f".حالت {fa} پیوی روشن / خاموش", f"نمایش {shown} در پیوی"))
        parts.append(blockquote(f".حالت {fa} گروه روشن / خاموش", "همان قابلیت، برای گروه‌ها"))
    parts.append("<b>می‌تونید چند حالت رو همزمان روشن نگه دارید.</b>")
    text = "\n".join(parts)
    btns = []
    for k, fa, *_ in ACTION_KINDS:
        for w, wfa in (("pv", "پیوی"), ("gp", "گروه")):
            key = f"act_{k}_{w}"
            on = bool(cfg.get(key))
            btns.append(btn(f"{mark(on)} {fa} {wfa}", f"s:ax:{key}:{n}", "green" if on else "red"))
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append(back_row(n, "بازگشت"))
    return text, rows


def view_clock(cfg, n):
    font = cfg.get("clock_font") or "mono"
    sample = "14 : 08".translate(styles.clock_digits(font))
    text = ("<b>⚙ بخش ساعت</b>\n\n"
            + blockquote("از اینجا ساعت کنار اسم، فامیل، بیو و عنوان چنل/گپ رو مدیریت کن.",
                         "ساعت به وقت تهران و هر دقیقه آپدیت می‌شه") + "\n"
            + blockquote(".ساعت اسم روشن | .ساعت فامیل روشن | .ساعت بیو روشن\n.ساعت فونت [اسم فونت]\n"
                         ".ساعت چت روشن  (توی گروه/کانالی که ادمینی)"))
    row = []
    for key, fa in (("first", "اسم"), ("last", "فامیل"), ("bio", "بیو")):
        on = bool(cfg.get(f"clock_{key}"))
        row.append(btn(f"{mark(on)} {fa}", f"s:ck:{key}:{n}", "green" if on else "red"))
    rows = [row[:2],
            [row[2], btn(f"🔤 فونت: {styles.CLOCK_FONT_FA.get(font, font)}  {sample}", f"s:ck:font:{n}", "blue")],
            [btn("⏱ ساعت چنل/گپ", f"s:ck:chat:{n}", "blue")],
            back_row(n, "بازگشت")]
    return text, rows


async def view_account(actions, n):
    fn = actions.get("info")
    try:
        info = await fn() if fn else "از دستور .اطلاعات توی چت استفاده کن"
    except Exception as ex:
        info = f"خطا: {ex}"
    text = "👤 <b>حساب کاربری</b>\n\n" + blockquote(info)
    row = [btn("🔄 بروزرسانی", f"s:ac:refresh:{n}", "blue")]
    if actions.get("ping"):
        row.append(btn("🏓 پینگ", f"s:ac:ping:{n}", "blue"))
    return text, [row, back_row(n, "بازگشت")]


async def render_view(key, n, cfg, actions):
    if key == "mg":
        return view_manage(cfg, n)
    if key == "ts":
        return view_textmode(cfg, n)
    if key == "ax":
        return view_action(cfg, n)
    if key == "ck":
        return view_clock(cfg, n)
    if key == "ac":
        return await view_account(actions, n)
    if key == "ad":
        return view_admin(cfg, n)
    if key in DETAIL_TOGGLES:
        return view_detail_toggle(key, cfg, n)
    return None


# ================= اجرای دکمه‌ها (مشترک بین سلف تکی و هاب) =================
async def apply_set(key, arg, cfg, save, on_change, actions):
    """تغییر تنظیم از داخل صفحه‌های ویژه. خروجی: متن alert یا None."""
    changed, note = [], None
    if key == "mg" and arg == "toggle":
        cfg["enabled"] = not cfg.get("enabled", True)
        changed = ["enabled"]
    elif key == "ts" and arg in styles.STYLE_FA:
        cur = styles.LEGACY.get(cfg.get("textmode"), cfg.get("textmode"))
        cfg["textmode"] = None if cur == arg else arg
        changed = ["textmode"]
    elif key == "ax" and arg in ACTION_KEYS:
        cfg[arg] = not cfg.get(arg)
        changed = [arg]
    elif key == "ck":
        if arg in ("first", "last", "bio"):
            cfg[f"clock_{arg}"] = not cfg.get(f"clock_{arg}")
            changed = [f"clock_{arg}"]
        elif arg == "font":
            order = styles.CLOCK_FONT_ORDER
            cur = cfg.get("clock_font") or "mono"
            cfg["clock_font"] = order[(order.index(cur) + 1) % len(order)] if cur in order else order[0]
            changed = ["clock_font"]
        elif arg == "chat":
            note = "توی گروه/کانالی که ادمینی بنویس: .ساعت چت روشن  (خاموش: .ساعت چت خاموش)"
    elif key in DETAIL_TOGGLES and arg in {ck for ck, _ in DETAIL_TOGGLES[key][1]}:
        cfg[arg] = not cfg.get(arg, arg == "autoreply_on")
        changed = [arg]
    elif key == "ad" and arg == "list":
        ids = cfg.get("self_admins") or []
        note = ("👮 ادمین‌ها: " + "  ".join(str(i) for i in ids)) if ids else "لیست ادمین خالیه (.تنظیم ادمین)"
    elif key == "ad" and arg == "prefix":
        note = f"🔣 پرفیکس ادمین: {cfg.get('admin_prefix') or 'بدون پرفیکس'}  |  تغییر: .تنظیم پرفیکس ادمین !"
    elif key == "ac" and arg == "ping":
        fn = actions.get("ping")
        note = await fn() if fn else None
    if changed:
        save()
        for c in changed:
            await on_change(c)
    return note


async def process(data, cfg, save, on_change, actions, tag=""):
    """خروجی یکی از: ("edit", text, rows) | ("edit_alert", text, rows, msg) | ("alert", msg) | ("close", text) | ("noop",)"""
    d = data.split(":")
    k = d[0]
    if k == "x":
        return ("close", "🎛 پنل بسته شد")
    if k == "m":
        t, r = main_view(tag)
        return ("edit", t, r)
    if k == "p":
        t, r = page_view(int(d[1]), cfg)
        return ("edit", t, r)
    if k == "v":                          # v:KEY:N
        res = await render_view(d[1], int(d[2]), cfg, actions)
        return ("edit",) + tuple(res) if res else ("noop",)
    if k == "s":                          # s:KEY:ARG:N
        note = await apply_set(d[1], d[2], cfg, save, on_change, actions)
        res = await render_view(d[1], int(d[3]), cfg, actions)
        if note and res:
            return ("edit_alert", res[0], res[1], note)
        return ("edit",) + tuple(res) if res else ("noop",)
    if k == "i":                          # i:N:IDX
        n, idx = int(d[1]), int(d[2])
        kind, key, _ = PAGES[n][1][idx]
        if kind == "t":
            cfg[key] = not cfg.get(key)
            save()
            await on_change(key)
        elif kind == "c":
            opts, cur = CYCLES[key], cfg.get(key)
            cfg[key] = opts[(opts.index(cur) + 1) % len(opts)] if cur in opts else opts[0]
            save()
            await on_change(key)
        elif kind == "a":
            fn = actions.get(key)
            return ("alert", await fn() if fn else "📌 دستور .اطلاعات یا .پینگ رو توی چت بزن")
        elif kind == "v":
            res = await render_view(key, n, cfg, actions)
            return ("edit",) + tuple(res) if res else ("noop",)
        else:
            dv = detail_view(n, idx)
            if dv is None:
                return ("alert", "📌 " + key)
            return ("edit", dv[0], dv[1])
        t, r = page_view(n, cfg)
        return ("edit", t, r)
    return ("noop",)


async def run_callback(ev, cfg, save, on_change, actions, tag=""):
    try:
        res = await process(ev.data.decode(), cfg, save, on_change, actions, tag)
        kind = res[0]
        if kind == "alert":
            await ev.answer(alert_text(res[1]), alert=True)
            return
        if kind == "close":
            await ev.edit(res[1], buttons=[])
            return
        if kind in ("edit", "edit_alert"):
            await ev.edit(fit_caption(res[1]), buttons=res[2], parse_mode="html")
        try:
            if kind == "edit_alert":
                await ev.answer(alert_text(res[3]), alert=True)
            else:
                await ev.answer()
        except Exception:
            pass
    except Exception as ex:
        if "not modified" in str(ex).lower():
            try:
                await ev.answer()
            except Exception:
                pass
            return
        print("panel error:", ex)
        try:
            await ev.answer("⚠️ خطا؛ دوباره امتحان کن", alert=True)
        except Exception:
            pass


CB_PATTERN = rb"(p:|i:|v:|s:|m$|x$)"   # دکمه‌های بازی (g:) و لایو (lv:) مال بقیه‌ن


async def _tag(bot, cache):
    if "t" not in cache:
        t = os.getenv("PANEL_TAG")
        if not t:
            try:
                t = f"Panel @{(await bot.get_me()).username}"
            except Exception:
                t = ""
        cache["t"] = t
    return cache["t"]


def setup_panel(bot, owner_id, cfg, save, on_change, actions):
    cache = {}

    @bot.on(events.NewMessage(pattern=r'/start', func=lambda e: e.is_private))
    async def start(ev):
        if ev.sender_id != owner_id:
            return
        await ev.respond(
            f'🎛 پنل {BRAND}\nروی دکمه بزن و یه چت انتخاب کن تا پنل اونجا باز بشه:',
            buttons=[[switch_btn('🎛 باز کردن پنل', 'panel', 'blue')]])

    @bot.on(events.InlineQuery)
    async def inline(ev):
        if ev.sender_id != owner_id:
            await ev.answer([])
            return
        text, rows = main_view(await _tag(bot, cache))
        await ev.answer([panel_article(ev, ev.sender_id, f"پنل {BRAND}", text, rows)],
                        cache_time=0, private=True)

    @bot.on(events.CallbackQuery(pattern=CB_PATTERN))
    async def callback(ev):
        if ev.sender_id != owner_id:
            # ادمین‌های سلف به پنل دسترسی دارن، به‌جز بخش «مدیریت ادمین»
            if ev.sender_id not in (cfg.get("self_admins") or []):
                await ev.answer("این پنل مال تو نیست", alert=True)
                return
            if not callback_allowed_for_admin(ev.data.decode()):
                await ev.answer("⛔ ادمین‌ها به مدیریت ادمین دسترسی ندارن", alert=True)
                return
        await run_callback(ev, cfg, save, on_change, actions, await _tag(bot, cache))


def setup_panel_hub(bot, get_ctx, deny_text="⛔ سلف تو فعال نیست (الماس یا زمانت تموم شده)."):
    """پنل مشترک برای همه‌ی کاربرهای هاب.
    get_ctx(uid) -> (cfg, save, actions) یا None. تغییرها توی فایل کانفیگ کاربر ذخیره می‌شه
    و پروسه‌ی سلف همون کاربر هر چند ثانیه یه بار اعمالشون می‌کنه."""
    cache = {}

    async def noop(_key):
        return None

    @bot.on(events.InlineQuery)
    async def inline(ev):
        ctx = get_ctx(ev.sender_id)
        if not ctx:
            await ev.answer([ev.builder.article("پنل", text=deny_text)], cache_time=0, private=True)
            return
        text, rows = main_view(await _tag(bot, cache))
        await ev.answer([panel_article(ev, ev.sender_id, "پنل سلف", text, rows)],
                        cache_time=0, private=True)

    @bot.on(events.CallbackQuery(pattern=CB_PATTERN))
    async def callback(ev):
        ctx = get_ctx(ev.sender_id)
        if not ctx:
            await ev.answer("این پنل مال تو نیست یا سلفت فعال نیست", alert=True)
            return
        cfg, save, actions = ctx
        await run_callback(ev, cfg, save, noop, actions, await _tag(bot, cache))
