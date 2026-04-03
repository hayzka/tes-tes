import asyncio
import os
import string
import time
import logging
from telethon import TelegramClient, functions
from telethon.errors import FloodWaitError
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- LOGGING ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- CONFIG ---
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
PASSWORD = os.getenv("PASSWORD", "yyy")

# Use /data/ for Railway Persistent Volume, fallback to local
SESSION_DIR = "/data/" if os.path.exists("/data") else "./"
SESSIONS = [f"{SESSION_DIR}acc{i}" for i in range(1, 11)]

AUTHORIZED_USERS = set()
clients = []
client_cooldown = {}
running_tasks = {}
client_index = 0

# ================= INIT CLIENTS =================
async def init_clients():
    if not API_ID or not API_HASH:
        logger.error("❌ API_ID or API_HASH missing from Environment Variables!")
        return

    for s in SESSIONS:
        try:
            # We use .connect() to avoid the interactive terminal login on Railway
            c = TelegramClient(s, int(API_ID), API_HASH)
            await c.connect()
            
            if not await c.is_user_authorized():
                logger.warning(f"⚠️ {s} is not authorized. Session file missing or expired.")
                continue
                
            clients.append(c)
            client_cooldown[c] = 0
            logger.info(f"✅ {s} ready")
        except Exception as e:
            logger.error(f"❌ {s} initialization failed: {e}")

# ================= ROTATION LOGIC =================
def get_available_client():
    global client_index
    now = time.time()
    available = [c for c in clients if client_cooldown[c] <= now]

    if not available:
        return None

    client = available[client_index % len(available)]
    client_index += 1
    return client

# ================= AUTH DECORATOR =================
def auth(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in AUTHORIZED_USERS:
            await update.message.reply_text("🔒 Silahkan /login <password> terlebih dahulu.")
            return
        return await func(update, context)
    return wrapper

# ================= COMMAND HANDLERS =================
async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0] == PASSWORD:
        AUTHORIZED_USERS.add(update.effective_user.id)
        await update.message.reply_text("✅ Login sukses!")
    else:
        await update.message.reply_text("❌ Password salah.")

async def check_one(client, username):
    try:
        ok = await client(functions.account.CheckUsernameRequest(username))
        return f"🟢 @{username}" if ok else f"🔴 @{username}"
    except FloodWaitError as e:
        client_cooldown[client] = time.time() + e.seconds
        return f"⚠️ @{username} flood {e.seconds}s"
    except Exception:
        return f"❌ @{username} error"

async def check_usernames_fast(usernames):
    sem = asyncio.Semaphore(5) # Conservative for Railway IPs
    async def worker(username):
        async with sem:
            for _ in range(3):
                client = get_available_client()
                if not client:
                    await asyncio.sleep(1)
                    continue
                res = await check_one(client, username)
                await asyncio.sleep(0.5)
                return res
            return f"⏳ @{username} (No clients)"
    
    tasks = [worker(u) for u in usernames]
    return await asyncio.gather(*tasks)

@auth
async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Gunakan: /check user1 user2")
    usernames = [u.replace("@", "") for u in context.args]
    result = await check_usernames_fast(usernames)
    await update.message.reply_text("\n".join(result))

@auth
async def keep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Gunakan: /keep username")
    
    username = context.args[0].replace("@", "")
    user_id = update.effective_user.id
    if user_id in running_tasks:
        return await update.message.reply_text("⚠️ Task sudah berjalan.")

    await update.message.reply_text(f"🚀 Hunting @{username}...")

    async def worker():
        try:
            while True:
                client = get_available_client()
                if not client:
                    await asyncio.sleep(1)
                    continue
                try:
                    ok = await client(functions.account.CheckUsernameRequest(username))
                    if ok:
                        await client(functions.account.UpdateUsernameRequest(username))
                        await update.message.reply_text(f"🎯 KEAMBIL: @{username}")
                        break
                except FloodWaitError as e:
                    client_cooldown[client] = time.time() + e.seconds
                except Exception:
                    pass
                await asyncio.sleep(0.8)
        except asyncio.CancelledError:
            logger.info(f"Task hunting @{username} dihentikan.")

    running_tasks[user_id] = asyncio.create_task(worker())

@auth
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in running_tasks:
        running_tasks[user_id].cancel()
        del running_tasks[user_id]
        await update.message.reply_text("🛑 Hunter dihentikan.")
    else:
        await update.message.reply_text("Tidak ada task aktif.")

# ================= SCAN LOGIC =================
def generate_tamhur(base):
    letters = string.ascii_lowercase
    return list({base[:i] + l + base[i:] for i in range(len(base)+1) for l in letters})

def generate_ganhur(base):
    letters = string.ascii_lowercase
    return list({base[:i] + l + base[i+1:] for i in range(len(base)) for l in letters})

def generate_uncommon(base):
    return list({base[:i] + base[i] + base[i:] for i in range(len(base))})

@auth
async def scan_tamhur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    base = context.args[0].replace("@", "")
    variants = generate_tamhur(base)[:40]
    await update.message.reply_text(f"🔍 Scanning tamhur @{base}...")
    res = await check_usernames_fast(variants)
    await update.message.reply_text("\n".join(res))

@auth
async def scan_ganhur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    base = context.args[0].replace("@", "")
    variants = generate_ganhur(base)[:40]
    await update.message.reply_text(f"🔍 Scanning ganhur @{base}...")
    res = await check_usernames_fast(variants)
    await update.message.reply_text("\n".join(res))

@auth
async def scan_uncommon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    base = context.args[0].replace("@", "")
    variants = generate_uncommon(base)[:40]
    await update.message.reply_text(f"🔍 Scanning uncommon @{base}...")
    res = await check_usernames_fast(variants)
    await update.message.reply_text("\n".join(res))

# ================= MAIN RUNNER =================
async def main():
    # 1. Initialize Telethon Clients
    await init_clients()
    
    if not clients:
        logger.error("❌ No authorized clients found. Bot will not work for checks.")

    # 2. Setup Telegram Bot
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("login", login))
    application.add_handler(CommandHandler("check", check))
    application.add_handler(CommandHandler("keep", keep))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("scantamhur", scan_tamhur))
    application.add_handler(CommandHandler("scanganhur", scan_ganhur))
    application.add_handler(CommandHandler("scanuncommon", scan_uncommon))

    # 3. Use async context manager to prevent "Running Loop" errors
    async with application:
        await application.initialize()
        await application.start_polling()
        
        logger.info("🚀 BOT READY ON RAILWAY")
        
        # 4. Keep alive
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
