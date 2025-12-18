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

# ================= CONFIG (STRICT) =================
BOT_TOKEN = os.environ["BOT_TOKEN"]
GROUP_ID = int(os.environ["GROUP_ID"])
ADMIN_IDS = [int(x) for x in os.environ["ADMIN_IDS"].split(",")]

STATE_FILE = "anon_state.json"
RATE_LIMIT = 1.3

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ================= STATE =================
queue: List[int] = []
sessions: Dict[int, int] = {}
last_time: Dict[int, float] = {}

# ================= PERSISTENCE =================
def save_state():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({"queue": queue, "sessions": sessions}, f)
    except Exception as e:
        log.warning(f"State save failed: {e}")

def load_state():
    global queue, sessions
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
            queue = data.get("queue", [])
            sessions = {int(k): int(v) for k, v in data.get("sessions", {}).items()}
        except Exception as e:
            log.warning(f"State load failed: {e}")

# ================= HELPERS =================
def is_admin(uid): 
    return uid in ADMIN_IDS

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
        queue.remove(uid)
    if queue:
        other = queue.pop(0)
        pair(uid, other)
        return other
    queue.append(uid)
    save_state()
    return None

async def send_menu(ctx, chat_id):
    await ctx.bot.send_message(
        chat_id,
        "Anonymous Bot\n"
        "/anon_start – Find partner\n"
        "/anon_next – Next partner\n"
        "/anon_stop – Stop chat\n"
        "/status – Chat status"
    )

# ================= COMMANDS =================
async def start(update: Update, ctx):
    await send_menu(ctx, update.effective_user.id)

async def anon_start(update, ctx):
    uid = update.effective_user.id
    p = find_partner(uid)
    if p:
        await ctx.bot.send_message(uid, "🎯 Partner connected.")
        await ctx.bot.send_message(p, "🎯 Partner connected.")
    else:
        await ctx.bot.send_message(uid, "⌛ Searching...")
    await send_menu(ctx, uid)

async def anon_next(update, ctx):
    uid = update.effective_user.id
    old = unpair(uid)
    if old:
        await ctx.bot.send_message(old, "⚠ Partner left.")
    await anon_start(update, ctx)

async def anon_stop(update, ctx):
    uid = update.effective_user.id
    p = unpair(uid)
    if p:
        await ctx.bot.send_message(p, "⚠ Partner left.")
    if uid in queue:
        queue.remove(uid)
        save_state()
    await ctx.bot.send_message(uid, "❌ Chat stopped.")
    await send_menu(ctx, uid)

async def status(update, ctx):
    uid = update.effective_user.id
    if uid in sessions:
        await update.message.reply_text("✔ Connected")
    elif uid in queue:
        await update.message.reply_text("⌛ Waiting")
    else:
        await update.message.reply_text("❌ Not in chat")

# ================= MESSAGE HANDLER =================
async def relay(update, ctx):
    uid = update.effective_user.id
    msg = update.effective_message

    if msg.text and msg.text.startswith("/"):
        return

    if uid in sessions and not rate_limited(uid):
        partner = sessions.get(uid)
        if partner:
            await ctx.bot.copy_message(
                partner,
                msg.chat_id,
                msg.message_id,
                caption=msg.caption
            )

# ================= BOOT =================
load_state()

app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("anon_start", anon_start))
app.add_handler(CommandHandler("anon_next", anon_next))
app.add_handler(CommandHandler("anon_stop", anon_stop))
app.add_handler(CommandHandler("status", status))
app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, relay))

log.info("Bot started")
app.run_polling()
