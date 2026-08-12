"""Utilitaire ponctuel : liste les tournois de tennis actifs et un match de
chacun, pour choisir manuellement quel tournoi suivre en continu.

Pas destiné à tourner en automatique (usage unique, via workflow_dispatch).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from odds import OddsAPIError, get_active_tennis_sport_keys, get_odds


def main() -> None:
    try:
        sport_keys = get_active_tennis_sport_keys()
    except OddsAPIError as exc:
        print(f"Erreur API cotes (sports) : {exc}")
        return

    print(f"{len(sport_keys)} tournoi(s) de tennis actif(s) : {sport_keys}")

    for sport_key in sport_keys[:8]:
        try:
            events = get_odds(sport_key, markets="h2h")
        except OddsAPIError as exc:
            print(f"  {sport_key} : erreur ({exc})")
            continue
        print(f"  {sport_key} : {len(events)} match(s)")
        for event in events[:5]:
            print(f"    - {event.get('home_team')} vs {event.get('away_team')} ({event.get('commence_time')})")


if __name__ == "__main__":
    main()
