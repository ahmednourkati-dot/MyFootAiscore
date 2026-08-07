"""Logique d'analyse football : récupération et traitement des données.

Client pour l'API football-data.org (https://www.football-data.org/documentation/api).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date

import requests

from config import FOOTBALL_API_BASE_URL, FOOTBALL_API_KEY

_TIMEOUT = 10

# Paramètres de l'analyse +1,5 buts.
TEAM_MATCHES_LIMIT = 10  # nombre de derniers matchs terminés analysés par équipe
FORM_MATCHES_LIMIT = 5  # nombre de matchs pris en compte pour la forme récente
MATCHES_TO_ANALYZE_LIMIT = 15  # nombre max de matchs du jour analysés (quota API gratuit)
TOP_N = 5  # nombre de matchs affichés par /analyse
_TEAM_REQUEST_DELAY = 1.0  # secondes entre deux appels /teams/{id}/matches (quota API gratuit)


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


# --- Analyse +1,5 buts -------------------------------------------------


@dataclass
class TeamStats:
    """Statistiques d'une équipe sur ses derniers matchs terminés."""

    team_id: int
    team_name: str
    matches_analyzed: int
    over_1_5_pct: float | None
    avg_scored: float | None
    avg_conceded: float | None
    form: str  # ex: "V-V-N-D-V", du plus récent au plus ancien
    form_pct: float | None
    error: str | None = None


@dataclass
class MatchAnalysis:
    """Résultat de l'analyse +1,5 buts pour un match."""

    match: dict
    home_stats: TeamStats
    away_stats: TeamStats
    score: float | None  # score +1,5 sur 100, None si données insuffisantes


