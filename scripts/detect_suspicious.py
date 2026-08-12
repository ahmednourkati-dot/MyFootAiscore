"""Vérifie les cotes (1X2, Over/Under 1.5 buts, corners, tennis) et alerte
en cas de variation suspecte.

Conçu pour être exécuté périodiquement par un workflow planifié (cron),
sans processus Telegram persistant. L'état est conservé dans STATE_PATH
entre deux exécutions, une entrée par (match, marché).

Note : les marchés "Over/Under 1.5 buts" (ligne alternative) et "corners"
dépendent de ce que l'abonnement The Odds API en cours donne accès — sur un
plan gratuit, ils peuvent renvoyer peu ou pas de données. Le script se
dégrade alors silencieusement (aucune alerte sur ces marchés, sans erreur).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import ALERT_CHAT_ID, TELEGRAM_BOT_TOKEN
from odds import (
    OddsAPIError,
    extract_market_prices,
    format_kickoff_djibouti,
    get_active_tennis_sport_keys,
    get_odds,
)
from suspect import detect_suspicious_match

STATE_PATH = Path(__file__).resolve().parent.parent / "state" / "suspect_state.json"

FOOTBALL_SPORT_KEY = "soccer"
FOOTBALL_MARKETS = "h2h,alternate_totals,alternate_totals_corners"
FOOTBALL_MARKETS_FALLBACK = "h2h,totals"
TENNIS_MARKETS = "h2h"
MAX_TENNIS_TOURNAMENTS = 10


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"snapshots": {}, "alerted": []}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def _match_label(event: dict) -> str:
    home = event.get("home_team") or "?"
    away = event.get("away_team") or "?"
    return f"{home} vs {away}"


MAX_REASONS_PER_ALERT = 6


def _format_alert(event: dict, market_label: str, reasons: list[str]) -> str:
    competition = event.get("sport_title") or "?"
    commence_time = event.get("commence_time")
    kickoff = format_kickoff_djibouti(commence_time) if commence_time else "?"

    lines = [
        "🚨 Match suspect",
        f"🏆 {competition}",
        f"🕒 {kickoff} (heure de Djibouti)",
        f"⚽ {_match_label(event)}",
        f"📊 Marché : {market_label}",
        "",
    ]
    shown = reasons[:MAX_REASONS_PER_ALERT]
    lines.extend(f"• {reason}" for reason in shown)
    remaining = len(reasons) - len(shown)
    if remaining > 0:
        lines.append(f"… et {remaining} autre(s) signal(aux)")
    return "\n".join(lines)


def _send_alert(text: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(url, json={"chat_id": ALERT_CHAT_ID, "text": text}, timeout=10)
    response.raise_for_status()


def _process_market(
    event: dict,
    market_key: str,
    market_label: str,
    state_key_suffix: str,
    snapshots: dict,
    alerted: set,
    current_state_keys: set,
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
    reasons = detect_suspicious_match(previous_prices, current_prices)
    snapshots[state_key] = current_prices

    if reasons and state_key not in alerted:
        alerted.add(state_key)
        _send_alert(_format_alert(event, market_label, reasons))
        print(f"Alerte envoyée pour {_match_label(event)} ({market_label})")


def _check_football(snapshots: dict, alerted: set, current_state_keys: set) -> None:
    try:
        events = get_odds(FOOTBALL_SPORT_KEY, markets=FOOTBALL_MARKETS)
    except OddsAPIError as exc:
        print(f"Marchés étendus indisponibles ({exc}), repli sur h2h+totals")
        try:
            events = get_odds(FOOTBALL_SPORT_KEY, markets=FOOTBALL_MARKETS_FALLBACK)
        except OddsAPIError as exc2:
            print(f"Erreur API cotes (football) : {exc2}")
            return

    print(f"Football : {len(events)} matchs récupérés")

    for event in events:
        _process_market(event, "h2h", "Cotes 1X2", "h2h", snapshots, alerted, current_state_keys)
        _process_market(
            event, "totals", "Over/Under 1.5 buts", "totals_1.5",
            snapshots, alerted, current_state_keys, point=1.5,
        )
        _process_market(
            event, "alternate_totals", "Over/Under 1.5 buts", "totals_1.5",
            snapshots, alerted, current_state_keys, point=1.5,
        )
        _process_market(
            event, "alternate_totals_corners", "Corners", "corners",
            snapshots, alerted, current_state_keys,
        )


def _check_tennis(snapshots: dict, alerted: set, current_state_keys: set) -> None:
    try:
        tournaments = get_active_tennis_sport_keys()
    except OddsAPIError as exc:
        print(f"Erreur API cotes (liste tennis) : {exc}")
        return

    print(f"Tennis : {len(tournaments)} tournois actifs trouvés : {tournaments}")

    for sport_key in tournaments[:MAX_TENNIS_TOURNAMENTS]:
        try:
            events = get_odds(sport_key, markets=TENNIS_MARKETS)
        except OddsAPIError as exc:
            print(f"Erreur API cotes (tennis {sport_key}) : {exc}")
            continue

        print(f"  {sport_key} : {len(events)} matchs récupérés")

        for event in events:
            _process_market(
                event, "h2h", "Cotes tennis", "h2h", snapshots, alerted, current_state_keys
            )


def main() -> None:
    if not ALERT_CHAT_ID:
        raise RuntimeError("ALERT_CHAT_ID manquant dans les variables d'environnement")

    state = _load_state()
    snapshots = state.setdefault("snapshots", {})
    alerted = set(state.setdefault("alerted", []))
    current_state_keys: set = set()

    _check_football(snapshots, alerted, current_state_keys)
    _check_tennis(snapshots, alerted, current_state_keys)

    # Purge l'état des matchs qui ne sont plus dans le calendrier de l'API.
    snapshots = {key: prices for key, prices in snapshots.items() if key in current_state_keys}
    alerted &= current_state_keys

    state["snapshots"] = snapshots
    state["alerted"] = sorted(alerted)
    _save_state(state)


if __name__ == "__main__":
    main()
