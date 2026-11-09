#!/usr/bin/env bash
# ============================================================
#  Musiqa bot — serverga o'rnatish (Ubuntu 22.04 / 24.04)
#  Ishga tushirish:  bash install.sh
# ============================================================
set -e

BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_USER="$(whoami)"
SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "==> [1/4] Kerakli dasturlar o'rnatilmoqda (python, ffmpeg)..."
$SUDO apt-get update -y
$SUDO apt-get install -y python3 python3-venv python3-pip ffmpeg

echo "==> [2/4] Python kutubxonalari o'rnatilmoqda..."
cd "$BOT_DIR"
python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r requirements.txt
./venv/bin/pip install -q -U yt-dlp

if [ ! -f .env ]; then
  cp .env.example .env
fi
if grep -q "BU_YERGA_TOKEN" .env; then
  echo ""
  echo "❗ .env faylida BOT_TOKEN yozilmagan."
  echo "   Tokenni yozing:  nano $BOT_DIR/.env"
  echo "   (saqlash: Ctrl+O, Enter; chiqish: Ctrl+X), keyin qayta:  bash install.sh"
  exit 1
fi

echo "==> [3/4] Avtomatik ishga tushish (systemd) sozlanmoqda..."
$SUDO tee /etc/systemd/system/musicbot.service >/dev/null <<EOF
[Unit]
Description=Musiqa Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
WorkingDirectory=$BOT_DIR
Environment=PYTHONUNBUFFERED=1
# har ishga tushganda yt-dlp yangilanadi (YouTube o'zgarsa ham ishlayveradi)
ExecStartPre=-$BOT_DIR/venv/bin/pip install -q -U yt-dlp
ExecStart=$BOT_DIR/venv/bin/python bot.py
Restart=always
RestartSec=5
# kuniga 1 marta o'zi qayta ishga tushadi -> yt-dlp har kuni yangilanadi
RuntimeMaxSec=86400

[Install]
WantedBy=multi-user.target
EOF

$SUDO systemctl daemon-reload
$SUDO systemctl enable musicbot >/dev/null
$SUDO systemctl restart musicbot

echo "==> [4/4] Tekshirilmoqda..."
sleep 8
$SUDO systemctl --no-pager --lines=15 status musicbot || true

echo ""
echo "✅ Tayyor! Bot ishlayapti va server o'chib-yonsa ham o'zi ishga tushadi."
echo ""
echo "Foydali buyruqlar:"
echo "  sudo journalctl -u musicbot -f     # loglarni jonli ko'rish (chiqish: Ctrl+C)"
echo "  sudo systemctl restart musicbot    # qayta ishga tushirish"
echo "  sudo systemctl stop musicbot       # to'xtatish"
echo "  sudo systemctl status musicbot     # holatini ko'rish"
