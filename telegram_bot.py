"""Bot Telegram : gestion des commandes et des interactions utilisateur.
"""

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from config import SUSPECT_CHECK_INTERVAL_MINUTES, TELEGRAM_BOT_TOKEN
from football import FootballAPIError, format_match, get_today_matches
from odds import OddsAPIError, extract_outcome_prices, format_kickoff_djibouti, get_odds
from suspect import detect_suspicious_match


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.bot_data.setdefault("subscribers", set()).add(update.effective_chat.id)
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


def _match_label(event: dict) -> str:
    home = event.get("home_team") or "?"
    away = event.get("away_team") or "?"
    return f"{home} vs {away}"


def _format_suspicious_alert(event: dict, reasons: list[str]) -> str:
    competition = event.get("sport_title") or "?"
    commence_time = event.get("commence_time")
    kickoff = format_kickoff_djibouti(commence_time) if commence_time else "?"

    lines = [
        "🚨 Match suspect",
        f"🏆 {competition}",
        f"🕒 {kickoff} (heure de Djibouti)",
        f"⚽ {_match_label(event)}",
        "",
    ]
    lines.extend(f"• {reason}" for reason in reasons)
    return "\n".join(lines)


async def check_suspicious_matches(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tâche périodique : compare les cotes actuelles aux précédentes et
    alerte les abonnés (utilisateurs ayant fait /start) en cas de match suspect."""
    subscribers = context.bot_data.get("subscribers")
    if not subscribers:
        return

    try:
        events = get_odds()
    except OddsAPIError:
        return

    previous_snapshots = context.bot_data.setdefault("odds_snapshots", {})
    already_alerted = context.bot_data.setdefault("alerted_matches", set())

    for event in events:
        event_id = event.get("id")
        if not event_id:
            continue

        current_prices = extract_outcome_prices(event)
        previous_prices = previous_snapshots.get(event_id)
        reasons = detect_suspicious_match(previous_prices, current_prices)
        previous_snapshots[event_id] = current_prices

        if reasons and event_id not in already_alerted:
            already_alerted.add(event_id)
            text = _format_suspicious_alert(event, reasons)
            for chat_id in subscribers:
                await context.bot.send_message(chat_id=chat_id, text=text)


def build_application() -> Application:
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("scores", scores))

    if application.job_queue is not None:
        application.job_queue.run_repeating(
            check_suspicious_matches,
            interval=SUSPECT_CHECK_INTERVAL_MINUTES * 60,
            first=10,
        )

    return application
