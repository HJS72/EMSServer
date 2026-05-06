from __future__ import annotations

import json
from pathlib import Path

from app.models import (
    ConfigConsumer,
    ConfigControllableConsumer,
    ConfigGenerator,
    ConfigGrid,
    DataPointConfig,
)


class DataPointConfigService:
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "datapoint_config.json"

    def _default(self) -> DataPointConfig:
        return DataPointConfig(
            consumers=[
                ConfigConsumer(name="Waschmaschine", state_key=""),
                ConfigConsumer(name="Trockner", state_key=""),
            ],
            controllable_consumers=[
                ConfigControllableConsumer(name="Ochsner", state_key="", control_key=""),
                ConfigControllableConsumer(name="Klima", state_key="", control_key=""),
            ],
            generators=[
                ConfigGenerator(name="PV", state_key="", has_battery=False),
                ConfigGenerator(name="PV mit Batterie", state_key="", has_battery=True),
            ],
            grid=ConfigGrid(),
        )

    def load(self) -> DataPointConfig:
        if not self._path.exists():
            config = self._default()
            self.save(config)
            return config

        payload = json.loads(self._path.read_text(encoding="utf-8"))
        return DataPointConfig.model_validate(payload)

    def save(self, config: DataPointConfig) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(config.model_dump(mode="json"), ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
