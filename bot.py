import os
import sqlite3
import logging
from datetime import datetime

from groq import Groq
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
CHAT_ID = int(os.environ.get("CHAT_ID", "0"))

groq_client = Groq(api_key=GROQ_API_KEY)
DB_PATH = "cupidon.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER,
            texte TEXT NOT NULL,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS reponses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER,
            reponse TEXT NOT NULL,
            auteur TEXT NOT NULL,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (question_id) REFERENCES questions(id)
        )
    """)
    conn.commit()
    conn.close()
    logger.info("Base de données initialisée")


def groq_repondre(prompt: str, system: str = "Tu es Cupidon, un assistant romantique.") -> str:
    reponse = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        max_tokens=200,
        temperature=0.9,
    )
    return reponse.choices[0].message.content.strip()


async def envoyer_question(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    question = groq_repondre(
        "Génère UNE question courte, originale et romantique pour un couple amoureux. "
        "Pas de clichés. Réponds UNIQUEMENT avec la question, sans introduction."
    )
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"💌 *Question du jour :*\n\n{question}",
        parse_mode="Markdown",
    )

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO questions (message_id, texte) VALUES (?, ?)",
        (msg.message_id, question),
    )
    conn.commit()
    conn.close()
    logger.info(f"Question envoyée (message_id={msg.message_id})")


async def question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if CHAT_ID and chat_id != CHAT_ID:
        return
    await envoyer_question(context, chat_id)


async def souvenirs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if CHAT_ID and chat_id != CHAT_ID:
        return

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT q.texte, r.reponse, r.auteur, r.date "
        "FROM reponses r JOIN questions q ON r.question_id = q.id "
        "ORDER BY r.date DESC LIMIT 20"
    ).fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text(
            "Aucun souvenir pour l'instant. Commencez avec /question !"
        )
        return

    lignes = ["💝 *Souvenirs :*"]
    for q, r, a, d in rows:
        lignes.append(f"\n📅 {d[:10]}")
        lignes.append(f"💬 _{q}_")
        lignes.append(f"👤 {a} → {r}")

    await update.message.reply_text("\n".join(lignes), parse_mode="Markdown")


async def souvenir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if CHAT_ID and chat_id != CHAT_ID:
        return

    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT q.texte, r.reponse, r.auteur, r.date "
        "FROM reponses r JOIN questions q ON r.question_id = q.id "
        "ORDER BY RANDOM() LIMIT 1"
    ).fetchone()
    conn.close()

    if not row:
        await update.message.reply_text("Aucun souvenir pour l'instant.")
        return

    q, r, a, d = row
    await update.message.reply_text(
        f"💝 *Souvenir du {d[:10]} :*\n\n"
        f"*Question :* {q}\n"
        f"*{a} :* {r}",
        parse_mode="Markdown",
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if CHAT_ID and chat_id != CHAT_ID:
        return

    conn = sqlite3.connect(DB_PATH)
    total_q = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    total_r = conn.execute("SELECT COUNT(*) FROM reponses").fetchone()[0]
    rows = conn.execute(
        "SELECT auteur, COUNT(*) FROM reponses GROUP BY auteur ORDER BY COUNT(*) DESC"
    ).fetchall()
    conn.close()

    lignes = ["📊 *Statistiques Cupidon*\n"]
    lignes.append(f"Questions posées : {total_q}")
    lignes.append(f"Réponses reçues : {total_r}")
    if total_q > 0:
        lignes.append(f"Taux de réponse : {total_r / total_q * 100:.0f}% ❤️")
    for auteur, count in rows:
        lignes.append(f"👤 {auteur} : {count} réponses")

    await update.message.reply_text("\n".join(lignes), parse_mode="Markdown")


async def repondre(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    chat_id = msg.chat_id
    if CHAT_ID and chat_id != CHAT_ID:
        return
    if not msg.reply_to_message or not msg.reply_to_message.from_user.is_bot:
        return

    replied_id = msg.reply_to_message.message_id

    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT id, texte FROM questions WHERE message_id = ?", (replied_id,)
    ).fetchone()
    if not row:
        conn.close()
        return

    q_id, question_texte = row
    conn.execute(
        "INSERT INTO reponses (question_id, reponse, auteur) VALUES (?, ?, ?)",
        (q_id, msg.text, msg.from_user.first_name),
    )
    conn.commit()
    conn.close()
    logger.info(f"Réponse sauvegardée pour la question #{q_id}")

    reaction = groq_repondre(
        f"Ma copine vient de répondre à ma question '{question_texte}' "
        f"par : '{msg.text}'. Réponds de façon adorable en 1-2 phrases, "
        f"en français, avec des emojis. Montre que tu es touché.",
        system="Tu es mon assistant romantique personnel.",
    )

    await msg.reply_text(f"🥰 {reaction}\n\n💾 Sauvegardé dans nos souvenirs !")


async def envoyer_question_auto(context: ContextTypes.DEFAULT_TYPE) -> None:
    if CHAT_ID:
        await envoyer_question(context, CHAT_ID)
    else:
        logger.warning("CHAT_ID non défini, impossible d'envoyer la question auto")


def main() -> None:
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        envoyer_question_auto,
        "cron",
        hour=10,
        minute=0,
        args=[app],
        id="question_quotidienne",
    )
    scheduler.start()

    app.add_handler(CommandHandler("question", question))
    app.add_handler(CommandHandler("souvenirs", souvenirs))
    app.add_handler(CommandHandler("souvenir", souvenir))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, repondre))

    logger.info("Bot Cupidon démarré !")
    app.run_polling()


if __name__ == "__main__":
    main()
