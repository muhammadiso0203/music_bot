"""
🎵 Musiqa topuvchi Telegram bot (VK music bot uslubida)
Manba: YouTube Music

Foydalanuvchi qo'shiqchi ismi yoki qo'shiq nomini yozadi ->
bot 10 talik qo'shiqlar ro'yxatini tugmalar ko'rinishida chiqaradi.
⬅️ ➡️ tugmalari bilan keyingi / oldingi 10 talikka o'tiladi.
Qo'shiq tugmasi bosilsa -> qo'shiqning o'zi (audio fayl) yuboriladi.
Bir marta yuborilgan qo'shiq keshlanadi - keyingi safar bir zumda keladi.
Instagram: reels / post havolasi yuborilsa -> video + "Musiqasini yuklash" tugmasi.
Admin panel: /admin (statistika, xabar yuborish, majburiy obuna, bloklash).
"""

import asyncio
import csv
import html
import io
import json
import logging
import os
import re
import shutil
import sqlite3
import time
from collections import OrderedDict
from itertools import count
from pathlib import Path

import yt_dlp
from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)
from dotenv import load_dotenv
from ytmusicapi import YTMusic

# ---------------------------------------------------------------- sozlamalar
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
MAX_DURATION = int(os.getenv("MAX_DURATION", "900"))  # soniya (15 daqiqa)
MAX_FILESIZE = 49 * 1024 * 1024                        # Telegram bot limiti ~50 MB
TOTAL_RESULTS = 50                                     # jami qo'shiqlar (5 sahifa)
PAGE_SIZE = 10                                         # bir sahifada 10 ta
PARALLEL_DOWNLOADS = 5
MAX_SEARCHES_IN_MEMORY = 2000

BASE_DIR = Path(__file__).resolve().parent
DL_DIR = BASE_DIR / "downloads"
DL_DIR.mkdir(exist_ok=True)
DB_PATH = BASE_DIR / "cache.db"
# ffmpeg: avval bot papkasidagi ffmpeg/ (Windows), bo'lmasa tizimdagi (server: apt install ffmpeg)
_LOCAL_FF = BASE_DIR / "ffmpeg" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
FFMPEG_DIR = str(_LOCAL_FF.parent) if _LOCAL_FF.exists() else None
_FFMPEG_FOUND = FFMPEG_DIR is not None or shutil.which("ffmpeg") is not None
# AUDIO_FORMAT=m4a -> eng tez (qayta kodlanmaydi). AUDIO_FORMAT=mp3 -> ffmpeg bilan mp3 (sekinroq)
AUDIO_FORMAT = os.getenv("AUDIO_FORMAT", "m4a").strip().lower()
HAS_FFMPEG = AUDIO_FORMAT == "mp3" and _FFMPEG_FOUND
PREFETCH_COUNT = int(os.getenv("PREFETCH_COUNT", "3"))  # ro'yxat chiqqanda oldindan yuklanadigan qo'shiqlar
PREFETCH_TTL = 15 * 60                                  # ishlatilmagan oldindan yuklangan fayl 15 daqiqada o'chadi
# ADMIN_ID: bir nechta admin bo'lsa vergul bilan: 111,222
ADMINS = {int(x) for x in re.findall(r"\d+", os.getenv("ADMIN_ID", ""))}
PROXY = os.getenv("PROXY", "").strip()                 # masalan: socks5://127.0.0.1:1080


class QuietLogger:
    """yt-dlp ning qizil ERROR yozuvlarini konsolga chiqarmaydi (biz o'zimiz log qilamiz)."""
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def ydl_opts(**extra) -> dict:
    opts = {"quiet": True, "no_warnings": True, "logger": QuietLogger()}
    if PROXY:
        opts["proxy"] = PROXY
    if FFMPEG_DIR:
        opts["ffmpeg_location"] = FFMPEG_DIR
    opts.update(extra)
    return opts

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("musicbot")

# ---------------------------------------------------------------- premium emoji
# emojis.json: {"nom": "custom_emoji_id"}. ID bo'sh bo'lsa oddiy emoji ishlatiladi.
# Admin panel -> 🎨 Emojilar orqali botning o'zidan o'zgartirish mumkin.
EMOJI_FILE = BASE_DIR / "emojis.json"
# nom: (oddiy zaxira emoji, qayerda ishlatiladi)
EMOJI_INFO = {
    # --- foydalanuvchi qismi
    "search": ("🔍", "Qidiruv, ro'yxat sarlavhasi"),
    "headphones": ("🎧", "Qo'shiq tagidagi yozuv"),
    "music": ("🎵", "/start, qo'shiqlar"),
    "loading": ("⏳", "Yuklanmoqda..."),
    "error": ("❌", "Xato xabarlari"),
    "notfound": ("😕", "Hech narsa topilmadi"),
    "write": ("✍️", "Qo'shiq nomini yozing"),
    "help": ("📖", "/help"),
    "ok": ("✅", "Tasdiq, muvaffaqiyat"),
    "hello": ("👋", "Salomlashish"),
    "prev": ("⬅️", "«Oldingi» tugmasi"),
    "next": ("➡️", "«Keyingi» tugmasi"),
    "close": ("❌", "«Yopish» tugmasi"),
    "lock": ("🔒", "Majburiy obuna xabari"),
    "join": ("➕", "Kanalga obuna tugmasi"),
    "check": ("✅", "«Tekshirish» tugmasi"),
    # --- admin panel
    "admin": ("🛠", "Admin panel sarlavhasi"),
    "stats": ("📊", "Statistika"),
    "users": ("👥", "Foydalanuvchilar"),
    "broadcast": ("📢", "Xabar yuborish"),
    "channel": ("📣", "Majburiy obuna bo'limi"),
    "ban": ("🚫", "Bloklash"),
    "unban": ("🔓", "Blokdan chiqarish"),
    "top": ("🔥", "Top qidiruvlar"),
    "export": ("📥", "Foydalanuvchilar fayli"),
    "emoji": ("🎨", "Emojilar bo'limi"),
    "back": ("🔙", "«Orqaga» tugmasi"),
    "refresh": ("🔄", "«Yangilash» tugmasi"),
    "send": ("📤", "«Yuborish» tugmasi"),
    "cancel": ("✖️", "«Bekor qilish» tugmasi"),
    "add": ("➕", "«Qo'shish» tugmasi"),
    "delete": ("🗑", "«O'chirish» tugmasi"),
    "time": ("🕒", "Vaqt"),
    "warning": ("⚠️", "Ogohlantirish"),
    "chart": ("📈", "Faollik"),
    "video": ("🎬", "Instagram video"),
}
DEFAULT_EMOJI = {k: v[0] for k, v in EMOJI_INFO.items()}
EMOJI_IDS: dict[str, str] = {}
_emoji_mtime = 0.0


def _emoji_file_changed() -> bool:
    try:
        return EMOJI_FILE.stat().st_mtime != _emoji_mtime
    except FileNotFoundError:
        return False


def load_emojis() -> None:
    """emojis.json ni o'qiydi; yangi nomlar bo'lsa faylga qo'shib qo'yadi."""
    global EMOJI_IDS, _emoji_mtime
    data = {}
    if EMOJI_FILE.exists():
        try:
            data = json.loads(EMOJI_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("emojis.json o'qilmadi: %s", e)
    EMOJI_IDS = {k: str(v).strip() for k, v in data.items() if str(v).strip().isdigit()}
    try:
        _emoji_mtime = EMOJI_FILE.stat().st_mtime
    except FileNotFoundError:
        _emoji_mtime = 0.0
    if any(k not in data for k in EMOJI_INFO):
        save_emojis()


def save_emojis() -> None:
    global _emoji_mtime
    full = {k: EMOJI_IDS.get(k, "") for k in EMOJI_INFO}
    full.update({k: v for k, v in EMOJI_IDS.items() if k not in full})
    EMOJI_FILE.write_text(json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")
    _emoji_mtime = EMOJI_FILE.stat().st_mtime


def set_emoji(name: str, emoji_id: str | None) -> None:
    """Bitta emojini o'zgartiradi (avval fayldagi qo'lda qilingan o'zgarishlarni o'qib oladi)."""
    if _emoji_file_changed():
        load_emojis()
    if emoji_id:
        EMOJI_IDS[name] = emoji_id
    else:
        EMOJI_IDS.pop(name, None)
    save_emojis()
    log.info("Emoji o'zgartirildi: %s = %s", name, emoji_id or "(oddiy)")


async def emoji_watcher():
    """emojis.json qo'lda tahrirlansa — 5 soniya ichida o'zi qayta o'qiladi (/emoji_reload shart emas)."""
    while True:
        await asyncio.sleep(5)
        if _emoji_file_changed():
            load_emojis()
            log.info("emojis.json qayta o'qildi: %d ta premium emoji", len(EMOJI_IDS))


def E(name: str) -> str:
    """Xabar matni uchun: premium emoji (ID bo'lsa) yoki oddiy emoji."""
    fallback = DEFAULT_EMOJI.get(name, "")
    eid = EMOJI_IDS.get(name)
    return f'<tg-emoji emoji-id="{eid}">{fallback}</tg-emoji>' if eid else fallback


def btn(name: str, text: str, cb: str | None = None, style: str | None = None,
        url: str | None = None) -> InlineKeyboardButton:
    """Rangli tugma: premium emoji ID bo'lsa animatsiyali ikonka, bo'lmasa oddiy emoji.
    style: "primary" (ko'k), "success" (yashil), "danger" (qizil), None (oddiy)."""
    kw = {"url": url} if url else {"callback_data": cb}
    eid = EMOJI_IDS.get(name)
    if eid:
        return InlineKeyboardButton(text=text, icon_custom_emoji_id=eid, style=style, **kw)
    return InlineKeyboardButton(text=f"{DEFAULT_EMOJI.get(name, '')} {text}".strip(), style=style, **kw)


def nav_button(name: str, label: str, callback: str, style: str | None = None) -> InlineKeyboardButton:
    """Ro'yxat tugmalari: premium bo'lsa ikonka + yozuv, bo'lmasa faqat oddiy emoji."""
    if EMOJI_IDS.get(name):
        return btn(name, label, callback, style)
    return InlineKeyboardButton(text=DEFAULT_EMOJI[name], callback_data=callback, style=style)


load_emojis()

# ---------------------------------------------------------------- kesh (sqlite)
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute("CREATE TABLE IF NOT EXISTS cache (song_id TEXT PRIMARY KEY, file_id TEXT NOT NULL)")
db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT)")
db.commit()


def cache_get(song_id: str) -> str | None:
    row = db.execute("SELECT file_id FROM cache WHERE song_id=?", (song_id,)).fetchone()
    return row[0] if row else None


def cache_set(song_id: str, file_id: str) -> None:
    db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?)", (song_id, file_id))
    db.commit()


