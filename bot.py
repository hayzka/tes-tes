import string
import time
import logging
import re
import asyncio

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Load dotenv jika dijalankan secara lokal
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from telethon import TelegramClient, functions
from telethon.errors import FloodWaitError
from telegram import (
    Update, InlineQueryResultArticle, InputTextMessageContent,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    InlineQueryHandler, CallbackQueryHandler, ContextTypes, filters
)

# Configuration from Environment Variables
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DATA_DIR = "./" 
BAN_FILE = f"{DATA_DIR}banned.txt"
USER_FILE = f"{DATA_DIR}users.txt"

BANNED_USERS = set()
clients = []
client_cooldown = {}
running_tasks = {}
client_index = 0
ALL_USERS = set()

# Temporary Cache untuk Menyimpan Hasil Scan per Message ID untuk Pagination
# Format: { inline_message_id: { "pages": [str_page1, str_page2, ...], "current_page": 0, "base": str } }
SCAN_CACHE = {}

# ================== PERSISTENCE ==================
def load_users():
    if os.path.exists(USER_FILE):
        with open(USER_FILE, "r") as f:
            for line in f:
                if line.strip(): ALL_USERS.add(int(line.strip()))

def save_user(user_id):
    if user_id not in ALL_USERS:
        ALL_USERS.add(user_id)
        with open(USER_FILE, "a") as f:
            f.write(f"{user_id}\n")

def load_bans():
    if os.path.exists(BAN_FILE):
        with open(BAN_FILE, "r") as f:
            for line in f:
                if line.strip(): BANNED_USERS.add(int(line.strip()))

def save_ban(user_id):
    BANNED_USERS.add(user_id)
    with open(BAN_FILE, "a") as f:
        f.write(f"{user_id}\n")

# ================== GENERATORS ==================
rata, tdk_rata, vokal = "asweruiozxcvnm", "qtypdfghjklb", "aeiou"

def gen_tamhur(b): return list({b[:i] + l + b[i:] for i in range(len(b)+1) for l in string.ascii_lowercase})
def gen_tamping(b): return list({l + b for l in string.ascii_lowercase} | {b + l for l in string.ascii_lowercase})
def gen_switch(b):
    res = set()
    for i in range(len(b) - 1):
        lst = list(b); lst[i], lst[i+1] = lst[i+1], lst[i]; res.add("".join(lst))
    return list(res)
def gen_uncommon(b): return list({b[:i] + b[i] + b[i:] for i in range(len(b))}) if b else []
def gen_ganhur(b): return list({b[:i] + l + b[i+1:] for i in range(len(b)) for l in string.ascii_lowercase})
def gen_kurhur(b): return list({b[:i] + b[i+1:] for i in range(len(b))}) if len(b) > 1 else []
def gen_canon(b):
    res = {b + 's'}; m = {'i': 'l', 'l': 'i'}
    for i, char in enumerate(b):
        if char in m: res.add(b[:i] + m[char] + b[i+1:])
    return list(res)
def gen_rata(b): return list({b[:i] + l + b[i:] for i in range(len(b)+1) for l in rata})
def gen_tidakrata(b): return list({b[:i] + l + b[i:] for i in range(len(b)+1) for l in tdk_rata})
def gen_vokal(b): return list({b[:i] + l + b[i:] for i in range(len(b)+1) for l in vokal})

GENERATORS = {
    "switch": (gen_switch, "Switch"),
    "tamping": (gen_tamping, "Tamping"),
    "tamhur": (gen_tamhur, "Tamhur"),
    "ganhur": (gen_ganhur, "Ganhur"),
    "uncommon": (gen_uncommon, "Uncommon"),
    "kurhur": (gen_kurhur, "Kurhur"),
    "rata": (gen_rata, "Rata"),
    "tidakrata": (gen_tidakrata, "Tidak Rata"),
    "vokal": (gen_vokal, "Vokal"),
}

