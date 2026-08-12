"""Détection de matchs suspects à partir des mouvements de cotes.

Un match suspect est un match dont le comportement de cotes n'est pas
normal : signaux anormaux, chute de cote traduisant des mises massives sur
une issue, écarts incohérents entre bookmakers, ou mouvements inhabituels
chez un bookmaker en particulier.

Faute de données publiques sur les volumes de mise réels (et sans IA
connectée pour estimer une vraie probabilité), ces règles ne calculent
PAS de "value bet" au sens mathématique (probabilité estimée x cote - 1).
Elles produisent uniquement un score de confiance dans la force du signal
statistique détecté, présenté comme une "anomalie de marché" — jamais
comme une value bet validée.
"""

from __future__ import annotations

from dataclasses import dataclass

# Seuils de détection (ajustables)
ODDS_DROP_THRESHOLD = 0.15          # chute relative de cote >= 15 % -> signal
BOOKMAKER_SPREAD_THRESHOLD = 0.20   # écart max/min entre bookmakers >= 20 % -> signal
MIN_BOOKMAKERS_FOR_SPREAD_CHECK = 3

# Pinnacle est réputée pour être le bookmaker le plus "sharp" (le plus
# efficient) du marché : ses mouvements de cotes précèdent souvent ceux
# des autres bookmakers, même quand ils ne s'écartent pas (encore) du
# marché. Un mouvement chez Pinnacle est donc signalé distinctement.
PINNACLE_NAME = "Pinnacle"

# Paliers de mise suggérée en fonction du score de confiance (% du capital)
STAKE_TIERS = (
    (85, 5.0),
    (70, 3.0),
    (50, 2.0),
    (0, 1.0),
)


@dataclass
class Signal:
    """Un signal statistique élémentaire détecté sur un marché."""

    category: str  # "massive_bet" | "incoherent_spread" | "unusual_bookmaker" | "pinnacle_move"
    text: str
    magnitude: float  # amplitude relative du signal (0.15 = 15 %)
    outcome: str  # issue visée par le signal (ex: nom d'équipe, "Draw", nom de joueur)


@dataclass
class MatchAnalysis:
    """Résultat de l'analyse d'un match : signaux, confiance, mise suggérée."""

    signals: list[Signal]
    confidence: int  # score de confiance dans le signal, 0-100 (PAS une probabilité de gain)
    stake_pct: float  # mise suggérée, en % du capital
    selection: str | None = None  # issue visée par le signal le plus fort
    odds_at_alert: float | None = None  # meilleure cote dispo sur `selection` au moment de l'alerte

    @property
    def reasons(self) -> list[str]:
        return [signal.text for signal in self.signals]


def _best_price_per_outcome(prices_by_bookmaker: dict[str, dict[str, float]]) -> dict[str, float]:
    """Retourne, pour chaque issue, la cote la plus élevée proposée."""
    best: dict[str, float] = {}
    for outcomes in prices_by_bookmaker.values():
        for outcome, price in outcomes.items():
            if outcome not in best or price > best[outcome]:
                best[outcome] = price
    return best


def _detect_massive_bet_signal(previous: dict[str, float], current: dict[str, float]) -> list[Signal]:
    """Chute brutale de cote sur une issue = indice de mises massives dessus."""
    signals = []
    for outcome, current_price in current.items():
        previous_price = previous.get(outcome)
        if not previous_price:
            continue
        drop = (previous_price - current_price) / previous_price
        if drop >= ODDS_DROP_THRESHOLD:
            signals.append(
                Signal(
                    category="massive_bet",
                    text=(
                        f"Mises massives suspectées sur « {outcome} » "
                        f"(cote {previous_price:.2f} → {current_price:.2f}, -{drop:.0%})"
                    ),
                    magnitude=drop,
                    outcome=outcome,
                )
            )
    return signals


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
) -> list[Signal]:
    """Écart entre bookmakers qui vient d'apparaître (pas déjà présent au relevé précédent).

    Comparer au relevé précédent évite de re-signaler indéfiniment un
    marché structurellement peu liquide (écart large mais stable) : seule
    une vraie variation (l'écart franchit le seuil) déclenche une alerte.
    """
    previous_spreads = _spread_by_outcome(previous_prices)
    current_spreads = _spread_by_outcome(current_prices)

    signals = []
    for outcome, spread in current_spreads.items():
        if spread < BOOKMAKER_SPREAD_THRESHOLD:
            continue
        if previous_spreads.get(outcome, 0.0) >= BOOKMAKER_SPREAD_THRESHOLD:
            continue
        signals.append(
            Signal(
                category="incoherent_spread",
                text=(
                    f"Variation de cotes incohérente entre bookmakers sur « {outcome} » "
                    f"(écart {spread:.0%})"
                ),
                magnitude=spread,
                outcome=outcome,
            )
        )
    return signals


