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
    """Bookmaker(s) qui s'écartent nettement du mouvement médian du marché.

    Comparer chaque bookmaker au mouvement médian (plutôt qu'à un seuil
    absolu) évite de signaler tous les bookmakers lors d'une repricing
    générale du marché (ex. réouverture des cotes), où beaucoup bougent
    dans des sens différents sans que rien ne soit réellement anormal.
    Seul un bookmaker qui s'écarte du comportement du marché est signalé.
    """
    common_bookmakers = set(previous) & set(current)
    if len(common_bookmakers) < MIN_BOOKMAKERS_FOR_SPREAD_CHECK:
        return []

    outcomes: set[str] = set()
    for bookmaker in common_bookmakers:
        outcomes.update(current[bookmaker])

    reasons = []
    for outcome in outcomes:
        changes: dict[str, float] = {}
        for bookmaker in common_bookmakers:
            previous_price = previous[bookmaker].get(outcome)
            current_price = current[bookmaker].get(outcome)
            if not previous_price or not current_price:
                continue
            changes[bookmaker] = (current_price - previous_price) / previous_price

        if len(changes) < MIN_BOOKMAKERS_FOR_SPREAD_CHECK:
            continue

        sorted_changes = sorted(changes.values())
        median_change = sorted_changes[len(sorted_changes) // 2]

        for bookmaker, change in changes.items():
            deviation = abs(change - median_change)
            if deviation < ODDS_DROP_THRESHOLD:
                continue
            previous_price = previous[bookmaker][outcome]
            current_price = current[bookmaker][outcome]
            reasons.append(
                f"Mouvement inhabituel chez {bookmaker} sur « {outcome} » "
                f"(cote {previous_price:.2f} → {current_price:.2f}, "
                f"écart au marché {deviation:.0%})"
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
