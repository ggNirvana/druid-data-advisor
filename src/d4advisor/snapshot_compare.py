from __future__ import annotations

import copy
import math
import re
from typing import Any, Iterable

from .calculations import season13_damage_branch
from .profile_fingerprint import character_fingerprint


EVENT_PRESETS: dict[str, dict[str, Any]] = {
    "shred": {
        "id": "shred",
        "name": "利爪撕扯直伤",
        "damage_kind": "direct",
        "element": "lightning",
        "form": "werewolf",
        "distance": "close",
        "vulnerable_uptime": 1.0,
        "main_stat": "willpower",
        "main_stat_divisor": 800.0,
    }
}

PANEL_STAT_SCALES = {
    "willpower": 1.0,
    "crit_chance": 0.01,
    "cooldown_reduction": 0.01,
    "attack_speed_bonus": 0.01,
    "resource_generation": 0.01,
    "max_life": 1.0,
    "companion_skill_ranks": 1.0,
    "shred_ranks": 1.0,
}

ADDITIVE_DAMAGE_STATS = {
    "all_damage_additive",
    "critical_damage_additive",
    "vulnerable_damage_additive",
}

ELEMENT_BUCKET_STATS = {
    "fire": "fire_damage_multiplier",
    "lightning": "lightning_damage_multiplier",
    "physical": "physical_damage_multiplier",
    "poison": "poison_damage_multiplier",
}

BRANCHES = (
    ("noncrit_nonvulnerable", False, False),
    ("crit_nonvulnerable", True, False),
    ("noncrit_vulnerable", False, True),
    ("crit_vulnerable", True, True),
)

WEREWOLF_CLOSE_CRIT = re.compile(
    r"狼人[：:]?.*?近距敌人.*?暴击伤害提高\s*(\d+(?:\.\d+)?)%\s*\[(?:x|×)\]",
    re.DOTALL | re.IGNORECASE,
)


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _affixes(item: dict[str, Any] | None) -> Iterable[dict[str, Any]]:
    if not item:
        return
    for group in ("implicit_affixes", "affixes", "tempering"):
        values = item.get(group, [])
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, dict) and isinstance(value.get("stat"), str):
                yield value


def _item_stat(item: dict[str, Any] | None, stat: str, scale: float = 1.0) -> float:
    total = 0.0
    for affix in _affixes(item):
        if affix.get("stat") == stat:
            total += _number(affix.get("value"), f"affix {stat}.value") * scale
    return total


def _equipment_stat(
    equipment: dict[str, dict[str, Any]], stat: str, scale: float = 1.0
) -> float:
    return math.fsum(_item_stat(item, stat, scale) for item in equipment.values())


