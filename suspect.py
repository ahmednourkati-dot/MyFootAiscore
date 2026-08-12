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


def _spread_by_outcome(prices_by_bookmaker: dict[str, dict[str, float]]) -> dict[str, float]:
    """Calcule l'écart relatif max/min entre bookmakers, pour chaque issue."""
    if len(prices_by_bookmaker) < MIN_BOOKMAKERS_FOR_SPREAD_CHECK:
        return {}

    outcomes: set[str] = set()
    for outcomes_map in prices_by_bookmaker.values():
        outcomes.update(outcomes_map)

    spreads: dict[str, float] = {}
    for outcome in outcomes:
        values = [
            outcomes_map[outcome]
            for outcomes_map in prices_by_bookmaker.values()
            if outcome in outcomes_map
        ]
        if len(values) < MIN_BOOKMAKERS_FOR_SPREAD_CHECK:
            continue
        spreads[outcome] = (max(values) - min(values)) / min(values)
    return spreads


def _detect_new_incoherent_spread(
    previous_prices: dict[str, dict[str, float]], current_prices: dict[str, dict[str, float]]
) -> list[str]:
    """Écart entre bookmakers qui vient d'apparaître (pas déjà présent au relevé précédent).

    Comparer au relevé précédent évite de re-signaler indéfiniment un
    marché structurellement peu liquide (écart large mais stable) : seule
    une vraie variation (l'écart franchit le seuil) déclenche une alerte.
    """
    previous_spreads = _spread_by_outcome(previous_prices)
    current_spreads = _spread_by_outcome(current_prices)

    reasons = []
    for outcome, spread in current_spreads.items():
        if spread < BOOKMAKER_SPREAD_THRESHOLD:
            continue
        if previous_spreads.get(outcome, 0.0) >= BOOKMAKER_SPREAD_THRESHOLD:
            continue
        reasons.append(
            f"Variation de cotes incohérente entre bookmakers sur « {outcome} » "
            f"(écart {spread:.0%})"
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
    reasons.extend(_detect_new_incoherent_spread(previous_prices, current_prices))

    previous_best = _best_price_per_outcome(previous_prices)
    current_best = _best_price_per_outcome(current_prices)
    reasons.extend(_detect_massive_bet_signal(previous_best, current_best))
    reasons.extend(_detect_unusual_bookmaker_moves(previous_prices, current_prices))

    return reasons
