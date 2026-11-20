#!/usr/bin/env bash
# NRT Self installer for Ubuntu/Debian VPS:  bash install.sh
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "📦 Installing dependencies (python, ffmpeg)..."
$SUDO apt-get update -y
$SUDO apt-get install -y python3 python3-venv python3-pip ffmpeg fonts-dejavu wget openssl
python3 -m venv venv
./venv/bin/pip install -q -r requirements.txt

if [ ! -f assets/Vazirmatn-Regular.ttf ]; then
  echo "🔤 Downloading Persian font..."
  wget -q -O assets/Vazirmatn-Regular.ttf \
    "https://github.com/rastikerdar/vazirmatn/raw/master/fonts/ttf/Vazirmatn-Regular.ttf" || \
    echo "⚠️ Font download failed; screenshots will use the default font"
fi

ask_required() {  # $1=variable name  $2=prompt text
  local v=""
  while [ -z "$v" ]; do read -rp "$2" v; done
  printf -v "$1" '%s' "$v"
}
ask_optional() { local v=""; read -rp "$2" v; printf -v "$1" '%s' "$v"; }

if [ "$1" = "--reconfigure" ] && [ -f .env ]; then   # شروع دوباره: .env قدیمی بکاپ میشه و سوال‌ها دوباره پرسیده میشن
  cp .env ".env.bak.$(date +%Y%m%d-%H%M%S)" && rm -f .env && echo "💾 .env قدیمی بکاپ شد"
