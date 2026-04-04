import asyncio
import os
import string
import time
import logging
import random
from telethon import TelegramClient, functions
from telethon.errors import FloodWaitError
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# config
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
PASSWORD = os.getenv("PASSWORD", "hi")

SESSION_DIR = "/data/" if os.path.exists("/data") else "./"
SESSIONS = [f"{SESSION_DIR}acc{i}" for i in range(1, 11)]

AUTHORIZED_USERS = set()
clients = []
client_cooldown = {}
running_tasks = {}
monitor_tasks = {}
client_index = 0

# gen
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

def gen_kurhur(b):
    if len(b) <= 1: return []
    return list({b[:i] + b[i+1:] for i in range(len(b))})

def gen_canon(b):
    res = set()
    res = {b + 's'}
    mapping = {'i': 'l', 'l': 'i'}
    for i, char in enumerate(b):
        if char in mapping:
            res.add(b[:i] + mapping[char] + b[i+1:])
    return list(res)

rata = "asweruiozxcvnm"
tdk_rata = "qtypdfghjklb"
vokal = "aeiou"

def gen_rata(b):
    return list({b[:i] + l + b[i:] for i in range(len(b)+1) for l in rata})

def gen_tidakrata(b):
    return list({b[:i] + l + b[i:] for i in range(len(b)+1) for l in tdk_rata})

def gen_vokal(b):
    return list({b[:i] + l + b[i:] for i in range(len(b)+1) for l in vokal})

def gen_tampingrata(b):
    return list({l + b for l in rata} | {b + l for l in rata})

def gen_tampingtidakrata(b):
    return list({l + b for l in tdk_rata} | {b + l for l in tdk_rata})

def gen_tamdal(b):
    if len(b) < 2: return []
    letters = string.ascii_lowercase
    return list({b[:i] + l + b[i:] for i in range(1, len(b)) for l in letters})

def gen_tamdalrata(b):
    if len(b) < 2: return []
    return list({b[:i] + l + b[i:] for i in range(1, len(b)) for l in rata})

def gen_tamdaltidakrata(b):
    if len(b) < 2: return []
    return list({b[:i] + l + b[i:] for i in range(1, len(b)) for l in tdk_rata})

def gen_cadel(b):
    cadel_chars = "wycl"
    return list({b[:i] + l + b[i:] for i in range(len(b)+1) for l in cadel_chars})

# init clients
async def init_clients():
    if not API_ID or not API_HASH:
        logger.error("❌ API_ID/HASH missing!")
        return
    for s in SESSIONS:
        try:
            c = TelegramClient(s, int(API_ID), API_HASH)
            await c.connect()
            if not await c.is_user_authorized(): continue
            clients.append(c)
            client_cooldown[c] = 0
            logger.info(f"✅ {s} ready")
        except Exception as e:
            logger.error(f"❌ {s} fail: {e}")

def get_available_client():
    global client_index
    now = time.time()
    available = [c for c in clients if client_cooldown[c] <= now]
    if not available: return None
    client = available[client_index % len(available)]
    client_index += 1
    return client

def auth(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in AUTHORIZED_USERS:
            await update.message.reply_text("/login dulu.")
            return
        return await func(update, context)
    return wrapper

# commands
async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0] == PASSWORD:
        AUTHORIZED_USERS.add(update.effective_user.id)
        await update.message.reply_text("Slmt")
    else:
        await update.message.reply_text("Salah")

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
    sem = asyncio.Semaphore(5)
    async def worker(username):
        async with sem:
            for _ in range(3):
                client = get_available_client()
                if not client:
                    await asyncio.sleep(1)
                    continue
                res = await check_one(client, username)
                await asyncio.sleep(0.6)
                return res
            return f"⏳ @{username} (No clients)"
    tasks = [worker(u) for u in usernames]
    return await asyncio.gather(*tasks)

@auth
async def keep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Gunakan: /keep user")
    username = context.args[0].replace("@", "")
    user_id = update.effective_user.id
    if user_id in running_tasks: return await update.message.reply_text("⚠️ Task aktif.")

    await update.message.reply_text(f"Keep @{username} (Auto-Channel)...")
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
                        # Auto-keep to Channel
                        created = await client(functions.channels.CreateChannelRequest(
                            title=f"Owned @{username}", about="@sladeid", megagroup=False
                        ))
                        await client(functions.channels.UpdateUsernameRequest(
                            channel=created.chats[0], username=username
                        ))
                        await update.message.reply_text(f" BERHASIL KEEP DI CHANNEL: @{username}")
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
    if not context.args:
        return await update.message.reply_text("Gunakan: /monitor username")
    
    username = context.args[0].replace("@", "")
    user_id = update.effective_user.id
    
    if user_id in monitor_tasks:
        return await update.message.reply_text("⚠️ Monitor sedang berjalan.")

    await update.message.reply_text(f" Memantau @{username} (Setiap 60 detik)...")

    async def monitor_worker():
        try:
            while True:
                client = get_available_client()
                if not client:
                    await asyncio.sleep(5)
                    continue
                try:
                    ok = await client(functions.account.CheckUsernameRequest(username))
                    if ok:
                        await update.message.reply_text(f"🔔 @{username} SEKARANG TERSEDIA!")
                        # berhenti
                        break
                except FloodWaitError as e:
                    client_cooldown[client] = time.time() + e.seconds
                except Exception:
                    pass
               
                await asyncio.sleep(60) 
        except asyncio.CancelledError:
            pass

    monitor_tasks[user_id] = asyncio.create_task(monitor_worker())

