"""پنل وبِ مدیریت هاب به سبک پنل سنایی (3x-ui) — فقط برای ادمین، بدون وابستگی اضافه، asyncio خالص.

امکانات:
  • داشبورد: آمار کاربرها، سلف‌های روشن، مجموع الماس، وضعیت سرور، نمودار عضو جدید، آخرین کاربرها و انتقال‌ها
  • کاربران: جستجو، فیلتر، مرتب‌سازی، خروجی CSV، روشن/خاموش‌کردن سلف، بن، الماس
  • صفحه‌ی هر کاربر: اطلاعات، افزایش/کاهش/تنظیم الماس، تست هدیه، پیام، ویرایش کامل تنظیمات سلف
    (همه‌ی کلیدهای کانفیگ + ویرایشگر JSON خام)، لاگ سلف، رفرال‌ها و انتقال‌ها
  • انتقال الماس بین کاربرها (یا شارژ از سیستم) با ثبت تاریخچه
  • کدهای الماس، مدیریت ادمین‌ها، پیام/الماس همگانی، تنظیمات .env، ریستارت

فعال‌سازی: توی .env مقدار WEB_PASSWORD رو بذار. پیش‌فرض فقط روی 127.0.0.1:8080 گوش می‌ده.
برای دسترسی از بیرون: پشت nginx/caddy با HTTPS (و WEB_SECURE=1) یا SSH tunnel.
"""
import asyncio
import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import shutil
import time
from datetime import datetime
from html import escape
from urllib.parse import parse_qs, quote, unquote, urlsplit
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tehran")
SESSION_TTL = 12 * 3600
MAX_BODY = 256 * 1024
PAGE_SIZE = 25
FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")

# ---------------- ظاهر (دارک/لایت، سبز-آبی مثل سنایی) ----------------
CSS = """
:root{--bg:#0b1020;--side:#15172a;--card:#171b32;--card2:#202544;--line:#343457;--tx:#f1efff;--mut:#a5a2c2;
--p:#7c3aed;--p2:#c084fc;--r:#b63f50;--o:#f0a020;--b:#3182ce;--sh:0 8px 24px #05061670}
[data-theme=light]{--bg:#f2effb;--side:#fff;--card:#fff;--card2:#f1edfa;--line:#ded6ed;--tx:#241a35;--mut:#716681;--p:#7c3aed;--p2:#9333ea;--r:#b63f50;--b:#3182ce;--sh:0 3px 14px #31204a16}
*{box-sizing:border-box}html,body{margin:0}
body{background:radial-gradient(ellipse at 85% 0%,#5522a526,transparent 38%),var(--bg);color:var(--tx);font-family:Vazirmatn,Tahoma,system-ui,sans-serif;line-height:1.7;font-size:14px}
a{color:var(--p2);text-decoration:none}
.app{display:flex;min-height:100vh}
.side{width:230px;background:var(--side);border-left:1px solid var(--line);padding:14px 10px;position:sticky;top:0;height:100vh;
overflow-y:auto;flex-shrink:0}
.brand{display:block;text-align:center;font-weight:800;font-size:21px;padding:8px 4px 16px;color:var(--p2)}
.side a.nv{display:flex;align-items:center;gap:9px;padding:10px 12px;border-radius:9px;color:var(--tx);margin-bottom:3px}
.side a.nv:hover{background:var(--card2)}.side a.nv.cur{background:var(--p);color:#fff}
.side .sp{height:1px;background:var(--line);margin:10px 0}
.main{flex:1;min-width:0;padding:18px 20px 40px}
.bar{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:16px;flex-wrap:wrap}
h1{font-size:19px;margin:0}h2{font-size:15.5px;margin:0 0 12px}
.card{background:linear-gradient(145deg,var(--card),var(--card2));border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:16px;box-shadow:var(--sh);animation:rise .35s ease both}
.grid{display:grid;gap:14px;margin-bottom:16px}.g4{grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
.g2{grid-template-columns:repeat(auto-fit,minmax(330px,1fr))}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;display:flex;gap:12px;align-items:center;box-shadow:var(--sh)}
.ico{width:42px;height:42px;border-radius:11px;display:grid;place-items:center;font-size:20px;background:var(--card2);flex-shrink:0}
.stat b{display:block;font-size:21px;line-height:1.2}.stat span{color:var(--mut);font-size:12.5px}
.c-p .ico{background:#00877122}.c-b .ico{background:#2f7de122}.c-o .ico{background:#f0a02022}.c-r .ico{background:#e0414122}
table{width:100%;border-collapse:collapse}th,td{padding:9px 8px;border-bottom:1px solid var(--line);text-align:right;font-size:13.5px;vertical-align:middle}
th{color:var(--mut);font-weight:600;white-space:nowrap}tr:hover td{background:var(--card2)}.tw{overflow-x:auto}
input,textarea,select{background:var(--card2);color:var(--tx);border:1px solid var(--line);border-radius:8px;padding:8px 10px;font:inherit;max-width:100%}
input:focus,textarea:focus,select:focus{outline:2px solid var(--p);outline-offset:-1px}
textarea{width:100%;min-height:90px}
button,.btn{background:var(--p);color:#fff;border:0;border-radius:8px;padding:8px 14px;font:inherit;cursor:pointer;display:inline-block;transition:.15s;white-space:nowrap}
button:hover,.btn:hover{filter:brightness(1.12);transform:translateY(-1px);box-shadow:0 5px 16px #0003}
.btn.red,button.red{background:var(--r)}.btn.gray,button.gray{background:var(--card2);color:var(--tx);border:1px solid var(--line)}
.btn.blue,button.blue{background:var(--b)}.btn.org,button.org{background:var(--o);color:#201500}.sm{padding:4px 10px;font-size:12.5px}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:8px}.row form{margin:0}
.tag{padding:2px 10px;border-radius:99px;font-size:12px;background:var(--card2);border:1px solid var(--line);display:inline-block}
.on{background:#00877122;color:var(--p2);border-color:#00877166}.off{color:var(--mut)}.ban{background:#e0414122;color:#ff8a8a;border-color:#e0414166}
.blu{background:#2f7de122;color:#7db4ff;border-color:#2f7de166}
.flash{background:#00877122;border:1px solid var(--p);border-radius:10px;padding:10px 14px;margin-bottom:16px}
.hint{color:var(--mut);font-size:12.5px;margin:2px 0 10px}.mut{color:var(--mut)}.center{text-align:center}
.field{margin-bottom:14px}.field label{display:block;font-weight:700;margin-bottom:4px}.field input{width:100%}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:16px}.tabs a{padding:7px 14px;border-radius:8px;background:var(--card);border:1px solid var(--line);color:var(--tx)}
.tabs a.cur{background:var(--p);border-color:var(--p);color:#fff}
.kv{display:grid;grid-template-columns:150px 1fr;gap:6px 12px}.kv span:nth-child(odd){color:var(--mut)}
.login{max-width:360px;margin:14vh auto}.log{background:#050a14;color:#b8f5d0;border-radius:8px;padding:12px;font:12px/1.6 monospace;
direction:ltr;text-align:left;white-space:pre-wrap;word-break:break-all;max-height:520px;overflow:auto}
code,.ltr{direction:ltr;unicode-bidi:embed;font-family:monospace}
.sw{position:relative;display:inline-block;width:42px;height:23px}.sw input{opacity:0;width:0;height:0}
.sw i{position:absolute;inset:0;background:var(--line);border-radius:23px;transition:.2s;cursor:pointer}
.sw i:before{content:"";position:absolute;height:17px;width:17px;right:3px;top:3px;background:#fff;border-radius:50%;transition:.2s}
.sw input:checked+i{background:var(--p)}.sw input:checked+i:before{transform:translateX(-19px)}
.bars{display:flex;align-items:flex-end;gap:10px;height:120px}.bars div{flex:1;text-align:center;font-size:11.5px;color:var(--mut)}
.bars i{display:block;background:linear-gradient(0deg,var(--p),var(--p2));border-radius:6px 6px 0 0;min-height:3px;margin-bottom:4px}
.pg{display:flex;gap:6px;align-items:center;margin-top:12px;flex-wrap:wrap}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;transition-duration:.01ms!important;scroll-behavior:auto!important}}
@media(max-width:820px){.app{display:block}.side{width:auto;height:auto;position:static;display:flex;gap:4px;overflow-x:auto;
border-left:0;border-bottom:1px solid var(--line);padding:8px}.side .brand,.side .sp{display:none}.side a.nv{white-space:nowrap;margin:0}
.main{padding:12px}.kv{grid-template-columns:1fr}}
"""

