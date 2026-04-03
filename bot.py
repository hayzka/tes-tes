import asyncio
import string
from telethon import TelegramClient, functions
from telethon.errors import UsernameInvalidError, UsernameOccupiedError, FloodWaitError

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# =====================
# CONFIG
# =====================
import os

api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")

PASSWORD = "yyy"

SESSIONS = ["acc1", "acc2", "acc3"]

AUTHORIZED_USERS = set()
clients = []
client_index = 0
running_tasks = {}

# =====================
# INIT CLIENTS
# =====================
async def init_clients():
    for s in SESSIONS:
        c = TelegramClient(s, api_id, api_hash)
        await c.start()
        clients.append(c)

def get_client():
    global client_index
    c = clients[client_index]
    client_index = (client_index + 1) % len(clients)
    return c

# =====================
# AUTH
# =====================
def auth(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in AUTHORIZED_USERS:
            await update.message.reply_text(" /login dulu")
            return
        return await func(update, context)
    return wrapper

# =====================
# LOGIN
# =====================
async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0] == PASSWORD:
        AUTHORIZED_USERS.add(update.effective_user.id)
        await update.message.reply_text("Slmt")
    else:
        await update.message.reply_text("Salah, yang bener aja")

# =====================
# VARIATION
# =====================
def tambah_huruf(base):
    letters = string.ascii_lowercase
    return list({base[:i] + l + base[i:] for i in range(len(base)+1) for l in letters})

def ganti_huruf(base):
    letters = string.ascii_lowercase
    return list({base[:i] + l + base[i+1:] for i in range(len(base)) for l in letters})

def uncommon(base):
    return list({base[:i] + base[i] + base[i:] for i in range(len(base))})

# =====================
# CHECK FUNCTION
# =====================
async def check_usernames(usernames):
    results = []

    for username in usernames:
        client = get_client()

        try:
            ok = await client(functions.account.CheckUsernameRequest(username))

            if ok:
                results.append(f"🟢 @{username}")
            else:
                results.append(f"🔴 @{username}")

        except UsernameInvalidError:
            results.append(f"⚠️ @{username}")

        except UsernameOccupiedError:
            results.append(f"🔴 @{username}")

        except FloodWaitError as e:
            await asyncio.sleep(e.seconds)

        except Exception:
            results.append(f"❌ @{username}")

        await asyncio.sleep(0.3)

    return results

# =====================
# COMMAND CHECK
# =====================
@auth
async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("/check username")

    usernames = [u.replace("@", "") for u in context.args]
    result = await check_usernames(usernames)

    await update.message.reply_text("\n".join(result))

# =====================
# SCAN COMMANDS (AUTO CHECK)
# =====================
@auth
async def scantamhur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("/scantamhur username")

    base = context.args[0].replace("@", "")
    variants = tambah_huruf(base)[:50]

    await update.message.reply_text("🔍 scanning tamhur...")
    result = await check_usernames(variants)

    await update.message.reply_text("\n".join(result))

@auth
async def scanganhur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("/scanganhur username")

    base = context.args[0].replace("@", "")
    variants = ganti_huruf(base)[:50]

    await update.message.reply_text("🔍 scanning ganhur...")
    result = await check_usernames(variants)

    await update.message.reply_text("\n".join(result))

@auth
async def scanuncommon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("/scanuncommon username")

    base = context.args[0].replace("@", "")
    variants = uncommon(base)[:50]

    await update.message.reply_text("🔍 scanning uncommon...")
    result = await check_usernames(variants)

    await update.message.reply_text("\n".join(result))

# =====================
# MAIN
# =====================
async def main():
    await init_clients()

    app = ApplicationBuilder().token(bot_token).build()

    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("check", check))
    app.add_handler(CommandHandler("scantamhur", scantamhur))
    app.add_handler(CommandHandler("scanganhur", scanganhur))
    app.add_handler(CommandHandler("scanuncommon", scanuncommon))

    print("🔥 BOT GROUP READY...")

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    # biar tetap jalan
    while True:
        await asyncio.sleep(999)

import asyncio

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
   
