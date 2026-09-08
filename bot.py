import os
import string
import time
import logging
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
from telegram import (
    Update, InlineQueryResultArticle, InputTextMessageContent,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, 
    InlineQueryHandler, CallbackQueryHandler, ChosenInlineResultHandler, ContextTypes
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
client_index = 0
ALL_USERS = set()

# Cache sementara hasil scan per inline message id
SCAN_CACHE = {}

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
        except Exception: 
            pass

def get_available_client():
    global client_index
    now = time.time()
    available = [c for c in clients if client_cooldown[c] <= now]
    if not available: return None
    client = available[client_index % len(available)]
    client_index += 1
    return client

def chunk_results(items, chunk_size=15):
    return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]

def build_pagination_keyboard(current_page, total_pages, target_base, mode_key):
    if total_pages <= 1:
        return None
    
    buttons = []
    for i in range(total_pages):
        label = f"• {i+1} •" if i == current_page else f"{i+1}"
        buttons.append(InlineKeyboardButton(label, callback_data=f"page_{mode_key}_{target_base}_{i}"))
    
    return InlineKeyboardMarkup([buttons])

# Task Async yang Menjalankan Scan LIVE Real-Time
async def auto_scan_task_live(context: ContextTypes.DEFAULT_TYPE, inline_msg_id: str, mode_key: str, base: str):
    if not inline_msg_id:
        logger.error("❌ auto_scan_task_live dibatalkan: inline_message_id kosong.")
        return

    if not clients:
        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_msg_id,
                text="❌ Tidak ada acc aktif untuk scan."
            )
        except Exception as err:
            logger.error(f"Gagal kirim pesan error akun: {err}")
        return

    try:
        gen_func, lbl = GENERATORS.get(mode_key, (gen_tamhur, "Tamhur"))
        raw_res = gen_func(base)
        if mode_key == "uncommon":
            raw_res += gen_canon(base)

        candidates = list(set(raw_res))[:150]
        found_avail = []
        last_update_time = time.time()
        sem = asyncio.Semaphore(len(clients) * 3)

        async def worker(u):
            nonlocal last_update_time
            async with sem:
                for _ in range(2):
                    c = get_available_client()
                    if not c:
                        await asyncio.sleep(0.1)
                        continue
                    try:
                        ok = await c(functions.account.CheckUsernameRequest(u))
                        await asyncio.sleep(0.15)
                        if ok:
                            res_str = f"🟢 @{u}"
                            found_avail.append(res_str)

                            now = time.time()
                            if now - last_update_time > 2.5:
                                last_update_time = now
                                live_text = (
                                    f"scanning @{base} ({lbl})...\n"
                                    f"ditemukan: {len(found_avail)}\n\n" +
                                    "\n".join(found_avail[:15]) +
                                    ("\n..." if len(found_avail) > 15 else "")
                                )
                                try:
                                    await context.bot.edit_message_text(
                                        inline_message_id=inline_msg_id,
                                        text=live_text
                                    )
                                except Exception:
                                    pass
                            return res_str
                        return None
                    except FloodWaitError as e:
                        client_cooldown[c] = time.time() + e.seconds
                        continue
                    except Exception:
                        return None
                return None

        await asyncio.gather(*(worker(u) for u in candidates))

        if not found_avail:
            try:
                await context.bot.edit_message_text(
                    inline_message_id=inline_msg_id,
                    text=f"❌ Gak ada atau gak akun gua limit jadi gak nemu untuk @{base}."
                )
            except Exception as e:
                logger.error(f"Gagal edit pesan 'gak nemu': {e}")
            return

        pages = chunk_results(found_avail, chunk_size=15)
        
        SCAN_CACHE[inline_msg_id] = {
            "pages": pages,
            "mode_label": lbl,
            "base": base,
            "mode_key": mode_key
        }

        page_text = (
            f"hasil scan untuk @{base} ({lbl})\n"
            f"ada {len(found_avail)} usn\n\n" + 
            "\n".join(pages[0])
        )
        
        reply_markup = build_pagination_keyboard(0, len(pages), base, mode_key)

        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_msg_id,
                text=page_text,
                reply_markup=reply_markup
            )
        except Exception as final_err:
            logger.error(f"Gagal update hasil akhir: {final_err}")

    except Exception as e:
        logger.error(f"❌ Error fatal saat scan: {e}", exc_info=True)
        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_msg_id,
                text=f"❌ Terjadi Error: {e}"
            )
        except Exception:
            pass

# ================== CHOSEN INLINE RESULT ==================
async def chosen_inline_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chosen = update.chosen_inline_result
    inline_msg_id = chosen.inline_message_id
    result_id = chosen.result_id

    if not inline_msg_id:
        logger.warning("⚠️ ChosenInlineResult diterima tanpa inline_message_id!")
        return

    parts = result_id.split("_")
    if len(parts) >= 3:
        mode_key = parts[1]
        base = parts[2]
        
        asyncio.create_task(auto_scan_task_live(context, inline_msg_id, mode_key, base))

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
                description="anjay, uncommon anjay, tamping anjay, ganhur anjay, dll",
                input_message_content=InputTextMessageContent(
                    "Contoh penggunaan:\n"
                    " @sunless2bot adnan"
                )
            )
        ]
        await update.inline_query.answer(results, cache_time=1)
        return

    parts = query.split(maxsplit=1)
    
    if parts[0].lower() in GENERATORS and len(parts) > 1:
        mode_key = parts[0].lower()
        base = parts[1].replace("@", "")
        mode_label = GENERATORS[mode_key][1]
    else:
        mode_key = "tamhur"
        base = query.replace("@", "")
        mode_label = "Tamhur"

    loading_text = (
        f"Sedang mencari @{base} ({mode_label})..."  
    )

    results = [
        InlineQueryResultArticle(
            id=f"scan_{mode_key}_{base}_{int(time.time())}",
            title=f"Scan @{base} ({mode_label})",
            description=f"Langsung scan variasi username @{base}",
            input_message_content=InputTextMessageContent(loading_text)
        )
    ]
    
    await update.inline_query.answer(results, cache_time=1)

# ================== CALLBACK QUERY HANDLER (PAGINATION) ==================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    inline_msg_id = query.inline_message_id

    if data.startswith("page_"):
        _, mode_key, base, page_idx = data.split("_", 3)
        page_idx = int(page_idx)

        if inline_msg_id not in SCAN_CACHE:
            await query.answer("⚠️ Session scan ini sudah kadaluarsa. Silakan scan ulang.", show_alert=True)
            return

        cache_data = SCAN_CACHE[inline_msg_id]
        pages = cache_data["pages"]
        lbl = cache_data["mode_label"]

        if page_idx >= len(pages):
            await query.answer()
            return

        page_text = (
            f" hasil scan @{base} ({lbl}) - Halaman {page_idx + 1}/{len(pages)}\n"
            f"Total ditemukan: {sum(len(p) for p in pages)} usn\n\n" + 
            "\n".join(pages[page_idx])
        )

        reply_markup = build_pagination_keyboard(page_idx, len(pages), base, mode_key)

        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_msg_id,
                text=page_text,
                reply_markup=reply_markup
            )
            await query.answer(f"Halaman {page_idx + 1}")
        except Exception:
            await query.answer()

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
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(ChosenInlineResultHandler(chosen_inline_result))

    logger.info("🚀 Bot berjalan...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
