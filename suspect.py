"""Détection de matchs suspects à partir des mouvements de cotes.

Un match suspect est un match dont le comportement de cotes n'est pas
normal : signaux anormaux, chute de cote traduisant des mises massives sur
une issue, écarts incohérents entre bookmakers, ou mouvements inhabituels
chez un bookmaker en particulier.

Faute de données publiques sur les volumes de mise réels, ces règles
utilisent les mouvements de cotes entre deux relevés comme indicateur
indirect ("proxy") des mises massives.
"""

from __future__ import annotations

# Seuils de détection (ajustables)
ODDS_DROP_THRESHOLD = 0.15          # chute relative de cote >= 15 % -> signal
BOOKMAKER_SPREAD_THRESHOLD = 0.20   # écart max/min entre bookmakers >= 20 % -> signal
MIN_BOOKMAKERS_FOR_SPREAD_CHECK = 3


def _best_price_per_outcome(prices_by_bookmaker: dict[str, dict[str, float]]) -> dict[str, float]:
    """Retourne, pour chaque issue, la cote la plus élevée proposée."""
    best: dict[str, float] = {}
    for outcomes in prices_by_bookmaker.values():
        for outcome, price in outcomes.items():
            if outcome not in best or price > best[outcome]:
                best[outcome] = price
    return best


def _detect_massive_bet_signal(previous: dict[str, float], current: dict[str, float]) -> list[str]:
    """Chute brutale de cote sur une issue = indice de mises massives dessus."""
    reasons = []
    for outcome, current_price in current.items():
        previous_price = previous.get(outcome)
        if not previous_price:
            continue
        drop = (previous_price - current_price) / previous_price
        if drop >= ODDS_DROP_THRESHOLD:
            reasons.append(
                f"Mises massives suspectées sur « {outcome} » "
                f"(cote {previous_price:.2f} → {current_price:.2f}, -{drop:.0%})"
            )
    return reasons


def _detect_incoherent_spread(prices_by_bookmaker: dict[str, dict[str, float]]) -> list[str]:
    """Écart anormal entre bookmakers sur une même issue."""
    reasons = []
    if len(prices_by_bookmaker) < MIN_BOOKMAKERS_FOR_SPREAD_CHECK:
        return reasons

    outcomes: set[str] = set()
    for outcomes_map in prices_by_bookmaker.values():
        outcomes.update(outcomes_map)

    for outcome in outcomes:
        values = [
            outcomes_map[outcome]
            for outcomes_map in prices_by_bookmaker.values()
            if outcome in outcomes_map
        ]
        if len(values) < MIN_BOOKMAKERS_FOR_SPREAD_CHECK:
            continue
        spread = (max(values) - min(values)) / min(values)
        if spread >= BOOKMAKER_SPREAD_THRESHOLD:
            reasons.append(
                f"Variation de cotes incohérente entre bookmakers sur « {outcome} » "
                f"({min(values):.2f} à {max(values):.2f}, écart {spread:.0%})"
            )
    return reasons


def _detect_unusual_bookmaker_moves(
    previous: dict[str, dict[str, float]], current: dict[str, dict[str, float]]
) -> list[str]:
    """Un bookmaker qui bouge fortement, à contre-courant du marché."""
    reasons = []
    common_bookmakers = set(previous) & set(current)
    for bookmaker in common_bookmakers:
        prev_outcomes = previous[bookmaker]
        curr_outcomes = current[bookmaker]
        for outcome, current_price in curr_outcomes.items():
            previous_price = prev_outcomes.get(outcome)
            if not previous_price:
                continue
            move = abs(current_price - previous_price) / previous_price
            if move >= ODDS_DROP_THRESHOLD:
                reasons.append(
                    f"Mouvement inhabituel chez {bookmaker} sur « {outcome} » "
                    f"(cote {previous_price:.2f} → {current_price:.2f})"
                )
    return reasons


def detect_suspicious_match(
    previous_prices: dict[str, dict[str, float]] | None,
    current_prices: dict[str, dict[str, float]],
) -> list[str]:
    """Retourne les raisons pour lesquelles un match est jugé suspect.

    `previous_prices` et `current_prices` sont au format
    {bookmaker: {issue: cote}}, tel que renvoyé par `odds.extract_outcome_prices`.
    Liste vide si rien d'anormal n'est détecté.

    Sans relevé précédent (premier passage sur ce match), seul l'écart
    entre bookmakers ne suffit pas à juger un match suspect : il faut un
    historique pour observer une vraie variation dans le temps.
    """
    if not previous_prices:
        return []

    reasons: list[str] = []
    reasons.extend(_detect_incoherent_spread(current_prices))

    previous_best = _best_price_per_outcome(previous_prices)
    current_best = _best_price_per_outcome(current_prices)
    reasons.extend(_detect_massive_bet_signal(previous_best, current_best))
    reasons.extend(_detect_unusual_bookmaker_moves(previous_prices, current_prices))

    return reasons
