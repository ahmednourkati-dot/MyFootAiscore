"""Client pour l'API de cotes sportives (The Odds API).

Documentation : https://the-odds-api.com/liveapi/guides/v4/
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from config import ODDS_API_BASE_URL, ODDS_API_KEY

_TIMEOUT = 10
_SPORT_KEY = "soccer"
_DJIBOUTI_TZ = ZoneInfo("Africa/Djibouti")


class OddsAPIError(Exception):
    """Erreur lors d'un appel à l'API de cotes."""


def get_odds(sport_key: str = _SPORT_KEY) -> list[dict]:
    """Récupère les cotes 1X2 (h2h) actuelles des matchs à venir, par bookmaker."""
    if not ODDS_API_KEY:
        raise OddsAPIError("ODDS_API_KEY manquant dans les variables d'environnement (.env)")

    url = f"{ODDS_API_BASE_URL}/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu",
        "markets": "h2h",
        "oddsFormat": "decimal",
    }
    try:
        response = requests.get(url, params=params, timeout=_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise OddsAPIError(f"Échec de l'appel à l'API de cotes : {exc}") from exc
    return response.json()


def extract_outcome_prices(event: dict) -> dict[str, dict[str, float]]:
    """Transforme un événement de l'API en {bookmaker: {issue: cote}}."""
    prices: dict[str, dict[str, float]] = {}
    for bookmaker in event.get("bookmakers", []):
        title = bookmaker.get("title") or bookmaker.get("key") or "?"
        for market in bookmaker.get("markets", []):
            if market.get("key") != "h2h":
                continue
            outcomes = {
                outcome["name"]: outcome["price"]
                for outcome in market.get("outcomes", [])
                if "name" in outcome and "price" in outcome
            }
            if outcomes:
                prices[title] = outcomes
    return prices


def format_kickoff_djibouti(commence_time: str) -> str:
    """Formate une heure de coup d'envoi (ISO 8601 UTC) en heure de Djibouti."""
    dt_utc = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
    dt_djibouti = dt_utc.astimezone(_DJIBOUTI_TZ)
    return dt_djibouti.strftime("%d/%m %H:%M")
