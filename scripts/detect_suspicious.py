"""Vérifie les cotes 1X2 du football et alerte en cas de variation suspecte.

Conçu pour être exécuté périodiquement par un workflow planifié (cron),
sans processus Telegram persistant. L'état est conservé dans STATE_PATH
entre deux exécutions, une entrée par match.

Portée volontairement réduite à un seul scénario (football, marché h2h,
un seul appel API par passage) pour tenir dans le quota gratuit de
l'API de cotes (500 requêtes/mois) à un intervalle de 2h. Le tennis et
les marchés Over/Under 1.5 / corners ont été retirés : ils multiplient
le nombre d'appels et ne rentraient plus dans ce budget à 2h.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import ALERT_CHAT_ID, TELEGRAM_BOT_TOKEN
from odds import OddsAPIError, extract_market_prices, format_kickoff_djibouti, get_odds
from suspect import MatchAnalysis, analyze_match

STATE_PATH = Path(__file__).resolve().parent.parent / "state" / "suspect_state.json"

FOOTBALL_SPORT_KEY = "soccer"
FOOTBALL_MARKETS = "h2h"


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"snapshots": {}, "alerted": [], "pending_results": [], "results_history": []}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def _match_label(event: dict) -> str:
    home = event.get("home_team") or "?"
    away = event.get("away_team") or "?"
    return f"{home} vs {away}"


MAX_REASONS_PER_ALERT = 6


def _format_alert(event: dict, market_label: str, analysis: MatchAnalysis) -> str:
    competition = event.get("sport_title") or "?"
    commence_time = event.get("commence_time")
    kickoff = format_kickoff_djibouti(commence_time) if commence_time else "?"
    reasons = analysis.reasons

    lines = [
        "🚨 Match suspect",
        f"🏆 {competition}",
        f"🕒 {kickoff} (heure de Djibouti)",
        f"⚽ {_match_label(event)}",
        f"📊 Marché : {market_label}",
        f"🏷️ Nature : Anomalie de marché (pas une value bet calculée — aucune probabilité réelle estimée)",
        f"🎯 Confiance du signal : {analysis.confidence}%",
        f"💰 Mise suggérée : {analysis.stake_pct:.0f}% du capital",
        "",
    ]
    shown = reasons[:MAX_REASONS_PER_ALERT]
    lines.extend(f"• {reason}" for reason in shown)
    remaining = len(reasons) - len(shown)
    if remaining > 0:
        lines.append(f"… et {remaining} autre(s) signal(aux)")
    lines.append("")
    lines.append(
        "⚠️ Confiance = force du signal statistique, pas une probabilité de gain validée. "
        "Ne mise jamais plus que tu ne peux perdre."
    )
    return "\n".join(lines)


def _send_alert(text: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(url, json={"chat_id": ALERT_CHAT_ID, "text": text}, timeout=10)
    response.raise_for_status()


def _record_pending(
    pending_results: list, event: dict, market_label: str, state_key: str, analysis: MatchAnalysis
) -> None:
    """Enregistre une alerte envoyée pour vérifier plus tard si son issue s'est réalisée."""
    if not analysis.selection or analysis.odds_at_alert is None:
        return

    pending_results.append(
        {
            "state_key": state_key,
            "event_id": event.get("id"),
            "sport_key": FOOTBALL_SPORT_KEY,
            "competition": event.get("sport_title") or "?",
            "home_team": event.get("home_team"),
            "away_team": event.get("away_team"),
            "commence_time": event.get("commence_time"),
            "market_label": market_label,
            "selection": analysis.selection,
            "odds_at_alert": analysis.odds_at_alert,
            "stake_pct": analysis.stake_pct,
            "confidence": analysis.confidence,
            "alerted_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def _process_market(
    event: dict,
    market_key: str,
    market_label: str,
    state_key_suffix: str,
    snapshots: dict,
    alerted: set,
    current_state_keys: set,
    pending_results: list,
    point: float | None = None,
) -> None:
    event_id = event.get("id")
    if not event_id:
        return

    state_key = f"{event_id}:{state_key_suffix}"

    current_prices = extract_market_prices(event, market_key, point=point)
    if not current_prices:
        return

    current_state_keys.add(state_key)
    previous_prices = snapshots.get(state_key)
    analysis = analyze_match(previous_prices, current_prices)
    snapshots[state_key] = current_prices

    if analysis.signals and state_key not in alerted:
        alerted.add(state_key)
        _send_alert(_format_alert(event, market_label, analysis))
        _record_pending(pending_results, event, market_label, state_key, analysis)
        print(
            f"Alerte envoyée pour {_match_label(event)} ({market_label}) "
            f"- confiance {analysis.confidence}%, mise {analysis.stake_pct:.0f}%"
        )


def _check_football(
    snapshots: dict, alerted: set, current_state_keys: set, pending_results: list
) -> None:
    try:
        events = get_odds(FOOTBALL_SPORT_KEY, markets=FOOTBALL_MARKETS)
    except OddsAPIError as exc:
        print(f"Erreur API cotes (football) : {exc}")
        return

    print(f"Football : {len(events)} matchs récupérés")

    for event in events:
        _process_market(
            event, "h2h", "Cotes 1X2", "h2h", snapshots, alerted, current_state_keys, pending_results
        )


def main() -> None:
    if not ALERT_CHAT_ID:
        raise RuntimeError("ALERT_CHAT_ID manquant dans les variables d'environnement")

    state = _load_state()
    snapshots = state.setdefault("snapshots", {})
    alerted = set(state.setdefault("alerted", []))
    pending_results = state.setdefault("pending_results", [])
    state.setdefault("results_history", [])
    current_state_keys: set = set()

    _check_football(snapshots, alerted, current_state_keys, pending_results)

    # Purge l'état des matchs qui ne sont plus dans le calendrier de l'API.
    snapshots = {key: prices for key, prices in snapshots.items() if key in current_state_keys}
    alerted &= current_state_keys

    state["snapshots"] = snapshots
    state["alerted"] = sorted(alerted)
    _save_state(state)


if __name__ == "__main__":
    main()