@auth
async def unmonitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in monitor_tasks:
        monitor_tasks[user_id].cancel()
        del monitor_tasks[user_id]
        await update.message.reply_text("Monitor dihentikan.")
    else:
        await update.message.reply_text("Tidak ada monitor aktif.")

@auth
async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
    
        "<b>Commands:</b>\n"
        "• /login [password]\n"
        "• /keep [user] - buat autokeep\n"
        "• /stop - hentiin autokeep\n\n"
        "• /monitor [user] - mantau usn\n\n"
        "• /unmonitor \n\n"
         
        
        "<b>Scanning:</b>\n"
        "• /scanswitch \n"
        "• /scankurhur \n"
        "• /scancadel - 'wycl'\n"
        "• /scancanon - Tambah 's' / ubah i-l\n\n"
        
        "<b>Scanning:</b>\n"
        "• /scanrata - tamhur rata\n"
        "• /scantidakrata - tamhur gak rata\n"
        "• /scanvokal - tamhur vokal\n\n"
        
        "<b>Scanning Tamping:</b>\n"
        "• /scantamping \n"
        "• /scantampingrata \n"
        "• /scantampingtidakrata \n"

         "<b>Scanning Tamdal:</b>\n"
        "• /scantamdal \n"
        "• /scantamdalrata \n"
        "• /scantamdaltidakrata \n\n"

        "<i>Noted: keep sama monitor jangan sering dipake</i>"
        
    )
    await update.message.reply_text(text, parse_mode='HTML')

# scan handler
def create_scan_handler(gen_func, label):
    @auth
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args: 
            await update.message.reply_text(f"Gunakan: /{label.lower()} [username]")
            return
        
        base = context.args[0].replace("@", "")
        variants = gen_func(base)[:100]
        
        if not clients:
            await update.message.reply_text("❌ Tidak ada akun (clients) yang siap!")
            return

        await update.message.reply_text(f"Scanning {label} @{base}...")
        res = await check_usernames_fast(variants)
        
        # Split message if it's too long for Telegram
        response_text = "\n".join(res)
        if len(response_text) > 4096:
            for i in range(0, len(response_text), 4096):
                await update.message.reply_text(response_text[i:i+4096])
        else:
            await update.message.reply_text(response_text)
    return handler

# main 
# main 
async def main():
    # 1. Start the Telethon worker clients
    await init_clients()
    
    # 2. Build the Bot Application
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # 3. Add Core Commands
    application.add_handler(CommandHandler("login", login))
    application.add_handler(CommandHandler("info", info)) 
    application.add_handler(CommandHandler("keep", keep))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("monitor", monitor))   
    application.add_handler(CommandHandler("unmonitor", unmonitor)) 

    # 4. Add Scan Commands
    commands = [
        ("scantamping", gen_tamping, "Tamping"),
        ("scanswitch", gen_switch, "Switch"),
        ("scankurhur", gen_kurhur, "Kurhur"),
        ("scancanon", gen_canon, "Canon"),
        ("scanrata", gen_rata, "Rata"),
        ("scantidakrata", gen_tidakrata, "Tidak Rata"),
        ("scanvokal", gen_vokal, "Vokal"),
        ("scantampingrata", gen_tampingrata, "Tamping Rata"),
        ("scantampingtidakrata", gen_tampingtidakrata, "Tamping Tdk Rata"),
        ("scantamdal", gen_tamdal, "Tamdal"),
        ("scantamdalrata", gen_tamdalrata, "Tamdal Rata"),
        ("scantamdaltidakrata", gen_tamdaltidakrata, "Tamdal Tdk Rata"),
        ("scancadel", gen_cadel, "Cadel"),
    ]
    
    for cmd, gen, lbl in commands:
        application.add_handler(CommandHandler(cmd, create_scan_handler(gen, lbl)))

    # 5. Start Polling
    logger.info("🚀 BOT STARTING POLLING")
    # run_polling is blocking, so it stays running here
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply() # This prevents "Event loop is already running" errors
    
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