# ================== CORE LOGIC ==================
async def init_clients():
    if not API_ID or not API_HASH: 
        logger.error("❌ API_ID atau API_HASH kosong!")
        return
    for i in range(1, 21):
        s = f"{DATA_DIR}acc{i}"
        try:
            c = TelegramClient(s, int(API_ID), API_HASH)
            await c.connect()
            if await c.is_user_authorized():
                clients.append(c)
                client_cooldown[c] = 0
                logger.info(f"✅ acc{i} Ready")
            else: 
                await c.disconnect()
        except Exception as e: 
            pass

def get_available_client():
    global client_index
    now = time.time()
    available = [c for c in clients if client_cooldown[c] <= now]
    if not available: return None
    client = available[client_index % len(available)]
    client_index += 1
    return client

async def check_usernames_fast(usernames):
    if not usernames or not clients:
        return []
    
    sem = asyncio.Semaphore(len(clients) * 3)
    
    async def worker(u):
        async with sem:
            for _ in range(2):
                c = get_available_client()
                if not c:
                    await asyncio.sleep(0.1)
                    continue
                try:
                    ok = await c(functions.account.CheckUsernameRequest(u))
                    await asyncio.sleep(0.15)
                    if ok: return f"🟢 @{u}"
                    return None
                except FloodWaitError as e:
                    client_cooldown[c] = time.time() + e.seconds
                    continue
                except Exception:
                    return None
            return None

    results = await asyncio.gather(*(worker(u) for u in usernames))
    return [r for r in results if r]

# Helper Function untuk Membagi List Hasil Menjadi Beberapa Halaman (Pagination)
def chunk_results(items, chunk_size=15):
    return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]

def build_pagination_keyboard(current_page, total_pages, target_base, mode_key):
    if total_pages <= 1:
        return None
    
    buttons = []
    for i in range(total_pages):
        label = f"• {i+1} •" if i == current_page else f"{i+1}"
        # Callback data format: page_mode_base_pageIndex
        buttons.append(InlineKeyboardButton(label, callback_data=f"page_{mode_key}_{target_base}_{i}"))
    
    return InlineKeyboardMarkup([buttons])

# ================== INLINE HANDLER (INSTANT CLICK) ==================
async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip()
    uid = update.inline_query.from_user.id

    if uid in BANNED_USERS:
        return

    save_user(uid)

    if not query:
        results = [
            InlineQueryResultArticle(
                id="help",
                title="misal",
                description="anjay, tamping anjay, tamdal anjay, uncommon anjay, ganhur anjay, dll",
                input_message_content=InputTextMessageContent(
                    "Contoh penggunaan:\n"
                    "`Adnan` buat scan tamhur biasa\n"
                    "`<spesifik> adnan` buat scan yang spesifik"
                )
            )
        ]
        await update.inline_query.answer(results, cache_time=1)
        return

    parts = query.split(maxsplit=1)
    
    if parts[0].lower() in GENERATORS and len(parts) > 1:
        mode_key = parts[0].lower()
        base = parts[1].replace("@", "")
        mode_label = GENERATORS[mode_key][1]
    else:
        mode_key = "tamhur"
        base = query.replace("@", "")
        mode_label = "Tamhur"

    # Pesan Awal (Langsung terkirim saat diklik di inline, tanpa nunggu scan)
    initial_text = (
        f"⏳ MEMULAI SCAN UNTUK @{base}\n"
        f"Mode: {mode_label}\n\n"
        f"Tunggu bentar, akun sedang memeriksa ketersediaan..."
    )

    # Tombol interaktif awal
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔎 Mulai proses...", callback_data=f"startscan_{mode_key}_{base}")
    ]])

    results = [
        InlineQueryResultArticle(
            id=f"init_{base}_{int(time.time())}",
            title=f"Mulai Scan @{base} ({mode_label})",
            description=f"Klik buat nyari @{base}",
            input_message_content=InputTextMessageContent(initial_text, parse_mode="HTML"),
            reply_markup=keyboard
        )
    ]
    await update.inline_query.answer(results, cache_time=1)

