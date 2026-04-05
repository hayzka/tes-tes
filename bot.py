import asyncio
import os
import string
import time
import logging
import nest_asyncio
from telethon import TelegramClient, functions
from telethon.errors import FloodWaitError, UsernameOccupiedError, UsernameInvalidError, RPCError
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# ================== LOGGING & MEMORY DB ==================
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Simpan user di RAM (Tanpa file agar tidak crash di Railway)
seen_users = set()

# ================== CONFIG ==================
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
PASSWORD = os.getenv("PASSWORD", "sunny")
ADMIN_ID = os.getenv("ADMIN_ID") 

# Cari di folder utama (GitHub)
SESSION_DIR = "./" 
SESSIONS = [f"{SESSION_DIR}acc{i}" for i in range(1, 11)]

AUTHORIZED_USERS = set()
clients = []
client_cooldown = {}
running_tasks = {}
client_index = 0

# ================== ALL GENERATORS (16 TYPES) ==================
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
    await asyncio.sleep(5)
    for s in SESSIONS:
        full_path = f"{s}.session"
        if os.path.exists(full_path):
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
    global client_index
    if not clients: return None
    now = time.time()
    available = [c for c in clients if client_cooldown.get(c, 0) <= now]
    if not available: return None
    client = available[client_index % len(available)]
    client_index += 1
    return client

async def check_usernames_fast(usernames):
    sem = asyncio.Semaphore(5)
    async def worker(u):
        async with sem:
            cl = get_available_client()
            if not cl: return None
            try:
                if await cl(functions.account.CheckUsernameRequest(u)): return f"🟢 @{u}"
            except FloodWaitError as e: client_cooldown[cl] = time.time() + e.seconds
            except: pass
            return None
    results = await asyncio.gather(*(worker(u) for u in usernames))
    return [r for r in results if r]

# ================== HANDLERS ==================
def auth_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in AUTHORIZED_USERS: return 
        return await func(update, context)
    return wrapper

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    seen_users.add(update.effective_user.id)
    await update.message.reply_text(f"Halo {update.effective_user.first_name}! Silakan kirim pesan.")

# Simpan ID pesan otomatis biar bisa dihapus nanti
# Format: {user_id: message_id}
pending_replies = {}
seen_users = set()

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    username = f"@{update.effective_user.username}" if update.effective_user.username else "No Usn"
    text = update.message.text
    
    seen_users.add(user_id)
    
    # --- 1. ADMIN MEMBALAS (REPLY) ---
    if user_id in AUTHORIZED_USERS and update.message.reply_to_message:
        reply_text = update.message.reply_to_message.text
        if "🆔 ID:" in reply_text:
            try:
                target_id = int(reply_text.split("🆔 ID:")[1].split("\n")[0].strip())
                
                # KIRIM PESAN KE USER
                await context.bot.send_message(
                    chat_id=target_id, 
                    text=f"💬 <b>Pesan dari Admin:</b>\n\n{text}", 
                    parse_mode='HTML'
                )
                
                # HAPUS PESAN "PESAN DITERIMA" DI SISI USER (Jika ada)
                if target_id in pending_replies:
                    try:
                        await context.bot.delete_message(
                            chat_id=target_id, 
                            message_id=pending_replies[target_id]
                        )
                        del pending_replies[target_id] # Hapus dari memori setelah sukses
                    except: pass 
                
                await update.message.reply_text(f"✅ Terkirim & Pesan otomatis dihapus.")
            except Exception as e:
                await update.message.reply_text(f"❌ Gagal: {e}")
            return

    # --- 2. USER BIASA CHAT ---
    if user_id not in AUTHORIZED_USERS:
        # Kirim pesan otomatis dan simpan ID-nya
        sent_msg = await update.message.reply_text("Pesan diterima! Admin akan segera membalas.")
        pending_replies[user_id] = sent_msg.message_id
        
        # Lapor ke Admin
        if ADMIN_ID:
            report = (
                f"📩 <b>PESAN BARU MASUK</b>\n"
                f"👤 Dari: {user_name} ({username})\n"
                f"🆔 ID: <code>{user_id}</code>\n\n"
                f"💬 Isi:\n{text}\n\n"
                f"ℹ️ <i>Reply pesan ini untuk membalas.</i>"
            )
            await context.bot.send_message(chat_id=int(ADMIN_ID), text=report, parse_mode='HTML')
            
async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0] == PASSWORD:
        AUTHORIZED_USERS.add(update.effective_user.id)
        await update.message.reply_text("🔓 **Login Berhasil.** Fitur Admin Aktif.")
    else: await update.message.reply_text("❌ Password salah.")

@auth_only
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    msg = " ".join(context.args)
    count = 0
    for uid in list(seen_users):
        try:
            await context.bot.send_message(chat_id=uid, text=msg)
            count += 1
            await asyncio.sleep(0.05)
        except: pass
    await update.message.reply_text(f"✅ Broadcast selesai ke {count} user.")

@auth_only
async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "<b>🛠 ADMIN PANEL</b>\n\n"
        "<b>CORE:</b>\n"
        "• /login [pw], /broadcast [msg]\n"
        "• /keep [usn], /stop\n\n"
        "<b>SCANS:</b>\n"
        "• /check, /scanswitch, /scankurhur, /scanganhur\n"
        "• /scancadel, /scancanon, /scanuncommon, /scantamhur\n"
        "• /scanrata, /scantidakrata, /scanvokal, /scantamping\n"
        "• /scantampingrata, /scantampingtidakrata\n"
        "• /scantamdal, /scantamdalrata, /scantamdaltidakrata"
    )
    await update.message.reply_text(text, parse_mode='HTML')

@auth_only
async def keep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    u = context.args[0].replace("@", "")
    uid = update.effective_user.id
    if uid in running_tasks: return await update.message.reply_text("⚠️ Task aktif.")
    async def worker():
        while True:
            cl = get_available_client()
            if not cl: await asyncio.sleep(10); continue
            try:
                if await cl(functions.account.CheckUsernameRequest(u)):
                    res = await cl(functions.channels.CreateChannelRequest(title=f"{u}", about="@slateid"))
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

# ================== RUNNER ==================
async def main():
    await init_clients()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("broadcast", broadcast))
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
        app.add_handler(CommandHandler(cmd, create_scan(gen, lbl)))

    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_msg))
    await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    nest_asyncio.apply()
    asyncio.run(main())
