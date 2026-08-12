"""Vérifie les cotes et alerte en cas de match suspect.

Conçu pour être exécuté périodiquement par un workflow planifié (cron),
sans processus Telegram persistant. L'état (dernier relevé de cotes,
matchs déjà signalés) est conservé dans STATE_PATH entre deux exécutions.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import ALERT_CHAT_ID, TELEGRAM_BOT_TOKEN
from odds import OddsAPIError, extract_outcome_prices, format_kickoff_djibouti, get_odds
from suspect import detect_suspicious_match

STATE_PATH = Path(__file__).resolve().parent.parent / "state" / "suspect_state.json"


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


def _format_alert(event: dict, reasons: list[str]) -> str:
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


def _send_alert(text: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(url, json={"chat_id": ALERT_CHAT_ID, "text": text}, timeout=10)
    response.raise_for_status()


def main() -> None:
    if not ALERT_CHAT_ID:
        raise RuntimeError("ALERT_CHAT_ID manquant dans les variables d'environnement")

    state = _load_state()
    snapshots = state.setdefault("snapshots", {})
    alerted = set(state.setdefault("alerted", []))

    try:
        events = get_odds()
    except OddsAPIError as exc:
        print(f"Erreur API cotes : {exc}")
        return

    current_event_ids = set()

    for event in events:
        event_id = event.get("id")
        if not event_id:
            continue
        current_event_ids.add(event_id)

        current_prices = extract_outcome_prices(event)
        previous_prices = snapshots.get(event_id)
        reasons = detect_suspicious_match(previous_prices, current_prices)
        snapshots[event_id] = current_prices

        if reasons and event_id not in alerted:
            alerted.add(event_id)
            _send_alert(_format_alert(event, reasons))
            print(f"Alerte envoyée pour {_match_label(event)}")

    # Purge l'état des matchs qui ne sont plus dans le calendrier de l'API.
    snapshots = {eid: prices for eid, prices in snapshots.items() if eid in current_event_ids}
    alerted &= current_event_ids

    state["snapshots"] = snapshots
    state["alerted"] = sorted(alerted)
    _save_state(state)


if __name__ == "__main__":
    main()
