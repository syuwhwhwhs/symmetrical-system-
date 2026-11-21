"""بازی‌های گروهی روی بات هلپر (۲۱ و دوئل تاس) با «سکه‌ی مجازی».
سکه‌ها فقط امتیاز بازی‌ان: خرید، فروش، انتقال یا تبدیل به پول ندارن."""
import asyncio
import html
import os
import random
import re
import sqlite3
import time
import uuid

from telethon import Button, events
from telethon.tl import types
from ui import auto_btn

DB_PATH = os.getenv("GAMES_DB", "games.db")


def _parse_chat_ids(raw):
    """GAME_CHAT_ID: یک یا چند آیدی عددی گروه، با کاما جدا. مثل -1001234567890"""
    ids = set()
    for part in (raw or "").replace("،", ",").split(","):
        part = part.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
        if part.lstrip("-").isdigit():
            n = int(part)
            # آیدی گروه/سوپرگروه رو با یا بدون پیشوند -100 قبول می‌کنیم
            ids.add(n)
            if n > 0:
                ids.add(int(f"-100{n}"))
                ids.add(-n)
    return ids


GAME_CHATS = _parse_chat_ids(os.getenv("GAME_CHAT_ID"))   # خالی = همه‌ی چت‌ها
START_COINS, DAILY_COINS = 1000, 500
def _env_int(name, default):
    try:
        return max(1, int(os.getenv(name, default)))
    except ValueError:
        return default


# حداقل/حداکثر/پیش‌فرض شرط (قابل تغییر با GAME_MIN_STAKE / GAME_MAX_STAKE / GAME_DEFAULT_STAKE توی .env)
MIN_STAKE, MAX_STAKE, DEFAULT_STAKE = _env_int("GAME_MIN_STAKE", 20), _env_int("GAME_MAX_STAKE", 100000), _env_int("GAME_DEFAULT_STAKE", 100)
DEFAULT_STAKE = max(DEFAULT_STAKE, MIN_STAKE)   # شرط هیچ‌وقت زیر حداقل (پیش‌فرض ۲۰) نمی‌شه
MAX_PLAYERS, LOBBY_TTL, TURN_TTL = 3, 120, 60
RNG = random.SystemRandom()
# حالت پیش‌فرض بازی ۲۱، بلک‌جک کارتی و نوبتی است؛ حالت شانسی فقط با GAME21_MODE=fair فعال می‌شود.
FAIR21 = os.getenv("GAME21_MODE", "cards").lower() == "fair"
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = "♠♥♦♣"
TITLES = {"bj": "🃏 <b>بازی ۲۱</b>", "dice": "🎲 <b>دوئل تاس</b>"}
FA2EN = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")

HELP = (
    "🎮 <b>بازی‌های گروهی</b> (با سکه‌ی مجازی)\n\n"
    "🃏 <code>/21 [شرط]</code> یا «بازی 21» ← ۲ تا ۳ نفره؛ با ربات شانس برد دقیقاً ۵۰/۵۰ است\n"
    "🎲 <code>/dice [شرط]</code> یا «دوئل تاس» ← هر کی تاس بزرگ‌تر بندازه می‌بره\n"
    "💰 <code>/balance</code> یا «موجودی»\n"
    "🎁 <code>/daily</code> یا «جایزه روزانه» ← هر ۲۴ ساعت یه بار\n"
    "🏆 <code>/top</code> ← برترین‌ها\n\n"
    f"حداقل شرط {MIN_STAKE} سکه‌ست. ادمین گروه با <code>/gamepanel</code> پنل مدیریت رو باز می‌کنه؛ بازی ۲۱ به‌صورت بلک‌جک کارتی و نوبتی اجرا می‌شه.\n"
    f"هر کاربر با {START_COINS} سکه شروع می‌کنه. سکه‌ها فقط امتیاز بازی‌ان: "
    "خرید و فروش و تبدیل به پول ندارن.\n"
    "<i>برای کار با متن فارسی بدون اسلش، حالت Privacy بات رو توی BotFather خاموش کن "
    "(/setprivacy ← Disable).</i>")


# ---------------- منطق خالص ----------------
def card_value(rank):
    return 11 if rank == "A" else 10 if rank in ("10", "J", "Q", "K") else int(rank)