JS = """
(function(){
var t=localStorage.getItem('nrt_theme');if(t)document.documentElement.setAttribute('data-theme',t);
document.addEventListener('click',function(e){
 var b=e.target.closest('[data-theme-toggle]');
 if(b){e.preventDefault();var n=document.documentElement.getAttribute('data-theme')==='light'?'dark':'light';
  document.documentElement.setAttribute('data-theme',n);localStorage.setItem('nrt_theme',n);}
 var c=e.target.closest('[data-confirm]');
 if(c&&!confirm(c.getAttribute('data-confirm'))){e.preventDefault();}
});
setTimeout(function(){var f=document.querySelector('.flash');if(f)f.style.display='none';},7000);
})();
"""
JS_HASH = "sha256-" + base64.b64encode(hashlib.sha256(JS.encode()).digest()).decode()

NAV = [("dash", "/", "📊", "داشبورد"), ("users", "/users", "👥", "کاربران"), ("transfer", "/transfer", "💎", "انتقال الماس"),
       ("codes", "/codes", "🎟", "کدهای الماس"), ("admins", "/admins", "👮", "ادمین‌ها"),
       ("bc", "/broadcast", "📢", "پیام همگانی"), ("settings", "/settings", "⚙️", "تنظیمات")]


def page(title, body, sess=None, flash="", cur="", brand="NRT Self"):
    if not sess:
        return (f'<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
                f'<title>{escape(title)}</title><style>{CSS}</style></head><body>{body}<script>{JS}</script></body></html>')
    links = "".join(f'<a class="nv {"cur" if k == cur else ""}" href="{u}"><span>{i}</span>{t}</a>' for k, u, i, t in NAV)
    links += (f'<div class="sp"></div><a class="nv" href="#" data-theme-toggle><span>🌓</span>تم روشن/تیره</a>'
              f'<form method="post" action="/logout" style="margin:0"><input type="hidden" name="csrf" value="{sess["csrf"]}">'
              f'<button class="gray" style="width:100%;text-align:right;margin-top:4px">🚪 خروج</button></form>')
    fl = f'<div class="flash">{escape(flash)}</div>' if flash else ""
    return (f'<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
            f'<title>{escape(title)} | {escape(brand)}</title><style>{CSS}</style></head><body>'
            f'<div class="app"><nav class="side"><a class="brand" href="/">{escape(brand)}</a>{links}</nav>'
            f'<main class="main"><div class="bar"><h1>{escape(title)}</h1></div>{fl}{body}</main></div>'
            f'<script>{JS}</script></body></html>')


def csrf_input(s):
    return f'<input type="hidden" name="csrf" value="{s["csrf"]}">'


def fmt_ts(ts):
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, TZ).strftime("%Y-%m-%d %H:%M")


def num(x, default=None):
    """عدد از فرم (ارقام فارسی و ویرگول هم قبوله)."""
    s = str(x).strip().translate(FA_DIGITS).replace(",", ".").replace("٫", ".")
    try:
        v = float(s)
    except ValueError:
        return default
    return v if v == v and abs(v) != float("inf") else default


# ---------------- ویرایشگر تنظیمات سلف ----------------
KEY_FA = {
    "enabled": "سلف روشن", "online": "حالت آنلاین", "prefix": "پرفیکس دستورها", "voice": "صدای متن به ویس",
    "textmode": "حالت متن (سبک)", "secretary": "منشی", "secretary_text": "متن منشی", "secretary_minutes": "فاصله‌ی منشی (دقیقه)",
    "autoreplies": "پاسخ‌های خودکار", "autoreply_on": "پاسخ خودکار روشن",
    "ar_pending": "کلمه‌های منتظر پاسخ", "content_on": "محتوا روشن", "content": "محتواهای ذخیره‌شده",
    "friends": "لیست دوستان", "autoseen": "سین خودکار پیوی", "seen_gp": "سین خودکار گروه",
    "seen_ch": "سین خودکار کانال", "seen_bot": "سین خودکار ربات", "react": "ری‌اکشن پیوی (همه)", "react_users": "ری‌اکشن کاربرها",
    "pvlock": "قفل پیوی", "antilogin": "ضد لاگین", "muted": "لیست سکوت",
    "filter_on": "فیلتر کلمات روشن", "filter_words": "کلمات فیلتر", "guard": "نگهبان چت", "force_join": "عضویت اجباری",
    "clock_first": "ساعت روی اسم", "clock_last": "ساعت روی فامیل", "clock_bio": "ساعت روی بیو", "clock_font": "فونت ساعت",
    "base_first": "اسم اصلی", "base_last": "فامیل اصلی", "base_bio": "بیو اصلی",
    "fc_on": "کامنت اول روشن", "fc_text": "متن کامنت اول", "fc_channels": "کانال‌های کامنت اول",
    "self_admins": "ادمین‌های سلف", "admin_prefix": "پرفیکس ادمین", "pe_on": "ایموجی پریمیوم", "pe_chan": "ایموجی پریمیوم چنل",
    "pe_packs": "پک‌های ایموجی", "tabchi_on": "تبچی روشن", "enemy_words": "لیست فحش",
}
for _k, _fa in (("meow", "میو"), ("pishi", "پیشی"), ("fish", "ماهی‌گیری")):
    KEY_FA.update({f"{_k}_on": f"{_fa} خودکار", f"{_k}_chats": f"گروه‌های {_fa}", f"{_k}_min": f"فاصله‌ی {_fa} (دقیقه)",
                   f"{_k}_text": f"متن {_fa}"})
for _a, _fa in (("chat", "تایپ"), ("game", "بازی"), ("voice", "ضبط ویس"), ("video", "ضبط ویدیو مسیج")):
    KEY_FA[f"act_{_a}_pv"] = f"اکشن {_fa} (پیوی)"
    KEY_FA[f"act_{_a}_gp"] = f"اکشن {_fa} (گروه)"

GROUPS = [
    ("⚙️ عمومی", ("enabled", "online", "prefix", "voice", "textmode")),
    ("🗂 منشی و پاسخ", ("secretary", "autoreply", "ar_", "content", "friend")),
    ("👁 سین و ری‌اکشن", ("autoseen", "seen_", "react")),
    ("🔒 امنیت", ("pvlock", "antilogin", "muted", "filter", "gbans", "guard", "force_join")),
    ("🕒 ساعت", ("clock", "base_")),
    ("🎭 حالت اکشن", ("act_", "action")),
    ("🥇 کامنت اول", ("fc_",)),
    ("👮 ادمین‌ها", ("self_admins", "admin_prefix")),
    ("🐱 خودکارها و ایموجی", ("meow_", "pishi_", "fish_", "pe_")),
    ("📣 تبچی، دشمن و بازی", ("tabchi", "banner", "starzi", "enemy", "enemies", "cat", "reminders")),
]


def group_of(key):
    for gi, (_, prefs) in enumerate(GROUPS):
        if any(key == p or key.startswith(p) for p in prefs):
            return gi
    return len(GROUPS)


def kind_of(v):
    if isinstance(v, bool):
        return "b"
    if isinstance(v, int):
        return "i"
    if isinstance(v, float):
        return "f"
    if v is None:
        return "n"
    if isinstance(v, str):
        return "s"
    return "j"


def parse_cfg_value(kind, raw, orig):
    """مقدار فرم ← مقدار پایتونی هم‌نوع مقدار اصلی. ValueError اگه نامعتبر بود."""
    if kind == "b":
        return raw == "1"
    if kind in ("i", "f"):
        v = num(raw)
        if v is None:
            raise ValueError("عدد نامعتبر")
        return int(v) if kind == "i" else v
    if kind == "n":
        raw = raw.strip()
        return raw or None
    if kind == "s":
        if len(raw) > 20000:
            raise ValueError("متن خیلی بلنده")
        return raw
    val = json.loads(raw or "null")
    if type(val) is not type(orig):
        raise ValueError("نوع JSON باید مثل مقدار قبلی باشه")
    return val


