import os
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
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    InlineQueryHandler, ContextTypes, filters
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
    # Mendukung hingga 20 akun session (acc1.session - acc20.session)
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
    
    # Menyesuaikan kapasitas kerja paralel dengan jumlah akun Telethon
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
                except:
                    return None
            return None

    results = await asyncio.gather(*(worker(u) for u in usernames))
    return [r for r in results if r]

# ================== INLINE HANDLER ==================
# ================== INLINE HANDLER ==================
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
                description="Anjay, tamping anjay, uncommon anjay, tamdal anjay, rata anjay, ganhur anjay, dll",
                input_message_content=InputTextMessageContent(
                    "Contoh penggunaan:\n"
                    "anjay (scan tamhur)\n"
                    "tamping anjay (Scan tamping)\n"
                    "tamdal anjay (Scan tamdal)\n"
                    "dkk"
                )
            )
        ]
        await update.inline_query.answer(results, cache_time=1)
        return

    parts = query.split(maxsplit=1)
    
    # 1. Pengecekan Mode Spesifik (misal: @bot switch anya / @bot tamping anya)
    if parts[0].lower() in GENERATORS and len(parts) > 1:
        mode_key = parts[0].lower()
        target_generators = {mode_key: GENERATORS[mode_key]}
        base = parts[1].replace("@", "")
        LIMIT_CANDIDATES = 150
        scan_title = f"Scan {GENERATORS[mode_key][1]}"

    # 2. Mode Direct / Langsung (misal: @bot anya) -> KHUSUS TAMHUR
    else:
        target_generators = {"tamhur":["tamhur"]}
        base = query.replace("@", "")
        LIMIT_CANDIDATES = 150  # Limit tinggi karena fokus ke 1 metode
        scan_title = "Scan tamhur"

    if not clients:
        text_res = "❌ Tidak ada acc aktif untuk scan."
    else:
        sections = []
        
        for key, (gen_func, lbl) in target_generators.items():
            raw_res = gen_func(base)
            if key == "uncommon":
                raw_res += gen_canon(base)
            
            # Mengambil hingga 150 kandidat
            candidates = list(set(raw_res))[:LIMIT_CANDIDATES]
            avail = await check_usernames_fast(candidates)
            
            if avail:
                sections.append(f"<b>{lbl.upper()} ({len(avail)}):</b>\n" + "\n".join(avail))

        if sections:
            text_res = f"HASIL SCAN UNTUK @{base}\n\n" + "\n\n".join(sections)
        else:
            text_res = f"❌ Gak ada atau gak akun gua yang limit jadi ga nemu"

    # Potong pesan jika melebihi batas karakter Telegram (4096)
    if len(text_res) > 4000:
        text_res = text_res[:3900] + "\n\n⚠️ Hasil dipotong karena melebihi batas panjang pesan Telegram."

    results = [
        InlineQueryResultArticle(
            id=f"scan_{base}_{int(time.time())}",
            title=f"{scan_title} untuk @{base}",
            description=f"Memeriksa hingga {LIMIT_CANDIDATES} variasi username",
            input_message_content=InputTextMessageContent(text_res, parse_mode="HTML")
        )
    ]
    await update.inline_query.answer(results, cache_time=1)
    
    # Pengaturan Mode Spesifik vs Mode All-in-One
    if parts[0].lower() in GENERATORS and len(parts) > 1:
        target_generators = {parts[0].lower(): GENERATORS[parts[0].lower()]}
        base = parts[1].replace("@", "")
        LIMIT_PER_TYPE = 150 # Limit besar jika memilih 1 tipe saja
    else:
        target_generators = {
            k: GENERATORS[k] for k in ["tamping", "tamhur", "ganhur", "uncommon", "switch", "rata", "kurhur"]
        }
        base = query.replace("@", "")
        LIMIT_PER_TYPE = 50  # 50 kandidat per tipe (Total ~350 kandidat diproses sekali klik)

    if not clients:
        text_res = "❌ Tidak ada acc aktif untuk scan."
    else:
        sections = []
        
        for key, (gen_func, lbl) in target_generators.items():
            raw_res = gen_func(base)
            if key == "uncommon":
                raw_res += gen_canon(base)
            
            candidates = list(set(raw_res))[:LIMIT_PER_TYPE]
            avail = await check_usernames_fast(candidates)
            
            if avail:
                sections.append(f"<b>{lbl.upper()} ({len(avail)}):</b>\n" + "\n".join(avail))

        if sections:
            text_res = f"HASIL SCAN UNTUK @{base}\n\n" + "\n\n".join(sections)
        else:
            text_res = f"❌ Ga ada atau gak akun gua limit jadi gak nemu"

    # Potong pesan jika melebihi batas karakter Telegram (4096)
    if len(text_res) > 4000:
        text_res = text_res[:3900] + "\n\n⚠️ Hasil dipotong karena melebihi batas panjang pesan Telegram."

    results = [
        InlineQueryResultArticle(
            id=f"scan_{base}_{int(time.time())}",
            title=f"Scan @{base}",
            description=f"Memeriksa puluhan hingga ratusan variasi username untuk @{base}",
            input_message_content=InputTextMessageContent(text_res, parse_mode="HTML")
        )
    ]
    await update.inline_query.answer(results, cache_time=1)

# ================== COMMAND HANDLERS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in BANNED_USERS: return
    save_user(user.id)
    await update.message.reply_text("Punya @rsunless")

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

    logger.info("🚀 Bot berjalan...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
