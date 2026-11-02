"""لایه‌ی ذخیره‌سازی (JSON). تراکر به جزئیات فایل وابسته نیست."""
from __future__ import annotations

import json
from pathlib import Path

from app.models import UserActivity


class JsonStorage:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> list[UserActivity]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            raw = json.load(f)
        return [UserActivity.from_dict(item) for item in raw.get("activities", [])]

    def load_users(self) -> list[str]:
        """کاربران ثبت‌شده (حتی بدون فعالیت)."""
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            return list(json.load(f).get("users", []))

    def save(self, activities: list[UserActivity], users: list[str] | None = None) -> None:
        payload = {"activities": [a.to_dict() for a in activities]}
        if users is not None:
            payload["users"] = sorted(users)
        self._write(payload)

    def _write(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)


def write_report(report: dict, path: str | Path) -> None:
    """ذخیره‌ی خروجی تحلیل در فایل JSON."""
    JsonStorage(path)._write(report)


def read_json(path: str | Path, default: dict | None = None) -> dict:
    """خواندن فایل JSON؛ اگر وجود نداشت `default` (یا dict خالی) برمی‌گردد."""
    path = Path(path)
    if not path.exists():
        return {} if default is None else default
    with path.open(encoding="utf-8") as f:
        return json.load(f)