def hand_total(hand):
    t = sum(card_value(r) for r, _ in hand)
    aces = sum(1 for r, _ in hand if r == "A")
    while t > 21 and aces:
        t -= 10
        aces -= 1
    return t


def fmt_hand(hand):
    return " ".join(f"{r}{s}" for r, s in hand)


def new_deck():
    d = [(r, s) for r in RANKS for s in SUITS]
    RNG.shuffle(d)
    return d


def split_pot(pot, winners):
    """pot رو بین برنده‌ها تقسیم می‌کنه؛ باقی‌مونده به اولی. خروجی: {id: مبلغ}"""
    share, rest = divmod(pot, len(winners))
    res = {w: share for w in winners}
    res[winners[0]] += rest
    return res


# ---------------- کیف پول (sqlite) ----------------
class Wallet:
    def __init__(self, path):
        self.c = sqlite3.connect(path)
        self.c.executescript("""
            CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, coins INTEGER NOT NULL,
                                             daily REAL NOT NULL DEFAULT 0, name TEXT);
            CREATE TABLE IF NOT EXISTS escrow(game TEXT, user INTEGER, amount INTEGER);""")
        # اگه بات وسط بازی ریستارت شده بود، شرط‌ها برمی‌گردن
        for uid, amt in self.c.execute("SELECT user, SUM(amount) FROM escrow GROUP BY user").fetchall():
            self.c.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (amt, uid))
        self.c.execute("DELETE FROM escrow")
        self.c.commit()

    def get(self, uid, name=None):
        r = self.c.execute("SELECT coins FROM users WHERE id=?", (uid,)).fetchone()
        if r is None:
            self.c.execute("INSERT INTO users(id, coins, name) VALUES(?,?,?)", (uid, START_COINS, name))
            self.c.commit()
            return START_COINS
        if name:
            self.c.execute("UPDATE users SET name=? WHERE id=?", (name, uid))
            self.c.commit()
        return r[0]

    def lock(self, gid, ids, stake):
        """شرط همه رو کم می‌کنه. اگه کسی کم داشت: لیست اون‌ها (و هیچ تغییری نمی‌ده)."""
        lacking = [i for i in ids if self.get(i) < stake]
        if lacking:
            return lacking
        for i in ids:
            self.c.execute("UPDATE users SET coins = coins - ? WHERE id = ?", (stake, i))
            self.c.execute("INSERT INTO escrow VALUES(?,?,?)", (gid, i, stake))
        self.c.commit()
        return []

    def pay(self, gid, payouts):
        for uid, amt in payouts.items():
            if amt:
                self.get(uid)
                self.c.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (amt, uid))
        self.c.execute("DELETE FROM escrow WHERE game=?", (gid,))
        self.c.commit()

    def daily(self, uid):
        self.get(uid)
        last = self.c.execute("SELECT daily FROM users WHERE id=?", (uid,)).fetchone()[0]
        wait = 86400 - (time.time() - last)
        if wait > 0:
            return int(wait)
        self.c.execute("UPDATE users SET coins = coins + ?, daily = ? WHERE id = ?",
                       (DAILY_COINS, time.time(), uid))
        self.c.commit()
        return 0

    def top(self, n=10):
        return self.c.execute("SELECT name, coins FROM users ORDER BY coins DESC LIMIT ?", (n,)).fetchall()


def mention(p):
    return f'<a href="tg://user?id={p["id"]}">{html.escape(p["name"])}</a>'


