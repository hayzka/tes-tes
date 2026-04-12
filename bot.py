import nest_asyncio
nest_asyncio.apply()

import asyncio
import os
import string
import time
import logging
from telethon import TelegramClient, functions
from telethon.errors import FloodWaitError
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# config
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
PASSWORD = os.getenv("PASSWORD", "nephis")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Deteksi Railway Volume
DATA_DIR = "/data/" if os.path.exists("/data") else "./"
BAN_FILE = f"{DATA_DIR}banned.txt"

# Memory DB
AUTHORIZED_USERS = set()
BANNED_USERS = set()
clients = []
client_cooldown = {}
running_tasks = {}
client_index = 0

# ban
def load_bans():
    if os.path.exists(BAN_FILE):
        with open(BAN_FILE, "r") as f:
            for line in f:
                if line.strip(): BANNED_USERS.add(int(line.strip()))
    logger.info(f"Loaded {len(BANNED_USERS)} banned users.")

def save_ban(user_id):
    BANNED_USERS.add(user_id)
    with open(BAN_FILE, "a") as f:
        f.write(f"{user_id}\n")

# gen usn
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
def gen_tampingrata(b): return list({l + b for l in rata} | {b + l for l in rata})
def gen_tampingtidakrata(b): return list({l + b for l in tdk_rata} | {b + l for l in tdk_rata})
def gen_tamdal(b): return list({b[:i] + l + b[i:] for i in range(1, len(b)) for l in string.ascii_lowercase}) if len(b) >= 2 else []
def gen_tamdalrata(b): return list({b[:i] + l + b[i:] for i in range(1, len(b)) for l in rata}) if len(b) >= 2 else []
def gen_tamdaltidakrata(b): return list({b[:i] + l + b[i:] for i in range(1, len(b)) for l in tdk_rata}) if len(b) >= 2 else []
def gen_cadel(b): return list({b[:i] + l + b[i:] for i in range(len(b)+1) for l in "wycl"})

# logic
async def init_clients():
    if not API_ID or not API_HASH: return
    for i in range(1, 11):
        s = f"{DATA_DIR}acc{i}"
        try:
            c = TelegramClient(s, int(API_ID), API_HASH)
            await c.connect()
            if await c.is_user_authorized():
                clients.append(c)
                client_cooldown[c] = 0
                logger.info(f"✅ acc{i} Ready")
            else: await c.disconnect()
        except Exception as e: logger.error(f"❌ acc{i}: {e}")

def get_available_client():
    global client_index
    now = time.time()
    available = [c for c in clients if client_cooldown[c] <= now]
    if not available: return None
    client = available[client_index % len(available)]
    client_index += 1
    return client

async def check_usernames_fast(usernames):
    sem = asyncio.Semaphore(5)
    async def worker(u):
        async with sem:
            for _ in range(3):
                c = get_available_client()
                if not c: await asyncio.sleep(1); continue
                try:
                    ok = await c(functions.account.CheckUsernameRequest(u))
                    await asyncio.sleep(0.5)
                    return f"🟢 @{u}" if ok else f"🔴 @{u}"
                except FloodWaitError as e:
                    client_cooldown[c] = time.time() + e.seconds
                    continue
                except: return f"❌ @{u}"
            return f"⏳ @{u}"
    return await asyncio.gather(*(worker(u) for u in usernames))

# ================== HANDLERS ==================
def auth(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        if uid in BANNED_USERS:
            await update.message.reply_text("🚫 Kamu dibanned.")
            return
        if uid not in AUTHORIZED_USERS and uid != ADMIN_ID:
            await update.message.reply_text("/login <pass> dulu.")
            return
        return await func(update, context)
    return wrapper

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Commands:\n"
        "• /login [password]\n"
        "• /keep [user] - buat autokeep\n"
        "• /stop - hentiin autokeep\n"
        "• /info \n\n"
        "Scanning:\n"
        "• /scanswitch \n"
        "• /scankurhur \n"
        "• /scancadel - 'wycl'\n\n"
        "Scanning:\n"
        "• /scanrata - tamhur rata\n"
        "• /scantidakrata - tamhur gak rata\n"
        "• /scanvokal - tamhur vokal\n"
        "• /scanuncommon - sop, scannon, cannon\n"
        "• /scantamhur\n"
        "• /scanganhur\n"
        "• /scanswitch \n\n"
        "Scanning Tamping:\n"
        "• /scantamping \n"
        "• /scantampingrata \n"
        "• /scantampingtidakrata \n\n"
        "Scanning Tamdal:\n"
        "• /scantamdal \n"
        "• /scantamdalrata \n"
        "• /scantamdaltidakrata \n\n"
        "Noted: keep jangan sering dipake"
    )
    await update.message.reply_text(help_text)

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in BANNED_USERS: return
    if context.args and context.args[0] == PASSWORD:
        AUTHORIZED_USERS.add(user.id)
        await update.message.reply_text("✅ Sukses Login.")
        await context.bot.send_message(ADMIN_ID, f"🔔 LOGIN \nName: {user.first_name}\nID: `{user.id}`")
    else: await update.message.reply_text("❌ Salah Password.")

