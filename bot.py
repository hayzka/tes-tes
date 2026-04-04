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
ADMIN_ID = os.getenv("ADMIN_ID") # Pastikan di Railway isinya hanya angka (ID Telegram kamu)

SESSION_DIR = "/data/" if os.path.exists("/data") else "./"
SESSIONS = [f"{SESSION_DIR}acc{i}" for i in range(1, 11)]

AUTHORIZED_USERS = set()
clients = []
client_cooldown = {}
running_tasks = {}
monitor_tasks = {}
client_index = 0

# ================== GENERATORS ==================
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

def gen_tamhur(b):
    letters = string.ascii_lowercase
    return list({b[:i] + l + b[i:] for i in range(len(b)+1) for l in letters})

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
    if not API_ID or not API_HASH: return
    for s in SESSIONS:
        try:
            c = TelegramClient(s, int(API_ID), API_HASH)
            await c.connect()
            if not await c.is_user_authorized(): continue
            clients.append(c)
            client_cooldown[c] = 0
            logger.info(f"✅ Client {s} Ready")
        except Exception as e:
            logger.error(f"❌ {s} Error: {e}")

def get_available_client():
    global client_index
    now = time.time()
    available = [c for c in clients if client_cooldown[c] <= now]
    if not available: return None
    client = available[client_index % len(available)]
    client_index += 1
    return client

