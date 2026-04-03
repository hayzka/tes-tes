import asyncio
import os
import string
import time
from telethon import TelegramClient, functions
from telethon.errors import UsernameInvalidError, UsernameOccupiedError, FloodWaitError

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes



api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")

PASSWORD = "yyy"

SESSIONS = [f"acc{i}" for i in range(1, 11)]

AUTHORIZED_USERS = set()
clients = []
client_cooldown = {}
running_tasks = {}

client_index = 0

# init client

async def init_clients():
    for s in SESSIONS:
        c = TelegramClient(s, api_id, api_hash)
        await c.start()
        clients.append(c)
        client_cooldown[c] = 0


def get_available_client():
    global client_index
    now = time.time()

    available = [c for c in clients if client_cooldown[c] <= now]

    if not available:
        return []

    client = available[client_index % len(available)]
    client_index += 1

    return [client]

# auth
def auth(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in AUTHORIZED_USERS:
            await update.message.reply_text("/login dulu")
            return
        return await func(update, context)
    return wrapper

# login
async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0] == PASSWORD:
        AUTHORIZED_USERS.add(update.effective_user.id)
        await update.message.reply_text("Slmt")
    else:
        await update.message.reply_text("Salah, yg bener aja")

# check
async def check_one(client, username):
    try:
        ok = await client(functions.account.CheckUsernameRequest(username))
        return f"🟢 @{username}" if ok else f"🔴 @{username}"

    except FloodWaitError as e:
        client_cooldown[client] = time.time() + e.seconds
        return f"⚠️ @{username}"

    except Exception:
        return f"❌ @{username}"

async def check_usernames_fast(usernames):
    sem = asyncio.Semaphore(30)

    async def worker(username):
        async with sem:
            available = get_available_client()

            if not available:
                await asyncio.sleep(0.5)
                return f"⏳ @{username}"

            client = available[0]
            result = await check_one(client, username)
            await asyncio.sleep(0.05)
            return result

    tasks = [worker(u) for u in usernames]
    return await asyncio.gather(*tasks)

@auth
async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("/check username")

    usernames = [u.replace("@", "") for u in context.args]
    result = await check_usernames_fast(usernames)

    await update.message.reply_text("\n".join(result))

# keep
@auth
async def keep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("/keep username")

    username = context.args[0].replace("@", "")
    user_id = update.effective_user.id

    if user_id in running_tasks:
        return await update.message.reply_text("Sudah running")

    await update.message.reply_text(f"Hunting @{username}")

    async def worker():
        while True:
            available = get_available_client()

            if not available:
                await asyncio.sleep(0.5)
                continue

            for client in available:
                try:
                    ok = await client(functions.account.CheckUsernameRequest(username))

                    if ok:
                        await client(functions.account.UpdateUsernameRequest(username))
                        await update.message.reply_text(f"sdh @{username}")
                        return

                except FloodWaitError as e:
                    client_cooldown[client] = time.time() + e.seconds

                except Exception:
                    pass

            await asyncio.sleep(0.05)

    running_tasks[user_id] = asyncio.create_task(worker())

# stop
@auth
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id in running_tasks:
        running_tasks[user_id].cancel()
        del running_tasks[user_id]
        await update.message.reply_text("Stopped")
    else:
        await update.message.reply_text("Tidak ada task")

# scan
def tambah_huruf(base):
    letters = string.ascii_lowercase
    return list({base[:i] + l + base[i:] for i in range(len(base)+1) for l in letters})

def ganti_huruf(base):
    letters = string.ascii_lowercase
    return list({base[:i] + l + base[i+1:] for i in range(len(base)) for l in letters})

def uncommon(base):
    return list({base[:i] + base[i] + base[i:] for i in range(len(base))})

@auth
async def scantamhur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    base = context.args[0]
    variants = tambah_huruf(base)[:50]

    await update.message.reply_text("scanning tamhur...")
    result = await check_usernames_fast(variants)
    await update.message.reply_text("\n".join(result))

@auth
async def scanganhur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    base = context.args[0]
    variants = ganti_huruf(base)[:50]

    await update.message.reply_text("scanning ganhur...")
    result = await check_usernames_fast(variants)
    await update.message.reply_text("\n".join(result))

@auth
async def scanuncommon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    base = context.args[0]
    variants = uncommon(base)[:50]

    await update.message.reply_text("scanning uncommon...")
    result = await check_usernames_fast(variants)
    await update.message.reply_text("\n".join(result))

# main
async def main():
    await init_clients()

    app = ApplicationBuilder().token(bot_token).build()

    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("check", check))
    app.add_handler(CommandHandler("keep", keep))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("scantamhur", scantamhur))
    app.add_handler(CommandHandler("scanganhur", scanganhur))
    app.add_handler(CommandHandler("scanuncommon", scanuncommon))

    print("BISA")

    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
   
