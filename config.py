"""Configuration du bot Telegram d'analyse football.

Charge les paramètres depuis les variables d'environnement (.env).
"""

import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")
FOOTBALL_API_BASE_URL = os.getenv("FOOTBALL_API_BASE_URL", "https://api.football-data.org/v4")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
ODDS_API_BASE_URL = os.getenv("ODDS_API_BASE_URL", "https://api.the-odds-api.com/v4")
SUSPECT_CHECK_INTERVAL_MINUTES = int(os.getenv("SUSPECT_CHECK_INTERVAL_MINUTES", "15"))
ALERT_CHAT_ID = os.getenv("ALERT_CHAT_ID")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN manquant dans les variables d'environnement (.env)")
