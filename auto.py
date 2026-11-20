"""
قابلیت‌های نسخه‌ی ۵ (هم‌ترتیب با منوی LTM Self):

  • سین خودکار جدا برای پیوی / گروه / کانال / ربات
  • پاسخ خودکار: روشن/خاموش، جدید، ذخیره (با ریپلای)، حذف، لیست
  • ری‌اکشن خودکار برای کاربرِ مشخص (توی هر چتی)
  • کامنت اول: تنظیم/حذف کانال، تنظیم متن (با ریپلای)، لیست، پاکسازی
  • مدیریت ادمین: ادمین‌های سلف می‌تونن دستورها رو برات اجرا کنن (پرفیکس جدا)
  • میو خودکار / پیشی خودکار / ماهی‌گیری خودکار: ارسال دوره‌ای یه کلمه توی گروه
  • ایموجی پریمیوم و ایموجی پریمیوم چنل (فقط اکانت Premium)

همه‌چیز از طریق setup_auto() به self_bot.py وصل می‌شه.
"""
import asyncio
import random
import re
import time

from telethon import errors, events
from telethon.tl import functions, types

FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")

# ================= ایموجی پریمیوم (توابع خالص؛ بدون نیاز به تلگرام) =================
_BASE = (r"[\U0001F000-\U0001FAFF\u2190-\u21FF\u2300-\u23FF\u24C2\u25A0-\u27BF\u2900-\u297F"
         r"\u2B00-\u2BFF\u3030\u303D\u3297\u3299\u00A9\u00AE\u203C\u2049\u2122\u2139]")
_SEQ = rf"{_BASE}[\U0001F3FB-\U0001F3FF]?\uFE0F?(?:\u200D{_BASE}[\U0001F3FB-\U0001F3FF]?\uFE0F?)*"
EMOJI_RE = re.compile(rf"(?:[\U0001F1E6-\U0001F1FF]{{2}}|{_SEQ})")


def u16(s):
    """طول رشته به واحد UTF-16 (آفست entityهای تلگرام این‌طوریه)."""
    return len(s.encode("utf-16-le")) // 2


def norm_emoji(s):
    return s.replace("\ufe0f", "")


def emoji_spans(text, emap, limit=60):
    """[(offset16, length16, document_id)] برای ایموجی‌هایی که توی emap (ایموجی ← آیدی پریمیوم) هستن."""
    out, pos, last = [], 0, 0
    for m in EMOJI_RE.finditer(text):
        pos += u16(text[last:m.start()])
        s = m.group(0)
        ln = u16(s)
        doc = emap.get(norm_emoji(s))
        if doc:
            out.append((pos, ln, doc))
            if len(out) >= limit:
                break
        pos += ln
        last = m.end()
    return out


# ================= پارس آرگومان‌ها (خالص) =================
def split_react_args(a):
    """'🔥 12345' | '12345 🔥' | '🔥' | '🔥 @user' ← (emoji, user_token یا None)"""
    emoji, user = None, None
    for t in (a or "").translate(FA).split():
        if re.fullmatch(r"-?\d{3,}", t) or (t.startswith("@") and len(t) > 2):
            user = user or t
        elif emoji is None and len(t) <= 12 and not any(ch.isalnum() for ch in t.replace("\ufe0f", "")):
            emoji = t
    return emoji, user


def parse_minutes(a, lo=1, hi=1440):
    m = re.fullmatch(r"\d+", (a or "").strip().translate(FA))
    if not m or not lo <= int(m.group(0)) <= hi:
        raise ValueError(f"یه عدد بین {lo} تا {hi} (دقیقه) بنویس")
    return int(m.group(0))


def valid_admin_prefix(a):
    """پرفیکس ادمین: ۱ یا ۲ نماد؛ x / X = بدون پرفیکس (رشته‌ی خالی)."""
    a = (a or "").strip()
    if a in ("x", "X"):
        return ""
    if not a or len(a) > 2 or any(ch.isalnum() or ch.isspace() for ch in a) or "@" in a:
        raise ValueError("پرفیکس ادمین باید ۱ یا ۲ نماد باشه (مثل ! / # $) یا x برای بدون پرفیکس")
    return a


