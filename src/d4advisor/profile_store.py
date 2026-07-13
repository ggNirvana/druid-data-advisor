from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .profile_fingerprint import character_fingerprint

PROTECTED_FIELDS = {
    "schema_version",
    "profile_id",
    "updated_at",
    "last_event",
    "build_ref",
    "version_lock_ref",
    "equipment",
}
MERGEABLE_FIELDS = {"stats", "paragon_overrides", "observations", "analysis"}
PROFILE_SCHEMA_VERSION = 1
ITEM_SCHEMA_VERSION = 1
EQUIPMENT_SLOT_TYPES = {
    "helm": "helm",
    "chest": "chest",
    "gloves": "gloves",
    "pants": "pants",
    "boots": "boots",
    "amulet": "amulet",
    "ring_1": "ring",
    "ring_2": "ring",
    "weapon": "weapon",
    "totem": "totem",
}
AFFIX_UNITS = {"flat", "percent", "ranks", "seconds", "count", "rating"}
AFFIX_OPERATORS = {"add", "multiply"}


def _validate_finite_tree(value: Any, path: str = "profile") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path} must contain only finite numbers")
    if isinstance(value, dict):
        for key, child in value.items():
            _validate_finite_tree(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_finite_tree(child, f"{path}[{index}]")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _deep_merge(target: dict[str, Any], updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _validate_item(slot: str, item: Any) -> None:
    if slot not in EQUIPMENT_SLOT_TYPES:
        raise ValueError(f"unknown equipment slot: {slot}")
    if not isinstance(item, dict):
        raise ValueError("item must be an object")
    schema_version = item.get("schema_version", ITEM_SCHEMA_VERSION)
    if isinstance(schema_version, bool) or schema_version != ITEM_SCHEMA_VERSION:
        raise ValueError(f"unsupported item schema_version: {schema_version}")
    item_slot = item.get("slot")
    if item_slot is not None:
        if not isinstance(item_slot, str) or item_slot != EQUIPMENT_SLOT_TYPES[slot]:
            raise ValueError(
                f"item slot {item_slot!r} is incompatible with equipment slot {slot}"
            )
    for field in ("name", "rarity"):
        if item.get(field) is not None and not isinstance(item[field], str):
            raise ValueError(f"item.{field} must be a string or null")
    item_power = item.get("item_power")
    if item_power is not None:
        if (
            isinstance(item_power, bool)
            or not isinstance(item_power, (int, float))
            or item_power < 0
        ):
            raise ValueError("item.item_power must be a non-negative number or null")
    for affix_field in ("implicit_affixes", "affixes"):
        affixes = item.get(affix_field, [])
        if not isinstance(affixes, list):
            raise ValueError(f"item.{affix_field} must be an array")
        for index, affix in enumerate(affixes):
            if not isinstance(affix, dict):
                raise ValueError(f"item.{affix_field}[{index}] must be an object")
            unit = affix.get("unit")
            if unit is not None and unit not in AFFIX_UNITS:
                raise ValueError(f"invalid affix unit: {unit}")
            operator = affix.get("operator")
            if operator is not None and operator not in AFFIX_OPERATORS:
                raise ValueError(f"invalid affix operator: {operator}")
    tempering = item.get("tempering")
    if tempering is not None and not isinstance(tempering, list):
        raise ValueError("item.tempering must be an array or null")
    masterworking = item.get("masterworking")
    if masterworking is not None and not isinstance(masterworking, (dict, list)):
        raise ValueError("item.masterworking must be an object, array, or null")
    enchantment = item.get("enchantment")
    if enchantment is not None and not isinstance(enchantment, (dict, list)):
        raise ValueError("item.enchantment must be an object, array, or null")
    power = item.get("power")
    if power is not None and not isinstance(power, dict):
        raise ValueError("item.power must be an object or null")
    _validate_finite_tree(item, "item")


def _validate_profile(profile: Any) -> None:
    if not isinstance(profile, dict):
        raise ValueError("profile must be an object")
    schema_version = profile.get("schema_version")
    if isinstance(schema_version, bool) or schema_version != PROFILE_SCHEMA_VERSION:
        raise ValueError(f"unsupported profile schema_version: {schema_version}")
    if (
        not isinstance(profile.get("profile_id"), str)
        or not profile["profile_id"].strip()
    ):
        raise ValueError("profile_id must be a non-empty string")
    expected_types = {
        "build_ref": dict,
        "stats": dict,
        "equipment": dict,
        "paragon_overrides": dict,
        "observations": list,
    }
    if "analysis" in profile:
        expected_types["analysis"] = dict
    for field, expected_type in expected_types.items():
        if not isinstance(profile.get(field), expected_type):
            raise ValueError(f"profile.{field} must be a {expected_type.__name__}")
    for slot, item in profile["equipment"].items():
        _validate_item(slot, item)
    enchantment_analysis = profile.get("analysis", {}).get("enchantment")
    if enchantment_analysis is not None:
        _validate_enchantment_analysis(enchantment_analysis)
    _validate_finite_tree(profile)


def _validate_enchantment_analysis(analysis: Any) -> None:
    if not isinstance(analysis, dict):
        raise ValueError("enchantment analysis must be an object")
    for field in ("ruleset", "scenario"):
        if not isinstance(analysis.get(field), str) or not analysis[field].strip():
            raise ValueError(f"enchantment analysis {field} must be a non-empty string")
    profile_fingerprint = analysis.get("profile_fingerprint")
    if (
        not isinstance(profile_fingerprint, str)
        or len(profile_fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in profile_fingerprint)
    ):
        raise ValueError(
            "enchantment analysis profile_fingerprint must be a SHA-256 digest"
        )
    confidence = analysis.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        raise ValueError("enchantment analysis confidence must be between 0 and 1")
    rankings = analysis.get("rankings")
    if not isinstance(rankings, dict) or not rankings:
        raise ValueError("enchantment analysis rankings must be an object")
    options = analysis.get("options")
    if not isinstance(options, list) or not options:
        raise ValueError("enchantment analysis options must be a non-empty array")
    objectives = analysis.get("objectives")
    if not isinstance(objectives, dict) or not objectives:
        raise ValueError("enchantment analysis objectives must be a non-empty object")
    normalized_objectives: dict[str, dict[str, float]] = {}
    for objective, weights in objectives.items():
        if (
            not isinstance(objective, str)
            or not objective.strip()
            or not isinstance(weights, dict)
        ):
            raise ValueError("enchantment analysis objectives are malformed")
        normalized_weights: dict[str, float] = {}
        for metric, weight in weights.items():
            if (
                not isinstance(metric, str)
                or not metric.strip()
                or isinstance(weight, bool)
                or not isinstance(weight, (int, float))
                or not math.isfinite(weight)
                or weight < 0
            ):
                raise ValueError(
                    f"enchantment analysis objectives.{objective} is malformed"
                )
            normalized_weights[metric] = float(weight)
        if not math.isclose(sum(normalized_weights.values()), 1.0, abs_tol=1e-9):
            raise ValueError(
                f"enchantment analysis objectives.{objective} weights must sum to 1"
            )
        normalized_objectives[objective] = normalized_weights
    if set(rankings) != set(normalized_objectives):
        raise ValueError("enchantment analysis rankings must match objectives")

    option_ids: set[str] = set()
    for index, option in enumerate(options):
        if not isinstance(option, dict):
            raise ValueError(f"enchantment analysis options[{index}] must be an object")
        for field in ("id", "slot", "replace_stat", "target_stat"):
            if not isinstance(option.get(field), str) or not option[field].strip():
                raise ValueError(
                    f"enchantment analysis options[{index}].{field} is required"
                )
        option_id = option["id"]
        if option_id in option_ids:
            raise ValueError(f"duplicate enchantment analysis option: {option_id}")
        option_ids.add(option_id)
        option_confidence = option.get("confidence")
        if (
            isinstance(option_confidence, bool)
            or not isinstance(option_confidence, (int, float))
            or not math.isfinite(option_confidence)
            or not 0 <= option_confidence <= 1
        ):
            raise ValueError(
                f"enchantment analysis options[{index}].confidence must be between 0 and 1"
            )
        if option_confidence > confidence:
            raise ValueError(
                f"enchantment analysis options[{index}].confidence cannot exceed common confidence"
            )
        exchange = option.get("affix_exchange")
        if not isinstance(exchange, dict):
            raise ValueError(
                f"enchantment analysis options[{index}].affix_exchange is required"
            )
        lost = exchange.get("lost")
        gained = exchange.get("gained")
        if not isinstance(lost, dict) or not isinstance(gained, dict):
            raise ValueError(
                f"enchantment analysis options[{index}].affix_exchange needs lost and gained"
            )
        if (
            lost.get("stat") != option["replace_stat"]
            or gained.get("stat") != option["target_stat"]
        ):
            raise ValueError(
                f"enchantment analysis options[{index}].affix_exchange stat mismatch"
            )
        for label, affix, numeric_fields in (
            ("lost", lost, ("value",)),
            ("gained", gained, ("minimum", "expected", "maximum")),
        ):
            if not isinstance(affix.get("unit"), str) or not affix["unit"].strip():
                raise ValueError(
                    f"enchantment analysis options[{index}].affix_exchange.{label}.unit is required"
                )
            for field in numeric_fields:
                value = affix.get(field)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or value < 0
                ):
                    raise ValueError(
                        f"enchantment analysis options[{index}].affix_exchange."
                        f"{label}.{field} must be a non-negative finite number"
                    )
        if not gained["minimum"] <= gained["expected"] <= gained["maximum"]:
            raise ValueError(
                f"enchantment analysis options[{index}].affix_exchange.gained roll order is invalid"
            )
        outcomes = option.get("outcomes")
        if not isinstance(outcomes, dict) or not outcomes:
            raise ValueError(
                f"enchantment analysis options[{index}].outcomes is required"
            )
        for metric, outcome in outcomes.items():
            if (
                not isinstance(metric, str)
                or not metric.strip()
                or not isinstance(outcome, dict)
            ):
                raise ValueError(
                    f"enchantment analysis options[{index}].outcomes is malformed"
                )
            current = outcome.get("current")
            after = outcome.get("after")
            direction = outcome.get("direction")
            if (
                isinstance(current, bool)
                or not isinstance(current, (int, float))
                or not math.isfinite(current)
                or current < 0
                or not isinstance(after, dict)
                or direction not in {"higher", "lower"}
            ):
                raise ValueError(
                    f"enchantment analysis options[{index}].outcomes.{metric} is malformed"
                )
            after_values: dict[str, float] = {}
            for bound in ("minimum", "expected", "maximum"):
                value = after.get(bound)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or value < 0
                ):
                    raise ValueError(
                        f"enchantment analysis options[{index}].outcomes.{metric}."
                        f"after.{bound} must be a non-negative finite number"
                    )
                after_values[bound] = float(value)
            delta_percents = {
                bound: (
                    (0.0 if value == 0 else None)
                    if current == 0
                    else (value / current - 1) * 100
                )
                for bound, value in after_values.items()
            }
            sign = 1 if direction == "higher" else -1
            utilities = {
                bound: value * sign if value is not None else None
                for bound, value in delta_percents.items()
            }
            finite_utilities = [
                value for value in utilities.values() if value is not None
            ]
            expected_fields = {
                "minimum_delta_percent": delta_percents["minimum"],
                "expected_delta_percent": delta_percents["expected"],
                "maximum_delta_percent": delta_percents["maximum"],
                "minimum_utility": utilities["minimum"],
                "utility_lower_bound": (
                    min(finite_utilities) if finite_utilities else None
                ),
                "expected_utility": utilities["expected"],
                "maximum_utility": utilities["maximum"],
                "utility_upper_bound": (
                    max(finite_utilities) if finite_utilities else None
                ),
            }
            for field, expected_value in expected_fields.items():
                actual_value = outcome.get(field)
                if expected_value is None:
                    matches = actual_value is None
                else:
                    matches = (
                        not isinstance(actual_value, bool)
                        and isinstance(actual_value, (int, float))
                        and math.isfinite(actual_value)
                        and math.isclose(
                            actual_value, expected_value, rel_tol=1e-9, abs_tol=1e-9
                        )
                    )
                if not matches:
                    raise ValueError(
                        f"enchantment analysis options[{index}].outcomes.{metric}.{field} "
                        "does not match its before/after values"
                    )
        expected_tradeoffs = sorted(
            metric
            for metric, outcome in outcomes.items()
            if outcome["expected_utility"] is not None
            and outcome["expected_utility"] < 0
        )
        if option.get("tradeoffs") != expected_tradeoffs:
            raise ValueError(
                f"enchantment analysis options[{index}].tradeoffs does not match outcomes"
            )

    options_by_id = {option["id"]: option for option in options}

    for objective, entries in rankings.items():
        if not isinstance(objective, str) or not objective.strip():
            raise ValueError(
                "enchantment analysis ranking names must be non-empty strings"
            )
        if not isinstance(entries, list) or not entries:
            raise ValueError(
                f"enchantment analysis rankings.{objective} must be a non-empty array"
            )
        ranked_ids: list[str] = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ValueError(
                    f"enchantment analysis rankings.{objective}[{index}] must be an object"
                )
            option_id = entry.get("id")
            if option_id not in option_ids:
                raise ValueError(
                    f"enchantment analysis rankings.{objective}[{index}] references unknown option"
                )
            ranked_ids.append(option_id)
            for field in ("score_lower_bound", "score_expected", "score_upper_bound"):
                value = entry.get(field)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    raise ValueError(
                        f"enchantment analysis rankings.{objective}[{index}].{field} "
                        "must be a finite number"
                    )
            entry_confidence = entry.get("confidence")
            if (
                isinstance(entry_confidence, bool)
                or not isinstance(entry_confidence, (int, float))
                or not math.isfinite(entry_confidence)
                or not 0 <= entry_confidence <= 1
            ):
                raise ValueError(
                    f"enchantment analysis rankings.{objective}[{index}].confidence "
                    "must be between 0 and 1"
                )
            matching_option = options_by_id[option_id]
            for field in ("slot", "replace_stat", "target_stat"):
                if entry.get(field) != matching_option[field]:
                    raise ValueError(
                        f"enchantment analysis rankings.{objective}[{index}].{field} "
                        "must match its option"
                    )
            if not math.isclose(entry_confidence, matching_option["confidence"]):
                raise ValueError(
                    f"enchantment analysis rankings.{objective}[{index}].confidence "
                    "must match its option"
                )
            tradeoffs = entry.get("tradeoffs")
            if not isinstance(tradeoffs, list) or not all(
                isinstance(value, str) for value in tradeoffs
            ):
                raise ValueError(
                    f"enchantment analysis rankings.{objective}[{index}].tradeoffs must be strings"
                )
            if tradeoffs != matching_option["tradeoffs"]:
                raise ValueError(
                    f"enchantment analysis rankings.{objective}[{index}].tradeoffs "
                    "must match its option"
                )
            missing_metrics = set(normalized_objectives[objective]).difference(
                matching_option["outcomes"]
            )
            if missing_metrics:
                raise ValueError(
                    f"enchantment analysis option {option_id} is missing objective metrics: "
                    + ", ".join(sorted(missing_metrics))
                )
            expected_scores = {
                "score_lower_bound": math.fsum(
                    weight * matching_option["outcomes"][metric]["utility_lower_bound"]
                    for metric, weight in normalized_objectives[objective].items()
                ),
                "score_expected": math.fsum(
                    weight * matching_option["outcomes"][metric]["expected_utility"]
                    for metric, weight in normalized_objectives[objective].items()
                ),
                "score_upper_bound": math.fsum(
                    weight * matching_option["outcomes"][metric]["utility_upper_bound"]
                    for metric, weight in normalized_objectives[objective].items()
                ),
            }
            for field, expected_score in expected_scores.items():
                if not math.isclose(
                    entry[field], expected_score, rel_tol=1e-9, abs_tol=1e-9
                ):
                    raise ValueError(
                        f"enchantment analysis rankings.{objective}[{index}].{field} "
                        "does not match option outcomes"
                    )
        if len(ranked_ids) != len(set(ranked_ids)) or set(ranked_ids) != option_ids:
            raise ValueError(
                f"enchantment analysis rankings.{objective} must reference every option once"
            )
        expected_order = sorted(
            entries,
            key=lambda entry: (
                -entry["score_expected"],
                -entry["score_lower_bound"],
                entry["id"],
            ),
        )
        if [entry["id"] for entry in entries] != [
            entry["id"] for entry in expected_order
        ]:
            raise ValueError(
                f"enchantment analysis rankings.{objective} is not correctly ordered"
            )
    _validate_finite_tree(analysis, "enchantment analysis")


