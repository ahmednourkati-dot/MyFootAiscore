"""Envoie un récapitulatif hebdomadaire des paris réglés (gagnés/perdus).

Conçu pour être exécuté une fois par semaine (dimanche soir, heure de
Djibouti). Ne consomme aucun crédit de l'API de cotes : il ne lit que
l'historique déjà réglé par settle_results.py.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import ALERT_CHAT_ID, TELEGRAM_BOT_TOKEN

STATE_PATH = Path(__file__).resolve().parent.parent / "state" / "suspect_state.json"
WEEK = timedelta(days=7)


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"results_history": []}


def _send_message(text: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(url, json={"chat_id": ALERT_CHAT_ID, "text": text}, timeout=10)
    response.raise_for_status()


def _format_summary(entries: list[dict]) -> str:
    if not entries:
        return (
            "📅 Récapitulatif de la semaine\n\n"
            "Aucun pari réglé cette semaine (pas assez de signaux ou de matchs terminés)."
        )

    wins = [e for e in entries if e["result"] == "won"]
    losses = [e for e in entries if e["result"] == "lost"]
    total_profit = sum(e["profit_pct"] for e in entries)
    win_rate = len(wins) / len(entries) * 100

    lines = [
        "📅 Récapitulatif de la semaine",
        "",
        f"🎯 Signaux réglés : {len(entries)}",
        f"✅ Gagnés : {len(wins)}",
        f"❌ Perdus : {len(losses)}",
        f"📈 Taux de réussite : {win_rate:.0f}%",
        f"💰 Résultat net : {total_profit:+.2f}% du capital (en cumulant les mises suggérées)",
        "",
        "Détail :",
    ]
    for entry in entries:
        icon = "✅" if entry["result"] == "won" else "❌"
        lines.append(
            f"{icon} {entry['home_team']} vs {entry['away_team']} — "
            f"{entry['selection']} @ {entry['odds_at_alert']:.2f} "
            f"({entry['profit_pct']:+.2f}%)"
        )

    lines.append("")
    lines.append(
        "⚠️ Résultat théorique basé sur les mises suggérées, pas de l'argent réellement engagé."
    )
    return "\n".join(lines)


def main() -> None:
    if not ALERT_CHAT_ID:
        raise RuntimeError("ALERT_CHAT_ID manquant dans les variables d'environnement")

    state = _load_state()
    history = state.get("results_history", [])

    cutoff = datetime.now(timezone.utc) - WEEK
    recent = [
        entry
        for entry in history
        if datetime.fromisoformat(entry["alerted_at"]) >= cutoff
    ]

    _send_message(_format_summary(recent))
    print(f"Récapitulatif envoyé : {len(recent)} pari(s) sur les 7 derniers jours.")


if __name__ == "__main__":
    main()
