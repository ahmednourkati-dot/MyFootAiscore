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


def get_odds(sport_key: str = _SPORT_KEY, markets: str = "h2h", region: str = "eu") -> list[dict]:
    """Récupère les cotes actuelles des matchs à venir pour un sport, par bookmaker."""
    if not ODDS_API_KEY:
        raise OddsAPIError("ODDS_API_KEY manquant dans les variables d'environnement (.env)")

    url = f"{ODDS_API_BASE_URL}/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": region,
        "markets": markets,
        "oddsFormat": "decimal",
    }
    try:
        response = requests.get(url, params=params, timeout=_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise OddsAPIError(f"Échec de l'appel à l'API de cotes : {exc}") from exc
    return response.json()


def get_scores(sport_key: str = _SPORT_KEY, days_from: int = 3) -> list[dict]:
    """Récupère les scores des matchs récents (dont les matchs terminés).

    Réutilise les mêmes identifiants de match ("id") que `get_odds()`,
    ce qui permet de faire correspondre un match dont on a suivi les
    cotes avec son résultat final, sans ambiguïté.
    """
    if not ODDS_API_KEY:
        raise OddsAPIError("ODDS_API_KEY manquant dans les variables d'environnement (.env)")

    url = f"{ODDS_API_BASE_URL}/sports/{sport_key}/scores"
    params = {"apiKey": ODDS_API_KEY, "daysFrom": days_from}
    try:
        response = requests.get(url, params=params, timeout=_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise OddsAPIError(f"Échec de l'appel à l'API de cotes : {exc}") from exc
    return response.json()


def get_active_tennis_sport_keys() -> list[str]:
    """Liste les tournois de tennis (ATP/WTA) actuellement actifs sur l'API.

    Exclut les marchés "outrights" (vainqueur du tournoi), qui ne
    correspondent pas à des matchs individuels.
    """
    if not ODDS_API_KEY:
        raise OddsAPIError("ODDS_API_KEY manquant dans les variables d'environnement (.env)")

    url = f"{ODDS_API_BASE_URL}/sports"
    params = {"apiKey": ODDS_API_KEY}
    try:
        response = requests.get(url, params=params, timeout=_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise OddsAPIError(f"Échec de l'appel à l'API de cotes : {exc}") from exc

    sports = response.json()
    return [
        sport["key"]
        for sport in sports
        if sport.get("group") == "Tennis" and not sport.get("has_outrights", False)
    ]


def extract_market_prices(
    event: dict, market_key: str, point: float | None = None
) -> dict[str, dict[str, float]]:
    """Transforme un événement en {bookmaker: {issue: cote}} pour un marché donné.

    Si `point` est précisé (ex. 1.5 pour un total de buts), ne garde que les
    lignes correspondant à ce point.
    """
    prices: dict[str, dict[str, float]] = {}
    for bookmaker in event.get("bookmakers", []):
        title = bookmaker.get("title") or bookmaker.get("key") or "?"
        for market in bookmaker.get("markets", []):
            if market.get("key") != market_key:
                continue
            outcomes = {}
            for outcome in market.get("outcomes", []):
                if "name" not in outcome or "price" not in outcome:
                    continue
                if point is not None and outcome.get("point") != point:
                    continue
                outcomes[outcome["name"]] = outcome["price"]
            if outcomes:
                prices[title] = outcomes
    return prices


def extract_outcome_prices(event: dict) -> dict[str, dict[str, float]]:
    """Transforme un événement de l'API en {bookmaker: {issue: cote}} (marché 1X2)."""
    return extract_market_prices(event, "h2h")


def format_kickoff_djibouti(commence_time: str) -> str:
    """Formate une heure de coup d'envoi (ISO 8601 UTC) en heure de Djibouti."""
    dt_utc = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
    dt_djibouti = dt_utc.astimezone(_DJIBOUTI_TZ)
    return dt_djibouti.strftime("%d/%m %H:%M")


def format_now_djibouti() -> str:
    """Formate l'heure actuelle en heure de Djibouti."""
    return datetime.now(_DJIBOUTI_TZ).strftime("%d/%m %H:%M")