class CharacterStore:
    """Atomic JSON character store with immutable snapshots after every update."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.current_path = self.root / "current.json"
        self.history_dir = self.root / "history"

    def initialize(
        self, *, profile_id: str, build_ref: dict[str, Any]
    ) -> dict[str, Any]:
        if self.current_path.exists():
            profile = self.load()
            self.render_snapshot()
            return profile
        profile = {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "profile_id": profile_id,
            "updated_at": _now(),
            "build_ref": build_ref,
            "version_lock_ref": "data/reference/version-lock.json",
            "stats": {},
            "equipment": {},
            "paragon_overrides": {},
            "observations": [],
        }
        self._save(profile, event="initialize")
        return profile

    def load(self) -> dict[str, Any]:
        if not self.current_path.exists():
            raise FileNotFoundError(
                "character store is not initialized; run `d4advisor profile init`"
            )
        profile = json.loads(self.current_path.read_text(encoding="utf-8"))
        _validate_profile(profile)
        return profile

    def merge_character_fields(self, fields: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(fields, dict):
            raise ValueError("profile merge input must be an object")
        protected = sorted(PROTECTED_FIELDS.intersection(fields))
        if protected:
            raise ValueError(
                f"protected profile fields cannot be merged: {', '.join(protected)}"
            )
        unsupported = sorted(set(fields).difference(MERGEABLE_FIELDS))
        if unsupported:
            raise ValueError(f"unsupported profile fields: {', '.join(unsupported)}")
        _validate_finite_tree(fields)
        expected_types = {
            "stats": dict,
            "paragon_overrides": dict,
            "observations": list,
            "analysis": dict,
        }
        for key, value in fields.items():
            if not isinstance(value, expected_types[key]):
                raise ValueError(
                    f"{key} must be an object"
                    if expected_types[key] is dict
                    else f"{key} must be an array"
                )
        profile = self.load()
        for key, value in fields.items():
            if isinstance(value, dict) and isinstance(profile.get(key), dict):
                _deep_merge(profile[key], value)
            else:
                profile[key] = copy.deepcopy(value)
        self._save(profile, event="merge_character_fields")
        return profile

    def set_item(
        self, slot: str, item: dict[str, Any], source: str | None = None
    ) -> dict[str, Any]:
        _validate_item(slot, item)
        profile = self.load()
        stored_item = copy.deepcopy(item)
        if source:
            stored_item["source_image"] = source
        profile.setdefault("equipment", {})[slot] = stored_item
        self._save(profile, event=f"set_item:{slot}")
        return profile

    def set_items(
        self,
        items: dict[str, dict[str, Any]],
        sources: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Validate and persist a batch of equipped items in one atomic profile update."""
        if not isinstance(items, dict) or not items:
            raise ValueError("items must be a non-empty slot-to-item object")
        for slot, item in items.items():
            _validate_item(slot, item)
        sources = sources or {}
        unsupported_sources = sorted(set(sources).difference(items))
        if unsupported_sources:
            raise ValueError(
                "item sources reference unknown batch slots: "
                + ", ".join(unsupported_sources)
            )

        profile = self.load()
        equipment = profile.setdefault("equipment", {})
        for slot, item in items.items():
            stored_item = copy.deepcopy(item)
            if sources.get(slot):
                stored_item["source_image"] = sources[slot]
            equipment[slot] = stored_item
        self._save(profile, event="set_items:" + ",".join(sorted(items)))
        return profile

    def set_enchantment_analysis(self, analysis: dict[str, Any]) -> dict[str, Any]:
        """Store advisory output without mutating equipped items or confirmed enchantments."""
        _validate_enchantment_analysis(analysis)
        profile = self.load()
        if analysis["profile_fingerprint"] != character_fingerprint(profile):
            raise ValueError(
                "enchantment analysis profile fingerprint does not match the current character"
            )
        profile.setdefault("analysis", {})["enchantment"] = copy.deepcopy(analysis)
        self._save(profile, event="set_enchantment_analysis")
        return profile

    def current_fingerprint(self) -> str:
        return character_fingerprint(self.load())

    def render_snapshot(self, output_path: str | Path | None = None) -> Path:
        return self._render_profile(
            self.load(), output_path or self.root / "snapshot.html"
        )

    def _render_profile(self, profile: dict[str, Any], output_path: str | Path) -> Path:
        from .snapshot_renderer import render_character_snapshot

        reference_root = self.root.parent / "reference"
        return render_character_snapshot(
            profile,
            output_path,
            _read_optional_json(reference_root / "version-lock.json"),
            _read_optional_json(reference_root / "fixed-build.json"),
        )

    def _save(self, profile: dict[str, Any], *, event: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        profile["updated_at"] = _now()
        profile["last_event"] = event
        _validate_profile(profile)
        encoded = (
            json.dumps(
                profile, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
            )
            + "\n"
        )
        temporary = self.current_path.with_suffix(".json.tmp")
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:10]
        timestamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S.%f%z")
        history_path = self.history_dir / f"{timestamp}-{digest}.json"
        history_temporary = history_path.with_suffix(".json.tmp")
        snapshot_path = self.root / "snapshot.html"
        staged_snapshot = self.root / ".snapshot.html.staged"
        try:
            self._render_profile(profile, staged_snapshot)
            temporary.write_text(encoded, encoding="utf-8")
            history_temporary.write_text(encoded, encoding="utf-8")
            os.replace(temporary, self.current_path)
            os.replace(history_temporary, history_path)
            os.replace(staged_snapshot, snapshot_path)
        finally:
            for staged_path in (temporary, history_temporary, staged_snapshot):
                staged_path.unlink(missing_ok=True)
