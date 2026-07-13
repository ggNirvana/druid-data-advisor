from __future__ import annotations

import math
from collections.abc import Iterable


def _finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def percentage_multiplier_to_factor(percent: float) -> float:
    """Convert an OCR percentage multiplier such as 18% to a x1.18 factor."""
    percent = _finite(percent, "percent")
    if percent < -100:
        raise ValueError("percent cannot produce a negative multiplier")
    return 1 + percent / 100


def expected_chained_attacks(probability: float, max_extra_attacks: int) -> float:
    """Return expected total attacks for a capped continue-on-success chain."""
    probability = _finite(probability, "probability")
    if not 0 <= probability <= 1:
        raise ValueError("probability must be between 0 and 1")
    if (
        isinstance(max_extra_attacks, bool)
        or not isinstance(max_extra_attacks, int)
        or max_extra_attacks < 0
    ):
        raise ValueError("max_extra_attacks must be a non-negative integer")
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
    """Calculate the legacy independent-factor approximation.

    Multipliers are expressed as total factors: 1.5 means x1.5. Additive bonus
    is expressed as bonus over base: 1.0 means +100%. This is exact only when
    additive damage is identical in every crit/vulnerable branch and the two
    states are independent. Current game ledgers must use
    :func:`season13_damage_branch` through ``season13-buckets-v1``.
    """
    base_damage = _finite(base_damage, "base_damage")
    additive_bonus = _finite(additive_bonus, "additive_bonus")
    crit_multiplier = _finite(crit_multiplier, "crit_multiplier")
    vulnerable_multiplier = _finite(vulnerable_multiplier, "vulnerable_multiplier")
    crit_chance = _finite(crit_chance, "crit_chance")
    vulnerable_uptime = _finite(vulnerable_uptime, "vulnerable_uptime")
    for label, value in (("crit_chance", crit_chance), ("vulnerable_uptime", vulnerable_uptime)):
        if not 0 <= value <= 1:
            raise ValueError(f"{label} must be between 0 and 1")
    if base_damage < 0 or additive_bonus < -1:
        raise ValueError("damage inputs cannot produce a negative base")
    if crit_multiplier < 0 or vulnerable_multiplier < 0:
        raise ValueError("multipliers must be non-negative")

    factors = tuple(
        _finite(value, f"independent_multipliers[{index}]")
        for index, value in enumerate(independent_multipliers)
    )
    if any(value < 0 for value in factors):
        raise ValueError("independent multipliers must be non-negative")
    independent_factor = math.prod(factors)
    crit_factor = 1 + crit_chance * (crit_multiplier - 1)
    vulnerable_factor = 1 + vulnerable_uptime * (vulnerable_multiplier - 1)
    return _finite(
        base_damage
        * (1 + additive_bonus)
        * independent_factor
        * crit_factor
        * vulnerable_factor,
        "calculated expected_hit_damage",
    )


def multiplier_bucket_factor(bonuses: Iterable[float]) -> float:
    """Return one Season 13 multiplier bucket as ``1 + sum(bonuses)``.

    Values are decimal bonuses: ``0.31`` means an affix displayed as ``x31%``.
    This helper is intentionally different from multiplying independent factors.
    """
    values = tuple(
        _finite(value, f"bonuses[{index}]") for index, value in enumerate(bonuses)
    )
    factor = 1 + math.fsum(values)
    if factor < 0:
        raise ValueError("bucket bonuses cannot produce a negative multiplier")
    return _finite(factor, "calculated multiplier_bucket_factor")