# ================= میو / پیشی / ماهی‌گیری =================
GAMES = {            # کلید ← (اسم فارسی دستور، متنی که فرستاده می‌شه، ایموجی)
    "meow": ("میو", "میو", "🐱"),
    "pishi": ("پیشی", "پیشی", "🐈"),
    "fish": ("ماهی گیری", "ماهی گیری", "🎣"),
}

# دستورهایی که ادمین‌های سلف نباید اجرا کنن (مدیریت ادمین، نشست‌ها، اکانت)
ADMIN_BLOCKED = ("تنظیم ادمین", "حذف ادمین", "لیست ادمین ها", "پاکسازی لیست ادمین", "تنظیم پرفیکس ادمین",
                 "پرفیکس", "نشست ها", "قطع نشست", "ضد لاگین", "بکاپ", "ثبت نام", "اطلاعات", "موجودی")


def is_blocked_for_admin(name):
    return any(name == b or name.startswith(b + " ") for b in ADMIN_BLOCKED)


def find_command(commands, body):
    """طولانی‌ترین نام دستور (تا ۴ کلمه). خروجی: (تابع، آرگومان، نام) یا (None, '', '')."""
    words = body.split()
    for n in (4, 3, 2, 1):
        if len(words) >= n:
            name = " ".join(words[:n])
            if name in commands:
                pieces = body.split(None, n)
                return commands[name], (pieces[n] if len(pieces) > n else ""), name
    return None, "", ""


class AdminEvent:
    """رویداد پیام ادمین؛ ویرایش پیام کسی دیگه ممکن نیست، پس edit ← جواب توی همون چت."""

    def __init__(self, ev):
        self._ev = ev

    def __getattr__(self, name):
        return getattr(self._ev, name)

    async def edit(self, *args, **kwargs):
        return await self._ev.respond(*args, **kwargs)

    async def delete(self, *args, **kwargs):
        try:
            return await self._ev.delete(*args, **kwargs)
        except Exception:
            return None


