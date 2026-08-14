"""Envoie sur Telegram un récapitulatif de toutes les value bets envoyées.

Déduplique les alertes envoyées plusieurs fois pour le même match/sélection
(un même écart de cote repéré chez plusieurs bookmakers ne compte qu'une
fois), et calcule la mise en Fdj à partir du pourcentage de mise suggéré,
sur un capital de départ fixe. N'attend pas les résultats des matchs
(les mises sont juste listées, pas encore réglées gagné/perdu).
"""

from __future__ import annotations

import json
import sys
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.detect_suspicious import _describe_selection, _send_alert

STATE_PATH = Path(__file__).resolve().parent.parent / "state" / "suspect_state.json"
CAPITAL_DEPART = 1000.0


def _dedupe(pending: list) -> list:
    """Une entrée par (match, sélection) : garde la première alerte reçue,
    peu importe combien de bookmakers ont signalé la même value."""
    seen: "OrderedDict[tuple, dict]" = OrderedDict()
    for entry in pending:
        key = (entry.get("home_team"), entry.get("away_team"), entry.get("selection"))
        if key not in seen:
            seen[key] = entry
    return list(seen.values())


def _build_summary(entries: list) -> str:
    lines = [
        "📊 Récapitulatif de toutes les value bets envoyées",
        f"💰 Capital de départ : {CAPITAL_DEPART:.0f} Fdj "
        "(doublons retirés — un même match/sélection alerté par plusieurs "
        "bookmakers ne compte qu'une fois)",
        "",
    ]

    total_mise = 0.0
    for i, entry in enumerate(entries, 1):
        event = {"home_team": entry["home_team"], "away_team": entry["away_team"]}
        description = _describe_selection(entry["selection"], event)
        stake_pct = entry["stake_pct"]
        mise = CAPITAL_DEPART * stake_pct / 100
        total_mise += mise
        lines.append(
            f"{i}. {entry['home_team']} vs {entry['away_team']} — {description} "
            f"@ {entry['odds_at_alert']:.2f} — {stake_pct:.0f}% → {mise:.0f} Fdj"
        )

    lines.append("")
    lines.append(
        f"💰 Total misé si tout est joué : {total_mise:.0f} Fdj "
        f"({total_mise / CAPITAL_DEPART * 100:.0f}% du capital)"
    )
    if total_mise > CAPITAL_DEPART:
        lines.append(
            "⚠️ Le total dépasse ton capital de départ : ce sont des "
            "suggestions indépendantes, ne mise pas sur tout en même temps."
        )
    lines.append("⚠️ Aucun résultat réglé pour l'instant (tous en attente de la fin du match).")
    return "\n".join(lines)


def main() -> None:
    state = json.loads(STATE_PATH.read_text())
    entries = _dedupe(state.get("pending_results", []))
    if not entries:
        _send_alert("📊 Aucune value bet en attente pour l'instant.")
        print("Rien à récapituler.")
        return

    text = _build_summary(entries)
    _send_alert(text)
    print(f"Récapitulatif envoyé : {len(entries)} match(s)/sélection(s), {len(text)} caractères.")


if __name__ == "__main__":
    main()
