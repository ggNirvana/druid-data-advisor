from __future__ import annotations

import hashlib
import json
from typing import Any


FINGERPRINT_FIELDS = (
    "profile_id",
    "build_ref",
    "stats",
    "equipment",
    "paragon_overrides",
)


def character_fingerprint(profile: dict[str, Any]) -> str:
    """Hash only character state that can change an advisory calculation."""
    if not isinstance(profile, dict):
        raise ValueError("profile must be an object")
    baseline = {field: profile.get(field) for field in FINGERPRINT_FIELDS}
    encoded = json.dumps(
        baseline,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
