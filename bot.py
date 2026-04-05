import asyncio
import os
import string
import time
import logging
import random
import nest_asyncio
from telethon import TelegramClient, functions
from telethon.errors import RPCError, FloodWaitError
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ================== LOGGING ==================
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ================== CONFIG ==================
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
PASSWORD = os.getenv("PASSWORD", "hi")
ADMIN_ID = os.getenv("ADMIN_ID") 

SESSION_DIR = "./" 
SESSIONS = [f"{SESSION_DIR}acc{i}" for i in range(1, 11)]

AUTHORIZED_USERS = set()
clients = []
client_cooldown = {}
running_tasks = {}

# ================== ALL 16 GENERATORS ==================
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
    res = {b + 's'}; mapping = {'i': 'l', 'l': 'i'}
    for i, char in enumerate(b):
        if char in mapping: res.add(b[:i] + mapping[char] + b[i+1:])
    return list(res)
def gen_cadel(b): return list({b[:i] + l + b[i:] for i in range(len(b)+1) for l in "wycl"})

rata, tdk_rata, vokal = "asweruiozxcvnm", "qtypdfghjklb", "aeiou"
def gen_rata(b): return list({b[:i] + l + b[i:] for i in range(len(b)+1) for l in rata})
def gen_tidakrata(b): return list({b[:i] + l + b[i:] for i in range(len(b)+1) for l in tdk_rata})
def gen_vokal(b): return list({b[:i] + l + b[i:] for i in range(len(b)+1) for l in vokal})
def gen_tampingrata(b): return list({l + b for l in rata} | {b + l for l in rata})
def gen_tampingtidakrata(b): return list({l + b for l in tdk_rata} | {b + l for l in tdk_rata})
def gen_tamdal(b): return list({b[:i] + l + b[i:] for i in range(1, len(b)) for l in string.ascii_lowercase}) if len(b) >= 2 else []
def gen_tamdalrata(b): return list({b[:i] + l + b[i:] for i in range(1, len(b)) for l in rata}) if len(b) >= 2 else []
def gen_tamdaltidakrata(b): return list({b[:i] + l + b[i:] for i in range(1, len(b)) for l in tdk_rata}) if len(b) >= 2 else []

# ================== CORE LOGIC ==================
async def init_clients():
    await asyncio.sleep(5)
    for s in SESSIONS:
        if os.path.exists(f"{s}.session"):
            try:
                c = TelegramClient(s, int(API_ID), API_HASH)
                await c.connect()
                if await c.is_user_authorized():
                    clients.append(c)
                    client_cooldown[c] = 0
                    logger.info(f"✅ {s} Ready!")
                else: await c.disconnect()
            except Exception as e: logger.error(f"❌ {s}: {e}")

def get_available_client():
    if not clients: return None
    now = time.time()
    available = [c for c in clients if client_cooldown.get(c, 0) <= now]
    return random.choice(available) if available else None

async def send_log(context, message):
    if ADMIN_ID:
        try: await context.bot.send_message(chat_id=int(ADMIN_ID), text=message, parse_mode='HTML')
        except: pass

async def check_fast(usernames, context):
    sem = asyncio.Semaphore(5)
    async def worker(u):
        async with sem:
            cl = get_available_client()
            if not cl: return None
            try:
                if await cl(functions.account.CheckUsernameRequest(u)):
                    return f"🟢 @{u}"
            except FloodWaitError as e:
                client_cooldown[cl] = time.time() + e.seconds
            except: pass
            return None
    results = await asyncio.gather(*(worker(u) for u in usernames))
    return [r for r in results if r]

# ================== HANDLERS ==================
def auth(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or update.effective_user.id not in AUTHORIZED_USERS:
            await update.message.reply_text("❌ /login [pw] dulu.")
            return
        return await func(update, context)
    return wrapper

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0] == PASSWORD:
        AUTHORIZED_USERS.add(update.effective_user.id)
        await update.message.reply_text("✅ Slmt.")
    else: await update.message.reply_text("❌ Salah.")

