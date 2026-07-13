from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any


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
            raise ValueError(f"item slot {item_slot!r} is incompatible with equipment slot {slot}")
    for field in ("name", "rarity"):
        if item.get(field) is not None and not isinstance(item[field], str):
            raise ValueError(f"item.{field} must be a string or null")
    item_power = item.get("item_power")
    if item_power is not None:
        if isinstance(item_power, bool) or not isinstance(item_power, (int, float)) or item_power < 0:
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
    if not isinstance(profile.get("profile_id"), str) or not profile["profile_id"].strip():
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
    _validate_finite_tree(profile)


class CharacterStore:
    """Atomic JSON character store with immutable snapshots after every update."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.current_path = self.root / "current.json"
        self.history_dir = self.root / "history"

    def initialize(self, *, profile_id: str, build_ref: dict[str, Any]) -> dict[str, Any]:
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
            raise FileNotFoundError("character store is not initialized; run `d4advisor profile init`")
        profile = json.loads(self.current_path.read_text(encoding="utf-8"))
        _validate_profile(profile)
        return profile

    def merge_character_fields(self, fields: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(fields, dict):
            raise ValueError("profile merge input must be an object")
        protected = sorted(PROTECTED_FIELDS.intersection(fields))
        if protected:
            raise ValueError(f"protected profile fields cannot be merged: {', '.join(protected)}")
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
                raise ValueError(f"{key} must be an object" if expected_types[key] is dict else f"{key} must be an array")
        profile = self.load()
        for key, value in fields.items():
            if isinstance(value, dict) and isinstance(profile.get(key), dict):
                _deep_merge(profile[key], value)
            else:
                profile[key] = copy.deepcopy(value)
        self._save(profile, event="merge_character_fields")
        return profile

    def set_item(self, slot: str, item: dict[str, Any], source: str | None = None) -> dict[str, Any]:
        _validate_item(slot, item)
        profile = self.load()
        stored_item = copy.deepcopy(item)
        if source:
            stored_item["source_image"] = source
        profile.setdefault("equipment", {})[slot] = stored_item
        self._save(profile, event=f"set_item:{slot}")
        return profile

    def render_snapshot(self, output_path: str | Path | None = None) -> Path:
        return self._render_profile(self.load(), output_path or self.root / "snapshot.html")

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
            json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
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