def season13_damage_branch(
    *,
    weapon_damage: float,
    skill_coefficient: float,
    main_stat: float,
    main_stat_divisor: float,
    additive_bonus: float,
    all_damage_bucket_bonus: float,
    independent_multipliers: Iterable[float],
    enemy_damage_factor: float,
    is_critical: bool = False,
    critical_base_factor: float = 1.5,
    critical_bucket_bonus: float = 0,
    is_vulnerable: bool = False,
    vulnerable_base_factor: float = 1.2,
    vulnerable_bucket_bonus: float = 0,
    is_dot: bool = False,
    dot_bucket_bonus: float = 0,
) -> float:
    """Calculate one fully declared Season 13 direct-hit or DoT branch.

    The four named multiplier families are additive only within their own bucket:
    all/physical/eligible elemental damage, critical-strike damage, vulnerable
    damage, and damage over time. Standalone powers remain independent factors.
    Probability weighting belongs outside this function so correlated critical and
    vulnerable states are not silently treated as independent.
    """
    weapon_damage = _finite(weapon_damage, "weapon_damage")
    skill_coefficient = _finite(skill_coefficient, "skill_coefficient")
    main_stat = _finite(main_stat, "main_stat")
    main_stat_divisor = _finite(main_stat_divisor, "main_stat_divisor")
    additive_bonus = _finite(additive_bonus, "additive_bonus")
    all_damage_bucket_bonus = _finite(
        all_damage_bucket_bonus, "all_damage_bucket_bonus"
    )
    enemy_damage_factor = _finite(enemy_damage_factor, "enemy_damage_factor")
    critical_base_factor = _finite(critical_base_factor, "critical_base_factor")
    critical_bucket_bonus = _finite(critical_bucket_bonus, "critical_bucket_bonus")
    vulnerable_base_factor = _finite(vulnerable_base_factor, "vulnerable_base_factor")
    vulnerable_bucket_bonus = _finite(
        vulnerable_bucket_bonus, "vulnerable_bucket_bonus"
    )
    dot_bucket_bonus = _finite(dot_bucket_bonus, "dot_bucket_bonus")

    if weapon_damage < 0 or skill_coefficient < 0 or main_stat < 0:
        raise ValueError("damage inputs must be non-negative")
    if main_stat_divisor <= 0:
        raise ValueError("main_stat_divisor must be greater than zero")
    if additive_bonus < -1 or enemy_damage_factor < 0:
        raise ValueError("damage inputs cannot produce a negative factor")
    if is_dot and is_critical:
        raise ValueError("damage-over-time branches cannot be critical")

    bucket_bonuses = (
        all_damage_bucket_bonus,
        critical_bucket_bonus,
        vulnerable_bucket_bonus,
        dot_bucket_bonus,
    )
    if any(value < -1 for value in bucket_bonuses):
        raise ValueError("a multiplier bucket bonus cannot be less than -100%")
    if critical_base_factor < 0 or vulnerable_base_factor < 0:
        raise ValueError("base critical/vulnerable factors must be non-negative")

    factors = tuple(
        _finite(value, f"independent_multipliers[{index}]")
        for index, value in enumerate(independent_multipliers)
    )
    if any(value < 0 for value in factors):
        raise ValueError("independent multipliers must be non-negative")

    result = (
        weapon_damage
        * skill_coefficient
        * (1 + main_stat / main_stat_divisor)
        * (1 + additive_bonus)
        * multiplier_bucket_factor((all_damage_bucket_bonus,))
        * math.prod(factors)
        * enemy_damage_factor
    )
    if is_critical:
        result *= critical_base_factor * multiplier_bucket_factor(
            (critical_bucket_bonus,)
        )
    if is_vulnerable:
        result *= vulnerable_base_factor * multiplier_bucket_factor(
            (vulnerable_bucket_bonus,)
        )
    if is_dot:
        result *= multiplier_bucket_factor((dot_bucket_bonus,))
    return _finite(result, "calculated season13_damage_branch")


def stack_damage_reductions(reductions: Iterable[float]) -> float:
    """Stack independent damage reductions multiplicatively."""
    reductions = tuple(
        _finite(value, f"reductions[{index}]") for index, value in enumerate(reductions)
    )
    if any(not 0 <= reduction < 1 for reduction in reductions):
        raise ValueError("each damage reduction must be in [0, 1)")
    return 1 - math.prod(1 - reduction for reduction in reductions)


def effective_health(life_and_absorption: float, total_damage_reduction: float) -> float:
    """Return EHP against a declared damage type and active reduction set."""
    life_and_absorption = _finite(life_and_absorption, "life_and_absorption")
    total_damage_reduction = _finite(total_damage_reduction, "total_damage_reduction")
    if life_and_absorption < 0:
        raise ValueError("life_and_absorption must be non-negative")
    if not 0 <= total_damage_reduction < 1:
        raise ValueError("total_damage_reduction must be in [0, 1)")
    return _finite(
        life_and_absorption / (1 - total_damage_reduction),
        "calculated effective_health",
    )