def _derived_panel(
    profile: dict[str, Any],
    current_equipment: dict[str, dict[str, Any]],
    simulated_equipment: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    stats = profile.get("stats", {})
    values: dict[str, Any] = {}
    for stat, scale in PANEL_STAT_SCALES.items():
        current_panel = stats.get(stat)
        if current_panel is None:
            continue
        current_value = _number(current_panel, f"profile.stats.{stat}")
        current_item_total = _equipment_stat(current_equipment, stat, scale)
        simulated_item_total = _equipment_stat(simulated_equipment, stat, scale)
        simulated_value = current_value - current_item_total + simulated_item_total
        values[stat] = {
            "current": current_value,
            "simulated": simulated_value,
            "absolute_delta": simulated_value - current_value,
            "current_item_sources": current_item_total,
            "simulated_item_sources": simulated_item_total,
        }

    # 每点全属性同时提供一点意力；把它纳入主属性重建，但不重复显示为独立面板行。
    if "willpower" in values:
        current_all = _equipment_stat(current_equipment, "all_attributes")
        simulated_all = _equipment_stat(simulated_equipment, "all_attributes")
        delta = simulated_all - current_all
        values["willpower"]["simulated"] += delta
        values["willpower"]["absolute_delta"] += delta
        values["willpower"]["current_item_sources"] += current_all
        values["willpower"]["simulated_item_sources"] += simulated_all
    return values


def _eligible_bucket(stat: str, event: dict[str, Any]) -> str | None:
    if stat == "critical_damage_multiplier":
        return "critical_strike"
    if stat == "vulnerable_damage_multiplier":
        return "vulnerable"
    if stat == "damage_over_time_multiplier":
        return "damage_over_time"
    if stat == "damage_multiplier":
        return "all_damage"
    if stat == ELEMENT_BUCKET_STATS.get(event["element"]):
        return "all_damage"
    return None


def _buckets(
    equipment: dict[str, dict[str, Any]],
    event: dict[str, Any],
    non_equipment_bonuses: dict[str, Any],
) -> dict[str, Any]:
    sources: dict[str, list[dict[str, Any]]] = {
        "all_damage": [],
        "critical_strike": [],
        "vulnerable": [],
        "damage_over_time": [],
    }
    for slot, item in equipment.items():
        for index, affix in enumerate(_affixes(item)):
            stat = str(affix.get("stat"))
            bucket = _eligible_bucket(stat, event)
            if bucket is None:
                continue
            displayed_percent = _number(
                affix.get("value"), f"{slot}.{stat}.value"
            )
            bonus = displayed_percent / 100.0
            sources[bucket].append(
                {
                    "id": f"{slot}:{stat}:{index}",
                    "slot": slot,
                    "item": item.get("name"),
                    "stat": stat,
                    "displayed_percent": displayed_percent,
                    "bonus": bonus,
                }
            )
    unknown_buckets = sorted(set(non_equipment_bonuses).difference(sources))
    if unknown_buckets:
        raise ValueError(
            "unknown non-equipment multiplier buckets: " + ", ".join(unknown_buckets)
        )
    for bucket, value in non_equipment_bonuses.items():
        bonus = _number(value, f"non_equipment_bucket_bonuses.{bucket}")
        sources[bucket].append(
            {
                "id": f"non_equipment:{bucket}",
                "slot": None,
                "item": None,
                "stat": "declared_non_equipment_bonus",
                "displayed_percent": bonus * 100.0,
                "bonus": bonus,
            }
        )
    return {
        bucket: {
            "bonus": math.fsum(source["bonus"] for source in bucket_sources),
            "factor": 1.0
            + math.fsum(source["bonus"] for source in bucket_sources),
            "sources": bucket_sources,
        }
        for bucket, bucket_sources in sources.items()
    }


def _power_description(item: dict[str, Any] | None) -> str:
    if not item or not isinstance(item.get("power"), dict):
        return ""
    description = item["power"].get("description")
    return description if isinstance(description, str) else ""


def _known_item_power(
    item: dict[str, Any] | None, event: dict[str, Any]
) -> tuple[dict[str, float], bool, str | None]:
    description = _power_description(item)
    factors = {branch_id: 1.0 for branch_id, _, _ in BRANCHES}
    if not description:
        return factors, True, None

    match = WEREWOLF_CLOSE_CRIT.search(description)
    if match and event["form"] == "werewolf" and event["distance"] == "close":
        factor = 1.0 + float(match.group(1)) / 100.0
        factors["crit_nonvulnerable"] = factor
        factors["crit_vulnerable"] = factor
        return factors, True, "werewolf_close_critical"
    return factors, False, None


def _swapped_power_factors(
    current_item: dict[str, Any], candidate: dict[str, Any], event: dict[str, Any]
) -> tuple[dict[str, float], dict[str, float], list[str]]:
    current_description = _power_description(current_item)
    candidate_description = _power_description(candidate)
    if current_description == candidate_description:
        neutral = {branch_id: 1.0 for branch_id, _, _ in BRANCHES}
        return neutral, neutral, []

    current, current_known, current_kind = _known_item_power(current_item, event)
    simulated, candidate_known, candidate_kind = _known_item_power(candidate, event)
    warnings: list[str] = []
    if not current_known:
        warnings.append("equipped_item_power_requires_manual_modeling")
    if not candidate_known:
        warnings.append("candidate_item_power_requires_manual_modeling")
    if current_kind or candidate_kind:
        warnings.append(
            "modeled_power_change:"
            f"{current_kind or 'none'}->{candidate_kind or 'none'}"
        )
    return current, simulated, warnings


def _changed_additive_damage_stats(
    current_item: dict[str, Any], candidate: dict[str, Any]
) -> list[str]:
    return sorted(
        stat
        for stat in ADDITIVE_DAMAGE_STATS
        if not math.isclose(_item_stat(current_item, stat), _item_stat(candidate, stat))
    )


def _item_stat_changed(
    current_item: dict[str, Any], candidate: dict[str, Any], stat: str
) -> bool:
    return not math.isclose(_item_stat(current_item, stat), _item_stat(candidate, stat))


def _branch_components(
    *,
    main_stat: float,
    divisor: float,
    buckets: dict[str, Any],
    powers: dict[str, float],
) -> dict[str, float]:
    values: dict[str, float] = {}
    for branch_id, is_critical, is_vulnerable in BRANCHES:
        values[branch_id] = season13_damage_branch(
            weapon_damage=1.0,
            skill_coefficient=1.0,
            main_stat=main_stat,
            main_stat_divisor=divisor,
            additive_bonus=0.0,
            all_damage_bucket_bonus=buckets["all_damage"]["bonus"],
            independent_multipliers=(powers[branch_id],),
            enemy_damage_factor=1.0,
            is_critical=is_critical,
            critical_base_factor=1.5,
            critical_bucket_bonus=buckets["critical_strike"]["bonus"],
            is_vulnerable=is_vulnerable,
            vulnerable_base_factor=1.2,
            vulnerable_bucket_bonus=buckets["vulnerable"]["bonus"],
            is_dot=False,
            dot_bucket_bonus=0.0,
        )
    return values


def _ratio(before: float, after: float) -> dict[str, float]:
    if before <= 0:
        raise ValueError("comparison baseline must be greater than zero")
    ratio = after / before
    return {"ratio": ratio, "percent": (ratio - 1.0) * 100.0}


def _expected_vulnerable_ratio(
    *,
    current_components: dict[str, float],
    simulated_components: dict[str, float],
    current_crit_chance: float,
    simulated_crit_chance: float,
    additive: dict[str, Any] | None,
) -> dict[str, Any]:
    a_noncrit = (1.0 - current_crit_chance) * current_components[
        "noncrit_vulnerable"
    ]
    a_crit = current_crit_chance * current_components["crit_vulnerable"]
    b_noncrit = (1.0 - simulated_crit_chance) * simulated_components[
        "noncrit_vulnerable"
    ]
    b_crit = simulated_crit_chance * simulated_components["crit_vulnerable"]

    if additive is not None:
        always = _number(additive.get("always", 0), "additive.always")
        critical = _number(additive.get("crit_only", 0), "additive.crit_only")
        vulnerable = _number(
            additive.get("vulnerable_only", 0), "additive.vulnerable_only"
        )
        noncrit_additive = 1.0 + always + vulnerable
        crit_additive = noncrit_additive + critical
        if noncrit_additive <= 0 or crit_additive < 0:
            raise ValueError("configured additive branch factors must be non-negative")
        before = a_noncrit * noncrit_additive + a_crit * crit_additive
        after = b_noncrit * noncrit_additive + b_crit * crit_additive
        return {
            "status": "exact_for_declared_additive_inputs",
            **_ratio(before, after),
            "current_normalized": before,
            "simulated_normalized": after,
        }

    # 未提供底部悬停的真实加法暴伤时，t=(X+Ac)/X >= 1。
    at_one = _ratio(a_noncrit + a_crit, b_noncrit + b_crit)["ratio"]
    if a_crit == 0:
        at_infinity = at_one
    else:
        at_infinity = b_crit / a_crit
    lower = min(at_one, at_infinity)
    upper = max(at_one, at_infinity)
    return {
        "status": "exact_bound_missing_additive_crit_pool",
        "ratio": {"minimum": lower, "maximum": upper},
        "percent": {
            "minimum": (lower - 1.0) * 100.0,
            "maximum": (upper - 1.0) * 100.0,
        },
        "candidate_index": {"minimum": lower * 100.0, "maximum": upper * 100.0},
        "current_index": 100.0,
    }


def _absolute_expected_damage(
    *,
    profile: dict[str, Any],
    event_id: str,
    slot: str,
    current_expected: dict[str, Any],
) -> dict[str, Any]:
    config = (
        profile.get("analysis", {}).get("damage_events", {}).get(event_id, {})
    )
    required = {
        "comparison_slot",
        "skill_coefficient",
        "enemy_damage_factor",
        "common_standalone_factor",
        "additive",
    }
    missing = sorted(field for field in required if field not in config)
    weapon_damage = profile.get("stats", {}).get("weapon_damage")
    if weapon_damage is None:
        missing.append("profile.stats.weapon_damage")
    if missing:
        return {
            "status": "missing_inputs",
            "missing": missing,
            "note": "相对提升仍可计算；绝对期望伤害不会使用面板顶部合成伤害反推。",
        }
    if config["comparison_slot"] != slot:
        return {
            "status": "comparison_slot_mismatch",
            "configured_slot": config["comparison_slot"],
            "requested_slot": slot,
        }
    if current_expected.get("status") != "exact_for_declared_additive_inputs":
        return {
            "status": "missing_inputs",
            "missing": ["analysis.damage_events.%s.additive" % event_id],
        }
    common = (
        _number(weapon_damage, "profile.stats.weapon_damage")
        * _number(config["skill_coefficient"], "skill_coefficient")
        * _number(config["enemy_damage_factor"], "enemy_damage_factor")
        * _number(config["common_standalone_factor"], "common_standalone_factor")
    )
    return {
        "status": "exact_for_declared_inputs",
        "current_expected_single_hit": common
        * current_expected["current_normalized"],
        "simulated_expected_single_hit": common
        * current_expected["simulated_normalized"],
    }


def compare_snapshot_item(
    profile: dict[str, Any],
    *,
    slot: str,
    candidate: dict[str, Any],
    event_id: str,
    ruleset: str,
) -> dict[str, Any]:
    """Atomically rebuild current and simulated loadouts for one item replacement."""
    if event_id not in EVENT_PRESETS:
        raise ValueError(f"unsupported event preset: {event_id}")
    event = copy.deepcopy(EVENT_PRESETS[event_id])
    equipment = profile.get("equipment")
    if not isinstance(equipment, dict) or slot not in equipment:
        raise ValueError(f"equipped slot is missing from profile: {slot}")
    current_item = equipment[slot]
    if not isinstance(candidate, dict):
        raise ValueError("candidate must be an item object")
    expected_item_slot = "ring" if slot.startswith("ring_") else slot
    if candidate.get("slot") not in (None, expected_item_slot):
        raise ValueError(
            f"candidate slot {candidate.get('slot')!r} is incompatible with {slot}"
        )

    simulated_equipment = copy.deepcopy(equipment)
    simulated_equipment[slot] = copy.deepcopy(candidate)
    panel = _derived_panel(profile, equipment, simulated_equipment)
    if event["main_stat"] not in panel or "crit_chance" not in panel:
        raise ValueError("profile lacks willpower or crit_chance required by shred preset")

    crit_panel = panel["crit_chance"]
    for side in ("current", "simulated"):
        if crit_panel[side] < 0:
            raise ValueError(f"derived {side} crit chance cannot be negative")
    if crit_panel["current"] > 1:
        raise ValueError("current profile crit chance cannot exceed 1")
    if crit_panel["simulated"] > 1:
        crit_panel["simulated_uncapped"] = crit_panel["simulated"]
        crit_panel["simulated"] = 1.0
        crit_panel["absolute_delta"] = 1.0 - crit_panel["current"]
    crit_panel["cap"] = 1.0

    damage_event_config = (
        profile.get("analysis", {}).get("damage_events", {}).get(event_id, {})
    )
    configured_non_equipment = damage_event_config.get(
        "non_equipment_bucket_bonuses", {}
    )
    if not isinstance(configured_non_equipment, dict):
        raise ValueError("non_equipment_bucket_bonuses must be an object")
    current_buckets = _buckets(equipment, event, configured_non_equipment)
    simulated_buckets = _buckets(
        simulated_equipment, event, configured_non_equipment
    )
    current_powers, simulated_powers, warnings = _swapped_power_factors(
        current_item, candidate, event
    )
    additive_changes = _changed_additive_damage_stats(current_item, candidate)
    blocking_reasons: list[str] = []
    if slot in {"weapon", "totem"}:
        blocking_reasons.append("weapon_set_base_damage_requires_rebuild")
    if _item_stat_changed(current_item, candidate, "shred_ranks"):
        blocking_reasons.append("shred_rank_skill_coefficient_requires_rebuild")
    if any("requires_manual_modeling" in warning for warning in warnings):
        blocking_reasons.append("changed_item_power_requires_manual_modeling")
    if additive_changes:
        warnings.append(
            "changed_additive_damage_stats_require_full_additive_input:"
            + ",".join(additive_changes)
        )
        blocking_reasons.append("changed_additive_damage_stats_require_rebuild")

    current_components = _branch_components(
        main_stat=panel[event["main_stat"]]["current"],
        divisor=event["main_stat_divisor"],
        buckets=current_buckets,
        powers=current_powers,
    )
    simulated_components = _branch_components(
        main_stat=panel[event["main_stat"]]["simulated"],
        divisor=event["main_stat_divisor"],
        buckets=simulated_buckets,
        powers=simulated_powers,
    )
    branches = {
        branch_id: _ratio(current_components[branch_id], simulated_components[branch_id])
        for branch_id, _, _ in BRANCHES
    }

    additive = damage_event_config.get("additive")
    if blocking_reasons:
        expected: dict[str, Any] = {
            "status": "requires_manual_rebuild",
            "blocking_reasons": blocking_reasons,
        }
    else:
        expected = _expected_vulnerable_ratio(
            current_components=current_components,
            simulated_components=simulated_components,
            current_crit_chance=panel["crit_chance"]["current"],
            simulated_crit_chance=panel["crit_chance"]["simulated"],
            additive=additive if isinstance(additive, dict) else None,
        )

    exact_branch = not blocking_reasons
    absolute = (
        {
            "status": "requires_manual_rebuild",
            "blocking_reasons": blocking_reasons,
        }
        if blocking_reasons
        else _absolute_expected_damage(
            profile=profile,
            event_id=event_id,
            slot=slot,
            current_expected=expected,
        )
    )
    current_main_factor = 1.0 + panel[event["main_stat"]]["current"] / event[
        "main_stat_divisor"
    ]
    simulated_main_factor = 1.0 + panel[event["main_stat"]]["simulated"] / event[
        "main_stat_divisor"
    ]
    component_deltas = {
        "main_stat_factor": _ratio(current_main_factor, simulated_main_factor),
        "all_damage_bucket": _ratio(
            current_buckets["all_damage"]["factor"],
            simulated_buckets["all_damage"]["factor"],
        ),
        "critical_strike_bucket": _ratio(
            current_buckets["critical_strike"]["factor"],
            simulated_buckets["critical_strike"]["factor"],
        ),
        "vulnerable_bucket": _ratio(
            current_buckets["vulnerable"]["factor"],
            simulated_buckets["vulnerable"]["factor"],
        ),
        "swapped_item_power_crit_vulnerable": _ratio(
            current_powers["crit_vulnerable"],
            simulated_powers["crit_vulnerable"],
        ),
    }
    return {
        "schema_version": 1,
        "operation": "snapshot_item_replacement",
        "ruleset": ruleset,
        "profile_fingerprint": character_fingerprint(profile),
        "event": event,
        "slot": slot,
        "current_item": current_item.get("name"),
        "candidate_item": candidate.get("name"),
        "algorithm": [
            "load_current_snapshot",
            "calculate_current_loadout",
            "clone_snapshot_in_memory",
            "remove_entire_equipped_item",
            "insert_candidate_item",
            "rebuild_panel_and_buckets_from_all_sources",
            "calculate_simulated_loadout_with_same_event",
        ],
        "derived_panel": panel,
        "buckets": {"current": current_buckets, "simulated": simulated_buckets},
        "component_deltas": component_deltas,
        "branch_deltas": branches,
        "full_buff_theoretical": {
            "branch": "crit_vulnerable",
            "precision": (
                "model_exact_for_displayed_item_values"
                if exact_branch and not additive_changes
                else "incomplete"
            ),
            **branches["crit_vulnerable"],
        },
        "expected_single_hit": expected,
        "absolute_expected_single_hit": absolute,
        "blocking_reasons": blocking_reasons,
        "assumptions": (
            []
            if "non_equipment_bucket_bonuses" in damage_event_config
            else ["no_non_equipment_named_bucket_bonuses"]
        ),
        "warnings": warnings,
    }
