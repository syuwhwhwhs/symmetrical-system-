#!/usr/bin/env bash
# آپدیت امن: کدهای قدیمی پاک می‌شن و کد جدید جاش میاد؛ .env، نشست‌ها، کانفیگ‌ها و دیتابیس‌ها دست‌نخورده می‌مونن.
#
#   bash update.sh                      ← از گیت‌هاب (اگه پوشه با git clone ساخته شده)
#   bash update.sh /مسیر/telegram-self-v9.zip   ← از فایل zip
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

# ۱) بکاپ از داده‌ها (قبل از هر کاری)
mkdir -p ../self_backups
BK="../self_backups/backup-$(date +%Y%m%d-%H%M%S).tar.gz"
tar -czf "$BK" --ignore-failed-read .env *.session self_config.json hub_sessions hub_configs hub.db games.db hub_games.db banners 2>/dev/null || true
echo "💾 بکاپ داده‌ها: $BK"

if [ -n "$1" ]; then
  # ۲) از zip: کدهای قدیمی (فایل‌های py/sh/md و assets) پاک می‌شن، داده‌ها نه
  [ -f "$1" ] || { echo "❌ فایل پیدا نشد: $1"; exit 1; }
  TMP="$(mktemp -d)"
  unzip -q "$1" -d "$TMP"
  SRC="$(find "$TMP" -maxdepth 2 -name self_bot.py -printf '%h\n' | head -1)"
  [ -n "$SRC" ] || { echo "❌ این zip شبیه پروژه نیست"; exit 1; }
  rm -f ./*.py ./*.sh ./*.md ./*.txt ./.env.example
  rm -rf ./assets
  cp -a "$SRC"/. .
  rm -rf "$TMP"
elif [ -d .git ]; then
  # ۲) از گیت‌هاب: هر فایل قدیمی که توی ریپو نیست پاک می‌شه، فایل‌های ignore شده (داده‌ها) می‌مونن
  git fetch --all -q
  BR="$(git rev-parse --abbrev-ref HEAD)"
  git reset --hard "origin/$BR"
else
  echo "❌ نه git هست نه zip دادی. مثال: bash update.sh telegram-self-v9.zip"; exit 1
fi

# ۳) کتابخونه‌ها و ریستارت
[ -d venv ] || python3 -m venv venv
./venv/bin/pip install -q -U -r requirements.txt
if systemctl list-unit-files 2>/dev/null | grep -q '^telegram-self.service'; then
  $SUDO systemctl restart telegram-self
  echo "🔁 سرویس ریستارت شد: systemctl status telegram-self"
else
  echo "ℹ️ سرویس systemd پیدا نشد؛ خودت اجرا کن: ./venv/bin/python hub.py  (یا self_bot.py)"
fi
echo "✅ آپدیت تموم شد."
