from __future__ import annotations

import copy
import math
import re
from typing import Any

from .calculations import (
    effective_health,
    expected_chained_attacks,
    multiplier_bucket_factor,
    season13_damage_branch,
    stack_damage_reductions,
)


def _finite_number(value: Any, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return result


def _probability(value: Any, name: str) -> float:
    result = _finite_number(value, name, minimum=0)
    if result > 1:
        raise ValueError(f"{name} must be at most 1")
    return result


def _required_text(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _calculate_legacy_damage_event(ledger: dict[str, Any]) -> dict[str, Any]:
    """Preserve the pre-bucket approximation only for explicitly legacy ledgers."""
    ruleset = _required_text(ledger, "ruleset")
    scenario = _required_text(ledger, "scenario")
    event = _required_text(ledger, "event")
    weapon_damage = _finite_number(
        ledger.get("weapon_damage", ledger.get("base_damage")),
        "weapon_damage",
        minimum=0,
    )
    if "weapon_damage" in ledger and "base_damage" in ledger:
        legacy_base_damage = _finite_number(ledger["base_damage"], "base_damage", minimum=0)
        if not math.isclose(weapon_damage, legacy_base_damage):
            raise ValueError("weapon_damage and base_damage must match when both are provided")
    coefficient = _finite_number(ledger.get("skill_coefficient"), "skill_coefficient", minimum=0)
    additive_bonus = _finite_number(ledger.get("additive_bonus", 0), "additive_bonus", minimum=-1)
    resource_uptime = _probability(ledger.get("resource_uptime", 1), "resource_uptime")
    casts_per_second = _finite_number(ledger.get("casts_per_second", 0), "casts_per_second", minimum=0)

    expected_independent_factor = 1.0
    ceiling_independent_factor = 1.0
    factor_breakdown: list[dict[str, Any]] = []
    ledger_confidence = _probability(ledger.get("confidence", 1), "confidence")
    confidences = [ledger_confidence]
    factor_ids: set[str] = set()
    for index, multiplier in enumerate(ledger.get("multipliers", [])):
        factor = _finite_number(multiplier.get("factor"), f"multipliers[{index}].factor", minimum=0)
        uptime = _probability(multiplier.get("uptime", 1), f"multipliers[{index}].uptime")
        confidence = _probability(
            multiplier.get("confidence", 1), f"multipliers[{index}].confidence"
        )
        active = _boolean(multiplier.get("active", True), f"multipliers[{index}].active")
        eligible = _boolean(
            multiplier.get("eligible", uptime > 0), f"multipliers[{index}].eligible"
        ) and uptime > 0
        factor_id = str(multiplier.get("id", f"factor_{index}"))
        if factor_id in factor_ids:
            raise ValueError(f"duplicate multiplier id: {factor_id}")
        factor_ids.add(factor_id)
        expected_factor = 1 + uptime * (factor - 1) if active and eligible else 1.0
        ceiling_factor = factor if active and eligible else 1.0
        expected_independent_factor *= expected_factor
        ceiling_independent_factor *= ceiling_factor
        if active and eligible:
            confidences.append(confidence)
        factor_breakdown.append(
            {
                "id": factor_id,
                "factor": factor,
                "uptime": uptime,
                "confidence": confidence,
                "active": active,
                "eligible": eligible,
                "expected_factor": expected_factor,
                "ceiling_factor": ceiling_factor,
            }
        )

    crit = ledger.get("crit", {})
    crit_chance = _probability(crit.get("chance", 0), "crit.chance")
    crit_factor = _finite_number(crit.get("factor", 1), "crit.factor", minimum=0)
    crit_eligible = _boolean(crit.get("eligible", crit_chance > 0), "crit.eligible") and crit_chance > 0
    crit_confidence = _probability(crit.get("confidence", 1), "crit.confidence")
    confidences.append(crit_confidence)
    expected_crit_factor = 1 + crit_chance * (crit_factor - 1) if crit_eligible else 1.0
    ceiling_crit_factor = crit_factor if crit_eligible else 1.0

    vulnerable = ledger.get("vulnerable", {})
    vulnerable_uptime = _probability(vulnerable.get("uptime", 0), "vulnerable.uptime")
    vulnerable_factor = _finite_number(
        vulnerable.get("factor", 1), "vulnerable.factor", minimum=0
    )
    vulnerable_eligible = _boolean(
        vulnerable.get("eligible", vulnerable_uptime > 0), "vulnerable.eligible"
    ) and vulnerable_uptime > 0
    vulnerable_confidence = _probability(
        vulnerable.get("confidence", 1), "vulnerable.confidence"
    )
    confidences.append(vulnerable_confidence)
    expected_vulnerable_factor = (
        1 + vulnerable_uptime * (vulnerable_factor - 1)
        if vulnerable_eligible
        else 1.0
    )
    ceiling_vulnerable_factor = vulnerable_factor if vulnerable_eligible else 1.0

    repeat = ledger.get("repeat", {})
    repeat_probability = _probability(repeat.get("probability", 0), "repeat.probability")
    max_extra_attacks = repeat.get("max_extra_attacks", 0)
    if isinstance(max_extra_attacks, bool) or not isinstance(max_extra_attacks, int) or max_extra_attacks < 0:
        raise ValueError("repeat.max_extra_attacks must be a non-negative integer")
    repeat_confidence = _probability(repeat.get("confidence", 1), "repeat.confidence")
    confidences.append(repeat_confidence)

    base_hit = _finite_number(
        weapon_damage * coefficient * (1 + additive_bonus), "calculated base_hit", minimum=0
    )
    expected_single_hit = _finite_number(
        base_hit
        * expected_independent_factor
        * expected_crit_factor
        * expected_vulnerable_factor,
        "calculated expected_single_hit",
        minimum=0,
    )
    theoretical_single_hit = _finite_number(
        base_hit
        * ceiling_independent_factor
        * ceiling_crit_factor
        * ceiling_vulnerable_factor,
        "calculated theoretical_single_hit",
        minimum=0,
    )
    expected_attacks = expected_chained_attacks(repeat_probability, max_extra_attacks)
    expected_per_cast = _finite_number(
        expected_single_hit * expected_attacks, "calculated expected_damage_per_cast", minimum=0
    )
    sustained_dps = _finite_number(
        expected_per_cast * casts_per_second * resource_uptime,
        "calculated sustained_dps",
        minimum=0,
    )

    return {
        "damage_model": "legacy-independent-v0",
        "precision": "legacy_approximation",
        "warnings": [
            "legacy-independent-v0 cannot represent Season 13 same-bucket dilution or "
            "crit/vulnerable-only additive damage"
        ],
        "ruleset": ruleset,
        "scenario": scenario,
        "event": event,
        "base_hit": base_hit,
        "expected_single_hit": expected_single_hit,
        "theoretical_single_hit": theoretical_single_hit,
        "expected_attacks_per_cast": expected_attacks,
        "expected_damage_per_cast": expected_per_cast,
        "sustained_dps": sustained_dps,
        "expected_independent_factor": expected_independent_factor,
        "ceiling_independent_factor": ceiling_independent_factor,
        "expected_crit_factor": expected_crit_factor,
        "expected_vulnerable_factor": expected_vulnerable_factor,
        "factor_breakdown": factor_breakdown,
        "inputs": {
            "weapon_damage": weapon_damage,
            "base_damage": weapon_damage,
            "skill_coefficient": coefficient,
            "additive_bonus": additive_bonus,
            "multipliers": factor_breakdown,
            "crit": {
                "chance": crit_chance,
                "factor": crit_factor,
                "eligible": crit_eligible,
                "confidence": crit_confidence,
            },
            "vulnerable": {
                "uptime": vulnerable_uptime,
                "factor": vulnerable_factor,
                "eligible": vulnerable_eligible,
                "confidence": vulnerable_confidence,
            },
            "repeat": {
                "probability": repeat_probability,
                "max_extra_attacks": max_extra_attacks,
                "confidence": repeat_confidence,
            },
            "casts_per_second": casts_per_second,
            "resource_uptime": resource_uptime,
            "confidence": ledger_confidence,
        },
        "confidence": min(confidences),
    }


_SEASON13_BUCKETS = (
    "all_damage",
    "critical_strike",
    "vulnerable",
    "damage_over_time",
)


def _season13_multiplier_buckets(
    ledger: dict[str, Any], confidences: list[float]
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    raw_buckets = ledger.get("multiplier_buckets")
    if not isinstance(raw_buckets, dict):
        raise ValueError("multiplier_buckets must be an object")
    unknown = sorted(set(raw_buckets) - set(_SEASON13_BUCKETS))
    if unknown:
        raise ValueError(f"unknown Season 13 multiplier bucket(s): {', '.join(unknown)}")

    totals: dict[str, float] = {}
    breakdown: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    for bucket_name in _SEASON13_BUCKETS:
        sources = raw_buckets.get(bucket_name, [])
        if not isinstance(sources, list):
            raise ValueError(f"multiplier_buckets.{bucket_name} must be an array")
        total = 0.0
        normalized_sources = []
        for index, source in enumerate(sources):
            if not isinstance(source, dict):
                raise ValueError(
                    f"multiplier_buckets.{bucket_name}[{index}] must be an object"
                )
            source_id = _required_text(source, "id")
            if source_id in source_ids:
                raise ValueError(f"duplicate multiplier bucket source id: {source_id}")
            source_ids.add(source_id)
            bonus = _finite_number(
                source.get("bonus"),
                f"multiplier_buckets.{bucket_name}[{index}].bonus",
                minimum=-1,
            )
            confidence = _probability(
                source.get("confidence", 1),
                f"multiplier_buckets.{bucket_name}[{index}].confidence",
            )
            active = _boolean(
                source.get("active", True),
                f"multiplier_buckets.{bucket_name}[{index}].active",
            )
            eligible = _boolean(
                source.get("eligible", True),
                f"multiplier_buckets.{bucket_name}[{index}].eligible",
            )
            included = active and eligible
            if included:
                total += bonus
                confidences.append(confidence)
            normalized_sources.append(
                {
                    "id": source_id,
                    "bonus": bonus,
                    "confidence": confidence,
                    "active": active,
                    "eligible": eligible,
                    "included": included,
                }
            )
        factor = multiplier_bucket_factor((total,))
        totals[bucket_name] = total
        breakdown.append(
            {
                "id": bucket_name,
                "bonus": total,
                "factor": factor,
                "sources": normalized_sources,
            }
        )
    return totals, breakdown


def _season13_standalone_multipliers(
    ledger: dict[str, Any], confidences: list[float]
) -> tuple[float, float, list[dict[str, Any]], bool]:
    if "multipliers" in ledger:
        raise ValueError(
            "season13-buckets-v1 uses standalone_multipliers; ambiguous multipliers are rejected"
        )
    sources = ledger.get("standalone_multipliers", [])
    if not isinstance(sources, list):
        raise ValueError("standalone_multipliers must be an array")
    expected_product = 1.0
    ceiling_product = 1.0
    breakdown = []
    source_ids: set[str] = set()
    probabilistic_count = 0
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(f"standalone_multipliers[{index}] must be an object")
        source_id = _required_text(source, "id")
        if source_id in source_ids:
            raise ValueError(f"duplicate standalone multiplier id: {source_id}")
        source_ids.add(source_id)
        factor = _finite_number(
            source.get("factor"), f"standalone_multipliers[{index}].factor", minimum=0
        )
        uptime = _probability(
            source.get("uptime", 1), f"standalone_multipliers[{index}].uptime"
        )
        confidence = _probability(
            source.get("confidence", 1),
            f"standalone_multipliers[{index}].confidence",
        )
        active = _boolean(
            source.get("active", True), f"standalone_multipliers[{index}].active"
        )
        eligible = _boolean(
            source.get("eligible", uptime > 0),
            f"standalone_multipliers[{index}].eligible",
        ) and uptime > 0
        expected_factor = 1 + uptime * (factor - 1) if active and eligible else 1.0
        ceiling_factor = factor if active and eligible else 1.0
        expected_product *= expected_factor
        ceiling_product *= ceiling_factor
        if active and eligible:
            confidences.append(confidence)
            if 0 < uptime < 1:
                probabilistic_count += 1
        breakdown.append(
            {
                "id": source_id,
                "factor": factor,
                "uptime": uptime,
                "confidence": confidence,
                "active": active,
                "eligible": eligible,
                "expected_factor": expected_factor,
                "ceiling_factor": ceiling_factor,
            }
        )
    return expected_product, ceiling_product, breakdown, probabilistic_count > 0


def _joint_direct_probabilities(
    ledger: dict[str, Any], *, crit_chance: float, vulnerable_uptime: float
) -> tuple[dict[str, float], str]:
    raw = ledger.get("joint_probabilities")
    keys = (
        "noncrit_nonvulnerable",
        "crit_nonvulnerable",
        "noncrit_vulnerable",
        "crit_vulnerable",
    )
    if raw is None:
        probability_model = (
            "crit_vulnerable_independence"
            if 0 < crit_chance < 1 and 0 < vulnerable_uptime < 1
            else "marginals_without_correlation_ambiguity"
        )
        return (
            {
                "noncrit_nonvulnerable": (1 - crit_chance) * (1 - vulnerable_uptime),
                "crit_nonvulnerable": crit_chance * (1 - vulnerable_uptime),
                "noncrit_vulnerable": (1 - crit_chance) * vulnerable_uptime,
                "crit_vulnerable": crit_chance * vulnerable_uptime,
            },
            probability_model,
        )
    if not isinstance(raw, dict) or set(raw) != set(keys):
        raise ValueError(f"joint_probabilities must contain exactly: {', '.join(keys)}")
    probabilities = {
        key: _probability(raw[key], f"joint_probabilities.{key}") for key in keys
    }
    if not math.isclose(math.fsum(probabilities.values()), 1.0, abs_tol=1e-9):
        raise ValueError("joint_probabilities must sum to 1")
    observed_crit = probabilities["crit_nonvulnerable"] + probabilities["crit_vulnerable"]
    observed_vulnerable = (
        probabilities["noncrit_vulnerable"] + probabilities["crit_vulnerable"]
    )
    if not math.isclose(observed_crit, crit_chance, abs_tol=1e-9):
        raise ValueError("joint_probabilities do not match crit.chance")
    if not math.isclose(observed_vulnerable, vulnerable_uptime, abs_tol=1e-9):
        raise ValueError("joint_probabilities do not match vulnerable.uptime")
    return probabilities, "explicit_joint_probabilities"


def _calculate_season13_damage_event(ledger: dict[str, Any]) -> dict[str, Any]:
    ruleset = _required_text(ledger, "ruleset")
    scenario = _required_text(ledger, "scenario")
    event = _required_text(ledger, "event")
    damage_kind = ledger.get("damage_kind", "direct")
    if damage_kind not in {"direct", "dot"}:
        raise ValueError("damage_kind must be direct or dot")

    weapon_damage = _finite_number(
        ledger.get("weapon_damage"), "weapon_damage", minimum=0
    )
    coefficient = _finite_number(
        ledger.get("skill_coefficient"), "skill_coefficient", minimum=0
    )
    enemy_damage_factor = _finite_number(
        ledger.get("enemy_damage_factor"), "enemy_damage_factor", minimum=0
    )
    main_stat_input = ledger.get("main_stat")
    if not isinstance(main_stat_input, dict):
        raise ValueError("main_stat must be an object with value and divisor")
    main_stat = _finite_number(main_stat_input.get("value"), "main_stat.value", minimum=0)
    main_stat_divisor = _finite_number(
        main_stat_input.get("divisor"), "main_stat.divisor", minimum=0
    )
    if main_stat_divisor == 0:
        raise ValueError("main_stat.divisor must be greater than zero")
    main_stat_factor = 1 + main_stat / main_stat_divisor

    additive_input = ledger.get("additive")
    if not isinstance(additive_input, dict):
        raise ValueError("additive must be an object")
    additive = {
        key: _finite_number(additive_input.get(key, 0), f"additive.{key}", minimum=-1)
        for key in ("always", "crit_only", "vulnerable_only", "dot_only")
    }
    if any(value < 0 for key, value in additive.items() if key != "always"):
        raise ValueError("conditional additive bonuses must be non-negative")

    ledger_confidence = _probability(ledger.get("confidence", 1), "confidence")
    confidences = [ledger_confidence]
    bucket_totals, bucket_breakdown = _season13_multiplier_buckets(ledger, confidences)
    (
        expected_independent_factor,
        ceiling_independent_factor,
        factor_breakdown,
        assumes_independent_standalone_uptimes,
    ) = _season13_standalone_multipliers(ledger, confidences)

    crit_input = ledger.get("crit", {})
    if not isinstance(crit_input, dict):
        raise ValueError("crit must be an object")
    crit_chance = _probability(crit_input.get("chance", 0), "crit.chance")
    crit_base_factor = _finite_number(
        crit_input.get("base_factor"), "crit.base_factor", minimum=0
    )
    crit_eligible = _boolean(
        crit_input.get("eligible", crit_chance > 0), "crit.eligible"
    ) and crit_chance > 0
    crit_confidence = _probability(crit_input.get("confidence", 1), "crit.confidence")
    confidences.append(crit_confidence)
    if not crit_eligible and crit_chance != 0:
        raise ValueError("crit.chance must be 0 when crit is ineligible")

    vulnerable_input = ledger.get("vulnerable", {})
    if not isinstance(vulnerable_input, dict):
        raise ValueError("vulnerable must be an object")
    vulnerable_uptime = _probability(
        vulnerable_input.get("uptime", 0), "vulnerable.uptime"
    )
    vulnerable_base_factor = _finite_number(
        vulnerable_input.get("base_factor"), "vulnerable.base_factor", minimum=0
    )
    vulnerable_eligible = _boolean(
        vulnerable_input.get("eligible", vulnerable_uptime > 0), "vulnerable.eligible"
    ) and vulnerable_uptime > 0
    vulnerable_confidence = _probability(
        vulnerable_input.get("confidence", 1), "vulnerable.confidence"
    )
    confidences.append(vulnerable_confidence)
    if not vulnerable_eligible and vulnerable_uptime != 0:
        raise ValueError("vulnerable.uptime must be 0 when vulnerable is ineligible")

    if damage_kind == "dot":
        if crit_chance or bucket_totals["critical_strike"] or additive["crit_only"]:
            raise ValueError("DoT ledgers cannot contain active critical damage inputs")
    elif bucket_totals["damage_over_time"] or additive["dot_only"]:
        raise ValueError("direct-hit ledgers cannot contain active damage-over-time inputs")

    assumptions = []
    branches = []
    if damage_kind == "direct":
        probabilities, probability_model = _joint_direct_probabilities(
            ledger,
            crit_chance=crit_chance,
            vulnerable_uptime=vulnerable_uptime,
        )
        if probability_model == "crit_vulnerable_independence":
            assumptions.append(probability_model)
        branch_states = (
            ("noncrit_nonvulnerable", False, False),
            ("crit_nonvulnerable", True, False),
            ("noncrit_vulnerable", False, True),
            ("crit_vulnerable", True, True),
        )
    else:
        if "joint_probabilities" in ledger:
            raise ValueError("DoT ledgers do not use joint_probabilities")
        probabilities = {
            "dot_nonvulnerable": 1 - vulnerable_uptime,
            "dot_vulnerable": vulnerable_uptime,
        }
        probability_model = "vulnerable_marginal"
        branch_states = (
            ("dot_nonvulnerable", False, False),
            ("dot_vulnerable", False, True),
        )

    for branch_id, is_critical, is_vulnerable in branch_states:
        branch_additive = (
            additive["always"]
            + (additive["crit_only"] if is_critical else 0)
            + (additive["vulnerable_only"] if is_vulnerable else 0)
            + (additive["dot_only"] if damage_kind == "dot" else 0)
        )
        damage = season13_damage_branch(
            weapon_damage=weapon_damage,
            skill_coefficient=coefficient,
            main_stat=main_stat,
            main_stat_divisor=main_stat_divisor,
            additive_bonus=branch_additive,
            all_damage_bucket_bonus=bucket_totals["all_damage"],
            independent_multipliers=(expected_independent_factor,),
            enemy_damage_factor=enemy_damage_factor,
            is_critical=is_critical,
            critical_base_factor=crit_base_factor,
            critical_bucket_bonus=bucket_totals["critical_strike"],
            is_vulnerable=is_vulnerable,
            vulnerable_base_factor=vulnerable_base_factor,
            vulnerable_bucket_bonus=bucket_totals["vulnerable"],
            is_dot=damage_kind == "dot",
            dot_bucket_bonus=bucket_totals["damage_over_time"],
        )
        branches.append(
            {
                "id": branch_id,
                "probability": probabilities[branch_id],
                "is_critical": is_critical,
                "is_vulnerable": is_vulnerable,
                "additive_bonus": branch_additive,
                "damage": damage,
            }
        )

    expected_single_hit = _finite_number(
        math.fsum(branch["probability"] * branch["damage"] for branch in branches),
        "calculated expected_single_hit",
        minimum=0,
    )
    ceiling_is_critical = damage_kind == "direct" and crit_eligible
    ceiling_is_vulnerable = vulnerable_eligible
    ceiling_additive = (
        additive["always"]
        + (additive["crit_only"] if ceiling_is_critical else 0)
        + (additive["vulnerable_only"] if ceiling_is_vulnerable else 0)
        + (additive["dot_only"] if damage_kind == "dot" else 0)
    )
    theoretical_single_hit = season13_damage_branch(
        weapon_damage=weapon_damage,
        skill_coefficient=coefficient,
        main_stat=main_stat,
        main_stat_divisor=main_stat_divisor,
        additive_bonus=ceiling_additive,
        all_damage_bucket_bonus=bucket_totals["all_damage"],
        independent_multipliers=(ceiling_independent_factor,),
        enemy_damage_factor=enemy_damage_factor,
        is_critical=ceiling_is_critical,
        critical_base_factor=crit_base_factor,
        critical_bucket_bonus=bucket_totals["critical_strike"],
        is_vulnerable=ceiling_is_vulnerable,
        vulnerable_base_factor=vulnerable_base_factor,
        vulnerable_bucket_bonus=bucket_totals["vulnerable"],
        is_dot=damage_kind == "dot",
        dot_bucket_bonus=bucket_totals["damage_over_time"],
    )

    if assumes_independent_standalone_uptimes:
        assumptions.append("standalone_multiplier_uptime_independence")
    repeat = ledger.get("repeat", {})
    if not isinstance(repeat, dict):
        raise ValueError("repeat must be an object")
    repeat_probability = _probability(repeat.get("probability", 0), "repeat.probability")
    max_extra_attacks = repeat.get("max_extra_attacks", 0)
    if (
        isinstance(max_extra_attacks, bool)
        or not isinstance(max_extra_attacks, int)
        or max_extra_attacks < 0
    ):
        raise ValueError("repeat.max_extra_attacks must be a non-negative integer")
    repeat_confidence = _probability(repeat.get("confidence", 1), "repeat.confidence")
    confidences.append(repeat_confidence)
    expected_attacks = expected_chained_attacks(repeat_probability, max_extra_attacks)
    casts_per_second = _finite_number(
        ledger.get("casts_per_second", 0), "casts_per_second", minimum=0
    )
    resource_uptime = _probability(ledger.get("resource_uptime", 1), "resource_uptime")
    expected_per_cast = expected_single_hit * expected_attacks
    sustained_dps = expected_per_cast * casts_per_second * resource_uptime
    base_hit = weapon_damage * coefficient * main_stat_factor * enemy_damage_factor

    expected_crit_factor = (
        1
        + crit_chance
        * (
            crit_base_factor
            * multiplier_bucket_factor((bucket_totals["critical_strike"],))
            - 1
        )
        if damage_kind == "direct"
        else 1.0
    )
    expected_vulnerable_factor = 1 + vulnerable_uptime * (
        vulnerable_base_factor
        * multiplier_bucket_factor((bucket_totals["vulnerable"],))
        - 1
    )
    return {
        "damage_model": "season13-buckets-v1",
        "precision": (
            "conditional_expectation_with_declared_independence"
            if assumptions
            else "branch_exact_for_declared_inputs"
        ),
        "ruleset": ruleset,
        "scenario": scenario,
        "event": event,
        "damage_kind": damage_kind,
        "base_hit": base_hit,
        "expected_single_hit": expected_single_hit,
        "theoretical_single_hit": theoretical_single_hit,
        "expected_attacks_per_cast": expected_attacks,
        "expected_damage_per_cast": expected_per_cast,
        "sustained_dps": sustained_dps,
        "expected_independent_factor": expected_independent_factor,
        "ceiling_independent_factor": ceiling_independent_factor,
        "expected_crit_factor": expected_crit_factor,
        "expected_vulnerable_factor": expected_vulnerable_factor,
        "factor_breakdown": factor_breakdown,
        "bucket_breakdown": bucket_breakdown,
        "branches": branches,
        "probability_model": probability_model,
        "assumptions": assumptions,
        "warnings": [],
        "inputs": {
            "weapon_damage": weapon_damage,
            "skill_coefficient": coefficient,
            "main_stat": {"value": main_stat, "divisor": main_stat_divisor},
            "main_stat_factor": main_stat_factor,
            "enemy_damage_factor": enemy_damage_factor,
            "additive": additive,
            "multiplier_buckets": bucket_breakdown,
            "standalone_multipliers": factor_breakdown,
            "crit": {
                "chance": crit_chance,
                "base_factor": crit_base_factor,
                "eligible": crit_eligible,
                "confidence": crit_confidence,
            },
            "vulnerable": {
                "uptime": vulnerable_uptime,
                "base_factor": vulnerable_base_factor,
                "eligible": vulnerable_eligible,
                "confidence": vulnerable_confidence,
            },
            "repeat": {
                "probability": repeat_probability,
                "max_extra_attacks": max_extra_attacks,
                "confidence": repeat_confidence,
            },
            "casts_per_second": casts_per_second,
            "resource_uptime": resource_uptime,
            "confidence": ledger_confidence,
        },
        "confidence": min(confidences),
    }


def calculate_damage_event(ledger: dict[str, Any]) -> dict[str, Any]:
    """Reduce one versioned damage ledger with an explicitly selected model."""
    damage_model = ledger.get("damage_model")
    if damage_model == "season13-buckets-v1":
        return _calculate_season13_damage_event(ledger)
    if damage_model == "legacy-independent-v0":
        return _calculate_legacy_damage_event(ledger)
    raise ValueError(
        "damage_model is required; use season13-buckets-v1 for current calculations"
    )


def _delta(before: float, after: float) -> dict[str, float | None]:
    absolute = after - before
    return {
        "absolute": absolute,
        "percent": absolute / before * 100 if before != 0 else None,
    }


def _relative_changes(
    values_a: dict[str, float], values_b: dict[str, float],
) -> list[dict[str, float | str | None]]:
    changes = []
    for value_id in sorted(set(values_a) | set(values_b)):
        value_a = values_a.get(value_id, 1.0)
        value_b = values_b.get(value_id, 1.0)
        if math.isclose(value_a, value_b):
            continue
        changes.append(
            {
                "id": value_id,
                "a": value_a,
                "b": value_b,
                "relative_gain_percent": (value_b / value_a - 1) * 100
                if value_a != 0
                else None,
            }
        )
    changes.sort(
        key=lambda item: -(
            abs(item["relative_gain_percent"])
            if item["relative_gain_percent"] is not None
            else math.inf
        )
    )
    return changes


def _component_factors(result: dict[str, Any]) -> dict[str, float]:
    inputs = result["inputs"]
    if result.get("damage_model") == "season13-buckets-v1":
        bucket_factors = {
            f"bucket:{bucket['id']}": bucket["factor"]
            for bucket in result["bucket_breakdown"]
        }
        return {
            "weapon_damage": inputs["weapon_damage"],
            "skill_coefficient": inputs["skill_coefficient"],
            "main_stat_factor": inputs["main_stat_factor"],
            "enemy_damage_factor": inputs["enemy_damage_factor"],
            **bucket_factors,
            "independent_factor": result["expected_independent_factor"],
            "attacks_per_cast": result["expected_attacks_per_cast"],
            "casts_per_second": inputs["casts_per_second"],
            "resource_uptime": inputs["resource_uptime"],
        }
    return {
        "weapon_damage": inputs["weapon_damage"],
        "skill_coefficient": inputs["skill_coefficient"],
        "additive_pool_factor": 1 + inputs["additive_bonus"],
        "independent_factor": result["expected_independent_factor"],
        "critical_factor": result["expected_crit_factor"],
        "vulnerable_factor": result["expected_vulnerable_factor"],
        "attacks_per_cast": result["expected_attacks_per_cast"],
        "casts_per_second": inputs["casts_per_second"],
        "resource_uptime": inputs["resource_uptime"],
    }


def _defense_state(state: dict[str, Any], name: str) -> dict[str, float]:
    life = _finite_number(state.get("life"), f"{name}.life", minimum=0)
    barrier = _finite_number(state.get("barrier", 0), f"{name}.barrier", minimum=0)
    reductions = []
    for index, raw_reduction in enumerate(state.get("reductions", [])):
        reduction = _finite_number(
            raw_reduction, f"{name}.reductions[{index}]", minimum=0
        )
        if reduction >= 1:
            raise ValueError(f"{name}.reductions[{index}] must be less than 1")
        reductions.append(reduction)
    total_reduction = stack_damage_reductions(reductions)
    return {
        "life": life,
        "barrier": barrier,
        "total_damage_reduction": total_reduction,
        "effective_health": effective_health(life + barrier, total_reduction),
    }


def compare_loadouts(payload: dict[str, Any]) -> dict[str, Any]:
    """Compare A/B ledgers with identical scenario semantics."""
    scenario_results: dict[str, Any] = {}
    metrics = (
        "base_hit",
        "expected_single_hit",
        "theoretical_single_hit",
        "expected_damage_per_cast",
        "sustained_dps",
    )
    for scenario_name, pair in payload.get("scenarios", {}).items():
        for context_field in ("damage_model", "ruleset", "scenario", "event", "damage_kind"):
            if pair["a"].get(context_field) != pair["b"].get(context_field):
                raise ValueError(f"A/B must use the same {context_field}")
        a_result = calculate_damage_event(pair["a"])
        b_result = calculate_damage_event(pair["b"])
        a_factors = {
            item["id"]: item["expected_factor"] for item in a_result["factor_breakdown"]
        }
        b_factors = {
            item["id"]: item["expected_factor"] for item in b_result["factor_breakdown"]
        }
        for bucket in a_result.get("bucket_breakdown", []):
            a_factors[f"bucket:{bucket['id']}"] = bucket["factor"]
        for bucket in b_result.get("bucket_breakdown", []):
            b_factors[f"bucket:{bucket['id']}"] = bucket["factor"]
        factor_changes = [
            {
                "id": change["id"],
                "a_expected_factor": change["a"],
                "b_expected_factor": change["b"],
                "relative_gain_percent": change["relative_gain_percent"],
            }
            for change in _relative_changes(a_factors, b_factors)
        ]
        scenario_results[scenario_name] = {
            "a": a_result,
            "b": b_result,
            "deltas": {metric: _delta(a_result[metric], b_result[metric]) for metric in metrics},
            "factor_changes": factor_changes,
            "component_changes": _relative_changes(
                _component_factors(a_result), _component_factors(b_result)
            ),
        }

    defense_results: dict[str, Any] = {}
    for damage_type, pair in payload.get("defense", {}).items():
        a_state = _defense_state(pair["a"], f"defense.{damage_type}.a")
        b_state = _defense_state(pair["b"], f"defense.{damage_type}.b")
        defense_results[damage_type] = {
            "a": a_state,
            "b": b_state,
            "deltas": {
                "effective_health": _delta(
                    a_state["effective_health"], b_state["effective_health"]
                ),
                "life": _delta(a_state["life"], b_state["life"]),
            },
        }

    breakpoint_results: dict[str, Any] = {}
    for breakpoint_name, definition in payload.get("breakpoints", {}).items():
        value_a = _finite_number(definition.get("a"), f"breakpoints.{breakpoint_name}.a")
        value_b = _finite_number(definition.get("b"), f"breakpoints.{breakpoint_name}.b")
        thresholds = sorted(
            _finite_number(value, f"breakpoints.{breakpoint_name}.thresholds[{index}]")
            for index, value in enumerate(definition.get("thresholds", []))
        )
        tier_a = sum(value_a >= threshold for threshold in thresholds)
        tier_b = sum(value_b >= threshold for threshold in thresholds)
        breakpoint_results[breakpoint_name] = {
            "a": value_a,
            "b": value_b,
            "tier_a": tier_a,
            "tier_b": tier_b,
            "crossed": tier_a != tier_b,
            "thresholds": thresholds,
        }

    return {
        "scenarios": scenario_results,
        "defense": defense_results,
        "breakpoints": breakpoint_results,
    }


def _nested_value(values: dict[str, Any], dotted_path: str) -> Any:
    current: Any = values
    for segment in dotted_path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def _deep_overlay(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_overlay(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _breakpoint_states(
    stats: dict[str, Any],
    definitions: dict[str, Any],
    *,
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for name, definition in definitions.items():
        metric = _required_text(definition, "metric")
        thresholds = sorted(
            _finite_number(value, f"breakpoints.{name}.thresholds[{index}]")
            for index, value in enumerate(definition.get("thresholds", []))
        )
        raw_value = _nested_value(stats, metric)
        if raw_value is None:
            result: dict[str, Any] = {
                "metric": metric,
                "status": "missing",
                "value": None,
                "tier": None,
                "next_threshold": None,
                "gap_to_next": None,
                "thresholds": thresholds,
            }
        else:
            value = _finite_number(raw_value, metric)
            tier = sum(value >= threshold for threshold in thresholds)
            next_threshold = next((threshold for threshold in thresholds if value < threshold), None)
            result = {
                "metric": metric,
                "status": "known",
                "value": value,
                "tier": tier,
                "next_threshold": next_threshold,
                "gap_to_next": next_threshold - value if next_threshold is not None else None,
                "thresholds": thresholds,
            }
        if baseline is not None:
            baseline_tier = baseline.get(name, {}).get("tier")
            result["crossed_from_current"] = (
                baseline_tier is not None
                and result["tier"] is not None
                and baseline_tier != result["tier"]
            )
        results[name] = result
    return results


def _outcome_delta_percent(current: float, after: float) -> float | None:
    if current == 0:
        return 0.0 if after == 0 else None
    return (after / current - 1) * 100


def _required_roll_value(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    unit = _required_text(value, "unit")
    return {
        "value": _finite_number(value.get("value"), f"{path}.value", minimum=0),
        "unit": unit,
    }


def _required_roll_range(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    result = {
        bound: _finite_number(value.get(bound), f"{path}.{bound}", minimum=0)
        for bound in ("minimum", "expected", "maximum")
    }
    if not result["minimum"] <= result["expected"] <= result["maximum"]:
        raise ValueError(f"{path} requires minimum <= expected <= maximum")
    result["unit"] = _required_text(value, "unit")
    return result


def _contains_nested_value(values: dict[str, Any], dotted_path: str) -> bool:
    current: Any = values
    for segment in dotted_path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return False
        current = current[segment]
    return True


def analyze_enchantment_options(payload: dict[str, Any]) -> dict[str, Any]:
    """Rank legal enchantment replacements from complete before/after outcomes."""
    ruleset = _required_text(payload, "ruleset")
    scenario = _required_text(payload, "scenario")
    profile_fingerprint = _required_text(payload, "profile_fingerprint")
    if re.fullmatch(r"[0-9a-f]{64}", profile_fingerprint) is None:
        raise ValueError("profile_fingerprint must be a lowercase SHA-256 hex digest")
    stats = payload.get("stats", {})
    if not isinstance(stats, dict):
        raise ValueError("stats must be an object")
    breakpoint_definitions = payload.get("breakpoints", {})
    if not isinstance(breakpoint_definitions, dict):
        raise ValueError("breakpoints must be an object")
    baseline_breakpoints = _breakpoint_states(stats, breakpoint_definitions)

    objectives = payload.get("objectives")
    if not isinstance(objectives, dict) or not objectives:
        raise ValueError("objectives must be a non-empty object")
    normalized_objectives: dict[str, dict[str, float]] = {}
    for objective_name, definition in objectives.items():
        if not isinstance(definition, dict) or not isinstance(definition.get("weights"), dict):
            raise ValueError(f"objectives.{objective_name}.weights must be an object")
        raw_weights = {
            metric: _finite_number(
                weight,
                f"objectives.{objective_name}.weights.{metric}",
                minimum=0,
            )
            for metric, weight in definition["weights"].items()
        }
        weight_total = sum(raw_weights.values())
        if not math.isfinite(weight_total) or weight_total <= 0:
            raise ValueError(f"objectives.{objective_name} must have a positive weight")
        normalized_objectives[objective_name] = {
            metric: weight / weight_total for metric, weight in raw_weights.items()
        }

    options = payload.get("options")
    if not isinstance(options, list) or not options:
        raise ValueError("options must be a non-empty array")
    option_results: list[dict[str, Any]] = []
    option_ids: set[str] = set()
    common_confidence = _probability(payload.get("confidence", 1), "confidence")
    candidate_confidences: list[float] = []
    metric_semantics: dict[str, dict[str, Any]] = {}
    for option_index, option in enumerate(options):
        if not isinstance(option, dict):
            raise ValueError(f"options[{option_index}] must be an object")
        option_id = _required_text(option, "id")
        if option_id in option_ids:
            raise ValueError(f"duplicate enchantment option id: {option_id}")
        option_ids.add(option_id)
        slot = _required_text(option, "slot")
        replace_stat = _required_text(option, "replace_stat")
        target_stat = _required_text(option, "target_stat")
        declared_option_confidence = _probability(
            option.get("confidence", 1), f"options[{option_index}].confidence"
        )
        option_confidence = min(common_confidence, declared_option_confidence)
        candidate_confidences.append(option_confidence)
        replace_roll = _required_roll_value(
            option.get("replace_roll"), f"options[{option_index}].replace_roll"
        )
        target_roll = _required_roll_range(
            option.get("target_roll"), f"options[{option_index}].target_roll"
        )
        outcomes = option.get("outcomes")
        if not isinstance(outcomes, dict) or not outcomes:
            raise ValueError(f"options[{option_index}].outcomes must be a non-empty object")

        outcome_results: dict[str, Any] = {}
        for metric, outcome in outcomes.items():
            if not isinstance(outcome, dict) or not isinstance(outcome.get("after"), dict):
                raise ValueError(f"options[{option_index}].outcomes.{metric}.after must be an object")
            current = _finite_number(
                outcome.get("current"),
                f"options[{option_index}].outcomes.{metric}.current",
                minimum=0,
            )
            after = outcome["after"]
            minimum = _finite_number(
                after.get("minimum"),
                f"options[{option_index}].outcomes.{metric}.after.minimum",
                minimum=0,
            )
            expected = _finite_number(
                after.get("expected"),
                f"options[{option_index}].outcomes.{metric}.after.expected",
                minimum=0,
            )
            maximum = _finite_number(
                after.get("maximum"),
                f"options[{option_index}].outcomes.{metric}.after.maximum",
                minimum=0,
            )
            direction = outcome.get("direction", "higher")
            if direction not in {"higher", "lower"}:
                raise ValueError(
                    f"options[{option_index}].outcomes.{metric}.direction must be higher or lower"
                )
            semantics = metric_semantics.get(metric)
            if semantics is None:
                metric_semantics[metric] = {"current": current, "direction": direction}
            else:
                if not math.isclose(current, semantics["current"], rel_tol=1e-12, abs_tol=1e-12):
                    raise ValueError(
                        f"all options for {metric} must use the same current baseline"
                    )
                if direction != semantics["direction"]:
                    raise ValueError(
                        f"all options for {metric} must use the same direction"
                    )
            delta_percents = {
                "minimum": _outcome_delta_percent(current, minimum),
                "expected": _outcome_delta_percent(current, expected),
                "maximum": _outcome_delta_percent(current, maximum),
            }
            sign = 1 if direction == "higher" else -1
            utilities = {
                name: value * sign if value is not None else None
                for name, value in delta_percents.items()
            }
            finite_utilities = [value for value in utilities.values() if value is not None]
            outcome_results[metric] = {
                "current": current,
                "after": {
                    "minimum": minimum,
                    "expected": expected,
                    "maximum": maximum,
                },
                "direction": direction,
                "minimum_delta_percent": delta_percents["minimum"],
                "expected_delta_percent": delta_percents["expected"],
                "maximum_delta_percent": delta_percents["maximum"],
                "expected_absolute_delta": expected - current,
                "minimum_utility": utilities["minimum"],
                "utility_lower_bound": min(finite_utilities) if finite_utilities else None,
                "expected_utility": utilities["expected"],
                "maximum_utility": utilities["maximum"],
                "utility_upper_bound": max(finite_utilities) if finite_utilities else None,
            }

        option_result: dict[str, Any] = {
            "id": option_id,
            "slot": slot,
            "replace_stat": replace_stat,
            "target_stat": target_stat,
            "confidence": option_confidence,
            "outcomes": outcome_results,
            "notes": option.get("notes"),
            "affix_exchange": {
                "lost": {"stat": replace_stat, **replace_roll},
                "gained": {"stat": target_stat, **target_roll},
            },
        }
        if replace_stat == target_stat and replace_roll["unit"] == target_roll["unit"]:
            option_result["affix_exchange"]["net_same_stat"] = {
                bound: target_roll[bound] - replace_roll["value"]
                for bound in ("minimum", "expected", "maximum")
            } | {"unit": target_roll["unit"]}
        after_stats = option.get("after_stats")
        if breakpoint_definitions and not isinstance(after_stats, dict):
            raise ValueError(
                f"options[{option_index}].after_stats must provide complete minimum, expected, "
                "and maximum breakpoint states"
            )
        if after_stats is not None:
            if not isinstance(after_stats, dict):
                raise ValueError(f"options[{option_index}].after_stats must be an object")
            bound_breakpoints: dict[str, Any] = {}
            for bound in ("minimum", "expected", "maximum"):
                bound_stats = after_stats.get(bound)
                if not isinstance(bound_stats, dict):
                    raise ValueError(
                        f"options[{option_index}].after_stats.{bound} must be an object"
                    )
                for breakpoint_name, definition in breakpoint_definitions.items():
                    metric_path = _required_text(definition, "metric")
                    if not _contains_nested_value(bound_stats, metric_path):
                        raise ValueError(
                            f"options[{option_index}].after_stats.{bound} must include "
                            f"breakpoint metric {breakpoint_name}: {metric_path}"
                        )
                bound_breakpoints[bound] = _breakpoint_states(
                    bound_stats,
                    breakpoint_definitions,
                    baseline=baseline_breakpoints,
                )
            option_result["breakpoints"] = bound_breakpoints
        option_result["tradeoffs"] = sorted(
            metric
            for metric, outcome in outcome_results.items()
            if outcome["expected_utility"] is not None and outcome["expected_utility"] < 0
        )
        option_results.append(option_result)

    rankings: dict[str, list[dict[str, Any]]] = {}
    for objective_name, weights in normalized_objectives.items():
        ranked_options = []
        for option in option_results:
            weighted_lower: list[float] = []
            weighted_expected: list[float] = []
            weighted_upper: list[float] = []
            for metric, weight in weights.items():
                if metric not in option["outcomes"]:
                    raise ValueError(
                        f"option {option['id']} is missing outcome required by {objective_name}: {metric}"
                    )
                outcome = option["outcomes"][metric]
                if any(
                    outcome[field] is None
                    for field in (
                        "minimum_utility",
                        "expected_utility",
                        "maximum_utility",
                    )
                ):
                    raise ValueError(
                        f"option {option['id']} outcome {metric} needs a positive current value "
                        "for every non-zero roll bound"
                    )
                weighted_lower.append(weight * outcome["utility_lower_bound"])
                weighted_expected.append(weight * outcome["expected_utility"])
                weighted_upper.append(weight * outcome["utility_upper_bound"])
            ranked_options.append(
                {
                    "id": option["id"],
                    "slot": option["slot"],
                    "replace_stat": option["replace_stat"],
                    "target_stat": option["target_stat"],
                    "score_lower_bound": math.fsum(weighted_lower),
                    "score_expected": math.fsum(weighted_expected),
                    "score_upper_bound": math.fsum(weighted_upper),
                    "confidence": option["confidence"],
                    "tradeoffs": option["tradeoffs"],
                }
            )
        ranked_options.sort(
            key=lambda option: (
                -option["score_expected"],
                -option["score_lower_bound"],
                option["id"],
            )
        )
        rankings[objective_name] = ranked_options

    return {
        "ruleset": ruleset,
        "scenario": scenario,
        "profile_fingerprint": profile_fingerprint,
        "confidence": common_confidence,
        "minimum_candidate_confidence": min(candidate_confidences),
        "objectives": normalized_objectives,
        "metric_semantics": metric_semantics,
        "baseline_breakpoints": baseline_breakpoints,
        "options": option_results,
        "rankings": rankings,
    }


def audit_panel(stats: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    """Turn versioned stat targets into objective gaps for advisor judgement."""
    metric_results: dict[str, Any] = {}
    issues: list[dict[str, Any]] = []
    breakpoint_results = _breakpoint_states(stats, rules.get("breakpoints", {}))
    for metric, rule in rules.get("metrics", {}).items():
        priority = _finite_number(rule.get("priority", 1), f"metrics.{metric}.priority", minimum=0)
        target = _finite_number(rule.get("target"), f"metrics.{metric}.target")
        cap = rule.get("cap")
        cap_value = _finite_number(cap, f"metrics.{metric}.cap") if cap is not None else None
        if cap_value is not None and target > cap_value:
            raise ValueError(f"metrics.{metric}.target cannot exceed cap")
        raw_value = _nested_value(stats, metric)
        result: dict[str, Any] = {
            "category": rule.get("category"),
            "recommendation": rule.get("recommendation"),
            "priority": priority,
            "target": target,
            "cap": cap_value,
        }
        if raw_value is None:
            result.update(
                {"status": "missing", "value": None, "gap": None, "normalized_gap": None}
            )
            severity = priority
        else:
            value = _finite_number(raw_value, metric)
            result["value"] = value
            if cap_value is not None and value > cap_value:
                gap = value - cap_value
                normalized_gap = gap / abs(cap_value) if cap_value else gap
                result.update(
                    {"status": "overcap", "gap": gap, "normalized_gap": normalized_gap}
                )
                severity = normalized_gap * priority
            elif value < target:
                gap = target - value
                normalized_gap = gap / abs(target) if target else gap
                result.update(
                    {
                        "status": "below_target",
                        "gap": gap,
                        "normalized_gap": normalized_gap,
                    }
                )
                severity = normalized_gap * priority
            else:
                result.update({"status": "at_target", "gap": 0.0, "normalized_gap": 0.0})
                severity = 0.0
        result["severity"] = severity
        metric_results[metric] = result
        if result["status"] != "at_target":
            issues.append(
                {
                    "metric": metric,
                    "status": result["status"],
                    "severity": severity,
                    "gap": result["gap"],
                    "normalized_gap": result["normalized_gap"],
                    "category": result["category"],
                    "recommendation": result["recommendation"],
                }
            )

    marginal_results = []
    for index, option in enumerate(rules.get("marginal_options", [])):
        current_factor = _finite_number(
            option.get("current_factor"), f"marginal_options[{index}].current_factor", minimum=0
        )
        new_factor = _finite_number(
            option.get("new_factor"), f"marginal_options[{index}].new_factor", minimum=0
        )
        if current_factor == 0:
            raise ValueError("marginal current_factor must be greater than zero")
        result = {
            **option,
            "relative_gain_percent": (new_factor / current_factor - 1) * 100,
        }
        projected_stats = option.get("projected_stats")
        if projected_stats is not None:
            if not isinstance(projected_stats, dict):
                raise ValueError(f"marginal_options[{index}].projected_stats must be an object")
            projected_context = _deep_overlay(stats, projected_stats)
            result["projected_breakpoints"] = _breakpoint_states(
                projected_context,
                rules.get("breakpoints", {}),
                baseline=breakpoint_results,
            )
        marginal_results.append(result)

    issues.sort(key=lambda item: (-item["severity"], item["metric"]))
    marginal_results.sort(
        key=lambda item: (-item["relative_gain_percent"], str(item.get("id", "")))
    )
    rules_confidence = rules.get("confidence")
    return {
        "ruleset": rules.get("ruleset"),
        "scenario": rules.get("scenario"),
        "confidence": (
            _probability(rules_confidence, "rules.confidence")
            if rules_confidence is not None
            else None
        ),
        "metrics": metric_results,
        "breakpoints": breakpoint_results,
        "top_issues": issues[:3],
        "issues": issues,
        "marginal_options": marginal_results,
    }
