"""Vérifie les matchs terminés et détermine si les signaux envoyés
avaient raison (gagné/perdu), pour alimenter le récapitulatif hebdomadaire.

Un seul appel à l'API de cotes par passage (endpoint /scores, qui liste
les matchs récents d'un sport), quel que soit le nombre de paris en
attente — conçu pour être exécuté une fois par jour sans dépasser le
quota gratuit.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from odds import OddsAPIError, get_scores

STATE_PATH = Path(__file__).resolve().parent.parent / "state" / "suspect_state.json"

# Délai après le coup d'envoi avant de considérer un match comme terminé
SETTLE_BUFFER = timedelta(hours=3)
# Au-delà de ce délai sans résultat trouvé (match annulé, données manquantes...),
# on abandonne le suivi de ce pari plutôt que de le garder indéfiniment.
MAX_PENDING_AGE = timedelta(days=5)


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"snapshots": {}, "alerted": [], "pending_results": [], "results_history": []}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def _winner(score_entry: dict) -> str | None:
    """Détermine le nom de l'issue gagnante ("Draw" en cas d'égalité)."""
    scores = score_entry.get("scores")
    if not scores:
        return None
    try:
        parsed = [(s["name"], float(s["score"])) for s in scores]
    except (KeyError, TypeError, ValueError):
        return None

    values = {value for _, value in parsed}
    if len(values) == 1:
        return "Draw"

    return max(parsed, key=lambda item: item[1])[0]


def _settle_entry(entry: dict, scores_by_id: dict) -> dict | None:
    score_entry = scores_by_id.get(entry["event_id"])
    if not score_entry or not score_entry.get("completed"):
        return None

    winner = _winner(score_entry)
    if winner is None:
        return None

    won = winner == entry["selection"]
    profit_pct = entry["stake_pct"] * (entry["odds_at_alert"] - 1) if won else -entry["stake_pct"]

    return {**entry, "result": "won" if won else "lost", "winner": winner, "profit_pct": profit_pct}


def main() -> None:
    state = _load_state()
    pending = state.setdefault("pending_results", [])
    history = state.setdefault("results_history", [])

    if not pending:
        print("Aucun pari en attente de règlement.")
        return

    try:
        scores = get_scores()
    except OddsAPIError as exc:
        print(f"Erreur API cotes (scores) : {exc}")
        return

    scores_by_id = {s["id"]: s for s in scores if s.get("id")}
    now = datetime.now(timezone.utc)

    still_pending = []
    settled_count = 0
    for entry in pending:
        commence_time = datetime.fromisoformat(entry["commence_time"].replace("Z", "+00:00"))

        if now < commence_time + SETTLE_BUFFER:
            still_pending.append(entry)
            continue

        settled = _settle_entry(entry, scores_by_id)
        if settled:
            history.append(settled)
            settled_count += 1
            print(
                f"Réglé : {entry['home_team']} vs {entry['away_team']} "
                f"- {settled['result']} ({settled['profit_pct']:+.2f}% du capital)"
            )
            continue

        if now > commence_time + MAX_PENDING_AGE:
            print(f"Abandonné (pas de résultat après {MAX_PENDING_AGE.days}j) : "
                  f"{entry['home_team']} vs {entry['away_team']}")
            continue

        still_pending.append(entry)

    state["pending_results"] = still_pending
    state["results_history"] = history
    _save_state(state)

    print(f"{settled_count} pari(s) réglé(s), {len(still_pending)} toujours en attente.")


if __name__ == "__main__":
    main()
