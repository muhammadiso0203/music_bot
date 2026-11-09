@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist venv (
    echo [1/3] Virtual muhit yaratilmoqda...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo [2/3] Kutubxonalar o'rnatilmoqda / yangilanmoqda...
python -m pip install -q --upgrade pip
pip install -q -r requirements.txt
pip install -q -U yt-dlp

echo [3/3] Bot ishga tushmoqda...
python bot.py
pause
