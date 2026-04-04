import asyncio
import os
import string
import time
import logging
import random
import nest_asyncio
from telethon import TelegramClient, functions
from telethon.errors import FloodWaitError
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ================== LOGGING ==================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================== CONFIG ==================
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
PASSWORD = os.getenv("PASSWORD", "hi")
ADMIN_ID = os.getenv("ADMIN_ID") 

# Lokasi session. Pastikan folder ini ada atau hapus '/data/' jika tidak pakai Volume.
SESSION_DIR = "/data/" if os.path.exists("/data") else "./"
SESSIONS = [f"{SESSION_DIR}acc{i}" for i in range(1, 11)]

AUTHORIZED_USERS = set()
clients = []
client_cooldown = {}
running_tasks = {}
monitor_tasks = {}
client_index = 0

# ================== GENERATORS ==================
def gen_tamhur(b):
    letters = string.ascii_lowercase
    return list({b[:i] + l + b[i:] for i in range(len(b)+1) for l in letters})
    
def gen_tamping(b):
    letters = string.ascii_lowercase
    return list({l + b for l in letters} | {b + l for l in letters})

def gen_switch(b):
    res = set()
    for i in range(len(b) - 1):
        lst = list(b)
        lst[i], lst[i+1] = lst[i+1], lst[i]
        res.add("".join(lst))
    return list(res)

def gen_uncommon(b):
    if not b: return []
    return list({b[:i] + b[i] + b[i:] for i in range(len(b))})

def gen_ganhur(b):
    letters = string.ascii_lowercase
    return list({b[:i] + l + b[i+1:] for i in range(len(b)) for l in letters})

def gen_kurhur(b):
    if len(b) <= 1: return []
    return list({b[:i] + b[i+1:] for i in range(len(b))})

def gen_canon(b):
    res = {b + 's'}
    mapping = {'i': 'l', 'l': 'i'}
    for i, char in enumerate(b):
        if char in mapping:
            res.add(b[:i] + mapping[char] + b[i+1:])
    return list(res)

rata, tdk_rata, vokal = "asweruiozxcvnm", "qtypdfghjklb", "aeiou"

def gen_rata(b): return list({b[:i] + l + b[i:] for i in range(len(b)+1) for l in rata})
def gen_tidakrata(b): return list({b[:i] + l + b[i:] for i in range(len(b)+1) for l in tdk_rata})
def gen_vokal(b): return list({b[:i] + l + b[i:] for i in range(len(b)+1) for l in vokal})
def gen_tampingrata(b): return list({l + b for l in rata} | {b + l for l in rata})
def gen_tampingtidakrata(b): return list({l + b for l in tdk_rata} | {b + l for l in tdk_rata})
def gen_tamdal(b): return list({b[:i] + l + b[i:] for i in range(1, len(b)) for l in string.ascii_lowercase}) if len(b) >= 2 else []
def gen_tamdalrata(b): return list({b[:i] + l + b[i:] for i in range(1, len(b)) for l in rata}) if len(b) >= 2 else []
def gen_tamdaltidakrata(b): return list({b[:i] + l + b[i:] for i in range(1, len(b)) for l in tdk_rata}) if len(b) >= 2 else []
def gen_cadel(b): return list({b[:i] + l + b[i:] for i in range(len(b)+1) for l in "wycl"})

# ================== CORE LOGIC ==================
async def init_clients():
    if not API_ID or not API_HASH: 
        logger.error("❌ API_ID/HASH is missing!")
        return
    
    # Tunggu sebentar agar instance lama di Railway benar-benar mati
    await asyncio.sleep(10)
    
    for s in SESSIONS:
        if not os.path.exists(f"{s}.session"):
            logger.warning(f"⚠️ File {s}.session tidak ditemukan. Skip.")
            continue
            
        try:
            c = TelegramClient(s, int(API_ID), API_HASH)
            await c.connect()
            if not await c.is_user_authorized():
                logger.error(f"❌ {s} Unauthorized! Perlu login ulang.")
                continue
            
            clients.append(c)
            client_cooldown[c] = 0
            logger.info(f"✅ {s} Berhasil Konek!")
        except Exception as e:
            logger.error(f"❌ {s} Error: {e}")

async def send_log(context: ContextTypes.DEFAULT_TYPE, message: str):
    if not ADMIN_ID: return
    try:
        await context.bot.send_message(chat_id=int(ADMIN_ID), text=message, parse_mode='HTML')
    except: pass

# ================== AUTH & COMMANDS ==================
def auth(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id not in AUTHORIZED_USERS:
            if user: await update.message.reply_text("/login dulu.")
            return
        return await func(update, context)
    return wrapper

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0] == PASSWORD:
        AUTHORIZED_USERS.add(update.effective_user.id)
        await update.message.reply_text("Slmt")
    else:
        await update.message.reply_text("Salah")

@auth
async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Gunakan: /check [user]")
    base = context.args[0].replace("@", "")
    await update.message.reply_text(f"🔍 Scanning variations for @{base}...")
    
    if not clients:
        return await update.message.reply_text("❌ Tidak ada akun (session) yang aktif.")

    variants = gen_tamhur(base)[:100]
    
    # Fungsi pengecekan manual (fast)
    tasks = []
    sem = asyncio.Semaphore(5)
    
    async def worker(u):
        async with sem:
            cl = clients[random.randint(0, len(clients)-1)]
            try:
                ok = await cl(functions.account.CheckUsernameRequest(u))
                return f"🟢 @{u}" if ok else None
            except: return None

    results = await asyncio.gather(*(worker(v) for v in variants))
    available = [r for r in results if r]
    
    text = "<b>✅ AVAILABLE:</b>\n\n" + "\n".join(available) if available else "<b>❌ TIDAK ADA.</b>"
    await update.message.reply_text(text, parse_mode='HTML')

# ================== MAIN RUNNER ==================
async def main():
    await init_clients()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("check", check))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("keep", keep))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("monitor", monitor))
    app.add_handler(CommandHandler("unmonitor", unmonitor))

    scans = [
        ("scantamping", gen_tamping, "Tamping"), ("scanswitch", gen_switch, "Switch"),
        ("scantamhur", gen_tamhur, "Tamhur"), ("scanganhur", gen_ganhur, "Ganhur"),
        ("scanuncommon", gen_uncommon, "Uncommon"), ("scankurhur", gen_kurhur, "Kurhur"),
        ("scancanon", gen_canon, "Canon"), ("scanrata", gen_rata, "Rata"),
        ("scantidakrata", gen_tidakrata, "Tidak Rata"), ("scanvokal", gen_vokal, "Vokal"),
        ("scantampingrata", gen_tampingrata, "Tamping Rata"), ("scantampingtidakrata", gen_tampingtidakrata, "Tamping Tdk Rata"),
        ("scantamdal", gen_tamdal, "Tamdal"), ("scantamdalrata", gen_tamdalrata, "Tamdal Rata"),
        ("scantamdaltidakrata", gen_tamdaltidakrata, "Tamdal Tdk Rata"), ("scancadel", gen_cadel, "Cadel"),
                ]

    logger.info("🚀 BOT STARTING...")
    await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    nest_asyncio.apply()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    except:
        pass
