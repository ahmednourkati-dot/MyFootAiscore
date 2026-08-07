"""Bot Telegram : gestion des commandes et des interactions utilisateur.
"""

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from config import TELEGRAM_BOT_TOKEN
from football import (
    FootballAPIError,
    TOP_N,
    analyze_today_matches,
    format_match,
    format_match_analysis,
    get_today_matches,
)


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


async def analyse(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🔎 Analyse +1,5 buts en cours (10 derniers matchs de chaque équipe)…"
    )
    try:
        analyses = analyze_today_matches()
    except FootballAPIError as exc:
        await update.message.reply_text(f"⚠️ {exc}")
        return

    if not analyses:
        await update.message.reply_text(
            "Aucun match aujourd'hui, ou identifiants d'équipe indisponibles via l'API."
        )
        return

    ranked = sorted((a for a in analyses if a.score is not None), key=lambda a: a.score, reverse=True)
    unavailable = len(analyses) - len(ranked)
    top = ranked[:TOP_N]

    if not top:
        await update.message.reply_text(
            "Données insuffisantes (historique des 10 derniers matchs indisponible via l'API) "
            "pour calculer un score +1,5 sur les matchs du jour."
        )
        return

    header = f"📊 Top {len(top)} matchs +1,5 buts aujourd'hui :"
    blocks = [format_match_analysis(a) for a in top]
    if unavailable:
        blocks.append(f"ℹ️ {unavailable} match(s) non analysés (historique indisponible via l'API).")

    await update.message.reply_text(header + "\n\n" + "\n\n".join(blocks))


def build_application() -> Application:
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("scores", scores))
    application.add_handler(CommandHandler("analyse", analyse))
    return application
