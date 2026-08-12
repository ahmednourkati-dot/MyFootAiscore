"""Vérifie les cotes 1X2 du football (+ un match de tennis) et alerte en
cas de variation suspecte ou de value bet.

Conçu pour être exécuté périodiquement par un workflow planifié (cron),
sans processus Telegram persistant. L'état est conservé dans STATE_PATH
entre deux exécutions, une entrée par match.

Portée volontairement limitée pour tenir dans le quota gratuit de l'API
de cotes (500 requêtes/mois) : football limité aux 4 premiers matchs
retournés (1 appel API, quel que soit le nombre de matchs traités — la
limite ne sert qu'à réduire le bruit des alertes, pas le quota), et un
seul match de tennis suivi (Iga Swiatek vs Elina Svitolina, WTA Canadian
Open), vérifié seulement à quelques heures fixes dans la journée pour ne
pas doubler le nombre d'appels à chaque passage.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import ALERT_CHAT_ID, TELEGRAM_BOT_TOKEN
from odds import (
    OddsAPIError,
    extract_market_prices,
    format_kickoff_djibouti,
    format_now_djibouti,
    get_odds,
)
from suspect import MatchAnalysis, ValueBet, analyze_match, detect_value_bets

STATE_PATH = Path(__file__).resolve().parent.parent / "state" / "suspect_state.json"

FOOTBALL_SPORT_KEY = "soccer"
FOOTBALL_MARKETS = "h2h"
MAX_FOOTBALL_MATCHES = 4

# Un seul match de tennis suivi, choisi manuellement (voir discover_tennis.py).
TENNIS_SPORT_KEY = "tennis_wta_canadian_open"
TENNIS_PLAYERS = {"Iga Swiatek", "Elina Svitolina"}
# Vérifié seulement à ces heures (UTC) pour ne pas doubler le nombre
# d'appels API à chaque passage (le foot, lui, tourne à chaque passage).
TENNIS_CHECK_HOURS_UTC = {0, 6, 12, 18}


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {
        "snapshots": {},
        "alerted": [],
        "value_alerted": [],
        "pending_results": [],
        "results_history": [],
    }


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def _match_label(event: dict) -> str:
    home = event.get("home_team") or "?"
    away = event.get("away_team") or "?"
    return f"{home} vs {away}"


def _sport_emoji(event: dict) -> str:
    title = (event.get("sport_title") or "").upper()
    if "WTA" in title or "ATP" in title:
        return "🎾"
    return "⚽"


MAX_REASONS_PER_ALERT = 6


def _describe_selection(outcome: str, event: dict) -> str:
    """Traduit une issue brute (nom d'équipe / "Draw") en description claire."""
    home = event.get("home_team")
    away = event.get("away_team")
    if outcome == "Draw":
        return "Match nul"
    if outcome == home:
        return f"Victoire de {home}"
    if outcome == away:
        return f"Victoire de {away}"
    return outcome


def _format_alert(event: dict, market_label: str, analysis: MatchAnalysis) -> str:
    competition = event.get("sport_title") or "?"
    commence_time = event.get("commence_time")
    kickoff = format_kickoff_djibouti(commence_time) if commence_time else "?"
    reasons = analysis.reasons

    lines = [
        "🚨 Match suspect",
        f"🏆 {competition}",
        f"🕒 {kickoff} (heure de Djibouti)",
        f"{_sport_emoji(event)} {_match_label(event)}",
        "",
    ]
    if analysis.selection and analysis.odds_at_alert is not None:
        description = _describe_selection(analysis.selection, event)
        lines.append(
            f"👉 À MISER : {description} @ {analysis.odds_at_alert:.2f} "
            f"— {analysis.stake_pct:.0f}% du capital"
        )
        lines.append("")
    lines.extend(
        [
            f"📊 Marché : {market_label}",
            f"🏷️ Nature : Anomalie de marché (pas une value bet calculée — aucune probabilité réelle estimée)",
            f"🎯 Confiance du signal : {analysis.confidence}%",
            "",
        ]
    )
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


def _format_value_alert(event: dict, market_label: str, vb: ValueBet) -> str:
    competition = event.get("sport_title") or "?"
    commence_time = event.get("commence_time")
    kickoff = format_kickoff_djibouti(commence_time) if commence_time else "?"

    lines = [
        "💎 Value bet détectée",
        f"🏆 {competition}",
        f"🕒 {kickoff} (heure de Djibouti)",
        f"{_sport_emoji(event)} {_match_label(event)}",
        "",
        f"👉 À MISER : {_describe_selection(vb.outcome, event)} @ {vb.odds:.2f} "
        f"— {vb.stake_pct:.0f}% du capital",
        f"🏦 Chez {vb.bookmaker}",
        "",
        f"📊 Marché : {market_label}",
        f"📐 Probabilité juste (Pinnacle dévigorée) : {vb.fair_probability:.0%}",
        f"📈 Espérance de gain estimée : +{vb.ev_pct:.0%}",
        "",
        "⚠️ Value calculée par rapport à la cote « juste » de Pinnacle (référence "
        "marché sharp), pas une garantie de gain sur ce match précis. "
        "Ne mise jamais plus que tu ne peux perdre.",
    ]
    return "\n".join(lines)


def _record_pending(
    pending_results: list,
    event: dict,
    market_label: str,
    state_key: str,
    sport_key: str,
    *,
    selection: str,
    odds_at_alert: float,
    stake_pct: float,
    confidence: int,
    alert_type: str,
) -> None:
    """Enregistre une alerte envoyée pour vérifier plus tard si son issue s'est réalisée."""
    pending_results.append(
        {
            "state_key": state_key,
            "event_id": event.get("id"),
            "sport_key": sport_key,
            "competition": event.get("sport_title") or "?",
            "home_team": event.get("home_team"),
            "away_team": event.get("away_team"),
            "commence_time": event.get("commence_time"),
            "market_label": market_label,
            "selection": selection,
            "odds_at_alert": odds_at_alert,
            "stake_pct": stake_pct,
            "confidence": confidence,
            "alert_type": alert_type,
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
    value_alerted: set,
    current_state_keys: set,
    pending_results: list,
    session_alerts: list,
    sport_key: str = FOOTBALL_SPORT_KEY,
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
        _record_pending(
            pending_results,
            event,
            market_label,
            state_key,
            sport_key,
            selection=analysis.selection,
            odds_at_alert=analysis.odds_at_alert,
            stake_pct=analysis.stake_pct,
            confidence=analysis.confidence,
            alert_type="suspicious",
        )
        session_alerts.append(f"🚨 {_match_label(event)}")
        print(
            f"Alerte envoyée pour {_match_label(event)} ({market_label}) "
            f"- confiance {analysis.confidence}%, mise {analysis.stake_pct:.0f}%"
        )

    for vb in detect_value_bets(current_prices):
        value_key = f"{state_key}|{vb.bookmaker}|{vb.outcome}"
        if value_key in value_alerted:
            continue
        value_alerted.add(value_key)
        _send_alert(_format_value_alert(event, market_label, vb))
        _record_pending(
            pending_results,
            event,
            market_label,
            state_key,
            sport_key,
            selection=vb.outcome,
            odds_at_alert=vb.odds,
            stake_pct=vb.stake_pct,
            confidence=round(vb.ev_pct * 100),
            alert_type="value",
        )
        session_alerts.append(f"💎 {_match_label(event)} ({vb.bookmaker})")
        print(
            f"Value bet envoyée pour {_match_label(event)} ({market_label}) "
            f"- {vb.bookmaker} {vb.outcome} @ {vb.odds:.2f}, EV +{vb.ev_pct:.0%}"
        )


def _check_football(
    snapshots: dict,
    alerted: set,
    value_alerted: set,
    current_state_keys: set,
    pending_results: list,
    session_alerts: list,
) -> int:
    try:
        events = get_odds(FOOTBALL_SPORT_KEY, markets=FOOTBALL_MARKETS)
    except OddsAPIError as exc:
        print(f"Erreur API cotes (football) : {exc}")
        return 0

    events = events[:MAX_FOOTBALL_MATCHES]
    print(f"Football : {len(events)} matchs suivis (sur ceux disponibles)")
    for event in events:
        print(f"  - {_match_label(event)} ({event.get('sport_title')})")

    for event in events:
        _process_market(
            event, "h2h", "Cotes 1X2", "h2h", snapshots, alerted, value_alerted,
            current_state_keys, pending_results, session_alerts,
        )

    return len(events)


def _check_tennis(
    snapshots: dict,
    alerted: set,
    value_alerted: set,
    current_state_keys: set,
    pending_results: list,
    session_alerts: list,
) -> int:
    """Suit un seul match de tennis (voir TENNIS_SPORT_KEY / TENNIS_PLAYERS).

    Vérifié seulement à quelques heures fixes (TENNIS_CHECK_HOURS_UTC) pour
    ne pas doubler le nombre d'appels API à chaque passage.
    """
    if datetime.now(timezone.utc).hour not in TENNIS_CHECK_HOURS_UTC:
        return 0

    try:
        events = get_odds(TENNIS_SPORT_KEY, markets="h2h")
    except OddsAPIError as exc:
        print(f"Erreur API cotes (tennis) : {exc}")
        return 0

    match = next(
        (e for e in events if {e.get("home_team"), e.get("away_team")} == TENNIS_PLAYERS),
        None,
    )
    if not match:
        print("Tennis : match suivi introuvable (pas encore programmé ou terminé)")
        return 0

    print(f"Tennis : {_match_label(match)} suivi")
    _process_market(
        match, "h2h", "Vainqueur du match", "tennis-h2h", snapshots, alerted, value_alerted,
        current_state_keys, pending_results, session_alerts, sport_key=TENNIS_SPORT_KEY,
    )
    return 1


def _send_summary(n_football: int, n_tennis: int, session_alerts: list) -> None:
    now = format_now_djibouti()
    tennis_line = f"🎾 {n_tennis} match(s) de tennis suivi(s)\n" if n_tennis else ""
    if session_alerts:
        text = (
            f"✅ Vérification {now} (heure de Djibouti)\n"
            f"⚽ {n_football} matchs de foot analysés\n"
            f"{tennis_line}"
            f"🔔 {len(session_alerts)} alerte(s) détectée(s) (détails ci-dessus) :\n"
            + "\n".join(f"• {label}" for label in session_alerts)
        )
    else:
        text = (
            f"✅ Vérification {now} (heure de Djibouti)\n"
            f"⚽ {n_football} matchs de foot analysés\n"
            f"{tennis_line}"
            f"Rien de suspect ni de value bet détecté."
        )
    _send_alert(text)


def main() -> None:
    if not ALERT_CHAT_ID:
        raise RuntimeError("ALERT_CHAT_ID manquant dans les variables d'environnement")

    state = _load_state()
    snapshots = state.setdefault("snapshots", {})
    alerted = set(state.setdefault("alerted", []))
    value_alerted = set(state.setdefault("value_alerted", []))
    pending_results = state.setdefault("pending_results", [])
    state.setdefault("results_history", [])
    current_state_keys: set = set()
    session_alerts: list = []

    n_football = _check_football(
        snapshots, alerted, value_alerted, current_state_keys, pending_results, session_alerts
    )
    n_tennis = _check_tennis(
        snapshots, alerted, value_alerted, current_state_keys, pending_results, session_alerts
    )
    _send_summary(n_football, n_tennis, session_alerts)

    # Purge l'état des matchs qui ne sont plus dans le calendrier de l'API.
    snapshots = {key: prices for key, prices in snapshots.items() if key in current_state_keys}
    alerted &= current_state_keys
    value_alerted = {key for key in value_alerted if key.split("|", 1)[0] in current_state_keys}

    state["snapshots"] = snapshots
    state["alerted"] = sorted(alerted)
    state["value_alerted"] = sorted(value_alerted)
    _save_state(state)


if __name__ == "__main__":
    main()
