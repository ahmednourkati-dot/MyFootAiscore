"""Bot Telegram : gestion des commandes et des interactions utilisateur.
"""

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from config import TELEGRAM_BOT_TOKEN


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🤖 MyFootAiscore Bot actif")


def build_application() -> Application:
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    return application