@auth
async def scan_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2: return await update.message.reply_text("Usage: /scan <tipe> <username>")
    tipe, base = context.args[0].lower(), context.args[1].replace("@", "")
    gens = {
        "tamhur": gen_tamhur, "tamping": gen_tamping, "switch": gen_switch, "uncommon": gen_uncommon,
        "ganhur": gen_ganhur, "kurhur": gen_kurhur, "uncommon": gen_canon, "rata": gen_rata,
        "tidakrata": gen_tidakrata, "vokal": gen_vokal, "tampingrata": gen_tampingrata,
        "tampingtidakrata": gen_tampingtidakrata, "tamdal": gen_tamdal, "tamdalrata": gen_tamdalrata,
        "tamdaltidakrata": gen_tamdaltidakrata, "cadel": gen_cadel
    }
    if tipe not in gens: return await update.message.reply_text("Tipe tidak ada.")
    variants = gens[tipe](base)[:40]
    await update.message.reply_text(f"🔍 Scan {tipe} @{base}...")
    res = await check_usernames_fast(variants)
    await update.message.reply_text("\n".join(res))

@auth
async def keep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args: return
    target = context.args[0].replace("@", "")
    if user.id in running_tasks: return await update.message.reply_text("⚠️ Lagi jalan.")

    await update.message.reply_text(f"🚀 Hunting @{target}...")
    await context.bot.send_message(ADMIN_ID, f"🚀 HUNT \nUser: {user.first_name}\nTarget: @{target}")

    async def hunter():
        try:
            while True:
                c = get_available_client()
                if not c: await asyncio.sleep(1); continue
                try:
                    if await c(functions.account.CheckUsernameRequest(target)):
                        await c(functions.account.UpdateUsernameRequest(target))
                        await update.message.reply_text(f"🎯 DAPET: @{target}")
                        await context.bot.send_message(ADMIN_ID, f"🎯 BERHASIL\n@{target} by `{user.id}`")
                        break
                except FloodWaitError as e: client_cooldown[c] = time.time() + e.seconds
                except: pass
                await asyncio.sleep(0.8)
        except asyncio.CancelledError: pass

    running_tasks[user.id] = asyncio.create_task(hunter())

@auth
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in running_tasks:
        running_tasks[uid].cancel(); del running_tasks[uid]
        await update.message.reply_text("🛑 Berhenti.")
    else: await update.message.reply_text("Gak ada task.")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    tid = int(context.args[0])
    save_ban(tid)
    if tid in AUTHORIZED_USERS: AUTHORIZED_USERS.remove(tid)
    if tid in running_tasks: running_tasks[tid].cancel(); del running_tasks[tid]
    await update.message.reply_text(f"🚫 User {tid} Banned.")

# RUN
async def main():
    load_bans()
    await init_clients()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("scan", scan_handler))
    app.add_handler(CommandHandler("keep", keep))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("ban", ban))

    async with app:
        await app.initialize()
        if app.updater: await app.updater.start_polling()
        await app.start()
        logger.info("🚀 ONLINE")
        while True: await asyncio.sleep(3600)

