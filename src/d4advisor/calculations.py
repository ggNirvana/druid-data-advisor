from __future__ import annotations

import math
from collections.abc import Iterable


def percentage_multiplier_to_factor(percent: float) -> float:
    """Convert an OCR percentage multiplier such as 18% to a x1.18 factor."""
    if percent < -100:
        raise ValueError("percent cannot produce a negative multiplier")
    return 1 + percent / 100


def expected_chained_attacks(probability: float, max_extra_attacks: int) -> float:
    """Return expected total attacks for a capped continue-on-success chain."""
    if not 0 <= probability <= 1:
        raise ValueError("probability must be between 0 and 1")
    if max_extra_attacks < 0:
        raise ValueError("max_extra_attacks must be non-negative")
    return sum(probability**attempt for attempt in range(max_extra_attacks + 1))


def expected_hit_damage(
    *,
    base_damage: float,
    additive_bonus: float,
    independent_multipliers: Iterable[float],
    crit_chance: float,
    crit_multiplier: float,
    vulnerable_uptime: float,
    vulnerable_multiplier: float,
) -> float:
    """Calculate expected hit damage under declared crit/vulnerable uptimes.

    Multipliers are expressed as total factors: 1.5 means x1.5. Additive bonus
    is expressed as bonus over base: 1.0 means +100%.
    """
    for label, value in (("crit_chance", crit_chance), ("vulnerable_uptime", vulnerable_uptime)):
        if not 0 <= value <= 1:
            raise ValueError(f"{label} must be between 0 and 1")
    if base_damage < 0 or additive_bonus < -1:
        raise ValueError("damage inputs cannot produce a negative base")
    if crit_multiplier < 0 or vulnerable_multiplier < 0:
        raise ValueError("multipliers must be non-negative")

    independent_factor = math.prod(independent_multipliers)
    crit_factor = 1 + crit_chance * (crit_multiplier - 1)
    vulnerable_factor = 1 + vulnerable_uptime * (vulnerable_multiplier - 1)
    return base_damage * (1 + additive_bonus) * independent_factor * crit_factor * vulnerable_factor


def stack_damage_reductions(reductions: Iterable[float]) -> float:
    """Stack independent damage reductions multiplicatively."""
    reductions = tuple(reductions)
    if any(not 0 <= reduction < 1 for reduction in reductions):
        raise ValueError("each damage reduction must be in [0, 1)")
    return 1 - math.prod(1 - reduction for reduction in reductions)


def effective_health(life_and_absorption: float, total_damage_reduction: float) -> float:
    """Return EHP against a declared damage type and active reduction set."""
    if life_and_absorption < 0:
        raise ValueError("life_and_absorption must be non-negative")
    if not 0 <= total_damage_reduction < 1:
        raise ValueError("total_damage_reduction must be in [0, 1)")
    return life_and_absorption / (1 - total_damage_reduction)