# ================== CALLBACK QUERY HANDLER (LIVE UPDATE & PAGINATION) ==================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    inline_msg_id = query.inline_message_id

    # 1. Trigger Mulai Scan Secara Otomatis / Manual
    if data.startswith("startscan_"):
        _, mode_key, base = data.split("_", 2)
        await query.answer("Memulai scan...")

        if not clients:
            await context.bot.edit_message_text(
                inline_message_id=inline_msg_id,
                text="❌ ERROR: akun gua yang error anjay, coba chat akun gw",
                parse_mode="HTML"
            )
            return

        # Update Tampilan ke Mode Scanning Active
        await context.bot.edit_message_text(
            inline_message_id=inline_msg_id,
            text=f"🔄 SEDANG MENCARI VARIASI @{base}...\n\nSistem sedang memproses username...",
            parse_mode="HTML"
        )

        gen_func, lbl = GENERATORS[mode_key]
        raw_res = gen_func(base)
        if mode_key == "uncommon":
            raw_res += gen_canon(base)

        candidates = list(set(raw_res))[:150] # Mengambil hingga 150 kandidat

        # Melakukan Scanning
        avail = await check_usernames_fast(candidates)

        if not avail:
            text_res = f"❌ Ga ada usn {lbl} yang tersedia buat @{base} (atau gak akun gw lagi limit)"
            await context.bot.edit_message_text(
                inline_message_id=inline_msg_id,
                text=text_res,
                parse_mode="HTML"
            )
            return

        # Pecah Hasil menjadi Beberapa Halaman (Pagination)
        pages = chunk_results(avail, chunk_size=15)
        
        # Simpan Cache untuk Navigasi Halaman
        SCAN_CACHE[inline_msg_id] = {
            "pages": pages,
            "mode_label": lbl,
            "base": base,
            "mode_key": mode_key
        }

        # Format Tampilan Halaman Pertama (Page 0)
        page_text = (
            f"HASIL SCAN @{base} ({lbl})\n"
            f"Total Ditemukan: <b>{len(avail)} Username\n\n" + 
            "\n".join(pages[0])
        )
        
        reply_markup = build_pagination_keyboard(0, len(pages), base, mode_key)

        await context.bot.edit_message_text(
            inline_message_id=inline_msg_id,
            text=page_text,
            parse_mode="HTML",
            reply_markup=reply_markup
        )

    # 2. Handler Pindah Halaman (Pagination Click 1, 2, 3...)
    elif data.startswith("page_"):
        _, mode_key, base, page_idx = data.split("_", 3)
        page_idx = int(page_idx)

        if inline_msg_id not in SCAN_CACHE:
            await query.answer("⚠️ Scan ini sudah kadaluarsa. Silakan lakukan scan baru.", show_alert=True)
            return

        cache_data = SCAN_CACHE[inline_msg_id]
        pages = cache_data["pages"]
        lbl = cache_data["mode_label"]

        if page_idx >= len(pages):
            await query.answer()
            return

        page_text = (
            f"HASIL SCAN @{base} ({lbl}) - {page_idx + 1}/{len(pages)}\n\n" + 
            "\n".join(pages[page_idx])
        )

        reply_markup = build_pagination_keyboard(page_idx, len(pages), base, mode_key)

        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_msg_id,
                text=page_text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
            await query.answer(f" {page_idx + 1}")
        except Exception:
            await query.answer()

# ================== COMMAND HANDLERS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in BANNED_USERS: return
    save_user(user.id)
    await update.message.reply_text("P anjay")

async def post_init(application):
    logger.info("⚙️ Inisialisasi Telethon sessions...")
    await init_clients()
    logger.info(f"📊 Total akun aktif: {len(clients)} akun.")

def main():
    load_bans()
    load_users()
    
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN tidak ditemukan di Environment Variable!")
        return
        
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("🚀 Bot berjalan...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
