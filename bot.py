import feedparser
import sqlite3
import re
import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

# ================= CONFIG =================
import os

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))

CHANNELS = {
    "economy": "@economyosint",
    "gaming": "@gamingosint",
    "tech": "@techosint",
    "war": "@warmonitorosint"
}

RSS_FEEDS = {
    "economy": [
        "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        "https://www.ft.com/?format=rss",
    ],
    "gaming": [
        "https://www.gamespot.com/feeds/mashup/",
        "https://www.ign.com/rss/articles",
    ],
    "tech": [
        "https://techcrunch.com/feed/",
        "https://www.theverge.com/rss/index.xml",
    ],
    "war": [
        "https://www.reuters.com/world/rss",
        "https://www.aljazeera.com/xml/rss/all.xml",
    ]
}

FETCH_INTERVAL = 300

# ================= DB =================
conn = sqlite3.connect("news.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""CREATE TABLE IF NOT EXISTS seen (link TEXT PRIMARY KEY)""")
cursor.execute("""CREATE TABLE IF NOT EXISTS pending (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT,
    title TEXT,
    summary TEXT,
    link TEXT
)""")
conn.commit()

# ================= UTIL =================
def clean_text(text):
    if not text:
        return ""
    text = re.sub(r"<.*?>", "", text)
    return re.sub(r"\s+", " ", text).strip()

def clean_title(title):
    if not title:
        return "No title"
    for sep in [" - ", " | "]:
        if sep in title:
            title = title.split(sep)[0]
    return title.strip()

def already_seen(link):
    cursor.execute("SELECT 1 FROM seen WHERE link=?", (link,))
    return cursor.fetchone() is not None

def mark_seen(link):
    cursor.execute("INSERT OR IGNORE INTO seen VALUES (?)", (link,))
    conn.commit()

def save_pending(topic, title, summary, link):
    cursor.execute(
        "INSERT INTO pending (topic, title, summary, link) VALUES (?, ?, ?, ?)",
        (topic, title, summary, link)
    )
    conn.commit()
    return cursor.lastrowid

def get_pending(item_id):
    cursor.execute("SELECT * FROM pending WHERE id=?", (item_id,))
    return cursor.fetchone()

def delete_pending(item_id):
    cursor.execute("DELETE FROM pending WHERE id=?", (item_id,))
    conn.commit()

# ================= RSS JOB =================
async def fetch_news(context: ContextTypes.DEFAULT_TYPE):
    print("Fetching news...")

    app = context.application

    for topic, feeds in RSS_FEEDS.items():
        for url in feeds:
            feed = feedparser.parse(url)

            for entry in feed.entries[:5]:
                link = entry.get("link")
                if not link or already_seen(link):
                    continue

                title = clean_title(entry.get("title", "No title"))
                summary = clean_text(entry.get("summary", "")) or title

                mark_seen(link)
                item_id = save_pending(topic, title, summary, link)

                await send_to_admin(app, item_id, topic, title, summary, link)

                await asyncio.sleep(1)

# ================= ADMIN MESSAGE =================
async def send_to_admin(app, item_id, topic, title, summary, link):
    keyboard = [
        [
            InlineKeyboardButton("🟢 Approve", callback_data=f"approve:{item_id}"),
            InlineKeyboardButton("🔴 Reject", callback_data=f"reject:{item_id}")
        ]
    ]

    msg = f"""
🧠 NEW ARTICLE

📌 Topic: {topic}
📰 {title}

{summary[:400]}

🔗 {link}
"""

    await app.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=msg,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================= BUTTON HANDLER =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, item_id = query.data.split(":")
    item_id = int(item_id)

    item = get_pending(item_id)

    if not item:
        await query.edit_message_text("❌ Already processed.")
        return

    _, topic, title, summary, link = item

    if action == "approve":
        post = f"""
📰 {clean_title(title)}

{summary}

🔗 Source
{link}
"""

        await context.bot.send_message(
            chat_id=CHANNELS[topic],
            text=post
        )

        delete_pending(item_id)
        await query.edit_message_text("✅ Posted.")

    elif action == "reject":
        delete_pending(item_id)
        await query.edit_message_text("❌ Rejected.")

# ================= MAIN =================
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CallbackQueryHandler(button_handler))

    # ✅ clean background job (NO THREADS)
    app.job_queue.run_repeating(fetch_news, interval=FETCH_INTERVAL, first=5)

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
