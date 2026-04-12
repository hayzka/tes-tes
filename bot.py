import nest_asyncio
nest_asyncio.apply()

import asyncio
import os
import string
import time
import logging
from telethon import TelegramClient, functions
from telethon.errors import FloodWaitError, RPCError
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# ================== CONFIG ==================
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
PASSWORD = os.getenv("PASSWORD", "nephis")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DATA_DIR = "/data/" if os.path.exists("/data") else "./"
BAN_FILE = f"{DATA_DIR}banned.txt"

AUTHORIZED_USERS = set()
BANNED_USERS = set()
clients = []
client_cooldown = {}
running_tasks = {}
client_index = 0

# ================== PERSISTENCE ==================
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
def gen_tampingrata(b): return list({l + b for l in rata} | {b + l for l in rata})
def gen_tampingtidakrata(b): return list({l + b for l in tdk_rata} | {b + l for l in tdk_rata})
def gen_tamdal(b): return list({b[:i] + l + b[i:] for i in range(1, len(b)) for l in string.ascii_lowercase}) if len(b) >= 2 else []
def gen_tamdalrata(b): return list({b[:i] + l + b[i:] for i in range(1, len(b)) for l in rata}) if len(b) >= 2 else []
def gen_tamdaltidakrata(b): return list({b[:i] + l + b[i:] for i in range(1, len(b)) for l in tdk_rata}) if len(b) >= 2 else []
def gen_cadel(b): return list({b[:i] + l + b[i:] for i in range(len(b)+1) for l in "wycl"})

# ================== CORE LOGIC ==================
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
                    if ok: return f"🟢 @{u}"
                    return None
                except FloodWaitError as e:
                    client_cooldown[c] = time.time() + e.seconds
                    continue
                except: return None
            return None
    results = await asyncio.gather(*(worker(u) for u in usernames))
    return [r for r in results if r]

# ================== HANDLERS ==================
# ================== MONITORING & AUTH ==================

