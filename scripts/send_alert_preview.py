"""Envoie des exemples d'alertes sur Telegram, avec des données fictives.

Utile pour prévisualiser un changement de format sans attendre qu'une
vraie anomalie ou value bet soit détectée. Ne touche à aucun état
(state/suspect_state.json) et ne consomme aucun crédit d'API de cotes.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.detect_suspicious import _format_alert, _format_value_alert, _send_alert
from suspect import MatchAnalysis, Signal, ValueBet

FAKE_EVENT = {
    "sport_title": "Ligue 1",
    "commence_time": "2026-08-15T18:00:00Z",
    "home_team": "Équipe A",
    "away_team": "Équipe B",
}


def main() -> None:
    value_bet = ValueBet(
        bookmaker="Betfair",
        outcome="Équipe A",
        odds=2.40,
        fair_probability=0.46,
        ev_pct=0.10,
        stake_pct=3.0,
    )
    _send_alert("🔎 Exemple d'alerte (aperçu du nouveau format) :\n\n" + _format_value_alert(FAKE_EVENT, "Cotes 1X2", value_bet))

    analysis = MatchAnalysis(
        signals=[
            Signal(
                category="massive_bet",
                text="Mises massives suspectées sur « Équipe A » (cote 2.80 → 2.40, -14%)",
                magnitude=0.14,
                outcome="Équipe A",
            )
        ],
        confidence=65,
        stake_pct=3.0,
        selection="Équipe A",
        odds_at_alert=2.40,
    )
    _send_alert("🔎 Exemple d'alerte (aperçu du nouveau format) :\n\n" + _format_alert(FAKE_EVENT, "Cotes 1X2", analysis))

    print("2 exemples envoyés.")


if __name__ == "__main__":
    main()
