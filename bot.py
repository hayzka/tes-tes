import os
import string
import time
import logging
import re
import asyncio
import nest_asyncio

# Set up logger agar perintah logger.info / logger.error tidak crash
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# 1. Jalankan nest_asyncio dan load file .env di bagian paling atas
nest_asyncio.apply()
from dotenv import load_dotenv
load_dotenv()

# 2. Import library Telegram
from telethon import TelegramClient, functions
from telethon.errors import FloodWaitError, RPCError
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# 3. Masukkan variabel os.getenv
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
PASSWORD = os.getenv("PASSWORD", "nephis")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Gunakan folder lokal saat ini agar tidak terkena Permission Error di Termux
DATA_DIR = "./" 
BAN_FILE = f"{DATA_DIR}banned.txt"
USER_FILE = f"{DATA_DIR}users.txt"

AUTHORIZED_USERS = set()
BANNED_USERS = set()
clients = []
client_cooldown = {}
running_tasks = {}
client_index = 0

# ================== PERSISTENCE ==================
ALL_USERS = set()

def load_users():
    if os.path.exists(USER_FILE):
        with open(USER_FILE, "r") as f:
            for line in f:
                if line.strip(): 
                    ALL_USERS.add(int(line.strip()))

def save_user(user_id):
    if user_id not in ALL_USERS:
        ALL_USERS.add(user_id)
        with open(USER_FILE, "a") as f:
            f.write(f"{user_id}\n")

def load_bans():
    if os.path.exists(BAN_FILE):
        with open(BAN_FILE, "r") as f:
            for line in f:
                if line.strip(): 
                    BANNED_USERS.add(int(line.strip()))

def save_ban(user_id):
    BANNED_USERS.add(user_id)
    with open(BAN_FILE, "a") as f:
        f.write(f"{user_id}\n")

async def check_status(client, username):
    try:
        entity = await client.get_entity(username)
        from telethon.tl.types import Channel, Chat, User
        if isinstance(entity, Channel):
            return "SOLD (CH/GRUP)"
        elif isinstance(entity, User):
            return "SOLD (USER)"
        return "SOLD"
    except Exception as e:
        err = str(e).lower()
        if "banned" in err or "spam" in err:
            return "BANNED"
        if "collectible" in err:
            return "FRAGMENT"
        if "no node found" in err or "not found" in err:
            return "BISA DIKEEP"
        return "UNKNOWN / FLOOD"

async def scan_list(update, context, list_username):
    results = []
    # Jika skrip membutuhkan client aktif pertama untuk scan_list biasa
    client = clients[0] if clients else None
    if not client:
        await update.message.reply_text("❌ Tidak ada akun Telethon yang aktif.")
        return

    for username in list_username:
        status = await check_status(client, username)
        results.append(f"@{username} -> {status}")
    
    pesan_akhir = "Daftar Hasil Scan:\n\n" + "\n".join(results)
    await update.message.reply_text(pesan_akhir)

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
    if not API_ID or not API_HASH: 
        logger.error("❌ API_ID atau API_HASH kosong di .env")
        return
    for i in range(1, 11):
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
            logger.error(f"❌ acc{i}: {e}")

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

# --- 1. DECORATOR AUTH ---
def auth(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        uid = user.id
        text = update.message.text
        chat_type = update.effective_chat.type
        
        if uid not in AUTHORIZED_USERS and uid != ADMIN_ID:
            await update.message.reply_text(" /login <pass> dulu.")
            return

        source = "GRUP" if chat_type != "private" else "PRIVATE"
        log_text = (
            f"⚡ COMMAND LOG ({source})\n"
            f"👤 User: {user.first_name} ({uid})\n"
            f"⌨️ Action: `{text}`"
        )
        try:
            await context.bot.send_message(ADMIN_ID, log_text)
        except:
            pass
            
        return await func(update, context)
    return wrapper

# --- 2. HANDLER PESAN ---
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    text = update.message.text
    chat_type = update.effective_chat.type
    bot_obj = await context.bot.get_me()

    if uid == ADMIN_ID and update.message.reply_to_message:
        reply_to = update.message.reply_to_message
        target_text = reply_to.text or reply_to.caption
        if target_text:
            match = re.search(r'\((\d+)\)', target_text)
            if match:
                target_id = int(match.group(1))
                try:
                    await context.bot.send_message(target_id, f"{text}")
                    await update.message.reply_text(f"✅ Terkirim ke `{target_id}`")
                    return
                except: return

    if uid != ADMIN_ID:
        if 'save_user' in globals(): save_user(uid)
        if chat_type == "private":
            if not text.startswith('/'):
                log_pc = f"📥 PRIVATE MESSAGE\n👤 From: {user.first_name} ({uid})\n📝 Msg: {text}"
                await context.bot.send_message(ADMIN_ID, log_pc)
            return
        elif chat_type != "private":
            if update.message.reply_to_message and update.message.reply_to_message.from_user.id == bot_obj.id:
                log_grp = f"👥 GROUP REPLY\n👤 From: {user.first_name} ({uid})\n📝 Msg: {text}"
                await context.bot.send_message(ADMIN_ID, log_grp)
            return

# ================== COMMAND HANDLERS ==================
async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Commands:\n"
        "• /login [password]\n"
        "• /keep [user] - buat autokeep\n"
        "• /stop - hentiin autokeep\n"
        "• /bc - buat bc\n"
        "• /info \n\n"
        "Scanning:\n"
        "• /scanswitch \n"
        "• /scankurhur \n"
        "• /scancadel - 'wycl'\n\n"
        "Scanning:\n"
        "• /scanrata\n"
        "• /scantidakrata\n"
        "• /scanvokal\n"
        "• /scanuncommon\n"
        "• /scantamhur\n"
        "• /scanganhur\n"
        "Noted: keep jangan sering dipake"
    )
    await update.message.reply_text(help_text)

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in BANNED_USERS: return
    if context.args and context.args[0] == PASSWORD:
        AUTHORIZED_USERS.add(user.id)
        await update.message.reply_text("✅ Sukses Login.")
        await context.bot.send_message(ADMIN_ID, f"🔔 LOGIN SUCCESS\nName: {user.first_name} ({user.id})")
    else: await update.message.reply_text("❌ Password salah.")

