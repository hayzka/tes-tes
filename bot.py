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

SESSIONS = ["acc1", "acc2", "acc3", "acc4", "acc5", "acc6", "acc7", "acc8", "acc9", "acc10"]

AUTHORIZED_USERS = set()
clients = []
client_cooldown = {}
running_tasks = {}


async def init_clients():
    for s in SESSIONS:
        c = TelegramClient(s, api_id, api_hash)
        await c.start()
        clients.append(c)
        client_cooldown[c] = 0

def get_available_client():
    now = time.time()
    return [c for c in clients if client cooldown[c] <= now]

#auth

def auth(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in AUTHORIZED_USERS:
            await update.message.reply_text(" /login dulu")
            return
        return await func(update, context)
    return wrapper


# login

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0] == PASSWORD:
        AUTHORIZED_USERS.add(update.effective_user.id)
        await update.message.reply_text("Slmt")
    else:
        await update.message.reply_text("Salah, yang bener aja")


# scan

def tambah_huruf(base):
    letters = string.ascii_lowercase
    return list({base[:i] + l + base[i:] for i in range(len(base)+1) for l in letters})

def ganti_huruf(base):
    letters = string.ascii_lowercase
    return list({base[:i] + l + base[i+1:] for i in range(len(base)) for l in letters})

def uncommon(base):
    return list({base[:i] + base[i] + base[i:] for i in range(len(base))})

#autokeep

@auth
async def keep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("/keep username")
        
    username = context.args[0].replace("@", "")
    user_id = update_effective_user.id
    if user_id in running_tasks:
        return await update.message.reply_text("dah running")
        await update.message.reply_text(f"hunting @{usename}")

async def worker():
    while true:
        available = get_available_clients()
        if not available:
            await asyncio.sleep(2)
            continue
        for client in available:
            try:
                ok = await client(functions.account.CheckUsernameRequest(username))
                
                if ok:
                    await client(functions.account.CheckUsernameRequest(username))
                    await update.message.reply_text(f"dah dikeep @{usename}")
                    return
                    
            except FloodWaitError as e:
                client_cooldown[client] = time.time + e.second
            except Exeception:user_id = update_effective_user.id
    if user_id in running_tasks:
        return await update.message.reply_text("dah running")
        user_id = update_effective_user.id
    if user_id in running_tasks:
        return await update.message.reply_text("dah running")
        await update.message.reply_text(f"hunting @{usename}")

                pass
        
        await asyncio.sleep(0,5)

running tasks[user_id] = asyncio.create_tasks(worker())
                
#stop

@auth
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update_effective_user.id
    if user_id in running_tasks:
        running_tasks[user_id].cancel()
        del running_tasks[user_id]
        await update.message.reply_text(f"STOP")
    else:
         await update.message.reply_text(f"tidak ada tasks")
         

#

async def check_one(client, usernames):
        try:
            ok = await client(functions.account.CheckUsernameRequest(username))

            if ok:
                return f"🟢 @{username}"
            else:
                return f"🔴 @{username}"

        except FloodWaitError as e:
            client_cooldown[client] = time.time() + e.second
            return f"⚠️ @{username}"

        except UsernameOccupiedError:
            return f"🔴 @{username}"

        except Exception:
            return f"❌ @{username}"

    async def check_username_fast(username):
        results = []
        sem = asyncio.Semaphore(5)
        
        async def worker(username):
            async with sem:
                available = get_available_clients()
                if not available:
                    await asyncio.sleep(2)
                    return f"bntr @{username}"
                client = available[0]
                result = await check_one(client, username)
                await asyncio.sleep(0,3)
                return result

        tasks = [worker(u) for u in username]
        results = await asyncio.gather(*tasks)
        
        return results

#check

@auth
async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("/check username")

    usernames = [u.replace("@", "") for u in context.args]
    result = await check_usernames(usernames)

    await update.message.reply_text("\n".join(result))

#scan

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

#main

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

    print("🔥 BOT GROUP READY...")

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    
    while True:
        await asyncio.sleep(999)


if __name__ == "__main__":
    loop.run_until_complete(main())
   