async def send_log(context: ContextTypes.DEFAULT_TYPE, message: str):
    if not ADMIN_ID: return
    try:
        await context.bot.send_message(chat_id=int(ADMIN_ID), text=message, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Log Error: {e}")

# ================== AUTH DECORATOR ==================
def auth(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user: return
        if user.id not in AUTHORIZED_USERS:
            await update.message.reply_text("/login dulu.")
            await send_log(context, f"⚠️ <b>ACCESS DENIED:</b>\n{user.first_name} (@{user.username})")
            return
        cmd = update.message.text.split()[0] if update.message.text else "N/A"
        await send_log(context, f"👤 <b>ACTIVITY:</b> {user.first_name}\n<b>CMD:</b> <code>{cmd}</code>")
        return await func(update, context)
    return wrapper

# ================== COMMAND HANDLERS ==================
async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0] == PASSWORD:
        AUTHORIZED_USERS.add(update.effective_user.id)
        await update.message.reply_text("Slmt")
        await send_log(context, f"🔓 <b>LOGIN SUCCESS:</b> {update.effective_user.first_name}")
    else:
        await update.message.reply_text("Salah")

@auth
async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Gunakan: /check user1 user2")
    usernames = [u.replace("@", "") for u in context.args]
    await update.message.reply_text(f"🔍 Checking {len(usernames)} usernames...")
    results = await check_usernames_fast(usernames)
    available = [r for r in results if "🟢" in r]
    text = "<b>✅ TERSEDIA:</b>\n\n" + "\n".join(available) if available else "<b>❌ TIDAK ADA YANG TERSEDIA.</b>"
    await update.message.reply_text(text, parse_mode='HTML')

async def check_one(client, username):
    try:
        ok = await client(functions.account.CheckUsernameRequest(username))
        return f"🟢 @{username}" if ok else f"🔴 @{username}"
    except FloodWaitError as e:
        client_cooldown[client] = time.time() + e.seconds
        return f"⚠️ @{username} flood {e.seconds}s"
    except Exception: return f"❌ @{username} error"

async def check_usernames_fast(usernames):
    sem = asyncio.Semaphore(5)
    async def worker(username):
        async with sem:
            for _ in range(3):
                client = get_available_client()
                if not client: await asyncio.sleep(1); continue
                res = await check_one(client, username)
                await asyncio.sleep(0.6)
                return res
            return f"⏳ @{username} (No clients)"
    return await asyncio.gather(*(worker(u) for u in usernames))

@auth
async def keep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    username = context.args[0].replace("@", "")
    user_id = update.effective_user.id
    if user_id in running_tasks: return await update.message.reply_text("⚠️ Task aktif.")
    await update.message.reply_text(f"Keep @{username}...")
    async def worker():
        try:
            while True:
                client = get_available_client()
                if not client: await asyncio.sleep(1); continue
                try:
                    if await client(functions.account.CheckUsernameRequest(username)):
                        created = await client(functions.channels.CreateChannelRequest(title=f"Owned @{username}", about="@sladeid", megagroup=False))
                        await client(functions.channels.UpdateUsernameRequest(channel=created.chats[0], username=username))
                        await update.message.reply_text(f"🏆 BERHASIL KEEP: @{username}")
                        break
                except Exception: pass
                await asyncio.sleep(0.8)
        except asyncio.CancelledError: pass
    running_tasks[user_id] = asyncio.create_task(worker())

@auth
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in running_tasks:
        running_tasks[user_id].cancel()
        del running_tasks[user_id]
        await update.message.reply_text("Keep dihentikan.")

@auth
async def monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    username = context.args[0].replace("@", "")
    user_id = update.effective_user.id
    if user_id in monitor_tasks: return
    await update.message.reply_text(f"Memantau @{username}...")
    async def m_worker():
        try:
            while True:
                client = get_available_client()
                if not client: await asyncio.sleep(5); continue
                try:
                    if await client(functions.account.CheckUsernameRequest(username)):
                        await update.message.reply_text(f"🔔 @{username} TERSEDIA!")
                        break
                except Exception: pass
                await asyncio.sleep(60)
        except asyncio.CancelledError: pass
    monitor_tasks[user_id] = asyncio.create_task(m_worker())

@auth
async def unmonitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in monitor_tasks:
        monitor_tasks[user_id].cancel()
        del monitor_tasks[user_id]
        await update.message.reply_text("Monitor off.")

@auth
async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "<b>Commands:</b>\n"
        "• /login [password]\n"
        "• /keep [user] - buat autokeep\n"
        "• /stop - hentiin autokeep\n\n"
        "• /monitor [user] - mantau usn\n"
        "• /unmonitor \n\n"
        "<b>Scanning:</b>\n"
        "• /scanswitch \n"
        "• /scankurhur \n"
        "• /scanganhur \n\n"
        "<b>Scanning:</b>\n"
        "• /scancadel - 'wycl'\n"
        "• /scancanon - Tambah 's' / ubah i-l\n\n"
        "• /scanuncommon - sop\n"
        "• /scantamhur \n"
        "• /scanrata - tamhur rata\n"
        "• /scantidakrata - tamhur gak rata\n"
        "• /scanvokal - tamhur vokal\n\n"
        "<b>Scanning Tamping:</b>\n"
        "• /scantamping \n"
        "• /scantampingrata \n"
        "• /scantampingtidakrata \n\n"
        "<b>Scanning Tamdal:</b>\n"
        "• /scantamdal \n"
        "• /scantamdalrata \n"
        "• /scantamdaltidakrata \n\n"
        "<i>Noted: keep sama monitor jangan sering dipake</i>"
    )
    await update.message.reply_text(text, parse_mode='HTML')

def create_scan_handler(gen_func, label):
    @auth
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args: return
        base = context.args[0].replace("@", "")
        variants = gen_func(base)[:100]
        await update.message.reply_text(f"Scanning {label} @{base}...")
        res = await check_usernames_fast(variants)
        txt = "\n".join(res)
        for i in range(0, len(txt), 4000): await update.message.reply_text(txt[i:i+4000])
    return handler

# ================== RUNNER ==================
async def main():
    await init_clients()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Handlers
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
    for cmd, gen, lbl in scans:
        app.add_handler(CommandHandler(cmd, create_scan_handler(gen, lbl)))

    logger.info("🚀 SYSTEM ONLINE")
    await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    nest_asyncio.apply()
    asyncio.run(main())
