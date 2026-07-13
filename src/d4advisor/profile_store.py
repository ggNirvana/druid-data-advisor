from __future__ import annotations

import copy
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class CharacterStore:
    """Atomic JSON character store with immutable snapshots after every update."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.current_path = self.root / "current.json"
        self.history_dir = self.root / "history"

    def initialize(self, *, profile_id: str, build_ref: dict[str, Any]) -> dict[str, Any]:
        if self.current_path.exists():
            return self.load()
        profile = {
            "schema_version": 1,
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
        return json.loads(self.current_path.read_text(encoding="utf-8"))

    def merge_character_fields(self, fields: dict[str, Any]) -> dict[str, Any]:
        profile = self.load()
        for key, value in fields.items():
            if isinstance(value, dict) and isinstance(profile.get(key), dict):
                profile[key].update(copy.deepcopy(value))
            else:
                profile[key] = copy.deepcopy(value)
        self._save(profile, event="merge_character_fields")
        return profile

    def set_item(self, slot: str, item: dict[str, Any], source: str | None = None) -> dict[str, Any]:
        profile = self.load()
        stored_item = copy.deepcopy(item)
        if source:
            stored_item["source_image"] = source
        profile.setdefault("equipment", {})[slot] = stored_item
        self._save(profile, event=f"set_item:{slot}")
        return profile

    def _save(self, profile: dict[str, Any], *, event: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        profile["updated_at"] = _now()
        profile["last_event"] = event
        encoded = json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temporary = self.current_path.with_suffix(".json.tmp")
        temporary.write_text(encoded, encoding="utf-8")
        os.replace(temporary, self.current_path)

        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:10]
        timestamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S.%f%z")
        history_path = self.history_dir / f"{timestamp}-{digest}.json"
        history_path.write_text(encoded, encoding="utf-8")