fi
valid_port() { [[ "$1" =~ ^[0-9]+$ ]] && [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }
envget() { grep -m1 "^$1=" .env 2>/dev/null | cut -d= -f2-; }
public_ip() { wget -qO- -T 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}'; }
open_port() {  # باز کردن پورت تو فایروال سرور (ufw) اگه فعال باشه
  if command -v ufw >/dev/null 2>&1 && $SUDO ufw status 2>/dev/null | grep -q "Status: active"; then
    $SUDO ufw allow "$1"/tcp >/dev/null && echo "🔓 ufw: port $1 opened"
  fi
}

MODE=1
WEB_MODE=1
if [ ! -f .env ]; then
  umask 077
  echo
  echo "Which mode do you want?"
  echo "  1) Personal self (only you) - login with your phone number, no bots needed"
  echo "  2) Multi-user hub + web admin panel (sell the self / multiple users)"
  read -rp "Choose (1 or 2) [1]: " MODE; MODE="${MODE:-1}"
  echo
  ask_required API_ID "API_ID (from my.telegram.org): "
  ask_required API_HASH "API_HASH (from my.telegram.org): "
  ask_required OWNER_ID "Your numeric Telegram ID (from @userinfobot): "
  ask_optional GAME_CHAT_ID "Game group numeric ID (optional; empty = all groups; or just send /gameon in your group): "
  read -rsp "ANTHROPIC_API_KEY (optional, for the AI command; input hidden): " ANTHROPIC_API_KEY; echo
  {
    echo "API_ID=$API_ID"
    echo "API_HASH=$API_HASH"
    echo "OWNER_ID=$OWNER_ID"
    echo "GAME_CHAT_ID=$GAME_CHAT_ID"
    echo "BANNER_PATH=assets/banner.jpg"
    echo "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY"
  } > .env
  if [ "$MODE" = "2" ]; then
    echo "--- Hub bots (from @BotFather) ---"
    ask_required HUB_BOT_TOKEN "Main hub bot token (from @BotFather): "
    ask_optional HUB_HELPER_BOT_TOKEN "Helper/game bot token (optional; run /setinline in @BotFather after creating it): "
    ask_optional ADMIN_IDS "ADMIN_IDS (admin numeric IDs, comma-separated; empty = only you): "
    ADMIN_IDS="${ADMIN_IDS:-$OWNER_ID}"
    read -rsp "Web panel password (empty = auto-generate; input hidden): " WEB_PASSWORD; echo
    GEN_PASS=""
    if [ -z "$WEB_PASSWORD" ]; then
      WEB_PASSWORD="$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)"; GEN_PASS=1
    fi
    echo
    echo "Web panel access:"
    echo "  1) Direct:  http://SERVER_IP:PORT   (you choose the port, like x-ui / Sanaei)"
    echo "  2) Domain with HTTPS (Caddy, automatic certificate)"
    echo "  3) Local only (SSH tunnel)"
    read -rp "Choose (1-3) [1]: " WEB_MODE; WEB_MODE="${WEB_MODE:-1}"
    DEF_PORT=8080; [ "$WEB_MODE" = "1" ] && DEF_PORT="$(shuf -i 10000-60000 -n 1)"
    WEB_PORT=""
    while :; do
      read -rp "Web panel port (1-65535; empty = $DEF_PORT): " WEB_PORT; WEB_PORT="${WEB_PORT:-$DEF_PORT}"
      valid_port "$WEB_PORT" && break
      echo "❌ invalid port"
    done
    WEB_DOMAIN=""
    if [ "$WEB_MODE" = "2" ]; then
      ask_required WEB_DOMAIN "Domain (e.g. panel.example.com; its A record must point to this server): "
    fi
    WEB_HOST=127.0.0.1; [ "$WEB_MODE" = "1" ] && WEB_HOST=0.0.0.0
    {
      echo "HUB_BOT_TOKEN=$HUB_BOT_TOKEN"
      echo "HUB_HELPER_BOT_TOKEN=$HUB_HELPER_BOT_TOKEN"
      echo "ADMIN_IDS=$ADMIN_IDS"
      echo "WEB_PASSWORD=$WEB_PASSWORD"
      echo "WEB_HOST=$WEB_HOST"
      echo "WEB_PORT=$WEB_PORT"
      echo "WEB_DOMAIN=$WEB_DOMAIN"
      if [ "$WEB_MODE" = "2" ]; then echo "WEB_SECURE=1"; else echo "WEB_SECURE=0"; fi
    } >> .env
  else
    echo "--- Bots (OPTIONAL) ---"
    echo "Press Enter on both to skip: the self will log in with your PHONE NUMBER in this terminal."
    ask_optional MANAGER_BOT_TOKEN "Manager bot token (optional, from @BotFather): "
    ask_optional HELPER_BOT_TOKEN "Helper/panel bot token (optional; run /setinline in @BotFather after creating it): "
    {
      echo "MANAGER_BOT_TOKEN=$MANAGER_BOT_TOKEN"
      echo "HELPER_BOT_TOKEN=$HELPER_BOT_TOKEN"
    } >> .env
  fi
  chmod 600 .env
else
  grep -q '^HUB_BOT_TOKEN=.' .env && MODE=2
  echo "ℹ️ .env already exists; skipping questions (mode: $MODE)"
  WEB_PORT="$(envget WEB_PORT)"; WEB_DOMAIN="$(envget WEB_DOMAIN)"
  if [ "$(envget WEB_HOST)" = "0.0.0.0" ]; then WEB_MODE=1; elif [ -n "$WEB_DOMAIN" ]; then WEB_MODE=2; else WEB_MODE=3; fi
fi

if [ "$MODE" != "2" ] && [ -z "$(envget MANAGER_BOT_TOKEN)" ] && [ ! -f clock_self.session ]; then
  echo
  echo "📱 Telegram login"
  echo "   1) Enter your phone number with country code (e.g. +989121234567)"
  echo "   2) Enter the code Telegram sends you (check your Telegram app)"
  echo "   3) Enter your two-step password if you have one"
  ./venv/bin/python self_bot.py --login || { echo "❌ Login failed. Try again with:  ./venv/bin/python self_bot.py --login  and then  systemctl restart telegram-self"; exit 1; }
fi

if [ "$MODE" = "2" ]; then ENTRY="hub.py"; else ENTRY="self_bot.py"; fi

echo "⚙️ Creating systemd service ($ENTRY)..."
$SUDO tee /etc/systemd/system/telegram-self.service >/dev/null <<UNIT
[Unit]
Description=NRT Self
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$DIR
ExecStart=$DIR/venv/bin/python $DIR/$ENTRY
Restart=always
RestartSec=5
UMask=0077

[Install]
WantedBy=multi-user.target
UNIT
$SUDO systemctl daemon-reload
$SUDO systemctl enable telegram-self
$SUDO systemctl restart telegram-self

WEB_PORT="${WEB_PORT:-8080}"
if [ "$MODE" = "2" ] && [ "$WEB_MODE" = "1" ]; then open_port "$WEB_PORT"; fi
if [ "$MODE" = "2" ] && [ "$WEB_MODE" = "2" ] && [ -n "${WEB_DOMAIN:-}" ]; then
  open_port 80; open_port 443
  echo "🔒 Setting up HTTPS with Caddy for $WEB_DOMAIN (the domain must point to this server's IP)..."
  if $SUDO apt-get install -y caddy; then
    printf '# nrt-self-panel\n%s {\n    reverse_proxy 127.0.0.1:%s\n}\n' "$WEB_DOMAIN" "$WEB_PORT" | $SUDO tee /etc/caddy/Caddyfile >/dev/null
    $SUDO systemctl restart caddy
  else
    echo "⚠️ Caddy install failed; set up SSH tunnel or nginx manually."
    WEB_DOMAIN=""
  fi
fi

echo
echo "✅ Done."
if [ "$MODE" = "2" ]; then
  echo "• Send /start to the hub bot (admins: /admin)."
  if [ "$WEB_MODE" = "2" ] && [ -n "${WEB_DOMAIN:-}" ]; then
    echo "• Web panel:  https://$WEB_DOMAIN"
  elif [ "$WEB_MODE" = "1" ]; then
    echo "• Web panel:  http://$(public_ip):$WEB_PORT"
    echo "  ⚠️ Open TCP port $WEB_PORT in your cloud firewall too (AWS: Security Group > Inbound rules)."
    echo "  ⚠️ This is plain HTTP; for HTTPS use a domain:  bash setpanel.sh"
  else
    echo "• Web panel (SSH tunnel):  ssh -L $WEB_PORT:127.0.0.1:$WEB_PORT user@SERVER_IP  ->  http://127.0.0.1:$WEB_PORT"
  fi
  [ -n "${GEN_PASS:-}" ] && echo "• Web panel password: $WEB_PASSWORD   (also saved in .env)"
else
  if [ -n "$(envget MANAGER_BOT_TOKEN)" ]; then
    echo "• Send /start to the manager bot and tap \"Activate self\"; then type .panel in any chat."
  else
    echo "• Logged in with your phone. In any chat (e.g. Saved Messages) send  .پنل  (first time it creates the panel bot automatically, ~30s) or  .راهنما"
  fi
fi
echo "• Change panel port/domain/password later:  bash setpanel.sh"
echo "• Status: systemctl status telegram-self"
echo "• Logs:   journalctl -u telegram-self -f"