if __name__ == "__main__":
    try: asyncio.run(main())
    except: pass, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return # Silent fail if not admin

    if not context.args:
        await update.message.reply_text("Gunakan: /ban <user_id>")
        return

    try:
        target_id = int(context.args[0])
        BANNED_USERS.add(target_id)
        if target_id in AUTHORIZED_USERS:
            AUTHORIZED_USERS.remove(target_id)
        
        # Stop their tasks if they are running
        if target_id in running_tasks:
            running_tasks[target_id].cancel()
            del running_tasks[target_id]

        await update.message.reply_text(f"🚫 User `{target_id}` telah dibanned.")
    except ValueError:
        await update.message.reply_text("ID tidak valid.")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    target_id = int(context.args[0])
    BANNED_USERS.discard(target_id)
    await update.message.reply_text(f"✅ User `{target_id}` telah di-unban.")
    
    async def worker():
        while True:
            cl = get_available_client()
            if not cl: await asyncio.sleep(10); continue
            try:
                if await cl(functions.account.CheckUsernameRequest(u)):
                    res = await cl(functions.channels.CreateChannelRequest(title=f".", about=""))
                    await cl(functions.channels.UpdateUsernameRequest(channel=res.chats[0], username=u))
                    me = await cl.get_me()
                    await update.message.reply_text(f"🏆 <b>SUCCESS KEEP @{u}</b>\n👤 <b>Owner:</b> {me.first_name}", parse_mode='HTML')
                    break
            except FloodWaitError as e: client_cooldown[cl] = time.time() + e.seconds
            except RPCError: break
            except: pass
            await asyncio.sleep(2)
        if uid in running_tasks: del running_tasks[uid]
        
    running_tasks[uid] = asyncio.create_task(worker())
    await update.message.reply_text(f"🚀 Hunting @{u}...")

@auth_only
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in running_tasks:
        running_tasks[uid].cancel(); del running_tasks[uid]
        await update.message.reply_text("🛑 Task Stop.")

def create_scan(gen, lbl):
    @auth_only
    async def h(u: Update, c: ContextTypes.DEFAULT_TYPE):
        if not c.args: return
        base = c.args[0].replace("@", "")
        m = await u.message.reply_text(f"🔍 Scan {lbl} @{base}...")
        res = await check_usernames_fast(gen(base)[:100])
        await m.edit_text("<b>AVAILABLE:</b>\n" + "\n".join(res) if res else "❌ Kosong.", parse_mode='HTML')
    return h

#RUNNER
async def main():
    try:
    
        await init_clients()
        

        app = ApplicationBuilder().token(BOT_TOKEN).build()
        
    
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("login", login))
        app.add_handler(CommandHandler("broadcast", broadcast))
        app.add_handler(CommandHandler("info", info))
        app.add_handler(CommandHandler("keep", keep))
        app.add_handler(CommandHandler("stop", stop))
        app.add_handler(CommandHandler("ban", ban))
        app.add_handler(CommandHandler("unban", unban))

        scans = [
            ("scantamping", gen_tamping, "Tamping"), ("scanswitch", gen_switch, "Switch"),
            ("scantamhur", gen_tamhur, "Tamhur"), ("scanganhur", gen_ganhur, "Ganhur"),
            ("scanuncommon", gen_uncommon, "Uncommon"), ("scankurhur", gen_kurhur, "Kurhur"),
            ("scancadel", gen_cadel, "Cadel"), ("scancanon", gen_canon, "Canon"),
            ("scanrata", gen_rata, "Rata"), ("scantidakrata", gen_tidakrata, "Tdk Rata"),
            ("scanvokal", gen_vokal, "Vokal"), ("scantampingrata", gen_tampingrata, "Tamping Rata"),
            ("scantampingtidakrata", gen_tampingtidakrata, "Tamping Tdk Rata"), ("scantamdal", gen_tamdal, "Tamdal"),
            ("scantamdalrata", gen_tamdalrata, "Tamdal Rata"), ("scantamdaltidakrata", gen_tamdaltidakrata, "Tamdal Tdk Rata"),
            ("check", gen_tamhur, "Check"),
        ]
        for cmd, gen, lbl in scans:
            app.add_handler(CommandHandler(cmd, create_scan(gen, lbl)))

        
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_msg))
        
        logger.info("🤖 Bot is starting polling...")
        
        
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        
        
        while True:
            await asyncio.sleep(3600)
            
    except Exception as e:
        logger.error(f"💥 Fatal Error: {e}")

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