def get_team_recent_matches(team_id: int, limit: int = TEAM_MATCHES_LIMIT) -> list[dict]:
    """Récupère les derniers matchs terminés d'une équipe, du plus récent au plus ancien."""
    url = f"{FOOTBALL_API_BASE_URL}/teams/{team_id}/matches"
    params = {"status": "FINISHED", "limit": limit}
    try:
        response = requests.get(url, headers=_headers(), params=params, timeout=_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise FootballAPIError(f"Échec de l'appel à l'API football (équipe {team_id}) : {exc}") from exc
    matches = response.json().get("matches", [])
    matches.sort(key=lambda m: m.get("utcDate") or "", reverse=True)
    return matches[:limit]


def _team_goals(match: dict, team_id: int) -> tuple[int, int] | None:
    """Retourne (buts marqués, buts encaissés) par `team_id` dans `match`, ou None si indisponible."""
    home = match.get("homeTeam") or {}
    away = match.get("awayTeam") or {}
    full_time = (match.get("score") or {}).get("fullTime") or {}
    home_score = full_time.get("home")
    away_score = full_time.get("away")
    if home_score is None or away_score is None:
        return None
    if home.get("id") == team_id:
        return home_score, away_score
    if away.get("id") == team_id:
        return away_score, home_score
    return None


def _result_letter(scored: int, conceded: int) -> str:
    if scored > conceded:
        return "V"
    if scored == conceded:
        return "N"
    return "D"


def _result_points(scored: int, conceded: int) -> int:
    if scored > conceded:
        return 3
    if scored == conceded:
        return 1
    return 0


def analyze_team(team_id: int, team_name: str, limit: int = TEAM_MATCHES_LIMIT) -> TeamStats:
    """Calcule le % de matchs +1,5 buts, la moyenne de buts et la forme récente d'une équipe."""
    try:
        matches = get_team_recent_matches(team_id, limit=limit)
    except FootballAPIError as exc:
        return TeamStats(team_id, team_name, 0, None, None, None, "", None, error=str(exc))

    goals_pairs = [g for g in (_team_goals(m, team_id) for m in matches) if g is not None]
    n = len(goals_pairs)
    if n == 0:
        return TeamStats(
            team_id, team_name, 0, None, None, None, "", None,
            error="aucun match terminé récent disponible via l'API",
        )

    over_1_5_count = sum(1 for scored, conceded in goals_pairs if scored + conceded >= 2)
    over_1_5_pct = over_1_5_count / n * 100
    avg_scored = sum(scored for scored, _ in goals_pairs) / n
    avg_conceded = sum(conceded for _, conceded in goals_pairs) / n

    form_pairs = goals_pairs[:FORM_MATCHES_LIMIT]
    form = "-".join(_result_letter(scored, conceded) for scored, conceded in form_pairs)
    form_pct = sum(_result_points(scored, conceded) for scored, conceded in form_pairs) / (3 * len(form_pairs)) * 100

    return TeamStats(team_id, team_name, n, over_1_5_pct, avg_scored, avg_conceded, form, form_pct)


def compute_over_1_5_score(home: TeamStats, away: TeamStats) -> float | None:
    """Combine les stats des deux équipes en un score +1,5 buts sur 100.

    Pondération : 50% taux historique de matchs +1,5 buts, 30% estimation du
    nombre de buts attendus (attaque vs défense adverse), 20% forme récente
    (offensive) des deux équipes.
    """
    if home.matches_analyzed == 0 or away.matches_analyzed == 0:
        return None

    component_over_1_5 = (home.over_1_5_pct + away.over_1_5_pct) / 2

    expected_total_goals = (
        (home.avg_scored + away.avg_conceded) + (away.avg_scored + home.avg_conceded)
    ) / 2
    component_goals = min(expected_total_goals / 4.0, 1.0) * 100

    component_form = (home.form_pct + away.form_pct) / 2

    score = 0.5 * component_over_1_5 + 0.3 * component_goals + 0.2 * component_form
    return round(score, 1)


def analyze_today_matches(
    matches_limit: int = MATCHES_TO_ANALYZE_LIMIT,
    team_matches_limit: int = TEAM_MATCHES_LIMIT,
) -> list[MatchAnalysis]:
    """Analyse les matchs du jour : stats +1,5 buts des deux équipes et score combiné."""
    today_matches = get_today_matches()[:matches_limit]
    cache: dict[int, TeamStats] = {}
    analyses: list[MatchAnalysis] = []

    for match in today_matches:
        home = match.get("homeTeam") or {}
        away = match.get("awayTeam") or {}
        home_id = home.get("id")
        away_id = away.get("id")
        if home_id is None or away_id is None:
            continue  # identifiants d'équipe indisponibles : pas d'analyse possible

        if home_id not in cache:
            cache[home_id] = analyze_team(home_id, home.get("name") or "?", limit=team_matches_limit)
            time.sleep(_TEAM_REQUEST_DELAY)
        if away_id not in cache:
            cache[away_id] = analyze_team(away_id, away.get("name") or "?", limit=team_matches_limit)
            time.sleep(_TEAM_REQUEST_DELAY)

        home_stats = cache[home_id]
        away_stats = cache[away_id]
        score = compute_over_1_5_score(home_stats, away_stats)
        analyses.append(MatchAnalysis(match=match, home_stats=home_stats, away_stats=away_stats, score=score))

    return analyses


def _format_team_stats(stats: TeamStats) -> str:
    if stats.matches_analyzed == 0:
        reason = stats.error or "données indisponibles"
        return f"  • {stats.team_name} : données indisponibles ({reason})"
    return (
        f"  • {stats.team_name} : +1,5 buts {stats.over_1_5_pct:.0f}% sur {stats.matches_analyzed} matchs"
        f" | moy. marqués {stats.avg_scored:.2f} / encaissés {stats.avg_conceded:.2f}"
        f" | forme {stats.form}"
    )


def format_match_analysis(analysis: MatchAnalysis) -> str:
    """Formate le résultat de l'analyse +1,5 buts d'un match pour l'affichage Telegram."""
    home = analysis.home_stats
    away = analysis.away_stats
    competition = analysis.match.get("competition", {}).get("name") or ""
    score_text = f"{analysis.score}/100" if analysis.score is not None else "N/A"
    lines = [f"⚽ {competition} : {home.team_name} vs {away.team_name} — Score +1,5 buts : {score_text}"]
    lines.append(_format_team_stats(home))
    lines.append(_format_team_stats(away))
    return "\n".join(lines)
