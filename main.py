"""Point d'entrée de l'application : démarre le bot Telegram.
"""

from telegram_bot import build_application


def main() -> None:
    application = build_application()
    application.run_polling()


if __name__ == "__main__":
    main()
