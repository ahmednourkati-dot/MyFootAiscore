"""Bot Telegram : gestion des commandes et des interactions utilisateur.
"""

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from config import TELEGRAM_BOT_TOKEN
from football import FootballAPIError, format_match, get_today_matches


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🤖 MyFootAiscore Bot actif")


async def scores(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        matches = get_today_matches()
    except FootballAPIError as exc:
        await update.message.reply_text(f"⚠️ {exc}")
        return

    if not matches:
        await update.message.reply_text("Aucun match aujourd'hui.")
        return

    text = "\n".join(format_match(match) for match in matches)
    await update.message.reply_text(text)


def build_application() -> Application:
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("scores", scores))
    return application