# --- jadvallarni yangilash (eski bazalar ham ishlayveradi)
def _add_col(table: str, col: str, decl: str) -> None:
    if col not in [r[1] for r in db.execute(f"PRAGMA table_info({table})")]:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


_add_col("users", "username", "TEXT")
_add_col("users", "joined_at", "INTEGER DEFAULT 0")
_add_col("users", "last_seen", "INTEGER DEFAULT 0")
_add_col("users", "banned", "INTEGER DEFAULT 0")
_add_col("users", "blocked", "INTEGER DEFAULT 0")      # foydalanuvchi botni bloklagan
db.execute("CREATE TABLE IF NOT EXISTS events (ts INTEGER, user_id INTEGER, kind TEXT, query TEXT)")
db.execute("CREATE INDEX IF NOT EXISTS events_ts ON events (kind, ts)")
db.execute("CREATE TABLE IF NOT EXISTS channels (chat_id INTEGER PRIMARY KEY, title TEXT, link TEXT)")
db.commit()

_last_touch: dict[int, float] = {}


def touch_user(user) -> None:
    """Foydalanuvchini saqlaydi / oxirgi faolligini yangilaydi (har 60 soniyada ko'pi bilan 1 marta)."""
    now = time.time()
    if now - _last_touch.get(user.id, 0) < 60:
        return
    _last_touch[user.id] = now
    db.execute(
        "INSERT INTO users (user_id, name, username, joined_at, last_seen) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, username=excluded.username, "
        "last_seen=excluded.last_seen, blocked=0",
        (user.id, user.full_name, user.username, int(now), int(now)),
    )
    db.commit()


def log_event(user_id: int, kind: str, query: str) -> None:
    db.execute("INSERT INTO events VALUES (?, ?, ?, ?)", (int(time.time()), user_id, kind, query[:200]))
    db.commit()


# ---------------------------------------------------------------- yordamchilar
def fmt_dur(sec: int) -> str:
    if not sec:
        return ""
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def clean_title(title: str) -> str:
    return re.sub(
        r"\s*[\(\[](official|video|audio|lyrics?|clip|music video|hd|4k|mv|премьера)[^\)\]]*[\)\]]",
        "", title, flags=re.I,
    ).strip()


def song_label(song: dict, n: int) -> str:
    """Tugmadagi yozuv: '1. Ijrochi — Qo'shiq  3:45'"""
    name = f"{song['artist']} — {song['title']}" if song["artist"] else song["title"]
    if len(name) > 48:
        name = name[:47] + "…"
    dur = fmt_dur(song["duration"])
    return f"{n}. {name}  {dur}".strip()


# ---------------------------------------------------------------- qidiruv
ytm = YTMusic()
FAST_LIMIT = 20                 # birinchi ro'yxat uchun (1 ta so'rov - tez)
SEARCH_CACHE_TTL = 60 * 60      # bir xil qidiruv 1 soat xotirada turadi
search_cache: "OrderedDict[str, tuple[float, list[dict]]]" = OrderedDict()


def norm(text: str) -> str:
    """Takrorlarni aniqlash uchun: kichik harf, faqat harf/raqam."""
    return re.sub(r"[^\w]+", "", (text or "").lower())


def song_key(song: dict) -> str:
    """Kesh kaliti."""
    return song["id"]


def _search_yt(query: str, limit: int) -> list[dict]:
    """YouTube Music katalogidan aynan QO'SHIQLARni qidiradi (klip/video emas)."""
    items: list[dict] = []
    seen: set[str] = set()
    try:
        for r in ytm.search(query, filter="songs", limit=limit):
            vid = r.get("videoId")
            if not vid or vid in seen:
                continue
            dur = int(r.get("duration_seconds") or 0)
            if dur and dur > MAX_DURATION:
                continue
            artist = ", ".join(a["name"] for a in (r.get("artists") or []) if a.get("name"))
            seen.add(vid)
            items.append({"src": "yt", "id": vid, "url": f"https://www.youtube.com/watch?v={vid}",
                          "title": r.get("title") or "Nomsiz", "artist": artist, "duration": dur})
    except Exception as e:
        log.warning("YouTube Music qidiruvi xatosi: %s", e)

    if items:
        return items[:limit]

    # zaxira yo'l: oddiy YouTube qidiruvi
    try:
        opts = ydl_opts(extract_flat=True, skip_download=True)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{query} audio", download=False)
    except Exception as e:
        log.warning("YouTube qidiruvi xatosi: %s", e)
        return []
    for e in info.get("entries") or []:
        if not e or not e.get("id") or e["id"] in seen:
            continue
        if e.get("live_status") in ("is_live", "is_upcoming"):
            continue
        dur = int(e.get("duration") or 0)
        if dur and dur > MAX_DURATION:
            continue
        title = clean_title(e.get("title") or "Nomsiz")
        artist = e.get("channel") or ""
        for sep in (" - ", " – ", " — "):
            if sep in title:
                artist, title = (x.strip() for x in title.split(sep, 1))
                break
        seen.add(e["id"])
        items.append({"src": "yt", "id": e["id"], "url": f"https://www.youtube.com/watch?v={e['id']}",
                      "title": title, "artist": artist, "duration": dur})
    return items[:limit]


def dedupe(items: list[dict]) -> list[dict]:
    result, seen = [], set()
    for song in items:
        k = norm(song["artist"]) + "|" + norm(song["title"])
        if k in seen or song["id"] in seen:
            continue
        seen.add(k)
        seen.add(song["id"])
        result.append(song)
    return result[:TOTAL_RESULTS]


def cache_lookup(query: str) -> list[dict] | None:
    hit = search_cache.get(norm(query))
    if hit and time.time() - hit[0] < SEARCH_CACHE_TTL:
        return hit[1]
    return None


def cache_store(query: str, items: list[dict]) -> None:
    search_cache[norm(query)] = (time.time(), items)
    search_cache.move_to_end(norm(query))
    while len(search_cache) > 500:
        search_cache.popitem(last=False)


async def search_songs(query: str, limit: int) -> list[dict]:
    return dedupe(await asyncio.to_thread(_search_yt, query, limit))


async def load_more(sid: str, query: str):
    """Fonda qolgan qo'shiqlarni (50 tagacha) yuklab, ro'yxatga qo'shadi."""
    try:
        full = await search_songs(query, TOTAL_RESULTS)
        s = searches.get(sid)
        if s:
            s["items"] = dedupe(s["items"] + full)   # birinchi 20 tasi joyida qoladi
            cache_store(query, s["items"])
    except Exception as e:
        log.warning("Qo'shimcha natijalar yuklanmadi: %s", e)


def _download(song: dict) -> Path | None:
    opts = ydl_opts(
        format="bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio/best",
        outtmpl=str(DL_DIR / f"{song['src']}_%(id)s.%(ext)s"),
        noplaylist=True,
        max_filesize=MAX_FILESIZE,
        http_chunk_size=10 * 1024 * 1024,   # YouTube tezlik cheklovini chetlab o'tadi
        socket_timeout=15,
        retries=3,
        cachedir=str(BASE_DIR / ".ytdlp_cache"),
    )
    if HAS_FFMPEG:
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192",
             "nopostoverwrites": True},
        ]
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(song["url"], download=True)
        path = Path(ydl.prepare_filename(info))
        if HAS_FFMPEG:
            path = path.with_suffix(".mp3")
    return path if path.exists() else None


def cleanup(song: dict) -> None:
    for f in DL_DIR.glob(f"{song['src']}_{song['id']}.*"):
        f.unlink(missing_ok=True)


# ---------------------------------------------------------------- qidiruvlar xotirasi
# Har bir qidiruvga qisqa ID beriladi -> eski ro'yxatlardagi tugmalar ham ishlayveradi
searches: "OrderedDict[str, dict]" = OrderedDict()
_counter = count(1)