# ---------------- بات ----------------
def setup_games(bot, db_path=None, admin_ids=None):
    wallet = Wallet(db_path or DB_PATH)
    wallet.c.execute("CREATE TABLE IF NOT EXISTS game_chats(chat_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL)")
    wallet.c.commit()
    games, by_chat, test_seen = {}, {}, {}

    def prize_of(g):
        return g["stake"] * (2 if g.get("vs_bot") else g["max"])

    def lobby_text(g):
        n = len(g["players"])
        names = "\n".join(f"• {mention(p)}" for p in g["players"])
        return (f"•—{TITLES[g['type']]}—•\n\n🎮 <b>بازی جدید</b>\n"
                f"👤 سازنده: {mention(g['players'][0])}\n"
                f"👥 تعداد بازیکنان: <b>{g['max']}</b>  ({n}/{g['max']})\n"
                f"💰 مقدار شرط: <b>{g['stake']}</b> سکه\n"
                f"🏆 جایزه برنده: <b>{prize_of(g)}</b> سکه\n\n{names}\n\n"
                f"⏳ در انتظار پیوستن بازیکن {n + 1}… (تا {LOBBY_TTL} ثانیه)")

    def lobby_buttons(g):
        i = g["id"]
        return [[auto_btn("✅ پیوستن", f"g:{i}:join".encode(), "green"),
                 auto_btn("❌ لغو بازی", f"g:{i}:cancel".encode(), "red")],
                [auto_btn("🤖 بازی با ربات", f"g:{i}:bot".encode(), "blue")]]

    def pick_buttons(g):
        i = g["id"]
        return [[auto_btn(str(n), f"g:{i}:n{n}".encode(), "blue") for n in range(2, MAX_PLAYERS + 1)]]

    def result_buttons(prize):
        return [[auto_btn(f"🏆 جایزه برنده: {prize}", f"gb:prize:{prize}".encode(), "green")],
                [auto_btn("💰 موجودی شما", b"gb:bal", "blue")]]

    def play_text(g):
        n = len(g["players"])
        head = f"{TITLES['bj']}\n💰 شرط: {g['stake']} | 🏆 جایزه: {prize_of(g)}\n"
        if g["vs_bot"]:
            p = g["players"][0]
            h = g["hands"][p["id"]]
            up = g["dealer"][0]
            return (head + f"\n🤖 ربات: {up[0]}{up[1]} ؟\n"
                    f"👤 {mention(p)}: {fmt_hand(h)}  = <b>{hand_total(h)}</b>")
        lines = [head]
        for i, p in enumerate(g["players"]):
            st = g["status"][p["id"]]
            mark = ("⏳ نوبت اوست" if i == g["turn"] else "…") if st == "play" else \
                   {"stand": "✋ ایستاد", "bust": "💥 سوخت"}[st]
            lines.append(f"• {mention(p)} — {len(g['hands'][p['id']])} کارت — {mark}")
        lines.append(f"\n⏱ هر نوبت {TURN_TTL} ثانیه. «دستم» کارت‌هات رو فقط به خودت نشون می‌ده.")
        return "\n".join(lines)

    def play_buttons(g):
        i = g["id"]
        return [[auto_btn("🃏 کارت بگیر", f"g:{i}:hit".encode()),
                 auto_btn("✋ بایست", f"g:{i}:stand".encode())],
                [auto_btn("👁 دستم", f"g:{i}:hand".encode())]]

    async def edit(g, text, buttons):
        try:
            await g["msg"].edit(text, buttons=buttons, parse_mode="html")
        except Exception as ex:
            if "not modified" not in str(ex).lower():
                print("games edit error:", ex)

    def close(g):
        games.pop(g["id"], None)
        if by_chat.get(g["chat"]) == g["id"]:
            by_chat.pop(g["chat"], None)
        g["state"] = "done"

    async def finish(g, text, payouts):
        wallet.pay(g["id"], payouts)
        close(g)
        await edit(g, text, result_buttons(max(payouts.values(), default=0)))

    # ---- بلک‌جک ----
    async def bj_start(g):
        g["deck"], g["hands"], g["status"], g["turn"] = new_deck(), {}, {}, 0
        for p in g["players"]:
            g["hands"][p["id"]] = [g["deck"].pop(), g["deck"].pop()]
            g["status"][p["id"]] = "stand" if hand_total(g["hands"][p["id"]]) == 21 else "play"
        if g["vs_bot"]:
            g["dealer"] = [g["deck"].pop(), g["deck"].pop()]
        await bj_advance(g)

    def arm_timer(g):
        g["token"] += 1
        asyncio.create_task(bj_timeout(g, g["token"]))

    async def bj_timeout(g, token):
        await asyncio.sleep(TURN_TTL)
        async with g["lock"]:
            if g["state"] != "play" or g["token"] != token:
                return
            g["status"][g["players"][g["turn"]]["id"]] = "stand"
            g["turn"] += 1
            await bj_advance(g)

    async def bj_advance(g):
        while g["turn"] < len(g["players"]) and g["status"][g["players"][g["turn"]]["id"]] != "play":
            g["turn"] += 1
        if g["turn"] >= len(g["players"]):
            await bj_finish(g)
            return
        arm_timer(g)
        await edit(g, play_text(g), play_buttons(g))

    async def bj_finish(g):
        players, stake = g["players"], g["stake"]
        if g["vs_bot"]:
            p = players[0]
            h, d = g["hands"][p["id"]], g["dealer"]
            pt = hand_total(h)
            if pt <= 21:
                while hand_total(d) < 17:
                    d.append(g["deck"].pop())
            dt = hand_total(d)
            natural = len(h) == 2 and pt == 21 and not (len(d) == 2 and dt == 21)
            if pt > 21 or (dt <= 21 and dt > pt):
                res, pay = "💥 باختی" if pt > 21 else "😔 ربات برد", 0
            elif dt > 21 or pt > dt:
                pay = stake * 5 // 2 if natural else stake * 2
                res = "🎉 بردی" + (" (بلک‌جک ×۲٫۵)" if natural else "")
            else:
                res, pay = "🤝 مساوی؛ شرط برگشت", stake
            text = (f"{TITLES['bj']}\n\n👤 {mention(p)}: {fmt_hand(h)} = <b>{pt}</b>\n"
                    f"🤖 ربات: {fmt_hand(d)} = <b>{dt}</b>\n\n{res}\n"
                    f"💰 {pay - stake:+d} سکه | موجودی: {wallet.get(p['id']) + pay}")
            await finish(g, text, {p["id"]: pay})
            return
        scores = {p["id"]: (-1 if hand_total(g["hands"][p["id"]]) > 21 else hand_total(g["hands"][p["id"]]))
                  for p in players}
        best = max(scores.values())
        pot = stake * len(players)
        if best < 0:
            res, payouts = "💥 همه سوختن؛ شرط‌ها برگشت", {p["id"]: stake for p in players}
        else:
            winners = [i for i, s in scores.items() if s == best]
            payouts = split_pot(pot, winners)
            wn = ", ".join(mention(p) for p in players if p["id"] in winners)
            res = f"🏆 برنده: {wn}\n💰 جایزه: {pot // len(winners)} سکه" if len(winners) == 1 else \
                  f"🤝 مساوی بین: {wn}\n💰 سهم هر نفر: {pot // len(winners)} سکه"
        rows = "\n".join(
            f"• {mention(p)}: {fmt_hand(g['hands'][p['id']])} = <b>{hand_total(g['hands'][p['id']])}</b>"
            f"{' 💥' if scores[p['id']] < 0 else ''}" for p in players)
        await finish(g, f"{TITLES['bj']}\n\n{rows}\n\n{res}", payouts)

    # ---- دوئل تاس ----
    async def dice_run(g):
        stake, players = g["stake"], g["players"]
        contenders = list(players) + ([{"id": 0, "name": "ربات"}] if g["vs_bot"] else [])
        log = []
        winner = None
        for rnd in range(3):
            vals = {}
            for p in contenders:
                await edit(g, f"{TITLES['dice']}\n💰 شرط: {stake}\n\n🎲 نوبت {mention(p)} ...", [])
                m = await bot.send_file(g["chat"], types.InputMediaDice("🎲"))
                vals[p["id"]] = m.media.value
                await asyncio.sleep(3.5)
            log.append(" | ".join(f"{html.escape(p['name'])}: {vals[p['id']]}" for p in contenders))
            best = max(vals.values())
            tied = [p for p in contenders if vals[p["id"]] == best]
            if len(tied) == 1:
                winner = tied[0]
                break
            contenders = tied
        pot = stake * (2 if g["vs_bot"] else len(players))
        if winner is None:
            payouts = {p["id"]: stake for p in players}
            res = "🤝 چند دور مساوی شد؛ شرط‌ها برگشت"
        elif winner["id"] == 0:
            payouts, res = {}, "😔 ربات برد"
        else:
            payouts, res = {winner["id"]: pot}, f"🏆 برنده: {mention(winner)}\n💰 جایزه: {pot} سکه"
        await finish(g, f"{TITLES['dice']}\n\n" + "\n".join(log) + f"\n\n{res}", payouts)

    # ---- شروع بازی ----
    async def begin(g, vs_bot):
        g["vs_bot"] = vs_bot
        if vs_bot and len(g["players"]) > 1:
            g["players"] = g["players"][:1]
        lacking = wallet.lock(g["id"], [p["id"] for p in g["players"]], g["stake"])
        if lacking:
            names = ", ".join(p["name"] for p in g["players"] if p["id"] in lacking)
            return f"موجودی کافی نیست: {names}"
        g["state"] = "play"
        if g["type"] == "bj" and g.get("vs_bot"):
            # درخواست کاربر: بازی با ربات، انتخاب برنده‌ی منصفانه‌ی ۵۰/۵۰ است.
            asyncio.create_task(fair_run_safe(g))
        elif g["type"] == "bj" and not FAIR21:
            await bj_start(g)
        elif g["type"] == "bj":
            asyncio.create_task(fair_run_safe(g))
        else:
            asyncio.create_task(dice_run_safe(g))
        return None

    async def fair_run(g):
        """برنده‌ی شانسی ۵۰/۵۰ (بین بازیکن‌ها، یا بازیکن و ربات)."""
        stake, players = g["stake"], g["players"]
        contenders = list(players) + ([{"id": 0, "name": "ربات"}] if g["vs_bot"] else [])
        await edit(g, f"{TITLES['bj']}\n💰 شرط: {stake}\n\n🎲 در حال انتخاب برنده...", [])
        await asyncio.sleep(2.5)
        winner = RNG.choice(contenders)
        pot = stake * (2 if g["vs_bot"] else len(players))
        losers = ", ".join(mention(p) if p["id"] else "ربات" for p in contenders if p is not winner)
        wname = mention(winner) if winner["id"] else "ربات"
        payouts = {winner["id"]: pot} if winner["id"] else {}
        prize = f"\n💰 جایزه: {pot} سکه" if winner["id"] else ""
        await finish(g, f"{TITLES['bj']}\n\nشرط تمام شد.\n\n🏆 برنده: {wname}\n😔 بازنده: {losers}{prize}", payouts)

    async def fair_run_safe(g):
        try:
            await fair_run(g)
        except Exception as ex:  # شرط‌ها رو برگردون
            print("fair21 error:", ex)
            if g["state"] != "done":
                wallet.pay(g["id"], {p["id"]: g["stake"] for p in g["players"]})
                close(g)

    async def dice_run_safe(g):
        try:
            await dice_run(g)
        except Exception as ex:  # شرط‌ها رو برگردون
            print("dice error:", ex)
            if g["state"] != "done":
                wallet.pay(g["id"], {p["id"]: g["stake"] for p in g["players"]})
                close(g)

    async def lobby_timeout(g):
        await asyncio.sleep(LOBBY_TTL)
        async with g["lock"]:
            if g["state"] in ("pick", "lobby"):
                close(g)
                await edit(g, f"{TITLES[g['type']]}\n\n⌛ کسی شروع نکرد؛ بازی لغو شد.", [])

    # ---- هندلرها ----
    async def create(ev, gtype, stake):
        if stake < MIN_STAKE or stake > MAX_STAKE:
            return await ev.reply(f"⚠️ حداقل شرط {MIN_STAKE} سکه‌ست؛ شرط باید بین {MIN_STAKE} تا {MAX_STAKE} سکه باشه.")
        if ev.chat_id in by_chat:
            return await ev.reply("توی این چت یه بازی فعال داریم؛ اول اون تموم بشه.")
        s = await ev.get_sender()
        me = {"id": ev.sender_id, "name": (getattr(s, "first_name", None) or "کاربر")[:25]}
        if wallet.get(me["id"], me["name"]) < stake:
            return await ev.reply(f"موجودیت کمه ({wallet.get(me['id'])} سکه).")
        g = {"id": uuid.uuid4().hex[:8], "type": gtype, "chat": ev.chat_id, "stake": stake,
             "owner": me["id"], "players": [me], "state": "pick", "lock": asyncio.Lock(),
             "token": 0, "vs_bot": False, "max": MAX_PLAYERS}
        games[g["id"]], by_chat[ev.chat_id] = g, g["id"]
        g["state"] = "pick"
        g["msg"] = await ev.reply(f"{TITLES[gtype]}\n\nتعداد بازیکنان شرط را انتخاب کنید:",
                                  buttons=pick_buttons(g), parse_mode="html")
        asyncio.create_task(lobby_timeout(g))

    def allowed(chat_id):
        # اگه توی همین گروه /gameon یا /gameoff زده شده باشه همون ملاکه؛ وگرنه GAME_CHAT_ID (خالی = همه‌ی گروه‌ها)
        row = wallet.c.execute("SELECT enabled FROM game_chats WHERE chat_id=?", (chat_id,)).fetchone()
        if row is not None:
            return bool(row[0])
        return not GAME_CHATS or chat_id in GAME_CHATS

    async def can_manage(ev):
        if admin_ids and ev.sender_id in admin_ids:
            return True
        try:
            p = await bot.get_permissions(ev.chat_id, ev.sender_id)
            return bool(p and p.is_admin)
        except Exception:
            return False

    def set_enabled(chat_id, on):
        wallet.c.execute("INSERT INTO game_chats(chat_id, enabled) VALUES(?,?) "
                         "ON CONFLICT(chat_id) DO UPDATE SET enabled=excluded.enabled", (chat_id, int(on)))
        wallet.c.commit()

    def panel_text(chat_id):
        row = wallet.c.execute("SELECT enabled FROM game_chats WHERE chat_id=?", (chat_id,)).fetchone()
        active = bool(row[0]) if row else (not GAME_CHATS or chat_id in GAME_CHATS)
        current = "در حال بازی" if chat_id in by_chat else "آماده"
        mode = "بازیکن‌ها: بلک‌جک کارتی | ربات: شانس ۵۰/۵۰"
        return ("🎮 <b>مدیریت بازی‌های گروه</b>\n\n"
                f"وضعیت: {'🟢 روشن' if active else '🔴 خاموش'}\n"
                f"وضعیت میز: {current}\n"
                f"بازی ۲۱: {mode}\n"
                f"شرط مجاز: {MIN_STAKE:,} تا {MAX_STAKE:,} سکه\n\n"
                "سکه‌ها فقط امتیاز بازی‌اند و قابل انتقال یا تبدیل به پول نیستند.")

    def panel_buttons(chat_id):
        row = wallet.c.execute("SELECT enabled FROM game_chats WHERE chat_id=?", (chat_id,)).fetchone()
        active = bool(row[0]) if row else (not GAME_CHATS or chat_id in GAME_CHATS)
        toggle = auto_btn("⏸ خاموش‌کردن بازی‌ها" if active else "✅ روشن‌کردن بازی‌ها",
                          b"gp:off" if active else b"gp:on", "red" if active else "green")
        return [[toggle], [auto_btn("🔄 تازه‌سازی", b"gp:refresh", "blue"),
                           auto_btn("📖 راهنمای بازی", b"gp:help", "blue")]]

    async def chat_cmd(ev, name):
        if name == "gameid":
            return await ev.reply(f"🆔 آیدی این چت: <code>{ev.chat_id}</code>", parse_mode="html")
        if ev.is_private:
            return await ev.reply("این دستور رو داخل گروه بزن.")
        if not await can_manage(ev):
            return await ev.reply("⛔ فقط ادمین گروه می‌تونه این دستور رو بزنه.")
        if name == "gamepanel":
            return await ev.reply(panel_text(ev.chat_id), buttons=panel_buttons(ev.chat_id), parse_mode="html")
        on = name == "gameon"
        set_enabled(ev.chat_id, on)
        if on:
            await ev.reply("✅ بازی‌ها در این گروه فعال شد!\n\n" + HELP, parse_mode="html")
        else:
            await ev.reply("⏸ بازی‌ها در این گروه خاموش شد.")

    async def on_msg(ev):
        raw0 = (ev.raw_text or "").strip()
        # «تست» در هر گروهی که بات توشه جواب می‌ده (مستقل از /gameon و لیست مجاز)
        tw = raw0.translate(FA2EN).replace("‌", " ").strip().lstrip("/").lower()
        if tw in ("تست", "test"):
            now = time.time()
            if now - test_seen.get(ev.chat_id, 0) > 15:   # ضد اسپم/لوپ
                test_seen[ev.chat_id] = now
                await ev.reply("✅ سلف آنلاینه و تو این گروه جواب می‌ده!\n"
                               "🎮 بازی: «بازی 21 50» یا /21 50 (عدد دوم = شرط)\n"
                               "💰 موجودی: /balance | جایزه‌ی روزانه: /daily", parse_mode="html")
            return
        mcmd = re.match(r"^/(gameon|gameoff|gameid|gamepanel)(?:@\w+)?$", raw0, re.I)
        if mcmd:
            return await chat_cmd(ev, mcmd.group(1).lower())
        if not allowed(ev.chat_id):
            return
        raw = (ev.raw_text or "").strip()
        if not raw or len(raw) > 60:
            return
        slash = raw.startswith("/")
        t = raw.lstrip("/").translate(FA2EN).replace("‌", " ")
        t = re.sub(r"@\w+", "", t, count=1).strip()
        m = re.match(r"^(.*?)(?:\s+(\d+))?$", t)
        word, arg = m.group(1).strip().lower(), m.group(2)
        stake = int(arg) if arg else DEFAULT_STAKE
        if slash:
            table = {"21": "bj", "bj": "bj", "dice": "dice", "balance": "bal", "bal": "bal",
                     "daily": "daily", "top": "top", "games": "help", "help": "help"}
        else:
            table = {"بازی 21": "bj", "دوئل تاس": "dice", "موجودی": "bal", "جایزه روزانه": "daily",
                     "برترین ها": "top", "راهنمای بازی": "help"}
        act = table.get(word)
        if not act and arg and f"{word} {arg}" in table:   # «بازی 21» (عدد جزو اسم دستوره)
            act, stake = table[f"{word} {arg}"], DEFAULT_STAKE
        if not act:
            m3 = re.match(r"^(.+?)\s+(\d+)$", t)   # «بازی 21 50» ← بازی 21 با شرط ۵۰
            if m3 and m3.group(1).strip().lower() in table:
                act, stake = table[m3.group(1).strip().lower()], int(m3.group(2))
        if not act:
            return
        if act in ("bj", "dice"):
            await create(ev, act, stake)
        elif act == "bal":
            s = await ev.get_sender()
            name = (getattr(s, "first_name", None) or "کاربر")[:25]
            await ev.reply(f"💰 موجودی {html.escape(name)}: <b>{wallet.get(ev.sender_id, name)}</b> سکه",
                           parse_mode="html")
        elif act == "daily":
            s = await ev.get_sender()
            wallet.get(ev.sender_id, (getattr(s, "first_name", None) or "کاربر")[:25])
            wait = wallet.daily(ev.sender_id)
            if wait:
                await ev.reply(f"⏳ جایزه‌ی بعدی تا {wait // 3600} ساعت و {wait % 3600 // 60} دقیقه‌ی دیگه")
            else:
                await ev.reply(f"🎁 {DAILY_COINS} سکه گرفتی! موجودی: {wallet.get(ev.sender_id)}")
        elif act == "top":
            rows = [f"{i}. {html.escape(n or '؟')} — {c}" for i, (n, c) in enumerate(wallet.top(), 1)]
            await ev.reply("🏆 <b>برترین‌ها</b>\n" + ("\n".join(rows) or "هنوز کسی نیست"), parse_mode="html")
        else:
            await ev.reply(HELP, parse_mode="html")

    async def on_cb(ev):
        if not allowed(ev.chat_id):
            return
        try:
            _, gid, act = ev.data.decode().split(":")
        except ValueError:
            return
        g = games.get(gid)
        if not g:
            await ev.answer("این بازی تموم شده.", alert=True)
            return
        uid = ev.sender_id
        async with g["lock"]:
            if g["state"] == "done":
                await ev.answer("این بازی تموم شده.", alert=True)
                return
            if g["state"] == "pick":
                if uid != g["owner"]:
                    return await ev.answer("فقط سازنده‌ی بازی می‌تونه.", alert=True)
                if act == "cancel":
                    close(g)
                    await ev.answer()
                    return await edit(g, f"{TITLES[g['type']]}\n\n❌ بازی لغو شد.", [])
                if act in ("n2", "n3") and int(act[1:]) <= MAX_PLAYERS:
                    g["max"], g["state"] = int(act[1:]), "lobby"
                    await ev.answer()
                    await edit(g, lobby_text(g), lobby_buttons(g))
                return
            if g["state"] == "lobby":
                if act == "join":
                    if any(p["id"] == uid for p in g["players"]):
                        return await ev.answer("تو توی بازی هستی.", alert=True)
                    if len(g["players"]) >= g["max"]:
                        return await ev.answer("ظرفیت پره.", alert=True)
                    s = await ev.get_sender()
                    name = (getattr(s, "first_name", None) or "کاربر")[:25]
                    if wallet.get(uid, name) < g["stake"]:
                        return await ev.answer(f"موجودیت کمه ({wallet.get(uid)} سکه).", alert=True)
                    g["players"].append({"id": uid, "name": name})
                    await ev.answer("پیوستی ✅")
                    if len(g["players"]) == g["max"]:
                        err = await begin(g, False)
                        if err:
                            await ev.respond(err)
                    else:
                        await edit(g, lobby_text(g), lobby_buttons(g))
                    return
                if uid != g["owner"]:
                    return await ev.answer("فقط سازنده‌ی بازی می‌تونه.", alert=True)
                if act == "cancel":
                    close(g)
                    await ev.answer()
                    await edit(g, f"{TITLES[g['type']]}\n\n❌ بازی لغو شد.", [])
                elif act in ("start", "bot"):
                    if act == "start" and len(g["players"]) < 2:
                        return await ev.answer("حداقل ۲ نفر لازمه؛ یا «با ربات» رو بزن.", alert=True)
                    err = await begin(g, act == "bot")
                    if err:
                        return await ev.answer(err, alert=True)
                    await ev.answer()
                return
            # --- بازی در جریان (بلک‌جک) ---
            if g["type"] != "bj":
                return await ev.answer("بازی در جریانه…")
            ids = [p["id"] for p in g["players"]]
            if uid not in ids:
                return await ev.answer("تو توی این بازی نیستی.", alert=True)
            if act == "hand":
                h = g["hands"][uid]
                return await ev.answer(f"{fmt_hand(h)}  = {hand_total(h)}", alert=True)
            if g["players"][g["turn"]]["id"] != uid:
                return await ev.answer("نوبت تو نیست.", alert=True)
            if act == "hit":
                g["hands"][uid].append(g["deck"].pop())
                h = g["hands"][uid]
                tot = hand_total(h)
                await ev.answer(f"{fmt_hand(h)}  = {tot}", alert=True)
                if tot > 21:
                    g["status"][uid] = "bust"
                elif tot == 21:
                    g["status"][uid] = "stand"
            elif act == "stand":
                g["status"][uid] = "stand"
                await ev.answer()
            else:
                return
            if g["status"][uid] != "play":
                g["turn"] += 1
            await bj_advance(g)

    async def on_panel_cb(ev):
        if ev.is_private or not await can_manage(ev):
            return await ev.answer("⛔ فقط ادمین گروه به این پنل دسترسی دارد.", alert=True)
        try:
            action = ev.data.decode().split(":", 1)[1]
        except (UnicodeDecodeError, IndexError):
            return await ev.answer("دکمه نامعتبر است.", alert=True)
        if action in ("on", "off"):
            set_enabled(ev.chat_id, action == "on")
        await ev.answer("ذخیره شد ✅" if action in ("on", "off") else "")
        if action == "help":
            await ev.respond(HELP, parse_mode="html")
        try:
            await ev.edit(panel_text(ev.chat_id), buttons=panel_buttons(ev.chat_id), parse_mode="html")
        except Exception as ex:
            if "not modified" not in str(ex).lower():
                print("game panel edit error:", ex)

    async def on_result_cb(ev):
        if not allowed(ev.chat_id):
            return
        parts = ev.data.decode().split(":")
        if parts[1] == "bal":
            s = await ev.get_sender()
            name = (getattr(s, "first_name", None) or "کاربر")[:25]
            await ev.answer(f"💰 موجودی تو: {wallet.get(ev.sender_id, name)} سکه", alert=True)
        elif parts[1] == "prize":
            await ev.answer(f"🏆 جایزه‌ی برنده‌ی این بازی: {parts[2]} سکه", alert=True)

    bot.on(events.NewMessage(incoming=True))(on_msg)
    bot.on(events.CallbackQuery(pattern=rb"g:"))(on_cb)
    bot.on(events.CallbackQuery(pattern=rb"gb:"))(on_result_cb)
    bot.on(events.CallbackQuery(pattern=rb"gp:"))(on_panel_cb)
    return {"on_msg": on_msg, "on_cb": on_cb, "on_result_cb": on_result_cb,
            "on_panel_cb": on_panel_cb, "wallet": wallet, "games": games}
