import os
import json
import time
import logging
from typing import Dict, List

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# --- CONFIGURATION ---
# It is better to rely on Environment Variables for security.
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID") or 0)
ADMIN_IDS = [int(x) for x in (os.getenv("ADMIN_IDS") or "").split(",") if x.strip()]

STATE_FILE = "anon_state.json"
RATE_LIMIT = 1.3

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- STATE MANAGEMENT ---
queue: List[int] = []
sessions: Dict[int, int] = {}
last_time: Dict[int, float] = {}

def save_state():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({"queue": queue, "sessions": sessions}, f)
    except Exception as e:
        logger.error(f"Save state failed: {e}")

def load_state():
    global queue, sessions
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                queue = data.get("queue", [])
                sessions = {int(k): int(v) for k, v in data.get("sessions", {}).items()}
    except Exception as e:
        logger.error(f"Load state failed: {e}")
        queue = []
        sessions = {}

# --- HELPERS ---
def is_admin(uid): 
    return uid in ADMIN_IDS

async def notify_admins(app, text):
    for adm in ADMIN_IDS:
        try:
            await app.bot.send_message(adm, f"[ADMIN]\n{text}")
        except:
            pass

def rate_limited(uid):
    now = time.time()
    if uid in last_time and now - last_time[uid] < RATE_LIMIT:
        return True
    last_time[uid] = now
    return False

def pair(a, b):
    sessions[a] = b
    sessions[b] = a
    save_state()

def unpair(uid):
    p = sessions.pop(uid, None)
    if p:
        sessions.pop(p, None)
        save_state()
    return p

def find_partner(uid):
    if uid in sessions:
        return sessions[uid]
    if uid in queue:
        try: queue.remove(uid)
        except: pass
    if queue:
        other = queue.pop(0)
        pair(uid, other)
        return other
    queue.append(uid)
    save_state()
    return None

async def send_menu(ctx, chat_id):
    menu_text = (
        "✨ **Anonymous Bot Menu** ✨\n\n"
        "/anon_start – Find a partner\n"
        "/anon_next – Skip to next partner\n"
        "/anon_stop – Stop current chat\n"
        "/status – Check connection status"
    )
    try:
        await ctx.bot.send_message(chat_id, menu_text, parse_mode="Markdown")
    except:
        pass

# --- COMMAND HANDLERS ---
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await send_menu(ctx, update.effective_user.id)

async def myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your ID: `{update.effective_user.id}`", parse_mode="Markdown")

async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in sessions:
        await update.message.reply_text("✅ Status: **Connected**", parse_mode="Markdown")
    elif uid in queue:
        await update.message.reply_text("⏳ Status: **Waiting in Queue**", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Status: **Not in chat**", parse_mode="Markdown")

async def anon_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    p = find_partner(uid)
    if p:
        await ctx.bot.send_message(uid, "🎯 **Partner connected!** Say hi.", parse_mode="Markdown")
        await ctx.bot.send_message(p, "🎯 **Partner connected!** Say hi.", parse_mode="Markdown")
    else:
        await ctx.bot.send_message(uid, "⏳ Searching for a partner... please wait.")

async def anon_next(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    old = unpair(uid)
    if old:
        await ctx.bot.send_message(old, "⚠️ Partner disconnected.")
    
    p = find_partner(uid)
    if p:
        await ctx.bot.send_message(uid, "🎯 **New partner connected!**", parse_mode="Markdown")
        await ctx.bot.send_message(p, "🎯 **New partner connected!**", parse_mode="Markdown")
    else:
        await ctx.bot.send_message(uid, "⏳ Searching for a new partner...")

async def anon_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    p = unpair(uid)
    if p:
        await ctx.bot.send_message(p, "⚠️ Partner disconnected.")
    if uid in queue:
        queue.remove(uid)
        save_state()
    await ctx.bot.send_message(uid, "❌ You left the chat.")

# --- MESSAGE HANDLING ---
async def handle_all_messages(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = update.effective_message

    if not msg or (msg.text and msg.text.startswith('/')):
        return

    # 1. Forward to Group (Monitoring)
    if any([msg.photo, msg.video, msg.audio, msg.voice, msg.document, msg.sticker]):
        try:
            await ctx.bot.forward_message(GROUP_ID, msg.chat_id, msg.message_id)
        except:
            pass

    # 2. Relay to Partner
    if uid in sessions and not rate_limited(uid):
        partner = sessions.get(uid)
        try:
            await ctx.bot.copy_message(
                chat_id=partner,
                from_chat_id=msg.chat_id,
                message_id=msg.message_id,
                caption=msg.caption
            )
        except:
            await ctx.bot.send_message(uid, "⚠️ Failed to send message to partner.")
    elif uid not in sessions:
        await ctx.bot.send_message(uid, "❌ You aren't connected to anyone. Use /anon_start")

# --- MAIN LOOP ---
if __name__ == "__main__":
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not found in environment variables!")
        exit(1)

    load_state()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("anon_start", anon_start))
    app.add_handler(CommandHandler("anon_next", anon_next))
    app.add_handler(CommandHandler("anon_stop", anon_stop))
    app.add_handler(CommandHandler("status", status))
    
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_all_messages, block=False))

    print("🚀 Bot is starting...")
    app.run_polling()
    