def cfg_diff(current, form):
    """کلیدهایی که توی فرم عوض شدن ← ({کلید: مقدار جدید}, [خطاها]). فقط کلیدهای موجود قابل تغییرن."""
    changes, errors = {}, []
    for fk, kind in form.items():
        if not fk.startswith("k_"):
            continue
        key = fk[2:]
        if key not in current or kind not in ("b", "i", "f", "s", "n", "j"):
            continue
        raw = form.get(f"v_{key}", "")
        try:
            new = parse_cfg_value(kind, raw, current[key])
        except (ValueError, json.JSONDecodeError):
            errors.append(KEY_FA.get(key, key))
            continue
        if new != current[key] or type(new) is not type(current[key]):
            changes[key] = new
    return changes, errors


def cfg_field(key, val):
    kind = kind_of(val)
    n = escape(key, quote=True)
    hid = f'<input type="hidden" name="k_{n}" value="{kind}">'
    if kind == "b":
        ctl = f'<label class="sw"><input type="checkbox" name="v_{n}" value="1" {"checked" if val else ""}><i></i></label>'
    elif kind in ("i", "f"):
        ctl = f'<input name="v_{n}" value="{val}" dir="ltr" style="width:140px">'
    elif kind in ("s", "n"):
        s = "" if val is None else str(val)
        if "\n" in s or len(s) > 60:
            ctl = f'<textarea name="v_{n}" rows="3">{escape(s)}</textarea>'
        else:
            ctl = f'<input name="v_{n}" value="{escape(s, quote=True)}" style="width:100%;max-width:420px">'
    else:
        txt = json.dumps(val, ensure_ascii=False)
        ctl = f'<textarea name="v_{n}" rows="{min(8, 2 + len(txt) // 80)}" dir="ltr">{escape(txt)}</textarea>'
    fa = KEY_FA.get(key)
    label = f'{escape(fa)}<br><code class="mut" style="font-size:11px">{escape(key)}</code>' if fa else f'<code>{escape(key)}</code>'
    return f"<tr><td style='width:34%'>{label}</td><td>{hid}{ctl}</td></tr>"