def auth(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        uid = user.id
        
        if uid in BANNED_USERS: return
            
        if uid not in AUTHORIZED_USERS and uid != ADMIN_ID:
            await update.message.reply_text("🔒 /login <pass> dulu.")
            return
        
        # LOG SEMUA COMMAND (Aktivitas user terpantau di sini)
        if uid != ADMIN_ID:
            cmd = update.message.text
            log_msg = f"⚡ **ACTIVITY LOG**\nUser: {user.first_name} ({uid})\nAction: `{cmd}`"
            try:
                await context.bot.send_message(ADMIN_ID, log_msg)
            except: pass
            
        return await func(update, context)
    return wrapper

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    text = update.message.text
    bot_obj = await context.bot.get_me()

    # 1. JIKA ADMIN REPLY LOG (Kirim pesan balik ke User)
    if uid == ADMIN_ID and update.message.reply_to_message:
        try:
            import re
            target_text = update.message.reply_to_message.text or update.message.reply_to_message.caption
            match = re.search(r'\((\d+)\)', target_text)
            
            if match:
                target_id = int(match.group(1))
                await context.bot.send_message(target_id, f"💬 **Pesan dari Admin:**\n{text}")
                await update.message.reply_text("✅ Terkirim.")
            else:
                await update.message.reply_text("❌ ID tidak ditemukan di pesan log.")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
        return

    # 2. JIKA USER REPLY BOT (Teruskan ke Admin)
    if uid != ADMIN_ID and update.message.reply_to_message:
        if update.message.reply_to_message.from_user.id == bot_obj.id:
            log_msg = f"💬 **USER REPLY BOT**\nFrom: {user.first_name} ({uid})\nMsg: {text}"
            await context.bot.send_message(ADMIN_ID, log_msg)

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
        await context.bot.send_message(ADMIN_ID, f"🔔 LOGIN ALERT\nName: {user.first_name}\nID: `{user.id}`")
    else: await update.message.reply_text("Salah pw nya.")

@auth
async def keep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not context.args: return
    u = context.args[0].replace("@", "")
    if uid in running_tasks: return await update.message.reply_text("⚠️ Task sudah jalan.")

    async def worker():
        while True:
            cl = get_available_client()
            if not cl: await asyncio.sleep(2); continue
            try:
                if await cl(functions.account.CheckUsernameRequest(u)):
                    res = await cl(functions.channels.CreateChannelRequest(title=f".", about=""))
                    await cl(functions.channels.UpdateUsernameRequest(channel=res.chats[0], username=u))
                    await update.message.reply_text(f"🏆 SUCCESS KEEP @{u}")
                    break
            except FloodWaitError as e: client_cooldown[cl] = time.time() + e.seconds
            except RPCError: break
            except: pass
            await asyncio.sleep(1)
        if uid in running_tasks: del running_tasks[uid]
        
    running_tasks[uid] = asyncio.create_task(worker())
    await update.message.reply_text(f"🚀 Hunting @{u}...")

@auth
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in running_tasks:
        running_tasks[uid].cancel(); del running_tasks[uid]
        await update.message.reply_text("🛑 Hunter Stop.")
    else: await update.message.reply_text("Gak ada task jalan.")

def create_scan(gen, lbl):
    @auth
    async def h(u: Update, c: ContextTypes.DEFAULT_TYPE):
        if not c.args: return
        base = c.args[0].replace("@", "")
        m = await u.message.reply_text(f"🔍 Scan {lbl} @{base}...")
        raw_res = gen(base)
        # Gabung dengan canon jika scanuncommon
        if lbl == "Uncommon": raw_res += gen_canon(base)
        
        res = await check_usernames_fast(list(set(raw_res))[:100])
        await m.edit_text("<b>AVAILABLE:</b>\n" + "\n".join(res) if res else "❌ Tidak ada yang tersedia.", parse_mode='HTML')
    return h

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target = int(context.args[0])
        save_ban(target)
        if target in running_tasks: 
            running_tasks[target].cancel(); del running_tasks[target]
        await update.message.reply_text(f"🚫 User {target} Banned.")
    except: pass

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target = int(context.args[0])
        if target in BANNED_USERS:
            BANNED_USERS.remove(target)
            # Hapus juga dari file agar permanen
            if os.path.exists(BAN_FILE):
                with open(BAN_FILE, "r") as f:
                    lines = f.readlines()
                with open(BAN_FILE, "w") as f:
                    for line in lines:
                        if line.strip() != str(target):
                            f.write(line)
            await update.message.reply_text(f"✅ User `{target}` telah di-unban.")
        else:
            await update.message.reply_text("User tidak ada di daftar ban.")
    except:
        await update.message.reply_text("Gunakan: /unban <user_id>")

# ================== MAIN ==================
async def main():
    load_bans()
    await init_clients()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    

    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("keep", keep))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_msg))

    scans = [
        ("scantamping", gen_tamping, "Tamping"), ("scanswitch", gen_switch, "Switch"),
        ("scantamhur", gen_tamhur, "Tamhur"), ("scanganhur", gen_ganhur, "Ganhur"),
        ("scanuncommon", gen_uncommon, "Uncommon"), ("scankurhur", gen_kurhur, "Kurhur"),
        ("scancadel", gen_cadel, "Cadel"), ("scanuncommon", gen_canon, "Uncommon"),
        ("scanrata", gen_rata, "Rata"), ("scantidakrata", gen_tidakrata, "Tdk Rata"),
        ("scanvokal", gen_vokal, "Vokal"), ("scantampingrata", gen_tampingrata, "Tamping Rata"),
        ("scantampingtidakrata", gen_tampingtidakrata, "Tamping Tdk Rata"), ("scantamdal", gen_tamdal, "Tamdal"),
        ("scantamdalrata", gen_tamdalrata, "Tamdal Rata"), ("scantamdaltidakrata", gen_tamdaltidakrata, "Tamdal Tdk Rata")
    ]
    for cmd, gen, lbl in scans:
        app.add_handler(CommandHandler(cmd, create_scan(gen, lbl)))

    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("🚀 ONLINE")
        while True: await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except:
        pass
