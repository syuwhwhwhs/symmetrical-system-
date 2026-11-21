"""دکمه‌های رنگی (سبز / آبی / قرمز) مشترک بین همه‌ی بات‌ها (پنل، هاب، مدیریت، بازی).

رنگ دکمه از «استایل دکمه»ی خود تلگرام میاد (Layer ≥ 222) و فقط وقتی کار می‌کنه که Telethon جدید باشه:
    pip install -U "telethon>=1.43,<2"
اگه Telethon قدیمی باشه، دکمه‌ها بی‌رنگ می‌شن و (پیش‌فرض) یه دایره‌ی رنگی 🟢🔵🔴 اول متنشون میاد
تا تفاوت رنگ‌ها دیده بشه. برای خاموش‌کردنش توی .env بنویس: BUTTON_EMOJI_FALLBACK=0

btn(text, data, color)       دکمه‌ی شیشه‌ای (callback)      color: green / blue / red
auto_btn(text, data)         همون، با حدس رنگ از متن (لغو/حذف/بازگشت قرمز، تایید/بله/شروع سبز، بقیه آبی)
url_btn(text, url, color)    دکمه‌ی لینک
text_btn / phone_btn         دکمه‌های کیبورد معمولی (انصراف / ارسال شماره)
switch_btn(text, query, c)   دکمه‌ی باز کردن اینلاین
"""
import inspect
import os

from telethon import Button
from telethon.tl import types

_COLOR_KW = {"blue": "bg_primary", "red": "bg_danger", "green": "bg_success"}
_DOT = {"blue": "🔵", "red": "🔴", "green": "🟢"}
FALLBACK = os.getenv("BUTTON_EMOJI_FALLBACK", "1") != "0"

RED_WORDS = ("❌", "🚫", "⛔", "انصراف", "لغو", "بستن", "حذف", "خیر", "پاک", "بازگشت", "🔙", "منوی اصلی",
             "🗑", "خاموش", "بن کردن", "مسدود")
GREEN_WORDS = ("✅", "✔", "✓", "تایید", "تأیید", "بله", "پیوستن", "شروع", "فعال", "🟢", "▶️", "➕", "روشن",
               "رفع بن", "هدیه", "🎁")


def _accepts_style(cls):
    try:
        return "style" in inspect.signature(cls.__init__).parameters
    except (TypeError, ValueError):
        return False


def style_supported():
    """آیا این نسخه‌ی Telethon استایل (رنگ) دکمه‌ها رو می‌شناسه؟ (هیچ‌وقت خطا نمی‌ده)"""
    try:
        cb = getattr(types, "KeyboardButtonCallback", None)
        return cb is not None and hasattr(types, "KeyboardButtonStyle") and _accepts_style(cb)
    except Exception:
        return False


def _style(color):
    return types.KeyboardButtonStyle(**{_COLOR_KW[color]: True})


def guess_color(text):
    t = str(text)
    if any(w in t for w in RED_WORDS):
        return "red"
    if any(w in t for w in GREEN_WORDS):
        return "green"
    return "blue"


def _label(text, color):
    """اگه رنگ واقعی پشتیبانی نشه، یه دایره‌ی رنگی اول متن (فقط وقتی متن با حرف شروع بشه)."""
    if FALLBACK and color in _DOT and text and (text[0].isalnum() or "\u0600" <= text[0] <= "\u06ff"):
        return f"{_DOT[color]} {text}"
    return text


def paint(button, color):
    """رنگ دادن به یه دکمه (Button.* یا آبجکت خام TL). اگه پشتیبانی نشه همون دکمه برمی‌گرده."""
    if not color or color not in _COLOR_KW:
        return button
    raw = getattr(button, "button", button)
    if style_supported() and _accepts_style(type(raw)):
        try:
            raw.style = _style(color)
            return button
        except Exception:
            pass
    return None   # یعنی رنگ اعمال نشد؛ فراخوان fallback رو انجام می‌ده


def btn(text, data, color=None):
    if isinstance(data, str):
        data = data.encode()
    if color and style_supported():
        try:
            return types.KeyboardButtonCallback(text=text, data=data, style=_style(color))
        except Exception:
            pass
    return Button.inline(_label(text, color), data)


def auto_btn(text, data=None, color=None):
    return btn(text, data if data is not None else b"-", color or guess_color(text))


def url_btn(text, url, color="blue"):
    b = Button.url(text, url)
    if paint(b, color) is None:
        b = Button.url(_label(text, color), url)
    return b


def switch_btn(text, query="", color="blue"):
    b = Button.switch_inline(text, query=query)
    if paint(b, color) is None:
        b = Button.switch_inline(_label(text, color), query=query)
    return b


def text_btn(text, color="red", resize=True):
    b = Button.text(text, resize=resize)
    if paint(b, color) is None:
        b = Button.text(_label(text, color), resize=resize)
    return b


def phone_btn(text, color="green", resize=True):
    b = Button.request_phone(text, resize=resize)
    if paint(b, color) is None:
        b = Button.request_phone(_label(text, color), resize=resize)
    return b


if not style_supported():
    print("⚠️ Telethon شما رنگ دکمه‌ها رو پشتیبانی نمی‌کنه (دکمه‌ها بی‌رنگن). نصب نسخه‌ی جدید: "
          'pip install -U "telethon>=1.43,<2"')