class WebPanel:
    def __init__(self, h, password, host="127.0.0.1", port=8080, secure=False):
        self.h, self.password, self.host, self.port, self.secure = h, password, host, port, secure
        self.sessions = {}          # token -> {"csrf", "exp"}
        self.fails = {}             # ip -> [count, until]
        self.started = h.get("start_time") or time.time()

    @property
    def brand(self):
        return self.h.get("BRAND") or "NRT Self"

    def pg(self, title, body, sess=None, flash="", cur=""):
        return page(title, body, sess, flash, cur, self.brand)

    # ---------- سرور ----------
    async def start(self):
        srv = await asyncio.start_server(self.handle, self.host, self.port, limit=MAX_BODY)
        print(f"Web panel: http://{self.host}:{self.port}")
        return srv

    async def handle(self, reader, writer):
        try:
            ip = (writer.get_extra_info("peername") or ("?",))[0]
            try:
                head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 15)
            except Exception:
                return
            lines = head.decode("latin-1").split("\r\n")
            try:
                method, target, _ = lines[0].split(" ", 2)
            except ValueError:
                return
            headers = {}
            for ln in lines[1:]:
                if ":" in ln:
                    k, v = ln.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            body = b""
            n = int(headers.get("content-length", "0") or 0)
            if n > MAX_BODY:
                return await self.send(writer, 413, "too large")
            if n:
                body = await asyncio.wait_for(reader.readexactly(n), 15)
            form = {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True).items()}
            u = urlsplit(target)
            query = {k: v[0] for k, v in parse_qs(u.query).items()}
            cookies = {}
            for part in headers.get("cookie", "").split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    cookies[k.strip()] = v.strip()
            sess = self.get_session(cookies.get("nrt_s"))
            status, hdrs, out = await self.route(method, unquote(u.path), query, form, sess, ip)
            await self.send(writer, status, out, hdrs)
        except Exception as ex:
            print("web error:", ex)
            try:
                await self.send(writer, 500, "خطای داخلی")
            except Exception:
                pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def send(self, writer, status, body, hdrs=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        reason = {200: "OK", 302: "Found", 400: "Bad Request", 403: "Forbidden", 404: "Not Found",
                  413: "Too Large", 429: "Too Many Requests", 500: "Error"}.get(status, "OK")
        h = {"Content-Type": "text/html; charset=utf-8", "Content-Length": str(len(data)),
             "Connection": "close", "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff",
             "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
             "Content-Security-Policy": f"default-src 'none'; style-src 'unsafe-inline'; script-src '{JS_HASH}'; "
                                        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"}
        h.update(hdrs or {})
        head = f"HTTP/1.1 {status} {reason}\r\n" + "".join(f"{k}: {v}\r\n" for k, v in h.items()) + "\r\n"
        writer.write(head.encode("latin-1") + data)
        await writer.drain()

    # ---------- نشست ----------
    def get_session(self, token):
        s = self.sessions.get(token or "")
        if not s:
            return None
        if s["exp"] < time.time():
            self.sessions.pop(token, None)
            return None
        s["token"] = token
        return s

    def new_session(self):
        tok = secrets.token_urlsafe(32)
        self.sessions[tok] = {"csrf": secrets.token_urlsafe(24), "exp": time.time() + SESSION_TTL}
        return tok

    def cookie(self, tok, clear=False):
        c = f"nrt_s={tok}; Path=/; HttpOnly; SameSite=Strict; Max-Age={0 if clear else SESSION_TTL}"
        return c + ("; Secure" if self.secure else "")

    @staticmethod
    def redirect(to, extra=None):
        h = {"Location": to}
        h.update(extra or {})
        return 302, h, ""

    def flash_to(self, to, msg):
        return self.redirect(f"{to}{'&' if '?' in to else '?'}m={quote(msg)}")

    def nf(self, sess):
        return 404, {}, self.pg("۴۰۴", '<div class="card">پیدا نشد.</div>', sess)

    # ---------- مسیرها ----------
    async def route(self, method, path, q, form, sess, ip):
        if path == "/login":
            if method == "POST":
                f = self.fails.get(ip, [0, 0])
                if f[1] > time.time():
                    return 429, {}, page("قفل", '<div class="card login center">تلاش‌های زیاد؛ چند دقیقه بعد دوباره امتحان کن.</div>')
                if hmac.compare_digest(form.get("password", "").encode(), self.password.encode()):
                    self.fails.pop(ip, None)
                    return self.redirect("/", {"Set-Cookie": self.cookie(self.new_session())})
                f[0] += 1
                if f[0] >= 5:
                    f = [0, time.time() + 300]
                self.fails[ip] = f
                await asyncio.sleep(1)
            return 200, {}, page("ورود", (
                f'<form class="card login" method="post" action="/login"><h2 class="center">🔐 {escape(self.brand)}</h2>'
                '<div class="field"><input type="password" name="password" placeholder="رمز پنل" autofocus required></div>'
                '<button style="width:100%">ورود</button>'
                + ('<p class="mut center">رمز اشتباه بود.</p>' if method == "POST" else "") + "</form>"))
        if not sess:
            return self.redirect("/login")
        if method == "POST":
            if not hmac.compare_digest(form.get("csrf", "").encode(), sess["csrf"].encode()):
                return 403, {}, self.pg("خطا", '<div class="card">درخواست نامعتبر (CSRF).</div>', sess)
            if path == "/logout":
                self.sessions.pop(sess["token"], None)
                return self.redirect("/login", {"Set-Cookie": self.cookie("", clear=True)})
            return await self.post(path, form, sess)
        flash = q.get("m", "")
        if path == "/":
            return 200, {}, self.dashboard(sess, flash)
        if path == "/users":
            return 200, {}, self.users_page(q, sess, flash)
        if path == "/export/users.csv":
            return self.export_csv()
        if path == "/transfer":
            return 200, {}, self.transfer_page(q, sess, flash)
        if path == "/codes":
            return 200, {}, self.codes_page(sess, flash)
        if path == "/admins":
            return 200, {}, self.admins_page(sess, flash)
        if path == "/broadcast":
            return 200, {}, self.broadcast_page(sess, flash)
        if path == "/settings":
            return 200, {}, self.settings_page(sess, flash)
        if path.startswith("/user/"):
            try:
                uid = int(path.split("/")[2])
            except (ValueError, IndexError):
                return self.nf(sess)
            if not self.user_exists(uid):
                return self.nf(sess)
            return 200, {}, self.user_page(uid, q, sess, flash)
        return self.nf(sess)

    # ---------- داده ----------
    def all_users(self):
        db = self.h.get("db")
        if db is not None:
            cur = db.execute("SELECT * FROM users")
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        return [self.h["db_get"](i) for i in self.h["db_all"]()]

    def is_adm(self, uid):
        return uid in self.h["admins"]

    def bal(self, u):
        return "♾" if self.is_adm(u["user_id"]) else f"{(u['diamonds'] or 0):.1f}"

    def runway(self, u):
        fn = self.h.get("runway_seconds")
        if not fn:
            return "—"
        secs, mode = fn(u)
        if mode == "admin":
            return "♾"
        return self.h["fmt_duration"](secs) + (" (تست)" if mode == "trial" else "")

    def uname(self, u):
        return f'@{escape(u["username"])}' if u.get("username") else "—"

    def name_of(self, uid, cache):
        if uid == 0:
            return "سیستم"
        if uid not in cache:
            row = self.h["db"].execute("SELECT username FROM users WHERE user_id=?", (uid,)).fetchone() if self.h.get("db") else None
            cache[uid] = row[0] if row and row[0] else None
        un = cache[uid]
        return f'<a href="/user/{uid}">{uid}</a>' + (f' <span class="mut">@{escape(un)}</span>' if un else "")

    def tags(self, u):
        uid = u["user_id"]
        on = uid in self.h["running"]
        t = f'<span class="tag {"on" if on else "off"}">{"روشن" if on else "خاموش"}</span> '
        if u.get("banned"):
            t += '<span class="tag ban">بن</span> '
        if self.is_adm(uid):
            t += '<span class="tag blu">ادمین</span> '
        if not self.h["is_logged_in"](uid):
            t += '<span class="tag">بدون لاگین</span>'
        return t

    def form(self, action, inner, sess):
        return f'<form class="row" method="post" action="{action}">{csrf_input(sess)}{inner}</form>'

    # ---------- داشبورد ----------
    def dashboard(self, sess, flash):
        h = self.h
        users = self.all_users()
        total_d = sum(u["diamonds"] or 0 for u in users if not self.is_adm(u["user_id"]))
        today = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        new_today = sum(1 for u in users if (u.get("created_at") or 0) >= today)
        db = h.get("db")
        n_tr = db.execute("SELECT COUNT(*) FROM transfers").fetchone()[0] if db else 0
        stats = [("c-p", "👥", len(users), "کل کاربرها"), ("c-p", "🟢", len(h["running"]), "سلف روشن"),
                 ("c-b", "🔑", sum(1 for u in users if h["is_logged_in"](u["user_id"])), "لاگین‌شده"),
                 ("c-r", "⛔", sum(1 for u in users if u.get("banned")), "مسدود"),
                 ("c-o", "💎", f"{total_d:,.0f}", "مجموع الماس"), ("c-b", "🆕", new_today, "عضو جدید امروز"),
                 ("c-o", "🔁", n_tr, "تعداد انتقال‌ها")]
        st = "".join(f'<div class="stat {c}"><div class="ico">{i}</div><div><b>{v}</b><span>{t}</span></div></div>'
                     for c, i, v, t in stats)
        days = []
        for k in range(6, -1, -1):
            d0 = today - k * 86400
            cnt = sum(1 for u in users if d0 <= (u.get("created_at") or 0) < d0 + 86400)
            days.append((datetime.fromtimestamp(d0, TZ).strftime("%m/%d"), cnt))
        mx = max([c for _, c in days] + [1])
        bars = "".join(f'<div><i style="height:{int(c / mx * 90) + 3}px"></i>{c}<br>{d}</div>' for d, c in days)
        up = h["fmt_duration"](time.time() - self.started)
        try:
            la = " / ".join(f"{x:.2f}" for x in os.getloadavg())
        except OSError:
            la = "—"
        mem = "—"
        try:
            with open("/proc/meminfo") as f:
                mi = {ln.split(":")[0]: int(ln.split()[1]) for ln in f if ":" in ln}
            tot, av = mi["MemTotal"] // 1024, mi["MemAvailable"] // 1024
            mem = f"{tot - av} / {tot} MB"
        except Exception:
            pass
        try:
            du = shutil.disk_usage("/")
            disk = f"{(du.total - du.free) // 2**30} / {du.total // 2**30} GB"
        except Exception:
            disk = "—"
        server = (f'<div class="kv"><span>آپتایم هاب</span><span>{up}</span><span>Load</span><span class="ltr">{la}</span>'
                  f'<span>رم</span><span class="ltr">{mem}</span><span>دیسک</span><span class="ltr">{disk}</span></div>')
        recent = sorted(users, key=lambda u: u.get("created_at") or 0, reverse=True)[:6]
        rows = "".join(f'<tr><td><a href="/user/{u["user_id"]}">{u["user_id"]}</a></td><td>{self.uname(u)}</td>'
                       f'<td>{self.bal(u)}</td><td>{fmt_ts(u.get("created_at"))}</td></tr>' for u in recent)
        trs = ""
        if db:
            cache = {}
            for r in db.execute("SELECT from_id,to_id,amount,at FROM transfers ORDER BY id DESC LIMIT 6").fetchall():
                trs += (f'<tr><td>{self.name_of(r[0], cache)}</td><td>{self.name_of(r[1], cache)}</td>'
                        f'<td>{r[2]:.1f}</td><td>{fmt_ts(r[3])}</td></tr>')
        body = (f'<div class="grid g4">{st}</div>'
                f'<div class="grid g2"><div class="card"><h2>📈 عضو جدید (۷ روز اخیر)</h2><div class="bars">{bars}</div></div>'
                f'<div class="card"><h2>🖥 وضعیت سرور</h2>{server}</div></div>'
                f'<div class="grid g2"><div class="card"><h2>🆕 آخرین کاربرها</h2><div class="tw"><table>'
                f'<tr><th>آیدی</th><th>یوزرنیم</th><th>الماس</th><th>عضویت</th></tr>{rows}</table></div></div>'
                f'<div class="card"><h2>🔁 آخرین انتقال‌ها</h2><div class="tw"><table>'
                f'<tr><th>از</th><th>به</th><th>الماس</th><th>زمان</th></tr>{trs or "<tr><td colspan=4 class=mut>هنوز انتقالی نیست</td></tr>"}'
                f'</table></div></div></div>')
        return self.pg("داشبورد", body, sess, flash, "dash")

    # ---------- کاربران ----------
    FILTERS = {"all": "همه", "run": "سلف روشن", "off": "خاموش", "ban": "مسدود", "adm": "ادمین", "nologin": "بدون لاگین"}
    SORTS = {"new": "جدیدترین", "dia": "بیشترین الماس", "id": "آیدی"}

    def users_page(self, q, sess, flash):
        h = self.h
        users = self.all_users()
        s = q.get("s", "").strip()
        f = q.get("f", "all") if q.get("f") in self.FILTERS else "all"
        o = q.get("o", "new") if q.get("o") in self.SORTS else "new"
        if s:
            found = set(h["db_search"](s))
            users = [u for u in users if u["user_id"] in found]
        pred = {"all": lambda u: True, "run": lambda u: u["user_id"] in h["running"],
                "off": lambda u: u["user_id"] not in h["running"], "ban": lambda u: u.get("banned"),
                "adm": lambda u: self.is_adm(u["user_id"]), "nologin": lambda u: not h["is_logged_in"](u["user_id"])}[f]
        users = [u for u in users if pred(u)]
        key = {"new": lambda u: -(u.get("created_at") or 0), "dia": lambda u: -(u["diamonds"] or 0), "id": lambda u: u["user_id"]}[o]
        users.sort(key=key)
        try:
            pg = max(0, int(q.get("p", "0")))
        except ValueError:
            pg = 0
        pages = max(1, (len(users) + PAGE_SIZE - 1) // PAGE_SIZE)
        pg = min(pg, pages - 1)
        rows = ""
        for u in users[pg * PAGE_SIZE:(pg + 1) * PAGE_SIZE]:
            uid = u["user_id"]
            on = uid in h["running"]
            act = ""
            if on:
                act += self.form(f"/user/{uid}/stop", '<button class="gray sm">⏸ خاموش</button>', sess)
            elif h["is_logged_in"](uid) and not u.get("banned"):
                act += self.form(f"/user/{uid}/start", '<button class="sm">▶️ روشن</button>', sess)
            act += f'<a class="btn blue sm" href="/user/{uid}">مدیریت</a>'
            rows += (f'<tr><td><a href="/user/{uid}">{uid}</a></td><td>{self.uname(u)}</td>'
                     f'<td class="ltr">{escape(str(u.get("phone") or "—"))}</td><td>{self.bal(u)}</td><td>{self.runway(u)}</td>'
                     f'<td>{self.tags(u)}</td><td><div class="row" style="margin:0">{act}</div></td></tr>')
        base = f"s={quote(s)}&f={f}&o={o}"
        nav = ""
        if pg > 0:
            nav += f'<a class="btn gray sm" href="/users?p={pg-1}&{base}">قبلی</a>'
        if pg < pages - 1:
            nav += f'<a class="btn gray sm" href="/users?p={pg+1}&{base}">بعدی</a>'
        fsel = "".join(f'<option value="{k}" {"selected" if k == f else ""}>{v}</option>' for k, v in self.FILTERS.items())
        osel = "".join(f'<option value="{k}" {"selected" if k == o else ""}>{v}</option>' for k, v in self.SORTS.items())
        body = (f'<div class="card"><form class="row" method="get" action="/users"><input name="s" value="{escape(s, quote=True)}" '
                f'placeholder="آیدی یا یوزرنیم"><select name="f">{fsel}</select><select name="o">{osel}</select>'
                f'<button>🔍 اعمال</button><a class="btn gray" href="/export/users.csv">⬇️ CSV</a></form>'
                f'<div class="hint">{len(users)} کاربر</div><div class="tw"><table><tr><th>آیدی</th><th>یوزرنیم</th><th>شماره</th>'
                f'<th>الماس</th><th>زمان باقی‌مانده</th><th>وضعیت</th><th>عملیات</th></tr>{rows}</table></div>'
                f'<div class="pg">{nav}<span class="mut">صفحه {pg+1} از {pages}</span></div></div>')
        return self.pg("کاربران", body, sess, flash, "users")

    def export_csv(self):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["user_id", "username", "phone", "diamonds", "banned", "logged_in", "running", "referrer", "created_at"])
        for u in self.all_users():
            w.writerow([u["user_id"], u.get("username") or "", u.get("phone") or "", u["diamonds"], u.get("banned"),
                        int(self.h["is_logged_in"](u["user_id"])), int(u["user_id"] in self.h["running"]),
                        u.get("referrer") or "", fmt_ts(u.get("created_at"))])
        return (200, {"Content-Type": "text/csv; charset=utf-8", "Content-Disposition": 'attachment; filename="users.csv"'},
                "\ufeff" + buf.getvalue())

    # ---------- صفحه‌ی کاربر ----------
    def cfg_file(self, uid):
        fn = self.h.get("cfg_path")
        return fn(uid) if fn else None

    def read_cfg(self, uid):
        p = self.cfg_file(uid)
        if not p or not os.path.exists(p):
            return None
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else None
        except (OSError, ValueError):
            return None

    def write_cfg(self, uid, data):
        p = self.cfg_file(uid)
        tmp = p + ".web.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)

    def tail_log(self, uid, n=80):
        d = self.h.get("log_dir")
        if not d:
            return None
        p = os.path.join(d, f"user_{uid}.log")
        try:
            with open(p, "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 16000))
                data = f.read().decode("utf-8", "replace")
        except OSError:
            return None
        return "\n".join(data.splitlines()[-n:])

    def user_exists(self, uid):
        db = self.h.get("db")
        return db is None or db.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone() is not None

    def user_page(self, uid, q, sess, flash):
        h = self.h
        u = h["db_get"](uid)
        tab = q.get("t", "info")
        if tab not in ("info", "cfg", "log", "tr"):
            tab = "info"
        on = uid in h["running"]
        tabs = "".join(f'<a class="{"cur" if tab == k else ""}" href="/user/{uid}?t={k}">{t}</a>'
                       for k, t in (("info", "👤 اطلاعات"), ("cfg", "🛠 تنظیمات سلف"), ("log", "📜 لاگ سلف"), ("tr", "🔁 انتقال و رفرال")))
        head = f'<div class="tabs">{tabs}<a href="/users">🔙 کاربران</a></div>'
        if tab == "cfg":
            body = self.user_cfg_tab(uid, sess)
        elif tab == "log":
            lg = self.tail_log(uid)
            body = ('<div class="card"><h2>📜 لاگ سلف (آخرین خط‌ها)</h2>'
                    + (f'<div class="log">{escape(lg)}</div>' if lg else '<p class="mut">لاگی نیست (سلف هنوز اجرا نشده یا خروجی نداره).</p>')
                    + f'<p><a class="btn gray sm" href="/user/{uid}?t=log">🔄 بروزرسانی</a></p></div>')
        elif tab == "tr":
            body = self.user_tr_tab(uid)
        else:
            body = self.user_info_tab(uid, u, on, sess)
        return self.pg(f"کاربر {uid}", head + body, sess, flash, "users")

    def user_info_tab(self, uid, u, on, sess):
        h = self.h
        trial = "هنوز نگرفته" if not u["trial_used"] else h["fmt_duration"](u["trial_seconds"])
        rc = h["ref_count"](uid) if h.get("ref_count") else "—"
        kv = (f'<div class="kv"><span>یوزرنیم</span><span>{self.uname(u)}</span><span>شماره</span><span class="ltr">{escape(str(u.get("phone") or "—"))}</span>'
              f'<span>الماس</span><span><b>{self.bal(u)}</b></span><span>زمان باقی‌مانده</span><span>{self.runway(u)}</span>'
              f'<span>تست رایگان</span><span>{escape(trial)}</span><span>وضعیت</span><span>{self.tags(u)}</span>'
              f'<span>تعداد رفرال</span><span>{rc}</span><span>معرف</span><span>{u.get("referrer") or "—"}</span>'
              f'<span>عضویت</span><span>{fmt_ts(u.get("created_at"))}</span></div>')
        info = f'<div class="card"><h2>👤 کاربر <code>{uid}</code></h2>{kv}</div>'
        acts = ""
        if not self.is_adm(uid):
            acts += self.form(f"/user/{uid}/diamond",
                              '<input name="amount" placeholder="تعداد الماس" required style="width:140px">'
                              '<button name="op" value="add">➕ افزایش</button><button class="red" name="op" value="sub">➖ کاهش</button>'
                              '<button class="org" name="op" value="set">= تنظیم موجودی</button>', sess)
        acts += self.form(f"/user/{uid}/trial", '<button class="gray">🎁 هدیه‌ی تست رایگان</button>', sess)
        if on:
            acts += self.form(f"/user/{uid}/stop", '<button class="gray">⏸ خاموش‌کردن سلف</button>', sess)
        elif h["is_logged_in"](uid):
            acts += self.form(f"/user/{uid}/start", '<button>▶️ روشن‌کردن سلف</button>', sess)
        if not self.is_adm(uid):
            acts += self.form(f"/user/{uid}/ban", f'<button class="red">{"🔓 رفع بن" if u["banned"] else "⛔ بن کردن"}</button>', sess)
        if h.get("delete_self") and h["is_logged_in"](uid):
            acts += self.form(f"/user/{uid}/delsess", '<button class="red" data-confirm="سلف و نشست این کاربر پاک بشه؟">🗑 حذف سلف و نشست</button>', sess)
        acts += (f'<div class="row"><a class="btn blue" href="/transfer?from={uid}">💎 انتقال الماس از این کاربر</a>'
                 f'<a class="btn blue" href="/transfer?to={uid}">💎 انتقال الماس به این کاربر</a></div>')
        msg = (f'<form method="post" action="/user/{uid}/msg">{csrf_input(sess)}'
               f'<textarea name="text" placeholder="متن پیام به این کاربر" required></textarea><button style="margin-top:8px">📨 ارسال پیام</button></form>')
        return info + f'<div class="card"><h2>عملیات</h2>{acts}</div><div class="card"><h2>پیام به کاربر</h2>{msg}</div>'

    def user_tr_tab(self, uid):
        db = self.h.get("db")
        if db is None:
            return '<div class="card">پایگاه داده در دسترس نیست.</div>'
        cache = {}
        trs = "".join(f'<tr><td>{self.name_of(r[0], cache)}</td><td>{self.name_of(r[1], cache)}</td><td>{r[2]:.1f}</td><td>{fmt_ts(r[3])}</td></tr>'
                      for r in db.execute("SELECT from_id,to_id,amount,at FROM transfers WHERE from_id=? OR to_id=? ORDER BY id DESC LIMIT 100",
                                          (uid, uid)).fetchall())
        refs = "".join(f'<tr><td><a href="/user/{r[0]}">{r[0]}</a></td><td>{("@" + escape(r[1])) if r[1] else "—"}</td><td>{fmt_ts(r[2])}</td></tr>'
                       for r in db.execute("SELECT user_id,username,created_at FROM users WHERE referrer=? ORDER BY created_at DESC LIMIT 200",
                                           (uid,)).fetchall())
        return (f'<div class="card"><h2>🔁 انتقال‌ها</h2><div class="tw"><table><tr><th>از</th><th>به</th><th>الماس</th><th>زمان</th></tr>'
                f'{trs or "<tr><td colspan=4 class=mut>خالی</td></tr>"}</table></div></div>'
                f'<div class="card"><h2>👥 زیرمجموعه‌ها</h2><div class="tw"><table><tr><th>آیدی</th><th>یوزرنیم</th><th>عضویت</th></tr>'
                f'{refs or "<tr><td colspan=3 class=mut>خالی</td></tr>"}</table></div></div>')

    def user_cfg_tab(self, uid, sess):
        cfg = self.read_cfg(uid)
        if cfg is None:
            return ('<div class="card"><h2>🛠 تنظیمات سلف</h2><p class="mut">این کاربر هنوز فایل تنظیمات نداره '
                    '(سلفش تا حالا اجرا نشده). بعد از اولین اجرا اینجا همه‌ی تنظیمات دیده و ویرایش می‌شه.</p></div>')
        groups = {}
        for k in sorted(cfg):
            groups.setdefault(group_of(k), []).append(k)
        cards = ""
        for gi in sorted(groups):
            title = GROUPS[gi][0] if gi < len(GROUPS) else "📦 سایر"
            rows = "".join(cfg_field(k, cfg[k]) for k in groups[gi])
            cards += f'<div class="card"><h2>{title}</h2><div class="tw"><table>{rows}</table></div></div>'
        raw = json.dumps(cfg, ensure_ascii=False, indent=1)
        on = uid in self.h["running"]
        hint = "سلف روشنه؛ تغییرها تا ۲ ثانیه‌ی دیگه اعمال می‌شن." if on else "سلف خاموشه؛ تغییرها موقع روشن‌شدن اعمال می‌شن."
        return (f'<form method="post" action="/user/{uid}/cfg">{csrf_input(sess)}'
                f'<div class="card"><div class="row"><button>💾 ذخیره‌ی تنظیمات</button><span class="hint">{hint} فقط مقدارهای عوض‌شده ذخیره می‌شن.</span></div></div>'
                f'{cards}<div class="card"><button>💾 ذخیره‌ی تنظیمات</button></div></form>'
                f'<div class="card"><h2>ویرایشگر JSON کامل</h2><p class="hint">برای تغییر هر چیزی (حتی لیست‌های بزرگ). JSON باید معتبر و یک آبجکت باشه.</p>'
                f'<form method="post" action="/user/{uid}/cfgraw">{csrf_input(sess)}<textarea name="json" rows="14" dir="ltr" '
                f'style="font-family:monospace">{escape(raw)}</textarea>'
                f'<button class="org" style="margin-top:8px" data-confirm="کل تنظیمات با این JSON جایگزین بشه؟">💾 جایگزینی کامل</button></form></div>')

    # ---------- انتقال الماس ----------
    def transfer_page(self, q, sess, flash):
        db = self.h.get("db")
        f, t = q.get("from", ""), q.get("to", "")
        cache = {}
        trs = ""
        if db:
            for r in db.execute("SELECT id,from_id,to_id,amount,at FROM transfers ORDER BY id DESC LIMIT 60").fetchall():
                trs += (f'<tr><td>{r[0]}</td><td>{self.name_of(r[1], cache)}</td><td>{self.name_of(r[2], cache)}</td>'
                        f'<td>{r[3]:.1f}</td><td>{fmt_ts(r[4])}</td></tr>')
        form = self.form("/transfer",
                         f'<input name="from" value="{escape(f, quote=True)}" placeholder="از (آیدی/یوزرنیم — خالی = از سیستم)" style="width:260px">'
                         f'<input name="to" value="{escape(t, quote=True)}" placeholder="به (آیدی/یوزرنیم)" required style="width:220px">'
                         '<input name="amount" placeholder="تعداد الماس" required style="width:130px"><button>💎 انتقال</button>', sess)
        body = (f'<div class="card"><h2>💎 انتقال الماس</h2>{form}'
                '<p class="hint">اگه «از» خالی باشه، الماس از سیستم شارژ می‌شه (چیزی از کسی کم نمی‌شه). اگه فرستنده ادمین باشه هم چیزی کم نمی‌شه چون موجودیش نامحدوده. '
                'گیرنده باید توی بات /start زده باشه.</p></div>'
                f'<div class="card"><h2>تاریخچه (۶۰ تای آخر)</h2><div class="tw"><table><tr><th>#</th><th>از</th><th>به</th><th>الماس</th><th>زمان</th></tr>'
                f'{trs or "<tr><td colspan=5 class=mut>هنوز انتقالی نیست</td></tr>"}</table></div></div>')
        return self.pg("انتقال الماس", body, sess, flash, "transfer")

    async def do_transfer(self, form):
        h = self.h
        amount = num(form.get("amount", ""))
        if amount is None or amount <= 0 or amount > 1e9:
            return self.flash_to("/transfer", "مقدار نامعتبره")
        to = h["db_find_user"](form.get("to", ""))
        if to is None:
            return self.flash_to("/transfer", "گیرنده توی بات ثبت‌نام نکرده")
        src = form.get("from", "").strip()
        frm = 0
        if src:
            frm = h["db_find_user"](src)
            if frm is None:
                return self.flash_to("/transfer", "فرستنده پیدا نشد")
            if frm == to:
                return self.flash_to("/transfer", "فرستنده و گیرنده یکی‌ان")
        if frm and not self.is_adm(frm):
            fu = h["db_get"](frm)
            if fu["diamonds"] < amount:
                return self.flash_to("/transfer", f"موجودی فرستنده کافی نیست ({fu['diamonds']:.1f})")
            new = fu["diamonds"] - amount
            h["db_set"](frm, diamonds=new)
            if new <= 0 and frm in h["running"] and h["running"][frm]["mode"] == "paid":
                await h["stop_self"](frm, "⏰ موجودی الماست صفر شد و سلفت خاموش شد.")
        tu = h["db_get"](to)
        h["db_set"](to, diamonds=tu["diamonds"] + amount)
        h["db"].execute("INSERT INTO transfers(from_id,to_id,amount,at) VALUES(?,?,?,?)", (frm, to, amount, time.time()))
        h["db"].commit()
        if frm:
            await h["notify"](frm, f"💎 {amount:.1f} الماس از حسابت به {to} منتقل شد.")
        await h["notify"](to, f"💎 {amount:.1f} الماس به حسابت اضافه شد. موجودی فعلی: {h['db_get'](to)['diamonds']:.1f}")
        return self.flash_to("/transfer", f"✅ {amount:.1f} الماس به {to} منتقل شد")

    # ---------- کدهای الماس ----------
    def codes_page(self, sess, flash):
        db = self.h["db"]
        rows = ""
        for code, amount, uses, at in db.execute("SELECT code,amount,uses,created_at FROM codes ORDER BY created_at DESC LIMIT 200").fetchall():
            used = db.execute("SELECT COUNT(*) FROM code_uses WHERE code=?", (code,)).fetchone()[0]
            delf = self.form("/codes/del", f'<input type="hidden" name="code" value="{escape(code, quote=True)}">'
                                           '<button class="red sm" data-confirm="کد حذف بشه؟">🗑</button>', sess)
            rows += (f'<tr><td class="ltr"><code>{escape(code)}</code></td><td>{amount:g}</td><td>{uses}</td><td>{used}</td>'
                     f'<td>{fmt_ts(at)}</td><td>{delf}</td></tr>')
        new = self.form("/codes/new",
                        '<input name="amount" placeholder="الماس هر کد" required style="width:140px">'
                        '<input name="uses" placeholder="تعداد استفاده" value="1" required style="width:130px">'
                        '<input name="code" placeholder="کد (خالی = رندوم)" dir="ltr" style="width:190px"><button>➕ ساخت کد</button>', sess)
        body = (f'<div class="card"><h2>🎟 ساخت کد الماس</h2>{new}</div>'
                f'<div class="card"><h2>کدها</h2><div class="tw"><table><tr><th>کد</th><th>الماس</th><th>باقی‌مانده</th><th>استفاده‌شده</th><th>ساخت</th><th></th></tr>'
                f'{rows or "<tr><td colspan=6 class=mut>کدی نیست</td></tr>"}</table></div></div>')
        return self.pg("کدهای الماس", body, sess, flash, "codes")

    # ---------- ادمین‌ها ----------
    def admins_page(self, sess, flash):
        h = self.h
        owners = h.get("owners") or set()
        rows = ""
        cache = {}
        for a in sorted(h["admins"]):
            own = a in owners
            btn = "—" if own else self.form("/admins/del", f'<input type="hidden" name="id" value="{a}"><button class="red sm" data-confirm="ادمین حذف بشه؟">حذف</button>', sess)
            rows += f'<tr><td>{self.name_of(a, cache)}</td><td>{"👑 مالک (.env)" if own else "ادمین"}</td><td>{btn}</td></tr>'
        add = self.form("/admins/add", '<input name="id" placeholder="آیدی عددی یا @یوزرنیم" required style="width:240px"><button>➕ افزودن ادمین</button>', sess)
        body = (f'<div class="card"><h2>👮 ادمین‌ها</h2>{add}<p class="hint">ادمین‌ها الماس نامحدود دارن و پنل ادمین بات رو می‌بینن. مالک‌ها فقط از .env عوض می‌شن.</p>'
                f'<div class="tw"><table><tr><th>کاربر</th><th>نقش</th><th></th></tr>{rows}</table></div></div>')
        return self.pg("ادمین‌ها", body, sess, flash, "admins")

    # ---------- پیام همگانی ----------
    def broadcast_page(self, sess, flash):
        dform = self.form("/broadcast/diamond", '<input name="amount" placeholder="تعداد" required style="width:140px">'
                                                '<button data-confirm="به همه الماس داده بشه؟">🎁 اضافه به همه</button>', sess)
        body = (f'<div class="card"><h2>📢 پیام همگانی</h2><form method="post" action="/broadcast/msg">{csrf_input(sess)}'
                f'<textarea name="text" placeholder="متن پیام همگانی" required></textarea>'
                f'<button style="margin-top:8px" data-confirm="برای همه ارسال بشه؟">ارسال به همه</button></form></div>'
                f'<div class="card"><h2>💎 الماس همگانی</h2>{dform}<p class="hint">ادمین‌ها و کاربرهای مسدود شامل نمی‌شن.</p></div>')
        return self.pg("پیام همگانی", body, sess, flash, "bc")

    # ---------- تنظیمات (.env) ----------
    ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    EDITABLE = {
        "BRAND": ("اسم برند", "توی پیام خوش‌آمدگویی و عنوان پنل", r"[^#\n\r]{1,40}"),
        "GAME_CHAT_ID": ("آیدی عددی گروه بازی", "مثل -1001234567890 ؛ چندتا را با کاما جدا کن. خالی = بازی در همه‌ی چت‌ها", r"-?\d+(,\s*-?\d+)*|"),
        "REPORTS_FORUM_ID": ("آیدی عددی گروه انجمن گزارش", "گروه گزارش باید Forum/Topics داشته باشد و با گروه بازی متفاوت باشد", r"-?\d+|"),
        "DIAMOND_SECONDS": ("ثانیه‌ی معادل هر الماس", "پیش‌فرض ۱۷۹۶ (حدود نیم ساعت)", r"\d{1,9}"),
        "TRIAL_SECONDS": ("طول تست رایگان (ثانیه)", "پیش‌فرض ۲۱۶۰۰ (۶ ساعت)", r"\d{1,9}"),
        "ACTIVATION_COST": ("هزینه‌ی فعالسازی (الماس)", "اولین فعالسازی با تست رایگان مجانیه", r"\d{1,6}(\.\d+)?"),
        "REF_REWARD": ("جایزه‌ی دعوت (الماس)", "برای هر زیرمجموعه", r"\d{1,6}(\.\d+)?"),
        "PRICES": ("قیمت‌های خرید الماس", "به شکل الماس:تومان با کاما؛ مثل 142:3550,450:11250", r"\d+:\d+(,\d+:\d+)*|"),
        "CHANNEL_URL": ("لینک چنل", "https://t.me/...", r"https?://[^\s#]{0,200}|"),
        "SUPPORT_GROUP_URL": ("لینک گپ پشتیبانی", "https://t.me/...", r"https?://[^\s#]{0,200}|"),
        "SUPPORT_USERNAME": ("یوزرنیم پشتیبان", "بدون @", r"@?\w{0,32}"),
        "PAY_INFO": ("متن راهنمای پرداخت", "مثلاً شماره کارت (یک خط)", r"[^#\n\r]{0,300}"),
    }
    SECRETS = ("HUB_BOT_TOKEN", "HUB_HELPER_BOT_TOKEN", "API_HASH", "WEB_PASSWORD", "ADMIN_IDS")

    def read_env(self):
        vals = {}
        try:
            with open(self.ENV_PATH, encoding="utf-8") as f:
                for line in f:
                    line = line.rstrip("\n")
                    if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        vals[k.strip()] = v.strip()
        except OSError:
            pass
        return vals

    def settings_page(self, sess, flash):
        env = self.read_env()
        fields = ""
        for k, (title, hint, _) in self.EDITABLE.items():
            fields += (f'<div class="field"><label>{escape(title)}</label>'
                       f'<input name="{k}" value="{escape(env.get(k, ""), quote=True)}" dir="ltr" autocomplete="off">'
                       f'<div class="hint">{escape(hint)}</div></div>')
        ok_tag, no_tag = '<span class="tag on">تنظیم شده</span>', '<span class="tag off">خالی</span>'
        sec = "".join(f'<tr><td dir="ltr">{k}</td><td>{ok_tag if env.get(k) else no_tag}</td></tr>' for k in self.SECRETS)
        rform = self.form("/restart", '<button class="red" data-confirm="ریستارت بشه؟">ریستارت هاب</button>', sess)
        body = (f'<div class="card"><h2>⚙️ تنظیمات هاب</h2><form method="post" action="/settings">{csrf_input(sess)}{fields}'
                f'<button>💾 ذخیره</button></form><p class="hint">تغییرها بعد از ریستارت اعمال می‌شن.</p></div>'
                f'<div class="card"><h2>🔁 ریستارت</h2><p class="hint">هاب دوباره بالا میاد؛ سلف کاربرها هم خودکار برمی‌گردن.</p>{rform}</div>'
                f'<div class="card"><h2>🔐 مقادیر محرمانه</h2><p class="hint">برای امنیت از توی وب قابل دیدن/تغییر نیستن؛ فقط فایل .env روی سرور.</p>'
                f'<div class="tw"><table>{sec}</table></div></div>')
        return self.pg("تنظیمات", body, sess, flash, "settings")

    def save_settings(self, form):
        new = {}
        for k, (title, _, rx) in self.EDITABLE.items():
            v = form.get(k, "").strip().translate(FA_DIGITS)
            if not re.fullmatch(rx, v):
                return self.flash_to("/settings", f"مقدار «{title}» نامعتبره")
            new[k] = v
        try:
            with open(self.ENV_PATH, encoding="utf-8") as f:
                lines = f.read().split("\n")
        except OSError:
            lines = []
        done = set()
        for i, line in enumerate(lines):
            k = line.split("=", 1)[0].strip()
            if "=" in line and k in new and not line.lstrip().startswith("#"):
                lines[i] = f"{k}={new[k]}"
                done.add(k)
        if lines and lines[-1] == "":
            lines.pop()
        lines += [f"{k}={v}" for k, v in new.items() if k not in done]
        tmp = self.ENV_PATH + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, self.ENV_PATH)
        return self.flash_to("/settings", "ذخیره شد ✅ برای اعمال، ریستارت کن")

    # ---------- عملیات (POST) ----------
    async def post(self, path, form, sess):
        h = self.h
        parts = [p for p in path.split("/") if p]
        try:
            if parts == ["settings"]:
                return self.save_settings(form)
            if parts == ["restart"]:
                if not h.get("restart"):
                    return self.flash_to("/settings", "ریستارت پشتیبانی نمی‌شه")
                asyncio.get_running_loop().call_later(1.0, h["restart"])
                return self.flash_to("/settings", "در حال ریستارت... چند ثانیه صبر کن و صفحه رو رفرش کن")
            if parts == ["transfer"]:
                return await self.do_transfer(form)
            if parts == ["codes", "new"]:
                return self.code_new(form)
            if parts == ["codes", "del"]:
                h["db"].execute("DELETE FROM codes WHERE code=?", (form.get("code", ""),))
                h["db"].commit()
                return self.flash_to("/codes", "کد حذف شد")
            if parts == ["admins", "add"]:
                return await self.admin_add(form)
            if parts == ["admins", "del"]:
                return self.admin_del(form)
            if parts[:1] == ["broadcast"] and len(parts) == 2:
                return await self.broadcast(parts[1], form)
            if parts[:1] == ["user"] and len(parts) == 3:
                uid = int(parts[1])
                if not self.user_exists(uid):
                    return self.nf(sess)
                return await self.user_action(uid, parts[2], form)
        except (ValueError, KeyError):
            return self.flash_to("/", "ورودی نامعتبر")
        return self.nf(sess)

    def code_new(self, form):
        amount, uses = num(form.get("amount", "")), num(form.get("uses", "1"))
        if amount is None or amount <= 0 or uses is None or not 1 <= uses <= 1_000_000:
            return self.flash_to("/codes", "مقدار یا تعداد نامعتبره")
        code = form.get("code", "").strip().upper()
        if code and not re.fullmatch(r"[A-Z0-9]{4,32}", code):
            return self.flash_to("/codes", "کد فقط حرف انگلیسی و عدد (۴ تا ۳۲ کاراکتر)")
        code = code or secrets.token_hex(5).upper()
        db = self.h["db"]
        if db.execute("SELECT 1 FROM codes WHERE code=?", (code,)).fetchone():
            return self.flash_to("/codes", "این کد قبلاً هست")
        db.execute("INSERT INTO codes(code,amount,uses,created_at) VALUES(?,?,?,?)", (code, amount, int(uses), time.time()))
        db.commit()
        return self.flash_to("/codes", f"کد ساخته شد: {code}")

    async def admin_add(self, form):
        h = self.h
        raw = form.get("id", "").strip().translate(FA_DIGITS)
        uid = int(raw) if raw.isdigit() else h["db_find_user"](raw)
        if uid is None:
            return self.flash_to("/admins", "کاربر پیدا نشد (با یوزرنیم باید توی بات /start زده باشه)")
        if uid in h["admins"]:
            return self.flash_to("/admins", "از قبل ادمینه")
        h["db"].execute("INSERT OR IGNORE INTO admins(user_id,added_by,added_at) VALUES(?,?,?)", (uid, 0, time.time()))
        h["db"].commit()
        h["admins"].add(uid)
        await h["notify"](uid, "👮 تو به‌عنوان ادمین اضافه شدی. /start بزن.")
        return self.flash_to("/admins", f"{uid} ادمین شد")

    def admin_del(self, form):
        h = self.h
        uid = int(form.get("id", "0"))
        if uid in (h.get("owners") or ()):
            return self.flash_to("/admins", "مالک‌ها از اینجا حذف نمی‌شن")
        h["db"].execute("DELETE FROM admins WHERE user_id=?", (uid,))
        h["db"].commit()
        h["admins"].discard(uid)
        return self.flash_to("/admins", "ادمین حذف شد")

    async def broadcast(self, kind, form):
        h = self.h
        ids = h["db_all"](include_banned=False)
        if kind == "msg":
            text = form.get("text", "").strip()
            if not text:
                return self.flash_to("/broadcast", "متن خالیه")
            sent = 0
            for uid in ids:
                try:
                    await h["send_html"](uid, f"📢 <b>پیام همگانی:</b>\n\n{escape(text)}")
                    sent += 1
                except Exception:
                    pass
                await asyncio.sleep(0.05)
            return self.flash_to("/broadcast", f"برای {sent} از {len(ids)} کاربر ارسال شد")
        if kind == "diamond":
            amount = num(form.get("amount", ""))
            if amount is None or amount <= 0:
                raise ValueError
            n = 0
            for uid in ids:
                if uid in h["admins"]:
                    continue
                u = h["db_get"](uid)
                h["db_set"](uid, diamonds=u["diamonds"] + amount)
                await h["notify"](uid, f"🎁 ادمین {amount:.1f} الماس به همه‌ی کاربرا هدیه داد!")
                n += 1
            return self.flash_to("/broadcast", f"به {n} کاربر {amount:.1f} الماس داده شد")
        raise ValueError

    async def user_action(self, uid, act, form):
        h = self.h
        back = f"/user/{uid}"
        u = h["db_get"](uid)
        if act == "diamond" and not self.is_adm(uid):
            amount = num(form.get("amount", ""))
            op = form.get("op")
            if amount is None or amount < 0 or (amount == 0 and op != "set") or amount > 1e9:
                return self.flash_to(back, "مقدار نامعتبره")
            if op == "add":
                new = u["diamonds"] + amount
            elif op == "sub":
                new = max(0.0, u["diamonds"] - amount)
            elif op == "set":
                new = amount
            else:
                raise ValueError
            h["db_set"](uid, diamonds=new)
            if new <= 0 and uid in h["running"] and h["running"][uid]["mode"] == "paid":
                await h["stop_self"](uid, "⏰ موجودی الماست توسط ادمین صفر شد و سلفت خاموش شد.")
            await h["notify"](uid, f"💎 موجودی الماست توسط ادمین تغییر کرد. موجودی فعلی: {new:.1f}")
            return self.flash_to(back, f"موجودی شد {new:.1f}")
        if act == "trial":
            h["db_set"](uid, trial_used=1, trial_seconds=h["TRIAL_SECONDS"])
            await h["notify"](uid, f"🎁 ادمین {h['fmt_duration'](h['TRIAL_SECONDS'])} تست رایگان بهت هدیه داد!")
            return self.flash_to(back, "تست هدیه داده شد")
        if act == "ban" and not self.is_adm(uid):
            h["db_set"](uid, banned=0 if u["banned"] else 1)
            if not u["banned"]:
                await h["stop_self"](uid, "⛔ دسترسیت توسط ادمین مسدود شد.")
            return self.flash_to(back, "وضعیت بن عوض شد")
        if act == "stop":
            await h["stop_self"](uid, "⏸ ادمین سلفت رو خاموش کرد.")
            return self.flash_to(back, "سلف خاموش شد")
        if act == "start":
            if not h.get("start_self"):
                return self.flash_to(back, "روشن‌کردن از وب پشتیبانی نمی‌شه")
            ok, err = await h["start_self"](uid)
            return self.flash_to(back, "سلف روشن شد ✅" if ok else f"روشن نشد: {err}")
        if act == "delsess" and h.get("delete_self"):
            await h["delete_self"](uid)
            await h["notify"](uid, "🗑 ادمین سلف و نشست تو رو حذف کرد. برای فعالسازی دوباره وارد شو.")
            return self.flash_to(back, "سلف و نشست حذف شد")
        if act == "msg":
            text = form.get("text", "").strip()
            if not text:
                return self.flash_to(back, "متن خالیه")
            try:
                await h["send_html"](uid, f"📨 <b>پیام از ادمین:</b>\n\n{escape(text)}")
                return self.flash_to(back, "ارسال شد")
            except Exception:
                return self.flash_to(back, "ارسال نشد (شاید بات رو بلاک کرده)")
        if act == "cfg":
            cur = self.read_cfg(uid)
            if cur is None:
                return self.flash_to(back + "?t=cfg", "فایل تنظیمات پیدا نشد")
            changes, errs = cfg_diff(cur, form)
            if errs:
                return self.flash_to(back + "?t=cfg", "مقدار نامعتبر: " + "، ".join(errs[:5]))
            if not changes:
                return self.flash_to(back + "?t=cfg", "تغییری نبود")
            cur.update(changes)
            self.write_cfg(uid, cur)
            return self.flash_to(back + "?t=cfg", f"✅ {len(changes)} تنظیم ذخیره شد")
        if act == "cfgraw":
            try:
                data = json.loads(form.get("json", ""))
            except ValueError:
                return self.flash_to(back + "?t=cfg", "JSON نامعتبره")
            if not isinstance(data, dict) or not data:
                return self.flash_to(back + "?t=cfg", "JSON باید یه آبجکت غیرخالی باشه")
            if self.cfg_file(uid) is None:
                return self.flash_to(back + "?t=cfg", "مسیر تنظیمات در دسترس نیست")
            self.write_cfg(uid, data)
            return self.flash_to(back + "?t=cfg", "✅ تنظیمات جایگزین شد")
        raise ValueError