@auth
async def keep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = update.effective_user
    if not context.args: return
    target = context.args[0].replace("@", "")
    if uid in running_tasks: return await update.message.reply_text("⚠️ Task sedang jalan.")

    async def worker():
        while True:
            cl = get_available_client()
            if not cl: await asyncio.sleep(2); continue
            try:
                if await cl(functions.account.CheckUsernameRequest(target)):
                    res = await cl(functions.channels.CreateChannelRequest(title=".", about=""))
                    await cl(functions.channels.UpdateUsernameRequest(channel=res.chats[0], username=target))
                    await update.message.reply_text(f"🎯 DAPET: @{target}")
                    await context.bot.send_message(ADMIN_ID, f"🎯 SUCCESS KEEP\nTarget: @{target}\nBy: {user.first_name} ({user.id})")
                    break
            except FloodWaitError as e: client_cooldown[cl] = time.time() + e.seconds
            except: break
            await asyncio.sleep(1)
        if uid in running_tasks: del running_tasks[uid]
        
    running_tasks[uid] = asyncio.create_task(worker())
    await update.message.reply_text(f"🚀 Hunting @{target}...")

@auth
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in running_tasks:
        running_tasks[uid].cancel(); del running_tasks[uid]
        await update.message.reply_text("🛑 Hunter dihentikan.")
    else: await update.message.reply_text("Gak ada task aktif.")

def create_scan(gen, lbl):
    @auth
    async def h(u: Update, c: ContextTypes.DEFAULT_TYPE):
        if not c.args: return
        base = c.args[0].replace("@", "")
        m = await u.message.reply_text(f"🔍 Scanning {lbl} @{base}...")
        raw_res = gen(base)
        if lbl == "Uncommon": raw_res += gen_canon(base)
        res = await check_usernames_fast(list(set(raw_res))[:100])
        await m.edit_text("<b>AVAILABLE:</b>\n" + "\n".join(res) if res else "❌ Tidak ada yang tersedia.", parse_mode='HTML')
    return h

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        tid = int(context.args[0]); save_ban(tid)
        if tid in running_tasks: running_tasks[tid].cancel(); del running_tasks[tid]
        await update.message.reply_text(f"🚫 User {tid} Banned.")
    except: pass

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        tid = int(context.args[0])
        if tid in BANNED_USERS: BANNED_USERS.remove(tid)
        await update.message.reply_text(f"✅ User {tid} Unbanned.")
    except: pass

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("❌ Format salah! Gunakan: `/bc <pesan>`")
        return

    pesan_bc = " ".join(context.args)
    targets = list(ALL_USERS)
    total = len(targets)
    
    if total == 0:
        await update.message.reply_text("❌ Belum ada user yang terdaftar di database.")
        return

    progress_msg = await update.message.reply_text(f"📢 Memulai broadcast ke {total} user...")
    sukses, gagal = 0, 0

    for user_id in targets:
        try:
            await context.bot.send_message(chat_id=user_id, text=f"{pesan_bc}", parse_mode='Markdown')
            sukses += 1
            await asyncio.sleep(0.05) 
        except Exception as e:
            logger.error(f"Gagal kirim ke {user_id}: {e}")
            gagal += 1
    
    await progress_msg.edit_text(
        f"✅ Broadcast Selesai!\n\n🚀 Berhasil: {sukses}\n❌ Gagal: {gagal}\n📊 Total Target: {total}"
    )

# ================== MAIN RUNNER ==================
async def main():
    load_bans()
    load_users()
    await init_clients()
    
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN tidak ditemukan di file .env")
        return
        
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("bc", broadcast))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("keep", keep))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))

    scans = [
        ("scantamping", gen_tamping, "Tamping"), ("scanswitch", gen_switch, "Switch"),
        ("scantamhur", gen_tamhur, "Tamhur"), ("scanganhur", gen_ganhur, "Ganhur"),
        ("scanuncommon", gen_uncommon, "Uncommon"), ("scankurhur", gen_kurhur, "Kurhur"),
        ("scancadel", gen_cadel, "Cadel"), ("scanrata", gen_rata, "Rata"), 
        ("scantidakrata", gen_tidakrata, "Tdk Rata"), ("scanvokal", gen_vokal, "Vokal"), 
        ("scantampingrata", gen_tampingrata, "Tamping Rata"), ("scantampingtidakrata", gen_tampingtidakrata, "Tamping Tdk Rata"), 
        ("scantamdal", gen_tamdal, "Tamdal"), ("scantamdalrata", gen_tamdalrata, "Tamdal Rata"), 
        ("scantamdaltidakrata", gen_tamdaltidakrata, "Tamdal Tdk Rata")
    ]
    for cmd, gen, lbl in scans:
        app.add_handler(CommandHandler(cmd, create_scan(gen, lbl)))

    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_msg))

    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("🚀 BOT IS ONLINE & RUNNING")
        while True: 
            await asyncio.sleep(3600)

if __name__ == "__main__":
    # Menghapus try-except bisu agar error asli terlihat di Termux jika terjadi sesuatu
    asyncio.run(main())