def _detect_unusual_bookmaker_moves(
    previous: dict[str, dict[str, float]], current: dict[str, dict[str, float]]
) -> list[Signal]:
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

    signals = []
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
            signals.append(
                Signal(
                    category="unusual_bookmaker",
                    text=(
                        f"Mouvement inhabituel chez {bookmaker} sur « {outcome} » "
                        f"(cote {previous_price:.2f} → {current_price:.2f}, "
                        f"écart au marché {deviation:.0%})"
                    ),
                    magnitude=deviation,
                    outcome=outcome,
                )
            )

    return signals


def _detect_pinnacle_move(
    previous: dict[str, dict[str, float]], current: dict[str, dict[str, float]]
) -> list[Signal]:
    """Mouvement de cote chez Pinnacle, la référence "sharp" du marché.

    Contrairement à `_detect_unusual_bookmaker_moves`, ce signal ne
    dépend pas d'un écart par rapport au marché : Pinnacle bougeant en
    premier (avant que les autres bookmakers ne suivent) est en soi un
    indicateur pertinent, pas seulement une divergence.
    """
    previous_pinnacle = previous.get(PINNACLE_NAME)
    current_pinnacle = current.get(PINNACLE_NAME)
    if not previous_pinnacle or not current_pinnacle:
        return []

    signals = []
    for outcome, current_price in current_pinnacle.items():
        previous_price = previous_pinnacle.get(outcome)
        if not previous_price:
            continue
        move = (current_price - previous_price) / previous_price
        if abs(move) < ODDS_DROP_THRESHOLD:
            continue
        direction = "cote raccourcie" if move < 0 else "cote allongée"
        signals.append(
            Signal(
                category="pinnacle_move",
                text=(
                    f"🎯 Pinnacle (référence sharp) bouge sur « {outcome} » "
                    f"(cote {previous_price:.2f} → {current_price:.2f}, "
                    f"{direction}, {abs(move):.0%})"
                ),
                magnitude=abs(move),
                outcome=outcome,
            )
        )
    return signals


def _confidence_from_signals(signals: list[Signal]) -> int:
    """Score de confiance (0-100) dans la force du signal statistique.

    Ce n'est PAS une probabilité de gain : plus de catégories de signaux
    confirmant la même anomalie, et une amplitude plus forte, augmentent
    la confiance dans le fait que le mouvement observé est réel et notable
    (pas juste du bruit de marché).
    """
    if not signals:
        return 0

    categories = {signal.category for signal in signals}
    max_magnitude = max(signal.magnitude for signal in signals)

    score = 30 + 20 * (len(categories) - 1) + min(30, max_magnitude * 50)
    if "pinnacle_move" in categories:
        score += 15  # Pinnacle est la référence sharp : bonus de confiance dédié

    return min(100, round(score))


def _stake_from_confidence(confidence: int) -> float:
    """Mise suggérée (% du capital) selon le score de confiance, par paliers."""
    for threshold, stake_pct in STAKE_TIERS:
        if confidence >= threshold:
            return stake_pct
    return STAKE_TIERS[-1][1]


def analyze_match(
    previous_prices: dict[str, dict[str, float]] | None,
    current_prices: dict[str, dict[str, float]],
) -> MatchAnalysis:
    """Analyse un match : signaux détectés, score de confiance, mise suggérée.

    `previous_prices` et `current_prices` sont au format
    {bookmaker: {issue: cote}}, tel que renvoyé par `odds.extract_outcome_prices`.

    Sans relevé précédent (premier passage sur ce match), seul l'écart
    entre bookmakers ne suffit pas à juger un match suspect : il faut un
    historique pour observer une vraie variation dans le temps.
    """
    if not previous_prices:
        return MatchAnalysis(signals=[], confidence=0, stake_pct=0.0)

    signals: list[Signal] = []
    signals.extend(_detect_new_incoherent_spread(previous_prices, current_prices))

    previous_best = _best_price_per_outcome(previous_prices)
    current_best = _best_price_per_outcome(current_prices)
    signals.extend(_detect_massive_bet_signal(previous_best, current_best))
    signals.extend(_detect_unusual_bookmaker_moves(previous_prices, current_prices))
    signals.extend(_detect_pinnacle_move(previous_prices, current_prices))

    confidence = _confidence_from_signals(signals)
    stake_pct = _stake_from_confidence(confidence) if signals else 0.0

    selection = None
    odds_at_alert = None
    if signals:
        # L'issue visée par le signal le plus fort (le plus fiable) est
        # considérée comme la "sélection" implicite, pour pouvoir vérifier
        # plus tard si le résultat du match lui a donné raison.
        primary_signal = max(signals, key=lambda signal: signal.magnitude)
        selection = primary_signal.outcome
        odds_at_alert = current_best.get(selection)

    return MatchAnalysis(
        signals=signals,
        confidence=confidence,
        stake_pct=stake_pct,
        selection=selection,
        odds_at_alert=odds_at_alert,
    )


def detect_suspicious_match(
    previous_prices: dict[str, dict[str, float]] | None,
    current_prices: dict[str, dict[str, float]],
) -> list[str]:
    """Retourne les raisons pour lesquelles un match est jugé suspect (compat)."""
    return analyze_match(previous_prices, current_prices).reasons
