from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class Storage:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.archive_dir = data_dir / "archive"
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def save_latest(self, payload: dict[str, Any]) -> None:
        target = self.data_dir / "latest_forecast.json"
        target.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def load_latest(self) -> dict[str, Any] | None:
        target = self.data_dir / "latest_forecast.json"
        if not target.exists():
            return None
        return json.loads(target.read_text(encoding="utf-8"))

    def save_daily_archive(self, payload: dict[str, Any]) -> None:
        day = datetime.now().strftime("%Y-%m-%d")
        target = self.archive_dir / f"forecast-{day}.json"
        target.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
