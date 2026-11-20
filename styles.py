"""سبک‌های متن (حالت متن) — مثل بخش «حالت متن» LTM Self.

دو نوع سبک داریم:
  • فونت‌های یونیکد (اسکریپت، فراکتور، دوبل، سنس، مونو، فول‌ویدث، دایره‌ای): حروف لاتین و عدد رو عوض می‌کنن.
  • سبک‌های فرمتی تلگرام (بولد، ایتالیک، اسپویلر، کوت، خط‌خورده، زیرخط، کد): entity می‌سازن.
حروف فارسی توی فونت‌های یونیکد تغییری نمی‌کنن (چون معادل یونیکد ندارن)؛ سبک‌های فرمتی روی فارسی هم کار می‌کنن.
بدون وابستگی به تلگرام؛ قابل تست مستقل.
"""
import random

# ---------- ساخت نقشه‌ی حروف ----------


def _alpha(upper, lower, digits=None, exc=None):
    m = {}
    for i in range(26):
        m[chr(65 + i)] = chr(upper + i)
        m[chr(97 + i)] = chr(lower + i)
    if digits:
        for i in range(10):
            m[str(i)] = chr(digits + i)
    m.update(exc or {})
    return m


MAPS = {
    "bolditalic": _alpha(0x1D468, 0x1D482),
    "script": _alpha(0x1D49C, 0x1D4B6, exc={
        "B": "\u212C", "E": "\u2130", "F": "\u2131", "H": "\u210B", "I": "\u2110",
        "L": "\u2112", "M": "\u2133", "R": "\u211B", "e": "\u212F", "g": "\u210A", "o": "\u2134"}),
    "scriptbold": _alpha(0x1D4D0, 0x1D4EA, 0x1D7CE),
    "fraktur": _alpha(0x1D504, 0x1D51E, exc={
        "C": "\u212D", "H": "\u210C", "I": "\u2111", "R": "\u211C", "Z": "\u2128"}),
    "frakturbold": _alpha(0x1D56C, 0x1D586, 0x1D7CE),
    "double": _alpha(0x1D538, 0x1D552, 0x1D7D8, exc={
        "C": "\u2102", "H": "\u210D", "N": "\u2115", "P": "\u2119",
        "Q": "\u211A", "R": "\u211D", "Z": "\u2124"}),
    "sans": _alpha(0x1D5A0, 0x1D5BA, 0x1D7E2),
    "sansbold": _alpha(0x1D5D4, 0x1D5EE, 0x1D7EC),
    "sansitalic": _alpha(0x1D608, 0x1D622),
    "sansbolditalic": _alpha(0x1D63C, 0x1D656),
    "mono": _alpha(0x1D670, 0x1D68A, 0x1D7F6),
    "fullwidth": _alpha(0xFF21, 0xFF41, 0xFF10),
    "circled": _alpha(0x24B6, 0x24D0, exc={"0": "\u24EA", **{str(i): chr(0x2460 + i - 1) for i in range(1, 10)}}),
}

# سبک‌هایی که با entity ساخته می‌شن
ENTITY_STYLES = {"bold", "italic", "spoiler", "quote", "strike", "underline", "code"}

# ترتیب دکمه‌ها (اولی سمت راست، مثل پنل LTM): (کلید، اسم فارسی)
STYLE_ORDER = [
    ("italic", "ایتالیک"), ("bold", "بولد"),
    ("script", "اسکریپت"), ("bolditalic", "بولد ایتالیک"),
    ("fraktur", "فراکتور"), ("scriptbold", "اسکریپت بولد"),
    ("double", "دوبل"), ("frakturbold", "فراکتور بولد"),
    ("sansbold", "سنس بولد"), ("sans", "سنس"),
    ("sansbolditalic", "سنس بولد ایتالیک"), ("sansitalic", "سنس ایتالیک"),
    ("fullwidth", "فول ویدث"), ("mono", "مونو"),
    ("spoiler", "اسپویلر"), ("circled", "دایره‌ای"),
    ("strike", "خط خورده"), ("quote", "کوت"),
    ("underline", "زیر خط"),
    ("random", "رندوم"),
]
STYLE_FA = dict(STYLE_ORDER)

# اسم‌های فارسی/انگلیسی که کاربر توی دستور می‌نویسه ← کلید
ALIASES = {fa: k for k, fa in STYLE_ORDER}
ALIASES.update({k: k for k, _ in STYLE_ORDER})
ALIASES.update({"کد": "code", "مونو": "mono", "دایره": "circled", "خط": "strike", "زیرخط": "underline",
                "کوت": "quote", "فول": "fullwidth", "فولویدث": "fullwidth"})
# سازگاری با نسخه‌ی قبلی (cfg["textmode"] قدیمی)
LEGACY = {"mono": "mono", "bold": "bold", "italic": "italic", "spoiler": "spoiler"}

_RANDOM_POOL = [k for k, _ in STYLE_ORDER if k != "random"]


def resolve(name):
    """اسم سبک (فارسی/انگلیسی) ← کلید؛ None اگه نامعتبر باشه."""
    return ALIASES.get((name or "").strip().lower()) or ALIASES.get((name or "").strip())


def transform(text, style):
    """متن رو با فونت یونیکدی تبدیل می‌کنه. اگه سبک فرمتی باشه همون متن برمی‌گرده."""
    m = MAPS.get(style)
    if not m:
        return text
    return "".join(m.get(ch, ch) for ch in text)


def u16len(s):
    """طول رشته بر حسب UTF-16 (واحدی که entityهای تلگرام استفاده می‌کنن)."""
    return len(s.encode("utf-16-le")) // 2


def apply(text, style):
    """خروجی: (متن جدید، لیست [(نوع_entity، offset، length)]).
    نوع‌ها: bold|italic|code|spoiler|quote|strike|underline. بدون entity ← لیست خالی."""
    if style == "random":
        style = random.choice(_RANDOM_POOL)
    if style in ENTITY_STYLES:
        return text, [(style, 0, u16len(text))]
    return transform(text, style), []


def preview(style, sample="Hello 123"):
    new, ents = apply(sample, style)
    return new


# ---------- ساعت: فونت ارقام ----------
CLOCK_FONTS = {
    "mono": "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿",
    "normal": "0123456789",
    "bold": "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗",
    "double": "𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡",
    "sans": "𝟢𝟣𝟤𝟥𝟦𝟧𝟨𝟩𝟪𝟫",
    "fa": "۰۱۲۳۴۵۶۷۸۹",
    "ar": "٠١٢٣٤٥٦٧٨٩",
    "circled": "⓪①②③④⑤⑥⑦⑧⑨",
    "fullwidth": "０１２３４５６７８９",
}
CLOCK_FONT_FA = {"mono": "مونو", "normal": "ساده", "bold": "بولد", "double": "دوبل", "sans": "سنس",
                 "fa": "فارسی", "ar": "عربی", "circled": "دایره‌ای", "fullwidth": "فول ویدث"}
CLOCK_FONT_ORDER = list(CLOCK_FONTS)


def clock_digits(font):
    return str.maketrans("0123456789", CLOCK_FONTS.get(font) or CLOCK_FONTS["mono"])


def all_clock_digit_chars():
    """همه‌ی کاراکترهای رقم توی همه‌ی فونت‌ها (برای پاک‌کردن ساعتِ آخر اسم/بیو)."""
    return "".join(CLOCK_FONTS.values())