def save_search(query: str, items: list[dict]) -> str:
    sid = format(next(_counter), "x")
    searches[sid] = {"query": query, "items": items}
    while len(searches) > MAX_SEARCHES_IN_MEMORY:
        searches.popitem(last=False)
    return sid


# ---------------------------------------------------------------- ro'yxat ko'rinishi
def pages_count(items: list) -> int:
    return max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)


def song_meta(song: dict) -> str:
    """'2:54 4.0M 128k' - davomiylik, taxminiy hajm va bitreyt."""
    dur = song["duration"]
    if not dur:
        return ""
    kbps = 192 if HAS_FFMPEG else 128                  # yuboriladigan fayl sifati
    size_mb = dur * kbps * 1000 / 8 / 1024 / 1024
    return f"{fmt_dur(dur)} {size_mb:.1f}M {kbps}k"


def list_text(query: str, items: list[dict], page: int) -> str:
    start = page * PAGE_SIZE
    lines = [f"{E('search')} <b>{html.escape(query)}</b>"]
    for i, song in enumerate(items[start : start + PAGE_SIZE], start=start + 1):
        name = html.escape(song["title"])
        if song["artist"]:
            name = f"{html.escape(song['artist'])} – {name}"
        meta = song_meta(song)
        lines.append(f"<b>{i}.</b> {name} <i>{meta}</i>" if meta else f"<b>{i}.</b> {name}")
    return "\n".join(lines)


