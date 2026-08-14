"""Envoie des exemples d'alertes sur Telegram, avec des données fictives.

Utile pour prévisualiser un changement de format sans attendre qu'une
vraie anomalie ou value bet soit détectée. Ne touche à aucun état
(state/suspect_state.json) et ne consomme aucun crédit d'API de cotes.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.detect_suspicious import _format_value_alert, _send_alert
from suspect import ValueBet

FAKE_FOOTBALL_EVENT = {
    "sport_title": "Ligue 1",
    "commence_time": "2026-08-15T18:00:00Z",
    "home_team": "Équipe A",
    "away_team": "Équipe B",
}

FAKE_TENNIS_EVENT = {
    "sport_title": "ATP Cincinnati Open",
    "commence_time": "2026-08-15T18:00:00Z",
    "home_team": "Novak Djokovic",
    "away_team": "Carlos Alcaraz",
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
    _send_alert("🔎 Exemple d'alerte (aperçu du nouveau format) :\n\n" + _format_value_alert(FAKE_FOOTBALL_EVENT, "Cotes 1X2", value_bet))

    tennis_value_bet = ValueBet(
        bookmaker="Betfair",
        outcome="Novak Djokovic",
        odds=2.10,
        fair_probability=0.52,
        ev_pct=0.09,
        stake_pct=3.0,
    )
    _send_alert(
        "🔎 Exemple d'alerte (aperçu du nouveau format) :\n\n"
        + _format_value_alert(FAKE_TENNIS_EVENT, "Vainqueur du match", tennis_value_bet)
    )

    print("2 exemples envoyés.")


if __name__ == "__main__":
    main()
