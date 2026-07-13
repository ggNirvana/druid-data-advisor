from __future__ import annotations

import copy
import math
from typing import Any

from .calculations import effective_health, expected_chained_attacks, stack_damage_reductions


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


def calculate_damage_event(ledger: dict[str, Any]) -> dict[str, Any]:
    """Reduce one versioned damage ledger into deterministic damage metrics."""
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
        for context_field in ("ruleset", "scenario", "event"):
            if pair["a"].get(context_field) != pair["b"].get(context_field):
                raise ValueError(f"A/B must use the same {context_field}")
        a_result = calculate_damage_event(pair["a"])
        b_result = calculate_damage_event(pair["b"])
        a_factors = {item["id"]: item["expected_factor"] for item in a_result["factor_breakdown"]}
        b_factors = {item["id"]: item["expected_factor"] for item in b_result["factor_breakdown"]}
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
