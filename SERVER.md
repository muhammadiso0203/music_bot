# 🖥 Botni serverga qo'yish (GitHub + MobaXterm)

MobaXterm — serverga ulanish dasturi. Unda serverga SSH orqali kirasiz (chap tomonda fayllar paneli ham bor).

## 1. Serverga kiring

MobaXterm → **Session → SSH** → *Remote host*: server IP, *Username*: `root` → **OK** → parolni yozing.

## 2. Botni GitHub'dan yuklab, o'rnating

Serverda ketma-ket yozing (`USERNAME/REPO` o'rniga o'z repongiz):

```
apt update && apt install -y git
git clone https://github.com/USERNAME/REPO.git musicbot
cd musicbot
cp .env.example .env
nano .env
```

`nano` ochilganda `BOT_TOKEN=` va `ADMIN_ID=` ni to'ldiring.
Saqlash: **Ctrl+O**, **Enter**. Chiqish: **Ctrl+X**.

Keyin:

```
bash install.sh
```

Oxirida `✅ Tayyor!` chiqsa — bot serverda ishlayapti. Server o'chib-yonsa ham o'zi ishga tushadi.

❗ Kompyuterdagi botni to'xtating — bitta token bilan ikkita bot ishlay olmaydi.

## 3. Eski ma'lumotlarni ko'chirish (ixtiyoriy)

Kesh, foydalanuvchilar ro'yxati va emojilar saqlanib qolishi uchun kompyuterdagi
`cache.db` va `emojis.json` fayllarini MobaXterm'ning chap panelidagi `/root/musicbot/`
papkasiga sichqoncha bilan tortib tashlang, so'ng:

```
systemctl restart musicbot
```

Instagram uchun cookie fayli bo'lsa — `instagram_cookies.txt` ni ham shu yerga tashlang.

## Foydali buyruqlar

| Buyruq | Nima qiladi |
|---|---|
| `journalctl -u musicbot -f` | Loglarni jonli ko'rish (chiqish: Ctrl+C) |
| `systemctl restart musicbot` | Qayta ishga tushirish |
| `systemctl stop musicbot` | To'xtatish |
| `systemctl status musicbot` | Holatini ko'rish |
| `nano /root/musicbot/.env` | Sozlamalarni o'zgartirish (keyin restart) |

## Botni yangilash

GitHub'dagi kod yangilangandan keyin serverda:

```
cd /root/musicbot && git pull && systemctl restart musicbot
```

## Eslatmalar

- `.env` (token), `cache.db`, `instagram_cookies.txt` GitHub'ga **chiqmaydi** (`.gitignore`).
- `yt-dlp` har kuni avtomatik yangilanadi; `ffmpeg` `install.sh` orqali o'rnatiladi.
