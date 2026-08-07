"""Logique d'analyse football : récupération et traitement des données.

Client pour l'API football-data.org (https://www.football-data.org/documentation/api).
"""

from __future__ import annotations

from datetime import date

import requests

from config import FOOTBALL_API_BASE_URL, FOOTBALL_API_KEY

_TIMEOUT = 10


class FootballAPIError(Exception):
    """Erreur lors d'un appel à l'API football."""


def _headers() -> dict:
    if not FOOTBALL_API_KEY:
        raise FootballAPIError("FOOTBALL_API_KEY manquant dans les variables d'environnement (.env)")
    return {"X-Auth-Token": FOOTBALL_API_KEY}


def get_matches(date_from: str, date_to: str | None = None) -> list[dict]:
    """Récupère les matchs programmés entre deux dates (format YYYY-MM-DD)."""
    url = f"{FOOTBALL_API_BASE_URL}/matches"
    params = {"dateFrom": date_from, "dateTo": date_to or date_from}
    try:
        response = requests.get(url, headers=_headers(), params=params, timeout=_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise FootballAPIError(f"Échec de l'appel à l'API football : {exc}") from exc
    return response.json().get("matches", [])


def get_today_matches() -> list[dict]:
    """Récupère les matchs du jour."""
    today = date.today().isoformat()
    return get_matches(today)


def format_match(match: dict) -> str:
    """Formate un match pour l'affichage Telegram."""
    home = match.get("homeTeam", {}).get("name") or "?"
    away = match.get("awayTeam", {}).get("name") or "?"
    competition = match.get("competition", {}).get("name") or ""
    status = match.get("status") or ""
    full_time = match.get("score", {}).get("fullTime", {})
    home_score = full_time.get("home")
    away_score = full_time.get("away")

    if home_score is not None and away_score is not None:
        result = f"{home} {home_score} - {away_score} {away}"
    else:
        result = f"{home} vs {away}"

    return f"⚽ {competition} : {result} ({status})"