def list_keyboard(sid: str, items: list[dict], page: int) -> InlineKeyboardMarkup:
    total = pages_count(items)
    start = page * PAGE_SIZE
    chunk = items[start : start + PAGE_SIZE]

    rows, row = [], []
    for i, _ in enumerate(chunk, start=start):
        row.append(InlineKeyboardButton(text=str(i + 1), callback_data=f"s:{sid}:{i}"))
        if len(row) == 5:                                # bir qatorda 5 ta raqam
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append(
        [
            nav_button("prev", "Oldingi", f"p:{sid}:{(page - 1) % total}", "primary"),
            nav_button("close", "Yopish", "close", "danger"),
            nav_button("next", "Keyingi", f"p:{sid}:{(page + 1) % total}", "primary"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------- bot
dp = Dispatcher()
download_sem = asyncio.Semaphore(PARALLEL_DOWNLOADS)
song_locks: dict[str, asyncio.Lock] = {}
BOT_USERNAME = ""


# ---------------------------------------------------------------- oldindan yuklash (prefetch)
# Ro'yxat chiqishi bilan birinchi qo'shiqlar fonda yuklanadi.
# Foydalanuvchi raqamni bosganda fayl allaqachon tayyor bo'ladi -> faqat Telegram'ga yuboriladi.
prefetch_tasks: dict[str, tuple[float, asyncio.Task]] = {}
prefetch_sem = asyncio.Semaphore(2)


async def _prefetch_one(song: dict) -> Path | None:
    try:
        async with prefetch_sem:
            return await asyncio.to_thread(_download, song)
    except Exception as e:
        log.debug("Prefetch o'tmadi %s: %s", song["id"], e)
        return None


def prefetch(items: list[dict]) -> None:
    if PREFETCH_COUNT <= 0:
        return
    for song in items[:PREFETCH_COUNT]:
        if song["id"] in prefetch_tasks or song["id"] in song_locks or cache_get(song_key(song)):
            continue
        if len(prefetch_tasks) >= 40:
            break
        prefetch_tasks[song["id"]] = (time.time(), asyncio.create_task(_prefetch_one(song)))


async def prefetch_janitor():
    """Ishlatilmay qolgan oldindan yuklangan fayllarni tozalaydi."""
    while True:
        await asyncio.sleep(120)
        now = time.time()
        for sid_, (ts, task) in list(prefetch_tasks.items()):
            if task.done() and now - ts > PREFETCH_TTL:
                prefetch_tasks.pop(sid_, None)
                for f in DL_DIR.glob(f"*_{sid_}.*"):
                    f.unlink(missing_ok=True)


async def get_file(song: dict) -> Path | None:
    entry = prefetch_tasks.pop(song["id"], None)
    if entry:
        path = await entry[1]          # tayyor bo'lsa darhol, yuklanayotgan bo'lsa tugashini kutamiz
        if path and path.exists():
            return path
    return await asyncio.to_thread(_download, song)


async def _upload(bot: Bot, chat_id: int, song: dict, caption: str) -> bool:
    """Bitta qo'shiqni yuklab, yuboradi. Muvaffaqiyatli bo'lsa True."""
    t0 = time.perf_counter()
    try:
        path = await get_file(song)
        if not path:
            return False
        t1 = time.perf_counter()
        name = f"{song['artist']} - {song['title']}".strip(" -")
        msg = await bot.send_audio(
            chat_id,
            FSInputFile(path, filename=f"{name[:100]}{path.suffix}"),
            title=song["title"][:64],
            performer=song["artist"][:64] or None,
            duration=song["duration"] or None,
            caption=caption,
        )
        cache_set(song_key(song), msg.audio.file_id)
        log.info("⏱ %s — %s | olish: %.1fs | Telegram'ga yuborish: %.1fs",
                 song["artist"], song["title"], t1 - t0, time.perf_counter() - t1)
        return True
    except Exception as e:
        log.error("Yuklab bo'lmadi [%s] %s: %s", song["src"], song["id"], e)
        return False
    finally:
        cleanup(song)


async def send_song(bot: Bot, chat_id: int, song: dict):
    caption = f"{E('headphones')} @{BOT_USERNAME}"
    key = song_key(song)

    file_id = cache_get(key)
    if file_id:
        try:
            await bot.send_audio(chat_id, file_id, caption=caption)
            return
        except Exception:
            log.warning("Keshdagi fayl ishlamadi: %s", key)

    lock = song_locks.setdefault(key, asyncio.Lock())
    status = await bot.send_message(
        chat_id, f"{E('loading')} Yuklanmoqda: <b>{html.escape(song_label(song, 0)[3:])}</b>"
    )
    async with lock, download_sem:
        # kutib turgan paytda boshqa foydalanuvchi uchun yuklangan bo'lishi mumkin
        file_id = cache_get(key)
        if file_id:
            await bot.send_audio(chat_id, file_id, caption=caption)
            await status.delete()
            return

        await bot.send_chat_action(chat_id, ChatAction.UPLOAD_VOICE)
        if await _upload(bot, chat_id, song, caption):
            await status.delete()
            return

        await status.edit_text(f"{E('error')} Bu qo'shiqni yuklab bo'lmadi. Ro'yxatdan boshqasini tanlang.")


# ================================================================ ADMIN PANEL
# /admin — faqat ADMIN_ID dagi foydalanuvchilar uchun:
#   📊 Statistika   📢 Xabar yuborish   📣 Majburiy obuna
#   🚫 Bloklash     🔥 Top qidiruvlar   📥 Foydalanuvchilar (CSV)   🎨 Emojilar

class AdminSt(StatesGroup):
    broadcast = State()
    broadcast_confirm = State()
    add_channel = State()
    ban = State()
    unban = State()
    emoji_set = State()


def is_admin_id(user_id: int) -> bool:
    return user_id in ADMINS


def is_admin(message: Message) -> bool:
    return bool(message.from_user and is_admin_id(message.from_user.id))


def day_start(days_ago: int = 0) -> int:
    t = time.localtime()
    midnight = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
    return int(midnight) - days_ago * 86400


async def safe_edit(msg: Message, text: str, kb: InlineKeyboardMarkup | None = None, **kw):
    """Xabarni tahrirlaydi; o'zgarmagan bo'lsa jim o'tadi."""
    try:
        await msg.edit_text(text, reply_markup=kb, disable_web_page_preview=True, **kw)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            await msg.answer(text, reply_markup=kb, disable_web_page_preview=True, **kw)


# ---------------------------------------------------------------- bloklash / obuna tekshiruvi
_banned_cache: set[int] = set()
_sub_ok: dict[int, float] = {}          # user_id -> oxirgi muvaffaqiyatli tekshiruv vaqti
SUB_CACHE_TTL = 10 * 60


def reload_banned() -> None:
    global _banned_cache
    _banned_cache = {r[0] for r in db.execute("SELECT user_id FROM users WHERE banned=1")}


def get_channels() -> list[tuple[int, str, str]]:
    return db.execute("SELECT chat_id, title, link FROM channels ORDER BY rowid").fetchall()


async def missing_channels(bot: Bot, user_id: int) -> list[tuple[int, str, str]]:
    channels = get_channels()
    if not channels:
        return []
    if time.time() - _sub_ok.get(user_id, 0) < SUB_CACHE_TTL:
        return []
    missing = []
    for ch in channels:
        try:
            m = await bot.get_chat_member(ch[0], user_id)
            if m.status in ("left", "kicked"):
                missing.append(ch)
        except Exception as e:
            log.warning("Kanal tekshirilmadi (%s): %s — bot kanalda admin ekanini tekshiring", ch[1], e)
    if not missing:
        _sub_ok[user_id] = time.time()
    return missing


def sub_keyboard(channels) -> InlineKeyboardMarkup:
    rows = [[btn("join", title, url=link, style="primary")] for _, title, link in channels]
    rows.append([btn("check", "Tekshirish", "checksub", style="success")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


SUB_EMOJIS = {"lock", "join", "check"}


def preview_channels():
    return get_channels() or [(0, "Namuna kanal", "https://t.me/telegram")]


def sub_text() -> str:
    return (f"{E('lock')} <b>Botdan foydalanish uchun</b> quyidagi kanallarga obuna bo'ling,\n"
            f"so'ng {E('check')} <b>Tekshirish</b> tugmasini bosing.")


class GateMiddleware(BaseMiddleware):
    """Har bir xabar/tugmadan oldin: foydalanuvchini saqlaydi, ban va majburiy obunani tekshiradi."""

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if not user or user.is_bot:
            return await handler(event, data)
        touch_user(user)
        if is_admin_id(user.id):
            return await handler(event, data)

        if user.id in _banned_cache:
            if isinstance(event, CallbackQuery):
                await event.answer("🚫 Siz bloklangansiz.", show_alert=True)
            return None

        chat = event.chat if isinstance(event, Message) else (event.message.chat if event.message else None)
        if chat is None or chat.type != "private":
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and event.data == "checksub":
            return await handler(event, data)

        missing = await missing_channels(data["bot"], user.id)
        if missing:
            if isinstance(event, CallbackQuery):
                await event.answer("Avval kanallarga obuna bo'ling!", show_alert=True)
            await data["bot"].send_message(user.id, sub_text(), reply_markup=sub_keyboard(missing))
            return None
        return await handler(event, data)


@dp.callback_query(F.data == "checksub")
async def on_checksub(cb: CallbackQuery, bot: Bot):
    _sub_ok.pop(cb.from_user.id, None)
    missing = await missing_channels(bot, cb.from_user.id)
    if missing:
        await cb.answer("❗ Hali hamma kanallarga obuna bo'lmadingiz.", show_alert=True)
        try:
            await cb.message.edit_reply_markup(reply_markup=sub_keyboard(missing))
        except Exception:
            pass
        return
    await cb.answer("✅ Rahmat!")
    try:
        await cb.message.delete()
    except Exception:
        pass
    await bot.send_message(cb.from_user.id,
                           f"{E('ok')} Rahmat! Endi qo'shiq nomi yoki qo'shiqchi ismini yozing {E('music')}")


# ---------------------------------------------------------------- menyular
def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("stats", "Statistika", "adm:stats", "primary"), btn("broadcast", "Xabar yuborish", "adm:bc", "success")],
        [btn("channel", "Majburiy obuna", "adm:ch", "primary"), btn("ban", "Bloklash", "adm:ban", "danger")],
        [btn("top", "Top qidiruvlar", "adm:top", "primary"), btn("export", "Foydalanuvchilar", "adm:export", "primary")],
        [btn("emoji", "Emojilar", "adm:emoji", "success"), btn("close", "Yopish", "close", "danger")],
    ])


def back_kb(extra: list | None = None) -> InlineKeyboardMarkup:
    rows = list(extra or [])
    rows.append([btn("back", "Orqaga", "adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_kb(extra: list | None = None) -> InlineKeyboardMarkup:
    rows = list(extra or [])
    rows.append([btn("cancel", "Bekor qilish", "adm:cancel", "danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_title() -> str:
    users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    return (f"{E('admin')} <b>Admin panel</b>\n\n"
            f"{E('users')} Foydalanuvchilar: <b>{users}</b>\n\n"
            "Kerakli bo'limni tanlang:")


@dp.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not is_admin(message):
        return
    await state.clear()
    await message.answer(admin_title(), reply_markup=admin_menu())


@dp.message(Command("cancel"), StateFilter("*"))
async def cmd_cancel(message: Message, state: FSMContext):
    if not is_admin(message):
        return
    await state.clear()
    await message.answer(f"{E('cancel')} Bekor qilindi.\n\n" + admin_title(), reply_markup=admin_menu())


@dp.callback_query(F.data.in_({"adm:menu", "adm:cancel"}), StateFilter("*"))
async def adm_menu(cb: CallbackQuery, state: FSMContext):
    if not is_admin_id(cb.from_user.id):
        return await cb.answer()
    await state.clear()
    await safe_edit(cb.message, admin_title(), admin_menu())
    await cb.answer("Bekor qilindi" if cb.data == "adm:cancel" else None)


# ---------------------------------------------------------------- 📊 statistika
def stats_text() -> str:
    q = lambda sql, *a: db.execute(sql, a).fetchone()[0]
    today, week, month = day_start(0), day_start(7), day_start(30)
    total = q("SELECT COUNT(*) FROM users")
    alive = q("SELECT COUNT(*) FROM users WHERE blocked=0")
    new_today = q("SELECT COUNT(*) FROM users WHERE joined_at>=?", today)
    new_week = q("SELECT COUNT(*) FROM users WHERE joined_at>=?", week)
    new_month = q("SELECT COUNT(*) FROM users WHERE joined_at>=?", month)
    active_today = q("SELECT COUNT(*) FROM users WHERE last_seen>=?", today)
    banned = q("SELECT COUNT(*) FROM users WHERE banned=1")
    s_today = q("SELECT COUNT(*) FROM events WHERE kind='search' AND ts>=?", today)
    s_all = q("SELECT COUNT(*) FROM events WHERE kind='search'")
    d_today = q("SELECT COUNT(*) FROM events WHERE kind='download' AND ts>=?", today)
    d_all = q("SELECT COUNT(*) FROM events WHERE kind='download'")
    v_today = q("SELECT COUNT(*) FROM events WHERE kind='video' AND ts>=?", today)
    v_all = q("SELECT COUNT(*) FROM events WHERE kind='video'")
    cached = q("SELECT COUNT(*) FROM cache")
    return (
        f"{E('stats')} <b>Statistika</b>\n\n"
        f"{E('users')} <b>Foydalanuvchilar</b>\n"
        f"├ Jami: <b>{total}</b>\n"
        f"├ Faol (botni bloklamagan): <b>{alive}</b>\n"
        f"├ Botni bloklaganlar: <b>{total - alive}</b>\n"
        f"├ Bugun qo'shildi: <b>{new_today}</b>\n"
        f"├ 7 kunda qo'shildi: <b>{new_week}</b>\n"
        f"├ 30 kunda qo'shildi: <b>{new_month}</b>\n"
        f"├ Bugun faol: <b>{active_today}</b>\n"
        f"└ Admin bloklagan: <b>{banned}</b>\n\n"
        f"{E('chart')} <b>Faollik</b>\n"
        f"├ Qidiruvlar (bugun / jami): <b>{s_today}</b> / <b>{s_all}</b>\n"
        f"├ Yuklashlar (bugun / jami): <b>{d_today}</b> / <b>{d_all}</b>\n"
        f"├ Instagram videolar (bugun / jami): <b>{v_today}</b> / <b>{v_all}</b>\n"
        f"└ Keshdagi qo'shiqlar: <b>{cached}</b>\n\n"
        f"{E('time')} <i>{time.strftime('%d.%m.%Y %H:%M')}</i>"
    )


@dp.callback_query(F.data == "adm:stats")
async def adm_stats(cb: CallbackQuery):
    if not is_admin_id(cb.from_user.id):
        return await cb.answer()
    await safe_edit(cb.message, stats_text(), back_kb([[btn("refresh", "Yangilash", "adm:stats", "primary")]]))
    await cb.answer()


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if not is_admin(message):
        return
    await message.answer(stats_text())


# ---------------------------------------------------------------- 🔥 top qidiruvlar
@dp.callback_query(F.data == "adm:top")
async def adm_top(cb: CallbackQuery):
    if not is_admin_id(cb.from_user.id):
        return await cb.answer()
    rows = db.execute(
        "SELECT LOWER(query) q, COUNT(*) c FROM events WHERE kind='search' AND ts>=? "
        "GROUP BY q ORDER BY c DESC LIMIT 15", (day_start(7),)
    ).fetchall()
    songs = db.execute(
        "SELECT query, COUNT(*) c FROM events WHERE kind='download' AND ts>=? "
        "GROUP BY query ORDER BY c DESC LIMIT 10", (day_start(7),)
    ).fetchall()
    lines = [f"{E('top')} <b>Top qidiruvlar (7 kun)</b>\n"]
    lines += [f"{i}. {html.escape(q)} — <b>{c}</b>" for i, (q, c) in enumerate(rows, 1)] or ["<i>Hali yo'q</i>"]
    lines.append(f"\n{E('music')} <b>Eng ko'p yuklangan qo'shiqlar (7 kun)</b>\n")
    lines += [f"{i}. {html.escape(q)} — <b>{c}</b>" for i, (q, c) in enumerate(songs, 1)] or ["<i>Hali yo'q</i>"]
    await safe_edit(cb.message, "\n".join(lines), back_kb([[btn("refresh", "Yangilash", "adm:top", "primary")]]))
    await cb.answer()


# ---------------------------------------------------------------- 📥 foydalanuvchilar CSV
@dp.callback_query(F.data == "adm:export")
async def adm_export(cb: CallbackQuery):
    if not is_admin_id(cb.from_user.id):
        return await cb.answer()
    await cb.answer("Tayyorlanmoqda...")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["user_id", "ism", "username", "qo'shilgan", "oxirgi faollik", "botni bloklagan", "ban"])
    fmt = lambda ts: time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else ""
    for uid, name, uname, j, l, bl, bn in db.execute(
        "SELECT user_id, name, username, joined_at, last_seen, blocked, banned FROM users ORDER BY joined_at"
    ):
        w.writerow([uid, name, f"@{uname}" if uname else "", fmt(j), fmt(l), "ha" if bl else "", "ha" if bn else ""])
    data = ("﻿" + buf.getvalue()).encode("utf-8")   # Excel o'zbekcha harflarni to'g'ri ochishi uchun
    total = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    await cb.message.answer_document(
        BufferedInputFile(data, filename=f"users_{time.strftime('%Y%m%d')}.csv"),
        caption=f"{E('export')} Foydalanuvchilar: <b>{total}</b>",
    )


# ---------------------------------------------------------------- 🎨 emojilar (botdan o'zgartirish)
def emoji_view() -> tuple[str, InlineKeyboardMarkup]:
    lines = [f"{E('emoji')} <b>Emojilar</b>  (premium: {len([k for k in EMOJI_INFO if k in EMOJI_IDS])}"
             f"/{len(EMOJI_INFO)})\n",
             "O'zgartirmoqchi bo'lgan emojini bosing:\n"]
    for k, (_, desc) in EMOJI_INFO.items():
        lines.append(f"{E(k)} <code>{k}</code> — {desc}")
    rows, row = [], []
    for k in EMOJI_INFO:
        row.append(btn(k, k, f"adm:em:{k}", "success" if k in EMOJI_IDS else None))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([btn("refresh", "emojis.json ni qayta o'qish", "adm:emojireload", "primary")])
    return "\n".join(lines), back_kb(rows)


@dp.callback_query(F.data == "adm:emoji", StateFilter("*"))
async def adm_emoji(cb: CallbackQuery, state: FSMContext):
    if not is_admin_id(cb.from_user.id):
        return await cb.answer()
    await state.clear()
    text, kb = emoji_view()
    await safe_edit(cb.message, text, kb)
    await cb.answer()


@dp.callback_query(F.data == "adm:emojireload")
async def adm_emoji_reload(cb: CallbackQuery, state: FSMContext):
    if not is_admin_id(cb.from_user.id):
        return await cb.answer()
    load_emojis()
    await cb.answer(f"✅ Qayta o'qildi: {len(EMOJI_IDS)} ta premium")
    text, kb = emoji_view()
    await safe_edit(cb.message, text, kb)


@dp.callback_query(F.data.startswith("adm:em:"))
async def adm_emoji_pick(cb: CallbackQuery, state: FSMContext):
    if not is_admin_id(cb.from_user.id):
        return await cb.answer()
    name = cb.data.split(":", 2)[2]
    if name not in EMOJI_INFO:
        return await cb.answer("Noma'lum emoji", show_alert=True)
    await state.set_state(AdminSt.emoji_set)
    await state.update_data(emoji_name=name, panel_msg=cb.message.message_id)
    extra = []
    if name in EMOJI_IDS:
        extra.append([btn("delete", "Oddiy emojiga qaytarish", f"adm:emreset:{name}", "danger")])
    extra.append([btn("back", "Emojilarga qaytish", "adm:emoji")])
    await safe_edit(
        cb.message,
        f"{E('emoji')} <b>{name}</b> — {EMOJI_INFO[name][1]}\n\n"
        f"Hozirgisi: {E(name)}  "
        f"({'premium' if name in EMOJI_IDS else 'oddiy'})\n\n"
        f"{E('write')} Yangi <b>premium emojini</b> yuboring:",
        cancel_kb(extra),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("adm:emreset:"), StateFilter("*"))
async def adm_emoji_reset(cb: CallbackQuery, state: FSMContext):
    if not is_admin_id(cb.from_user.id):
        return await cb.answer()
    name = cb.data.split(":", 2)[2]
    set_emoji(name, None)
    await state.clear()
    await cb.answer(f"♻️ {name}: oddiy emojiga qaytarildi")
    text, kb = emoji_view()
    await safe_edit(cb.message, text, kb)


@dp.message(AdminSt.emoji_set)
async def adm_emoji_got(message: Message, state: FSMContext):
    if not is_admin(message):
        return
    ents = [e for e in (message.entities or message.caption_entities or []) if e.type == "custom_emoji"]
    if not ents:
        return await message.answer(
            f"{E('warning')} Bu oddiy emoji. <b>Premium (animatsiyali) emoji</b> yuboring.",
            reply_markup=cancel_kb([[btn("back", "Emojilarga qaytish", "adm:emoji")]]),
        )
    name = (await state.get_data())["emoji_name"]
    set_emoji(name, ents[0].custom_emoji_id)
    await state.clear()
    await message.answer(
        f"{E('ok')} <b>{name}</b> o'zgartirildi: {E(name)}\n"
        f"<i>Qayerda chiqadi: {EMOJI_INFO[name][1]}</i>"
    )
    if name in SUB_EMOJIS:
        await message.answer(f"{E('warning')} <b>Namuna</b> — oddiy foydalanuvchilar ko'radigan obuna xabari "
                             "(admin uni odatda ko'rmaydi):")
        await message.answer(sub_text(), reply_markup=sub_keyboard(preview_channels()))
    text, kb = emoji_view()
    await message.answer(text, reply_markup=kb)


# ---------------------------------------------------------------- 📢 xabar yuborish
broadcast_running = False


@dp.callback_query(F.data == "adm:bc")
async def adm_bc(cb: CallbackQuery, state: FSMContext):
    if not is_admin_id(cb.from_user.id):
        return await cb.answer()
    if broadcast_running:
        return await cb.answer("⏳ Hozir boshqa xabar yuborilmoqda, tugashini kuting.", show_alert=True)
    n = db.execute("SELECT COUNT(*) FROM users WHERE blocked=0 AND banned=0").fetchone()[0]
    await state.set_state(AdminSt.broadcast)
    await safe_edit(
        cb.message,
        f"{E('broadcast')} <b>Xabar yuborish</b>\n\n"
        f"{E('users')} Qabul qiluvchilar: <b>{n}</b> ta\n\n"
        f"{E('write')} Yubormoqchi bo'lgan xabaringizni jo'nating — matn, rasm, video, audio, "
        "ovozli xabar, tugmali post (forward) — hammasi bo'ladi.",
        cancel_kb(),
    )
    await cb.answer()


@dp.message(AdminSt.broadcast)
async def adm_bc_got(message: Message, state: FSMContext):
    if not is_admin(message):
        return
    await state.update_data(src_chat=message.chat.id, src_msg=message.message_id)
    await state.set_state(AdminSt.broadcast_confirm)
    await message.answer(
        f"{E('warning')} Xabar yuqoridagidek ko'rinadi. <b>Hammaga yuborilsinmi?</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            btn("send", "Yuborish", "adm:bcgo", "success"),
            btn("cancel", "Bekor qilish", "adm:cancel", "danger"),
        ]]),
    )


@dp.callback_query(F.data == "adm:bcgo", AdminSt.broadcast_confirm)
async def adm_bc_go(cb: CallbackQuery, state: FSMContext, bot: Bot):
    global broadcast_running
    if not is_admin_id(cb.from_user.id):
        return await cb.answer()
    if broadcast_running:
        return await cb.answer("⏳ Boshqa xabar yuborilmoqda.", show_alert=True)
    data = await state.get_data()
    await state.clear()
    await cb.answer("Boshlandi!")
    await safe_edit(cb.message, f"{E('broadcast')} Yuborish boshlandi...")
    broadcast_running = True
    asyncio.create_task(run_broadcast(bot, cb.message, data["src_chat"], data["src_msg"]))


async def run_broadcast(bot: Bot, status: Message, src_chat: int, src_msg: int):
    global broadcast_running
    users = [r[0] for r in db.execute("SELECT user_id FROM users WHERE blocked=0 AND banned=0")]
    total, ok, blocked, failed = len(users), 0, 0, 0
    started, last_edit = time.time(), 0.0
    try:
        for i, uid in enumerate(users, 1):
            for _ in range(3):
                try:
                    await bot.copy_message(uid, src_chat, src_msg)
                    ok += 1
                    break
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
                except TelegramForbiddenError:
                    blocked += 1
                    db.execute("UPDATE users SET blocked=1 WHERE user_id=?", (uid,))
                    break
                except Exception:
                    failed += 1
                    break
            await asyncio.sleep(0.05)                       # ~20 ta/soniya — Telegram limiti ichida
            if time.time() - last_edit > 3 or i == total:
                last_edit = time.time()
                db.commit()
                try:
                    await status.edit_text(
                        f"{E('broadcast')} Yuborilmoqda... <b>{i}/{total}</b> ({i * 100 // max(total, 1)}%)\n\n"
                        f"{E('ok')} Yetkazildi: {ok}\n{E('ban')} Bloklagan: {blocked}\n{E('warning')} Xato: {failed}"
                    )
                except Exception:
                    pass
    finally:
        broadcast_running = False
        db.commit()
    mins, secs = divmod(int(time.time() - started), 60)
    await safe_edit(
        status,
        f"{E('ok')} <b>Xabar yuborildi!</b>\n\n"
        f"{E('users')} Jami: <b>{total}</b>\n{E('ok')} Yetkazildi: <b>{ok}</b>\n"
        f"{E('ban')} Botni bloklagan: <b>{blocked}</b>\n{E('warning')} Xato: <b>{failed}</b>\n"
        f"{E('time')} Vaqt: {mins} daq {secs} son",
        back_kb(),
    )


# ---------------------------------------------------------------- 📣 majburiy obuna
def channels_view() -> tuple[str, InlineKeyboardMarkup]:
    chans = get_channels()
    lines = [f"{E('channel')} <b>Majburiy obuna</b>\n"]
    if chans:
        lines.append("Foydalanuvchilar quyidagi kanallarga obuna bo'lishi shart:\n")
        lines += [f"{i}. <a href=\"{link}\">{html.escape(title)}</a>" for i, (_, title, link) in enumerate(chans, 1)]
    else:
        lines.append("<i>Kanal qo'shilmagan — bot hammaga ochiq.</i>")
    lines.append(f"\n{E('warning')} Bot har bir kanalda <b>admin</b> bo'lishi kerak.")
    rows = [[btn("delete", title[:30], f"adm:chdel:{cid}", "danger")] for cid, title, _ in chans]
    rows.append([btn("add", "Kanal qo'shish", "adm:chadd", "success")])
    rows.append([btn("lock", "Obuna xabarini ko'rish", "adm:chpreview", "primary")])
    return "\n".join(lines), back_kb(rows)


@dp.callback_query(F.data == "adm:chpreview")
async def adm_ch_preview(cb: CallbackQuery):
    if not is_admin_id(cb.from_user.id):
        return await cb.answer()
    await cb.answer()
    await cb.message.answer(sub_text(), reply_markup=sub_keyboard(preview_channels()))


@dp.callback_query(F.data == "adm:ch", StateFilter("*"))
async def adm_ch(cb: CallbackQuery, state: FSMContext):
    if not is_admin_id(cb.from_user.id):
        return await cb.answer()
    await state.clear()
    text, kb = channels_view()
    await safe_edit(cb.message, text, kb)
    await cb.answer()


@dp.callback_query(F.data.startswith("adm:chdel:"))
async def adm_ch_del(cb: CallbackQuery):
    if not is_admin_id(cb.from_user.id):
        return await cb.answer()
    cid = int(cb.data.split(":")[2])
    db.execute("DELETE FROM channels WHERE chat_id=?", (cid,))
    db.commit()
    _sub_ok.clear()
    text, kb = channels_view()
    await safe_edit(cb.message, text, kb)
    await cb.answer("🗑 O'chirildi")


@dp.callback_query(F.data == "adm:chadd")
async def adm_ch_add(cb: CallbackQuery, state: FSMContext):
    if not is_admin_id(cb.from_user.id):
        return await cb.answer()
    await state.set_state(AdminSt.add_channel)
    await safe_edit(
        cb.message,
        f"{E('add')} <b>Kanal qo'shish</b>\n\n"
        "1. Botni kanalga <b>admin</b> qilib qo'shing.\n"
        "2. Keyin bulardan birini yuboring:\n"
        "• kanal username: <code>@kanal_nomi</code>\n"
        "• kanal ID si: <code>-1001234567890</code>\n"
        "• yoki kanaldan istalgan postni shu yerga <b>forward</b> qiling",
        cancel_kb([[btn("back", "Kanallarga qaytish", "adm:ch")]]),
    )
    await cb.answer()


@dp.message(AdminSt.add_channel)
async def adm_ch_got(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message):
        return
    ident = None
    if message.forward_origin and getattr(message.forward_origin, "chat", None):
        ident = message.forward_origin.chat.id
    elif message.text:
        t = message.text.strip()
        m = re.search(r"(?:t\.me/|@)([A-Za-z0-9_]{4,})", t)
        if m and "+" not in t and "joinchat" not in t:
            ident = "@" + m.group(1)
        elif re.fullmatch(r"-?\d{6,}", t):
            ident = int(t)
    if ident is None:
        return await message.answer(f"{E('warning')} Tushunmadim. @username, -100... ID yoki forward yuboring.",
                                    reply_markup=cancel_kb())
    try:
        chat = await bot.get_chat(ident)
        me = await bot.get_chat_member(chat.id, bot.id)
    except Exception as e:
        return await message.answer(
            f"{E('error')} Kanal topilmadi yoki bot u yerda yo'q.\n<code>{html.escape(str(e)[:150])}</code>\n\n"
            "Botni kanalga admin qilib, qayta yuboring.", reply_markup=cancel_kb())
    if me.status not in ("administrator", "creator"):
        return await message.answer(f"{E('error')} Bot bu kanalda admin emas. Avval admin qiling, keyin qayta yuboring.",
                                    reply_markup=cancel_kb())

    link = f"https://t.me/{chat.username}" if chat.username else chat.invite_link
    if not link:
        try:
            link = await bot.export_chat_invite_link(chat.id)
        except Exception:
            return await message.answer(
                f"{E('error')} Taklif havolasini olib bo'lmadi. Botga «Invite users» huquqini bering.",
                reply_markup=cancel_kb())
    db.execute("INSERT OR REPLACE INTO channels (chat_id, title, link) VALUES (?, ?, ?)",
               (chat.id, chat.title or str(chat.id), link))
    db.commit()
    _sub_ok.clear()
    await state.clear()
    text, kb = channels_view()
    await message.answer(f"{E('ok')} <b>{html.escape(chat.title or '')}</b> qo'shildi!\n\n" + text,
                         reply_markup=kb, disable_web_page_preview=True)


# ---------------------------------------------------------------- 🚫 bloklash
def ban_view() -> tuple[str, InlineKeyboardMarkup]:
    rows = db.execute("SELECT user_id, name FROM users WHERE banned=1 ORDER BY last_seen DESC LIMIT 20").fetchall()
    lines = [f"{E('ban')} <b>Bloklash</b>\n\nBloklanganlar: <b>{len(_banned_cache)}</b>\n"]
    lines += [f"• <code>{uid}</code> — {html.escape(name or '')}" for uid, name in rows]
    lines.append("\nBloklangan foydalanuvchi botdan foydalana olmaydi.")
    kb = back_kb([[
        btn("ban", "Bloklash", "adm:banadd", "danger"),
        btn("unban", "Blokdan chiqarish", "adm:bandel", "success"),
    ]])
    return "\n".join(lines), kb


@dp.callback_query(F.data == "adm:ban", StateFilter("*"))
async def adm_ban(cb: CallbackQuery, state: FSMContext):
    if not is_admin_id(cb.from_user.id):
        return await cb.answer()
    await state.clear()
    text, kb = ban_view()
    await safe_edit(cb.message, text, kb)
    await cb.answer()


@dp.callback_query(F.data.in_({"adm:banadd", "adm:bandel"}))
async def adm_ban_ask(cb: CallbackQuery, state: FSMContext):
    if not is_admin_id(cb.from_user.id):
        return await cb.answer()
    adding = cb.data == "adm:banadd"
    await state.set_state(AdminSt.ban if adding else AdminSt.unban)
    await safe_edit(
        cb.message,
        f"{E('ban') if adding else E('unban')} <b>{'Bloklash' if adding else 'Blokdan chiqarish'}</b>\n\n"
        "Foydalanuvchining <b>ID raqamini</b> yuboring yoki uning xabarini forward qiling.",
        cancel_kb([[btn("back", "Orqaga", "adm:ban")]]),
    )
    await cb.answer()


@dp.message(StateFilter(AdminSt.ban, AdminSt.unban))
async def adm_ban_got(message: Message, state: FSMContext):
    if not is_admin(message):
        return
    uid = None
    if message.forward_origin and getattr(message.forward_origin, "sender_user", None):
        uid = message.forward_origin.sender_user.id
    elif message.text and message.text.strip().isdigit():
        uid = int(message.text.strip())
    if not uid:
        return await message.answer(f"{E('warning')} ID raqam yuboring (masalan: <code>123456789</code>).",
                                    reply_markup=cancel_kb())
    if is_admin_id(uid):
        return await message.answer(f"{E('warning')} Adminni bloklab bo'lmaydi.", reply_markup=cancel_kb())

    banning = await state.get_state() == AdminSt.ban.state
    db.execute("INSERT OR IGNORE INTO users (user_id, name, joined_at) VALUES (?, '', ?)", (uid, int(time.time())))
    db.execute("UPDATE users SET banned=? WHERE user_id=?", (1 if banning else 0, uid))
    db.commit()
    reload_banned()
    await state.clear()
    text, kb = ban_view()
    await message.answer(
        f"{E('ban') if banning else E('unban')} <code>{uid}</code> "
        f"{'bloklandi' if banning else 'blokdan chiqarildi'}.\n\n" + text,
        reply_markup=kb,
    )


# ================================================================ /ADMIN PANEL


# ================================================================ INSTAGRAM
# Foydalanuvchi Instagram havolasini yuborsa (reels, post, IGTV) -> video yuboriladi.
# Videolar alohida navbatda yuklanadi -> musiqa qismi sekinlashmaydi.
# Video tagida: "🎵 Musiqasini yuklash" (videodagi ovozni audio qilib beradi).

IG_RE = re.compile(
    r"https?://(?:www\.|m\.)?(?:instagram\.com|instagr\.am)/(?:[\w.]+/)?(reels?|p|tv|stories)/([\w-]+)", re.I
)
VIDEO_MAX = 49 * 1024 * 1024
video_sem = asyncio.Semaphore(int(os.getenv("VIDEO_PARALLEL", "3")))
IG_COOKIES = BASE_DIR / "instagram_cookies.txt"      # ixtiyoriy: yopiq/cheklangan postlar uchun
VID_DIR = DL_DIR / "video"
ig_meta: "OrderedDict[str, dict]" = OrderedDict()   # shortcode -> {"url", "query"}
video_locks: dict[str, asyncio.Lock] = {}

db.execute("CREATE TABLE IF NOT EXISTS media_cache (key TEXT PRIMARY KEY, data TEXT NOT NULL)")
db.commit()


def media_get(key: str) -> list | None:
    row = db.execute("SELECT data FROM media_cache WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def media_set(key: str, items: list) -> None:
    db.execute("INSERT OR REPLACE INTO media_cache VALUES (?, ?)", (key, json.dumps(items)))
    db.commit()


def remember_ig(key: str, **kw) -> None:
    ig_meta.setdefault(key, {}).update(kw)
    ig_meta.move_to_end(key)
    while len(ig_meta) > 3000:
        ig_meta.popitem(last=False)


def _ig_download(url: str, folder: str, audio_only: bool = False) -> tuple[list[Path], dict]:
    out = VID_DIR / folder
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    if audio_only:
        fmt = "ba[ext=m4a]/ba/b[ext=mp4]/b"
    elif _FFMPEG_FOUND:
        fmt = "b[ext=mp4][vcodec!=none][acodec!=none]/bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b"
    else:
        fmt = "b[ext=mp4][vcodec!=none][acodec!=none]/b[ext=mp4]/b"
    opts = ydl_opts(
        format=fmt,
        outtmpl=str(out / "%(autonumber)02d_%(id)s.%(ext)s"),
        merge_output_format="mp4",
        max_filesize=VIDEO_MAX,
        socket_timeout=20,
        retries=3,
        playlistend=10,
    )
    if IG_COOKIES.exists():
        opts["cookiefile"] = str(IG_COOKIES)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    ok_ext = {".mp4", ".mov", ".webm", ".m4a", ".mp3", ".jpg", ".jpeg", ".png", ".webp"}
    files = sorted(p for p in out.iterdir() if p.is_file() and p.suffix.lower() in ok_ext)
    return files, info


def ig_error_text(err: str) -> str:
    e = err.lower()
    if "login" in e or "cookie" in e or "rate" in e or "private" in e or "401" in e or "403" in e:
        if not IG_COOKIES.exists():
            log.warning("Instagram login so'radi. Barqaror ishlashi uchun bot papkasiga instagram_cookies.txt qo'ying.")
        return (f"{E('error')} Videoni olib bo'lmadi.\n"
                "Post <b>yopiq akkauntda</b> bo'lishi yoki Instagram vaqtincha cheklagan bo'lishi mumkin. "
                "Birozdan keyin qayta urinib ko'ring.")
    if "no video" in e or "there is no video" in e:
        return f"{E('notfound')} Bu postda video yo'q (faqat rasm)."
    return f"{E('error')} Videoni yuklab bo'lmadi. Havolani tekshirib, qayta yuboring."


def ig_keyboard(key: str) -> InlineKeyboardMarkup:
    rows = [[btn("music", "Musiqasini yuklash", f"igaud:{key}", "success")]]
    q = ig_meta.get(key, {}).get("query")
    if q:
        rows.append([btn("search", f"Qo'shiqni topish: {q[:30]}", f"igs:{key}", "primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ig_caption() -> str:
    return f"{E('video')} @{BOT_USERNAME}"


async def send_media_items(bot: Bot, chat_id: int, items: list, key: str):
    """items: [["video"|"photo", file_id_yoki_Path, {width,height,duration}], ...]"""
    kb = ig_keyboard(key)
    if len(items) == 1:
        kind, media, meta = items[0]
        media = FSInputFile(media) if isinstance(media, Path) else media
        if kind == "photo":
            return [await bot.send_photo(chat_id, media, caption=ig_caption(), reply_markup=kb)]
        return [await bot.send_video(chat_id, media, caption=ig_caption(), reply_markup=kb,
                                     supports_streaming=True, **(meta or {}))]
    group = []
    for i, (kind, media, meta) in enumerate(items[:10]):
        media = FSInputFile(media) if isinstance(media, Path) else media
        cap = ig_caption() if i == 0 else None
        group.append(InputMediaPhoto(media=media, caption=cap) if kind == "photo"
                     else InputMediaVideo(media=media, caption=cap, supports_streaming=True, **(meta or {})))
    msgs = await bot.send_media_group(chat_id, group)
    await bot.send_message(chat_id, f"{E('video')} Yana:", reply_markup=kb)
    return msgs


def _meta(info: dict) -> dict:
    m = {}
    for k in ("width", "height", "duration"):
        if info.get(k):
            m[k] = int(info[k])
    return m


async def handle_instagram(message: Message, bot: Bot, url: str, key: str):
    remember_ig(key, url=url)
    log_event(message.from_user.id, "video", key)
    ck = f"ig:{key}"

    cached = media_get(ck)
    if cached:
        try:
            await send_media_items(bot, message.chat.id, cached, key)
            return
        except Exception as e:
            log.warning("Keshdagi video ishlamadi %s: %s", key, e)

    status = await message.answer(f"{E('loading')} Video yuklanmoqda...")
    await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
    lock = video_locks.setdefault(key, asyncio.Lock())
    async with lock, video_sem:
        cached = media_get(ck)                    # kutib turganda boshqasi yuklagan bo'lishi mumkin
        if cached:
            await status.delete()
            await send_media_items(bot, message.chat.id, cached, key)
            return
        t0 = time.perf_counter()
        try:
            files, info = await asyncio.to_thread(_ig_download, url, key)
        except Exception as e:
            log.error("Instagram %s: %s", key, str(e)[:300])
            await status.edit_text(ig_error_text(str(e)))
            return
        try:
            if not files:
                await status.edit_text(f"{E('error')} Video juda katta (50 MB dan ortiq) yoki topilmadi.")
                return
            track, artist = info.get("track"), info.get("artist") or info.get("creator")
            if track:
                remember_ig(key, query=f"{artist} {track}".strip() if artist else track)

            entries = [e for e in (info.get("entries") or []) if e] or [info]
            items = []
            for i, f in enumerate(files[:10]):
                kind = "photo" if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") else "video"
                meta = _meta(entries[i]) if i < len(entries) and kind == "video" else {}
                items.append([kind, f, meta])
            t1 = time.perf_counter()
            msgs = await send_media_items(bot, message.chat.id, items, key)
            await status.delete()

            saved = []
            for (kind, _, meta), m in zip(items, msgs):
                fid = m.video.file_id if m.video else (m.photo[-1].file_id if m.photo else None)
                if fid:
                    saved.append([kind, fid, meta])
            if len(saved) == len(items):
                media_set(ck, saved)
            log.info("⏱ Instagram %s | olish: %.1fs | yuborish: %.1fs", key, t1 - t0, time.perf_counter() - t1)
        except Exception as e:
            log.exception("Instagram yuborish xatosi %s: %s", key, e)
            try:
                await status.edit_text(f"{E('error')} Videoni yuborib bo'lmadi (hajmi katta bo'lishi mumkin).")
            except Exception:
                pass
        finally:
            shutil.rmtree(VID_DIR / key, ignore_errors=True)


@dp.callback_query(F.data.startswith("igaud:"))
async def on_ig_audio(cb: CallbackQuery, bot: Bot):
    key = cb.data.split(":", 1)[1]
    ck = f"igaudio:{key}"
    await cb.answer("🎵 Musiqa tayyorlanmoqda...")
    cached = cache_get(ck)
    if cached:
        await bot.send_audio(cb.message.chat.id, cached, caption=f"{E('headphones')} @{BOT_USERNAME}")
        return
    url = ig_meta.get(key, {}).get("url") or f"https://www.instagram.com/p/{key}/"
    status = await bot.send_message(cb.message.chat.id, f"{E('loading')} Musiqa ajratilmoqda...")
    folder = f"{key}_audio"
    async with video_sem:
        try:
            files, info = await asyncio.to_thread(_ig_download, url, folder, True)
            audio = next((f for f in files if f.suffix.lower() in (".m4a", ".mp3", ".mp4")), None)
            if not audio:
                await status.edit_text(f"{E('error')} Bu videoda musiqa topilmadi.")
                return
            title = info.get("track") or "Instagram audio"
            performer = info.get("artist") or info.get("uploader") or info.get("channel") or None
            m = await bot.send_audio(
                cb.message.chat.id,
                FSInputFile(audio, filename=f"{(performer or 'instagram')} - {title}"[:90] + audio.suffix),
                title=title[:64], performer=performer[:64] if performer else None,
                duration=int(info.get("duration") or 0) or None,
                caption=f"{E('headphones')} @{BOT_USERNAME}",
            )
            if m.audio:
                cache_set(ck, m.audio.file_id)
            await status.delete()
        except Exception as e:
            log.error("Instagram audio %s: %s", key, str(e)[:300])
            await status.edit_text(ig_error_text(str(e)))
        finally:
            shutil.rmtree(VID_DIR / folder, ignore_errors=True)


@dp.callback_query(F.data.startswith("igs:"))
async def on_ig_search(cb: CallbackQuery, bot: Bot):
    key = cb.data.split(":", 1)[1]
    query = ig_meta.get(key, {}).get("query")
    if not query:
        return await cb.answer("Qo'shiq nomi topilmadi.", show_alert=True)
    await cb.answer("🔍 Qidirilmoqda...")
    log_event(cb.from_user.id, "search", query)
    items = cache_lookup(query) or await search_songs(query, FAST_LIMIT)
    if not items:
        return await bot.send_message(cb.message.chat.id, f"{E('notfound')} Hech narsa topilmadi.")
    sid = save_search(query, list(items))
    await bot.send_message(cb.message.chat.id, list_text(query, items, 0), reply_markup=list_keyboard(sid, items, 0))
    prefetch(items)


# ================================================================ /INSTAGRAM


@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        f"{E('hello')} Assalomu alaykum, <b>{html.escape(message.from_user.first_name)}</b>! {E('headphones')}\n\n"
        "Qo'shiqchi ismini yoki qo'shiq nomini yozing —\n"
        f"men qo'shiqlar ro'yxatini chiqaraman {E('music')}\n\n"
        f"{E('video')} Instagram havolasini yuborsangiz — videoni yuklab beraman\n\n"
        "<i>Masalan: Shahzoda</i>"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        f"{E('help')} <b>Qanday ishlatiladi</b>\n\n"
        "1️⃣ Qo'shiqchi ismi yoki qo'shiq nomini yozing\n"
        "2️⃣ 10 talik ro'yxat chiqadi, ⬅️ ➡️ bilan varaqlang\n"
        f"3️⃣ Qo'shiqni bosing — audio fayl keladi {E('ok')}\n\n"
        f"{E('video')} <b>Instagram</b>: reels yoki post havolasini yuboring — video keladi.\n"
        "Video tagidagi «Musiqasini yuklash» tugmasi videodagi musiqani audio qilib beradi."
    )


@dp.message(Command("emoji_reload"))
async def cmd_emoji_reload(message: Message):
    if not is_admin(message):
        return
    load_emojis()
    await message.answer(f"{E('ok')} emojis.json qayta yuklandi. Faol premium emojilar: <b>{len(EMOJI_IDS)}</b>")


@dp.message(Command("emoji"))
async def cmd_emoji(message: Message):
    if not is_admin(message):
        return
    lines = [f"<b>Emoji sozlamalari</b> (faol: {len(EMOJI_IDS)}/{len(DEFAULT_EMOJI)})\n"]
    for k, v in DEFAULT_EMOJI.items():
        lines.append(f"{E(k)} <code>{k}</code> — {'✅' if k in EMOJI_IDS else '—'}")
    lines.append("\nPremium emoji yuboring — ID sini aytaman.")
    await message.answer("\n".join(lines))


@dp.message(lambda m: bool(m.entities or m.caption_entities)
            and any(e.type == "custom_emoji" for e in (m.entities or m.caption_entities or [])))
async def on_custom_emoji(message: Message, bot: Bot):
    """Admin premium emoji yuborsa - ularning ID larini qaytaradi."""
    if not is_admin(message):
        return await on_text(message, bot)
    text = message.text or message.caption or ""
    raw = text.encode("utf-16-le")
    lines = ["<b>Premium emoji ID lari:</b>\n"]
    for e in (message.entities or message.caption_entities):
        if e.type != "custom_emoji":
            continue
        ch = raw[e.offset * 2 : (e.offset + e.length) * 2].decode("utf-16-le")
        lines.append(f'<tg-emoji emoji-id="{e.custom_emoji_id}">{ch}</tg-emoji> <code>{e.custom_emoji_id}</code>')
    lines.append("\nID ni nusxalab, <code>emojis.json</code> ga qo'ying va /emoji_reload yuboring.")
    await message.answer("\n".join(lines))


@dp.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message, bot: Bot):
    ig = IG_RE.search(message.text)
    if ig:
        url = ig.group(0)
        await handle_instagram(message, bot, url, ig.group(2))
        return
    query = message.text.strip()[:100]
    if len(query) < 2:
        await message.answer(f"{E('write')} Qo'shiq nomini to'liqroq yozing.")
        return

    # 1) shu so'z yaqinda qidirilgan bo'lsa - bir zumda
    log_event(message.from_user.id, "search", query)
    cached = cache_lookup(query)
    if cached:
        sid = save_search(query, list(cached))
        await message.answer(list_text(query, cached, 0), reply_markup=list_keyboard(sid, cached, 0))
        prefetch(cached)
        return

    status = await message.answer(f"{E('search')} Qidirilmoqda...")
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        items = await search_songs(query, FAST_LIMIT)   # 2) tez: faqat 1 ta so'rov
    except Exception as e:
        log.exception("Qidiruv xatosi: %s", e)
        await status.edit_text(f"{E('error')} Xatolik yuz berdi. Birozdan keyin qayta urinib ko'ring.")
        return

    if not items:
        await status.edit_text(f"{E('notfound')} Hech narsa topilmadi. Boshqacha yozib ko'ring.")
        return

    sid = save_search(query, items)
    await status.edit_text(list_text(query, items, 0), reply_markup=list_keyboard(sid, items, 0))
    prefetch(items)
    # 3) qolganlari fonda yuklanadi - foydalanuvchi ➡️ bosguncha tayyor bo'ladi
    if len(items) >= FAST_LIMIT - 5:
        asyncio.create_task(load_more(sid, query))
    else:
        cache_store(query, items)


@dp.callback_query(F.data.startswith("p:"))
async def on_page(cb: CallbackQuery):
    _, sid, page = cb.data.split(":")
    s = searches.get(sid)
    if not s:
        await cb.answer("Bu ro'yxat eskirgan, qaytadan qidiring.", show_alert=True)
        return
    page = int(page)
    try:
        await cb.message.edit_text(
            list_text(s["query"], s["items"], page),
            reply_markup=list_keyboard(sid, s["items"], page),
        )
    except Exception:
        pass  # bitta sahifa bo'lsa "o'zgarmadi" xatosi chiqadi
    await cb.answer()
    prefetch(s["items"][page * PAGE_SIZE :])


@dp.callback_query(F.data.startswith("s:"))
async def on_song(cb: CallbackQuery, bot: Bot):
    _, sid, idx = cb.data.split(":")
    s = searches.get(sid)
    if not s:
        await cb.answer("Bu ro'yxat eskirgan, qaytadan qidiring.", show_alert=True)
        return
    song = s["items"][int(idx)]
    await cb.answer("🎵 " + song["title"][:50])
    log_event(cb.from_user.id, "download", f"{song['artist']} - {song['title']}".strip(" -"))
    asyncio.create_task(send_song(bot, cb.message.chat.id, song))


@dp.callback_query(F.data == "noop")
async def on_noop(cb: CallbackQuery):
    await cb.answer()


@dp.callback_query(F.data == "close")
async def on_close(cb: CallbackQuery):
    try:
        await cb.message.delete()
    except Exception:
        pass
    await cb.answer()


@dp.message()
async def on_other(message: Message):
    await message.answer(f"{E('write')} Qo'shiq nomi yoki qo'shiqchi ismini yozing.")


def _warmup():
    """Ishga tushganda YouTube pleer ma'lumotlarini oldindan keshlaydi -> birinchi yuklash tezroq."""
    try:
        res = ytm.search("music", filter="songs", limit=1)
        if res and res[0].get("videoId"):
            with yt_dlp.YoutubeDL(ydl_opts(skip_download=True, cachedir=str(BASE_DIR / ".ytdlp_cache"))) as ydl:
                ydl.extract_info(f"https://www.youtube.com/watch?v={res[0]['videoId']}", download=False)
        log.info("Tayyor: YouTube keshi qizdirildi ✅")
    except Exception as e:
        log.warning("Warmup o'tmadi (muhim emas): %s", str(e)[:150])


async def main():
    global BOT_USERNAME
    if not ADMINS:
        log.warning("ADMIN_ID .env da yozilmagan — /admin panel ishlamaydi.")
    if not BOT_TOKEN or BOT_TOKEN == "BU_YERGA_TOKEN":
        raise SystemExit("❗ .env fayliga BOT_TOKEN yozing (@BotFather dan oling).")
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    me = await bot.me()
    BOT_USERNAME = me.username
    log.info(
        "Bot ishga tushdi: @%s | format: %s | proxy: %s",
        me.username, "mp3" if HAS_FFMPEG else "m4a", PROXY or "yo'q",
    )
    reload_banned()
    dp.message.outer_middleware(GateMiddleware())
    dp.callback_query.outer_middleware(GateMiddleware())
    await bot.set_my_commands([BotCommand(command="start", description="Botni ishga tushirish"),
                               BotCommand(command="help", description="Yordam")])
    await bot.delete_webhook(drop_pending_updates=True)
    for f in DL_DIR.glob("*"):          # oldingi ishga tushirishdan qolgan fayllar
        if f.is_dir():
            shutil.rmtree(f, ignore_errors=True)
        else:
            f.unlink(missing_ok=True)
    asyncio.create_task(asyncio.to_thread(_warmup))
    asyncio.create_task(prefetch_janitor())
    asyncio.create_task(emoji_watcher())
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as e:
        if str(e):
            print(e)