# ================= نصب روی سلف =================
def setup_auto(client, cfg, save, cmd, out, target, commands):
    cfg.setdefault("seen_gp", False)
    cfg.setdefault("seen_ch", False)
    cfg.setdefault("seen_bot", False)
    cfg.setdefault("autoreply_on", True)
    cfg.setdefault("ar_pending", [])
    cfg.setdefault("react_users", {})
    cfg.setdefault("self_admins", [])
    cfg.setdefault("admin_prefix", "")
    cfg.setdefault("pe_on", False)
    cfg.setdefault("pe_chan", False)
    cfg.setdefault("pe_packs", [])
    for k, (_, word, _e) in GAMES.items():
        cfg.setdefault(f"{k}_on", False)
        cfg.setdefault(f"{k}_chats", [])
        cfg.setdefault(f"{k}_min", 60)
        cfg.setdefault(f"{k}_text", word)
    save()

    me_cache = {}
    seen_last = {}
    game_last = {}
    pe = {"map": {}, "tried": 0.0}

    async def my_id():
        if "id" not in me_cache:
            me_cache["id"] = (await client.get_me()).id
        return me_cache["id"]

    def word_of(a):
        return a.split()[0] if a else ""

    def onoff(a):
        w = word_of(a)
        if w in ("روشن", "on", "1"):
            return True
        if w in ("خاموش", "off", "0"):
            return False
        raise ValueError("بنویس: روشن یا خاموش")

    def mark(on):
        return "✅ روشن" if on else "⛔ خاموش"

    async def entity_of(a):
        a = (a or "").strip().split()[0] if (a or "").strip() else ""
        if not a:
            raise ValueError("آیدی یا یوزرنیم کانال رو بنویس")
        a = re.sub(r"^(?:https?://)?t\.me/", "@", a)
        return await client.get_entity(int(a) if a.lstrip("-").isdigit() else a)

    async def name_of(uid):
        try:
            ent = await client.get_entity(int(uid))
            nm = " ".join(x for x in (getattr(ent, "first_name", None), getattr(ent, "last_name", None)) if x)
            nm = nm or getattr(ent, "title", None) or (f"@{ent.username}" if getattr(ent, "username", None) else "")
            return f"{nm} ({uid})" if nm else str(uid)
        except Exception:
            return str(uid)

    # ===================== سین خودکار (پیوی / گروه / کانال / ربات) =====================
    def seen_toggle(where, key, label):
        @cmd(f"سین خودکار {where}")
        async def _(e, a):
            cfg[key] = onoff(a)
            save()
            await out(e, f"👁 سین خودکار {label}: {mark(cfg[key])}")

    seen_toggle("پیوی", "autoseen", "پیوی")
    seen_toggle("گروه", "seen_gp", "گروه")
    seen_toggle("کانال", "seen_ch", "کانال")
    seen_toggle("ربات", "seen_bot", "ربات‌ها")

    async def mark_seen(e, key):
        now = time.time()
        if now - seen_last.get(e.chat_id, 0) < 2:   # توی گروه‌های شلوغ هر ۲ ثانیه یه بار کافیه
            return
        seen_last[e.chat_id] = now
        await e.message.mark_read()

    # ===================== پاسخ خودکار =====================
    @cmd("پاسخ خودکار")
    async def ar_toggle(e, a):
        cfg["autoreply_on"] = onoff(a)
        save()
        await out(e, f"💬 پاسخ خودکار: {mark(cfg['autoreply_on'])}")

    @cmd("پاسخ خودکار جدید")
    async def ar_new(e, a):
        w = a.strip()
        if not w or len(w) > 60:
            raise ValueError("کلمه‌ی کلیدی رو بنویس: .پاسخ خودکار جدید سلام")
        if w not in cfg["autoreplies"] and w not in cfg["ar_pending"]:
            cfg["ar_pending"].append(w)
        save()
        await out(e, f"✅ کلمه ثبت شد: {w}\nحالا روی پیام جواب ریپلای کن و بنویس:\n.ذخیره پاسخ خودکار {w}")

    @cmd("ذخیره پاسخ خودکار")
    async def ar_save(e, a):
        w = a.strip() or (cfg["ar_pending"][-1] if cfg["ar_pending"] else "")
        if not w:
            raise ValueError("کلمه رو بنویس: .ذخیره پاسخ خودکار سلام (با ریپلای)")
        if not e.is_reply:
            raise ValueError("روی پیامی که می‌خوای جواب باشه ریپلای کن")
        r = await e.get_reply_message()
        text = (r.raw_text or "").strip()
        if not text:
            raise ValueError("فقط پیام متنی می‌تونه جواب باشه")
        cfg["autoreplies"][w] = text
        if w in cfg["ar_pending"]:
            cfg["ar_pending"].remove(w)
        save()
        await out(e, f"✅ پاسخ «{w}» ذخیره شد")

    @cmd("حذف پاسخ خودکار")
    async def ar_del(e, a):
        w = a.strip()
        if not w:
            raise ValueError("کلمه رو بنویس: .حذف پاسخ خودکار سلام")
        found = cfg["autoreplies"].pop(w, None) is not None
        if w in cfg["ar_pending"]:
            cfg["ar_pending"].remove(w)
            found = True
        save()
        await out(e, f"✅ حذف شد: {w}" if found else f"چنین کلمه‌ای توی لیست نیست: {w}")

    @cmd("لیست پاسخ خودکار")
    async def ar_list(e, a):
        lines = [f"• {k} ← {v[:40]}{'…' if len(v) > 40 else ''}" for k, v in cfg["autoreplies"].items()]
        lines += [f"• {k} ← (هنوز جواب ذخیره نشده)" for k in cfg["ar_pending"]]
        await out(e, f"💬 پاسخ خودکار: {mark(cfg['autoreply_on'])}\n" + ("\n".join(lines) or "لیست خالیه"))

    # ===================== ری‌اکشن خودکار برای کاربر مشخص =====================
    @cmd("تنظیم ری اکشن")
    async def rx_set(e, a):
        emoji, user = split_react_args(a)
        if not emoji:
            raise ValueError("مثال: .تنظیم ری اکشن 🔥 12345  (یا با ریپلای: .تنظیم ری اکشن 🔥)")
        if e.is_reply:
            uid = (await e.get_reply_message()).sender_id
        elif user:
            ent = await client.get_entity(int(user) if user.lstrip("-").isdigit() else user)
            uid = ent.id
        else:
            raise ValueError("ریپلای کن یا آیدی/یوزرنیم بده")
        if not uid or uid == await my_id():
            raise ValueError("این کاربر قابل تنظیم نیست")
        cfg["react_users"][str(uid)] = emoji
        save()
        await out(e, f"✅ ری‌اکشن {emoji} برای {await name_of(uid)} تنظیم شد")

    @cmd("حذف ری اکشن")
    async def rx_del(e, a):
        _, user = split_react_args(a)
        if e.is_reply:
            uid = (await e.get_reply_message()).sender_id
        elif user:
            ent = await client.get_entity(int(user) if user.lstrip("-").isdigit() else user)
            uid = ent.id
        else:
            raise ValueError("ریپلای کن یا آیدی/یوزرنیم بده")
        gone = cfg["react_users"].pop(str(uid), None)
        save()
        await out(e, "✅ حذف شد" if gone else "این کاربر توی لیست نبود")

    @cmd("لیست ری اکشن")
    async def rx_list(e, a):
        if not cfg["react_users"]:
            return await out(e, "لیست ری‌اکشن خالیه")
        lines = [f"• {await name_of(u)} ← {em}" for u, em in cfg["react_users"].items()]
        await out(e, "❤ لیست ری‌اکشن کاربرها:\n" + "\n".join(lines))

    @cmd("پاکسازی لیست ری اکشن")
    async def rx_clear(e, a):
        cfg["react_users"].clear()
        save()
        await out(e, "✅ لیست ری‌اکشن خالی شد")

    async def react_to(e, emoji):
        try:
            await client(functions.messages.SendReactionRequest(
                peer=await e.get_input_chat(), msg_id=e.id, reaction=[types.ReactionEmoji(emoticon=emoji)]))
        except errors.FloodWaitError:
            pass
        except Exception:
            pass   # ری‌اکشنِ غیرمجاز توی اون چت، یا چت ری‌اکشن نداره

    # ===================== کامنت اول (نام‌های LTM Self) =====================
    @cmd("تنظیم کامنت اول")
    async def fc_add(e, a):
        ent = await entity_of(a)
        cid = await client.get_peer_id(ent)
        if cid not in cfg["fc_channels"]:
            cfg["fc_channels"].append(cid)
        cfg["fc_on"] = True
        save()
        await out(e, f"✅ کامنت اول برای «{getattr(ent, 'title', a)}» فعال شد")

    @cmd("حذف کامنت اول")
    async def fc_del(e, a):
        ent = await entity_of(a)
        cid = await client.get_peer_id(ent)
        if cid in cfg["fc_channels"]:
            cfg["fc_channels"].remove(cid)
        save()
        await out(e, f"✅ کامنت اول برای «{getattr(ent, 'title', a)}» غیرفعال شد")

    @cmd("تنظیم کامنت")
    async def fc_text(e, a):
        if e.is_reply:
            text = ((await e.get_reply_message()).raw_text or "").strip()
        else:
            text = a.strip()
        if not text:
            raise ValueError("روی یه پیام متنی ریپلای کن (چندتا متن رو با | جدا کن تا رندوم انتخاب بشه)")
        cfg["fc_text"] = text
        save()
        await out(e, f"✅ متن کامنت اول: {text[:200]}")

    @cmd("لیست کامنت")
    async def fc_list(e, a):
        names = []
        for cid in cfg["fc_channels"]:
            try:
                names.append(getattr(await client.get_entity(cid), "title", str(cid)))
            except Exception:
                names.append(str(cid))
        await out(e, f"🥇 کامنت اول: {mark(cfg['fc_on'])}\nمتن: {cfg['fc_text']}\nکانال‌ها:\n"
                     + ("\n".join(f"• {n}" for n in names) or "خالی"))

    @cmd("پاکسازی لیست کامنت")
    async def fc_clear(e, a):
        cfg["fc_channels"].clear()
        save()
        await out(e, "✅ لیست کانال‌های کامنت اول خالی شد")

    # ===================== مدیریت ادمین (ادمین‌های سلف) =====================
    @cmd("تنظیم ادمین")
    async def adm_add(e, a):
        uid = await target(e, a)
        if uid == await my_id():
            raise ValueError("خودت که صاحب سلفی 😄")
        if len(cfg["self_admins"]) >= 20:
            raise ValueError("حداکثر ۲۰ ادمین")
        if uid not in cfg["self_admins"]:
            cfg["self_admins"].append(uid)
        save()
        await out(e, f"✅ ادمین شد: {await name_of(uid)}")

    @cmd("حذف ادمین")
    async def adm_del(e, a):
        uid = await target(e, a)
        if uid in cfg["self_admins"]:
            cfg["self_admins"].remove(uid)
        save()
        await out(e, f"✅ از لیست ادمین حذف شد: {await name_of(uid)}")

    @cmd("لیست ادمین ها")
    async def adm_list(e, a):
        if not cfg["self_admins"]:
            return await out(e, "لیست ادمین خالیه")
        lines = [f"• {await name_of(u)}" for u in cfg["self_admins"]]
        ap = cfg["admin_prefix"] or "بدون پرفیکس"
        await out(e, f"👮 ادمین‌ها ({len(lines)}) | پرفیکس ادمین: {ap}\n" + "\n".join(lines))

    @cmd("پاکسازی لیست ادمین")
    async def adm_clear(e, a):
        cfg["self_admins"].clear()
        save()
        await out(e, "✅ لیست ادمین خالی شد")

    @cmd("تنظیم پرفیکس ادمین")
    async def adm_prefix(e, a):
        if not a.strip():
            return await out(e, f"🔣 پرفیکس ادمین: {cfg['admin_prefix'] or 'پیش‌فرض (بدون پرفیکس)'}\n"
                                "تغییر: .تنظیم پرفیکس ادمین !   |   بدون پرفیکس: .تنظیم پرفیکس ادمین x")
        cfg["admin_prefix"] = valid_admin_prefix(a)
        save()
        p = cfg["admin_prefix"]
        await out(e, f"✅ پرفیکس ادمین: {p or 'بدون پرفیکس'}" + (f"\nمثال: {p}پینگ" if p else ""))

    async def run_admin_command(e):
        text = (e.raw_text or "").strip()
        ap = cfg.get("admin_prefix") or ""
        if ap:
            if not text.startswith(ap):
                return False
            text = text[len(ap):].strip()
        fn, arg, name = find_command(commands, text)
        if not fn or is_blocked_for_admin(name):
            return False
        try:
            await fn(AdminEvent(e), arg)
        except Exception as ex:
            try:
                await e.respond(f"❌ {ex}")
            except Exception:
                pass
        return True

    # ===================== میو / پیشی / ماهی‌گیری خودکار =====================
    def make_game(k, fa, default_word, icon):
        @cmd(f"{fa} خودکار")
        async def game_cmd(e, a):
            w = word_of(a)
            chats = cfg[f"{k}_chats"]
            if w in ("روشن", "on", "1"):
                if e.is_private:
                    raise ValueError("این دستور رو توی همون گروهی که می‌خوای بزن")
                if e.chat_id not in chats:
                    chats.append(e.chat_id)
                cfg[f"{k}_on"] = True
                game_last.pop((k, e.chat_id), None)   # اولین پیام زود فرستاده بشه
                save()
                return await out(e, f"{icon} {fa} خودکار توی این گروه روشن شد (هر {cfg[f'{k}_min']} دقیقه «{cfg[f'{k}_text']}»)")
            if w in ("خاموش", "off", "0"):
                if e.is_private:
                    cfg[f"{k}_on"] = False
                elif e.chat_id in chats:
                    chats.remove(e.chat_id)
                if not chats:
                    cfg[f"{k}_on"] = False
                save()
                return await out(e, f"{icon} {fa} خودکار: ⛔ خاموش")
            await out(e, f"{icon} {fa} خودکار: {mark(cfg[f'{k}_on'])} | هر {cfg[f'{k}_min']} دقیقه | "
                         f"متن: {cfg[f'{k}_text']} | {len(chats)} گروه\n"
                         f".{fa} خودکار روشن | خاموش   (توی خود گروه)\n.تنظیم زمان {fa} [دقیقه]")

        @cmd(f"تنظیم زمان {fa}")
        async def game_time(e, a):
            cfg[f"{k}_min"] = parse_minutes(a)
            save()
            await out(e, f"✅ فاصله‌ی ارسال {fa}: هر {cfg[f'{k}_min']} دقیقه")

        @cmd(f"تنظیم متن {fa}")
        async def game_text(e, a):
            t = a.strip()
            if not t or len(t) > 100:
                raise ValueError(f"متنی که فرستاده بشه رو بنویس (پیش‌فرض: {default_word})")
            cfg[f"{k}_text"] = t
            save()
            await out(e, f"✅ متن {fa}: {t}")

    for _k, (_fa, _w, _ic) in GAMES.items():
        make_game(_k, _fa, _w, _ic)

    async def games_loop():
        while True:
            await asyncio.sleep(15)
            if not cfg["enabled"]:
                continue
            now = time.time()
            for k in GAMES:
                if not cfg.get(f"{k}_on"):
                    continue
                gap = max(1, int(cfg.get(f"{k}_min") or 60)) * 60
                for cid in list(cfg.get(f"{k}_chats", [])):
                    last = game_last.setdefault((k, cid), 0)
                    if now - last < gap + random.randint(0, 20):
                        continue
                    try:
                        await client.send_message(cid, cfg[f"{k}_text"])
                        game_last[(k, cid)] = time.time()
                    except errors.FloodWaitError as ex:
                        game_last[(k, cid)] = time.time() + ex.seconds
                    except (errors.ChatWriteForbiddenError, errors.ChannelPrivateError,
                            errors.UserBannedInChannelError):
                        cfg[f"{k}_chats"].remove(cid)   # دیگه اجازه‌ی نوشتن توی این گروه نیست
                        save()
                    except Exception as ex:
                        print(f"{k} auto error:", cid, ex)
                    await asyncio.sleep(2)

    # ===================== ایموجی پریمیوم =====================
    async def load_pack(setobj):
        r = await client(functions.messages.GetStickerSetRequest(stickerset=setobj, hash=0))
        n = 0
        for d in r.documents:
            for at in d.attributes:
                if isinstance(at, types.DocumentAttributeCustomEmoji) and at.alt:
                    pe["map"].setdefault(norm_emoji(at.alt), d.id)
                    n += 1
        return n

    async def load_emoji_map(force=False):
        if not force and time.time() - pe["tried"] < 300:
            return
        pe["tried"] = time.time()
        sets = []
        for nm in ("InputStickerSetEmojiGenericAnimations", "InputStickerSetEmojiDefaultStatuses",
                   "InputStickerSetEmojiDefaultTopicIcons"):
            cls = getattr(types, nm, None)
            if cls:
                sets.append(cls())
        for short in cfg["pe_packs"]:
            sets.append(types.InputStickerSetShortName(short_name=short))
        for s in sets:
            try:
                await load_pack(s)
            except Exception as ex:
                print("premium emoji pack error:", ex)

    async def need_premium():
        me = await client.get_me()
        if getattr(me, "premium", None) is False:
            raise ValueError("این قابلیت فقط برای اکانت‌های Telegram Premium کار می‌کنه")

    def pe_toggle(name, key, label):
        @cmd(name)
        async def _(e, a):
            w = word_of(a)
            if w == "وضعیت" or not w:
                if not pe["map"]:
                    await load_emoji_map(force=True)
                return await out(e, f"💎 {label}: {mark(cfg[key])} | {len(pe['map'])} ایموجی پریمیوم در دسترس\n"
                                    f".{name} روشن | خاموش   |   .ایموجی پریمیوم پک [لینک addemoji]")
            on = onoff(a)
            if on:
                await need_premium()
                await load_emoji_map(force=True)
                if not pe["map"]:
                    raise ValueError("ایموجی پریمیومی پیدا نشد؛ یه پک با .ایموجی پریمیوم پک [لینک] اضافه کن")
            cfg[key] = on
            save()
            await out(e, f"💎 {label}: {mark(on)}" + (f" ({len(pe['map'])} ایموجی)" if on else ""))

    pe_toggle("ایموجی پریمیوم", "pe_on", "ایموجی پریمیوم")
    pe_toggle("ایموجی پریمیوم چنل", "pe_chan", "ایموجی پریمیوم چنل")

    @cmd("ایموجی پریمیوم پک")
    async def pe_pack(e, a):
        m = re.search(r"(?:addemoji/)?([A-Za-z][\w]{2,63})\s*$", a.strip())
        if not m:
            raise ValueError("لینک یا اسم پک: .ایموجی پریمیوم پک https://t.me/addemoji/NAME")
        short = m.group(1)
        n = await load_pack(types.InputStickerSetShortName(short_name=short))
        if short not in cfg["pe_packs"]:
            cfg["pe_packs"].append(short)
            save()
        await out(e, f"✅ پک اضافه شد: {short} ({n} ایموجی)")

    async def premium_entities(e, text):
        """entityهای ایموجی پریمیوم برای متنِ یک پیام خروجی (لیست خالی اگه خاموشه)."""
        chan = bool(e.is_channel and not e.is_group)
        if not cfg.get("pe_chan" if chan else "pe_on") or not text or len(text) > 4000:
            return []
        if not EMOJI_RE.search(text):
            return []
        if not pe["map"]:
            await load_emoji_map()
        if not pe["map"]:
            return []
        return [types.MessageEntityCustomEmoji(offset=o, length=n, document_id=d)
                for o, n, d in emoji_spans(text, pe["map"])]

    # ===================== هوک ورودی =====================
    async def on_incoming(e):
        sid = e.sender_id
        if sid and not e.out and sid in cfg["self_admins"]:
            if await run_admin_command(e):
                return True
        try:
            if e.is_private:
                if cfg["seen_bot"]:
                    sender = await e.get_sender()
                    if getattr(sender, "bot", False):
                        await mark_seen(e, "seen_bot")
            elif e.is_channel and not e.is_group:
                if cfg["seen_ch"]:
                    await mark_seen(e, "seen_ch")
            elif cfg["seen_gp"]:
                await mark_seen(e, "seen_gp")
        except Exception:
            pass
        if sid and cfg["react_users"]:
            em = cfg["react_users"].get(str(sid))
            if em:
                await react_to(e, em)
        return False

    return {"incoming": on_incoming, "loops": [games_loop], "premium": premium_entities}
