#!/usr/bin/env bash
# تنظیم پنل وب (مثل پنل سنایی): پورت دلخواه، دسترسی با IP:پورت، دامنه با HTTPS، رمز.
#   bash setpanel.sh
cd "$(dirname "$0")"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
[ -f .env ] || { echo "❌ .env پیدا نشد؛ اول bash install.sh رو بزن."; exit 1; }

envget() { grep -m1 "^$1=" .env | cut -d= -f2-; }
envset() {  # envset KEY VALUE  (امن برای هر کاراکتری)
  python3 - "$1" "$2" <<'PY'
import sys
k, v = sys.argv[1], sys.argv[2]
lines = open(".env", encoding="utf-8").read().split("\n")
out, done = [], False
for ln in lines:
    if ln.startswith(k + "="):
        if not done:
            out.append(f"{k}={v}"); done = True
    else:
        out.append(ln)
if not done:
    while out and out[-1] == "":
        out.pop()
    out.append(f"{k}={v}")
    out.append("")
open(".env", "w", encoding="utf-8").write("\n".join(out))
PY
  chmod 600 .env
}
valid_port() { [[ "$1" =~ ^[0-9]+$ ]] && [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }
public_ip() { wget -qO- -T 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}'; }
open_port() {
  if command -v ufw >/dev/null 2>&1 && $SUDO ufw status 2>/dev/null | grep -q "Status: active"; then
    $SUDO ufw allow "$1"/tcp >/dev/null && echo "🔓 ufw: پورت $1 باز شد"
  fi
}
port_busy() { ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$1$"; }

ask_port() {  # خروجی تو NEWPORT
  local cur; cur="$(envget WEB_PORT)"; cur="${cur:-8080}"
  local def="${1:-$cur}"
  while :; do
    read -rp "پورت پنل (1-65535، خالی = $def): " NEWPORT; NEWPORT="${NEWPORT:-$def}"
    if ! valid_port "$NEWPORT"; then echo "❌ پورت نامعتبره"; continue; fi
    if [ "$NEWPORT" != "$cur" ] && port_busy "$NEWPORT"; then echo "❌ این پورت توسط برنامه‌ی دیگه‌ای استفاده میشه"; continue; fi
    break
  done
}

stop_our_caddy() {
  if [ -f /etc/caddy/Caddyfile ] && grep -q "nrt-self-panel" /etc/caddy/Caddyfile; then
    $SUDO systemctl stop caddy 2>/dev/null || true
    $SUDO systemctl disable caddy 2>/dev/null || true
  fi
}

restart_and_show() {
  $SUDO systemctl restart telegram-self 2>/dev/null && echo "🔁 سرویس ریستارت شد" || echo "ℹ️ سرویس systemd پیدا نشد؛ خودت ریستارت کن"
  show_info
}

show_info() {
  local host port dom sec
  host="$(envget WEB_HOST)"; port="$(envget WEB_PORT)"; dom="$(envget WEB_DOMAIN)"; sec="$(envget WEB_SECURE)"
  echo; echo "──────── پنل وب ────────"
  if [ "$sec" = "1" ] && [ -n "$dom" ]; then
    echo "آدرس:  https://$dom   (پورت داخلی: $port)"
  elif [ "$host" = "0.0.0.0" ]; then
    echo "آدرس:  http://$(public_ip):$port"
    echo "⚠️ پورت $port رو تو فایروال کلاد هم باز کن (AWS: Security Group > Inbound rules > Custom TCP)."
    echo "⚠️ HTTP ساده‌ست؛ برای HTTPS گزینه‌ی دامنه رو بزن."
  else
    echo "فقط لوکال: ssh -L $port:127.0.0.1:$port user@SERVER_IP  ->  http://127.0.0.1:$port"
  fi
  [ -n "$(envget WEB_PASSWORD)" ] && echo "رمز: $(envget WEB_PASSWORD)" || echo "⚠️ رمز تنظیم نشده؛ پنل وب خاموشه (گزینه‌ی ۵)"
  echo "────────────────────────"
}

while :; do
  echo
  echo "=== تنظیم پنل وب ==="
  echo " 1) تغییر پورت"
  echo " 2) دسترسی مستقیم با http://IP:پورت (پورت دلخواه)"
  echo " 3) دامنه با HTTPS (Caddy)"
  echo " 4) فقط لوکال (SSH tunnel)"
  echo " 5) تغییر رمز پنل"
  echo " 6) نمایش آدرس و رمز"
  echo " 0) خروج"
  read -rp "انتخاب: " C
  case "$C" in
    1)
      ask_port; envset WEB_PORT "$NEWPORT"
      if [ "$(envget WEB_HOST)" = "0.0.0.0" ]; then open_port "$NEWPORT"; fi
      if [ -f /etc/caddy/Caddyfile ] && grep -q "nrt-self-panel" /etc/caddy/Caddyfile; then
        printf '# nrt-self-panel\n%s {\n    reverse_proxy 127.0.0.1:%s\n}\n' "$(envget WEB_DOMAIN)" "$NEWPORT" | $SUDO tee /etc/caddy/Caddyfile >/dev/null
        $SUDO systemctl restart caddy
      fi
      restart_and_show ;;
    2)
      ask_port "$(shuf -i 10000-60000 -n 1)"
      stop_our_caddy
      envset WEB_HOST 0.0.0.0; envset WEB_PORT "$NEWPORT"; envset WEB_SECURE 0; envset WEB_DOMAIN ""
      open_port "$NEWPORT"; restart_and_show ;;
    3)
      read -rp "دامنه (مثلاً panel.example.com؛ رکورد A باید به IP این سرور بخوره): " DOM
      [ -n "$DOM" ] || { echo "❌ دامنه خالیه"; continue; }
      ask_port 8080
      if ! command -v caddy >/dev/null 2>&1; then $SUDO apt-get install -y caddy || { echo "❌ نصب Caddy ناموفق بود"; continue; }; fi
      printf '# nrt-self-panel\n%s {\n    reverse_proxy 127.0.0.1:%s\n}\n' "$DOM" "$NEWPORT" | $SUDO tee /etc/caddy/Caddyfile >/dev/null
      $SUDO systemctl enable caddy >/dev/null 2>&1; $SUDO systemctl restart caddy
      envset WEB_HOST 127.0.0.1; envset WEB_PORT "$NEWPORT"; envset WEB_SECURE 1; envset WEB_DOMAIN "$DOM"
      open_port 80; open_port 443; restart_and_show ;;
    4)
      ask_port 8080
      stop_our_caddy
      envset WEB_HOST 127.0.0.1; envset WEB_PORT "$NEWPORT"; envset WEB_SECURE 0; envset WEB_DOMAIN ""
      restart_and_show ;;
    5)
      read -rsp "رمز جدید (خالی = خودکار ساخته میشه): " P; echo
      [ -n "$P" ] || P="$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)"
      envset WEB_PASSWORD "$P"; restart_and_show ;;
    6) show_info ;;
    0) exit 0 ;;
    *) echo "گزینه‌ی نامعتبر" ;;
  esac
done