@auth
async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "<b>Commands:</b>\n"
        "• /login [pw], /keep [user], /stop\n\n"
        "<b>Scanning:</b>\n"
        "• /check, /scanswitch, /scankurhur, /scanganhur\n"
        "• /scancadel, /scancanon, /scanuncommon, /scantamhur\n"
        "• /scanrata, /scantidakrata, /scanvokal\n"
        "• /scantamping, /scantampingrata, /scantampingtidakrata\n"
        "• /scantamdal, /scantamdalrata, /scantamdaltidakrata"
    )
    await update.message.reply_text(text, parse_mode='HTML')

@auth
async def keep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    u = context.args[0].replace("@", "")
    uid = update.effective_user.id
    if uid in running_tasks: return await update.message.reply_text("⚠️ Aktif.")

    async def worker():
        while uid in running_tasks:
            cl = get_available_client()
            if not cl: await asyncio.sleep(10); continue
            try:
                if await cl(functions.account.CheckUsernameRequest(u)):
                    res = await cl(functions.channels.CreateChannelRequest(title=u, about="@slateid"))
                    await cl(functions.channels.UpdateUsernameRequest(channel=res.chats[0], username=u))
                    me = await cl.get_me()
                    msg = (f"🏆 <b>SUCCESS KEEP @{u}</b>\n"
                           f"👤 <b>Owner:</b> {me.first_name}\n"
                           f"🆔 <b>Account:</b> @{me.username or 'NoUsn'}")
                    await update.message.reply_text(msg, parse_mode='HTML')
                    await send_log(context, msg)
                    break
            except FloodWaitError as e: client_cooldown[cl] = time.time() + e.seconds
            except RPCError: break
            except Exception: pass
            await asyncio.sleep(2)
        running_tasks.pop(uid, None)

    running_tasks[uid] = asyncio.create_task(worker())
    await update.message.reply_text(f"🚀 Hunting @{u}...")

@auth
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in running_tasks:
        running_tasks.pop(update.effective_user.id).cancel()
        await update.message.reply_text("🛑 Stop.")

def create_handler(gen, lbl):
    @auth
    async def h(u: Update, c: ContextTypes.DEFAULT_TYPE):
        if not c.args: return
        base = c.args[0].replace("@", "")
        m = await u.message.reply_text(f"🔍 {lbl} @{base}...")
        res = await check_fast(gen(base)[:100], c)
        await m.edit_text("\n".join(res) if res else "❌ Kosong.")
    return h

# ================== RUNNER ==================
async def main():
    await init_clients()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("keep", keep))
    app.add_handler(CommandHandler("stop", stop))

    scans = [
        ("scantamping", gen_tamping, "Tamping"), ("scanswitch", gen_switch, "Switch"),
        ("scantamhur", gen_tamhur, "Tamhur"), ("scanganhur", gen_ganhur, "Ganhur"),
        ("scanuncommon", gen_uncommon, "Uncommon"), ("scankurhur", gen_kurhur, "Kurhur"),
        ("scancanon", gen_canon, "Canon"), ("scanrata", gen_rata, "Rata"),
        ("scantidakrata", gen_tidakrata, "Tdk Rata"), ("scanvokal", gen_vokal, "Vokal"),
        ("scantampingrata", gen_tampingrata, "Tamping Rata"), ("scantampingtidakrata", gen_tampingtidakrata, "Tamping Tdk Rata"),
        ("scantamdal", gen_tamdal, "Tamdal"), ("scantamdalrata", gen_tamdalrata, "Tamdal Rata"),
        ("scantamdaltidakrata", gen_tamdaltidakrata, "Tamdal Tdk Rata"), ("scancadel", gen_cadel, "Cadel"),
        ("check", gen_tamhur, "Check"),
    ]
    for cmd, gen, lbl in scans:
        app.add_handler(CommandHandler(cmd, create_handler(gen, lbl)))

    await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    nest_asyncio.apply()
    asyncio.run(main())
