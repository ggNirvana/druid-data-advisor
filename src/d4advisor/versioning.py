from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def version_lock_status(lock_path: str | Path, now: datetime | None = None) -> dict[str, Any]:
    lock_path = Path(lock_path)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    current_time = now or datetime.now().astimezone()
    cache_deadline = datetime.fromisoformat(lock["cache_valid_through"])
    if current_time.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    expired = current_time > cache_deadline
    return {
        "season": lock["season"],
        "ruleset": lock["ruleset"],
        "checked_at": lock["checked_at"],
        "cache_valid_through": lock["cache_valid_through"],
        "cache_expired": expired,
        "refresh_required": expired,
        "pending": lock.get("pending"),
    }
