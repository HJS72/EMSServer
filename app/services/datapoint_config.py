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
                ConfigConsumer(id="consumer-1", name="Waschmaschine", state_key=""),
                ConfigConsumer(id="consumer-2", name="Trockner", state_key=""),
            ],
            controllable_consumers=[
                ConfigControllableConsumer(
                    id="ctrl-1", 
                    name="Ochsner", 
                    state_key="EMS.Ochsner.Energie",
                    control_key="shelly.0.SHPLG-S#FDD4A3#1.Relay0.Power"
                ),
                ConfigControllableConsumer(id="ctrl-2", name="Klima", state_key="", control_key=""),
            ],
            generators=[
                ConfigGenerator(id="gen-1", name="Hoymiles", state_key="EMS.Hoymiles.Energie", has_battery=False),
                ConfigGenerator(
                    id="gen-2",
                    name="SolarEdge Hybrid",
                    state_key="",
                    has_battery=True,
                    pv_power_state_key="",
                    battery_soc_state_key="modbus.0.holdingRegisters.102853_Batterieladung",
                    battery_power_state_key="",
                    battery_capacity_wh_state_key="modbus.0.holdingRegisters.102787_Batt_Rated_Energy",
                    battery_rest_soc_percent=10.0,
                    battery_capacity_kwh=10.0,
                ),
            ],
            grid=ConfigGrid(
                id="grid-main",
                import_state_key="EMS.Grid.Energie.in",
                export_state_key="EMS.Grid.Energie.out"
            ),
            device_order=["gen-1", "gen-2", "consumer-1", "consumer-2", "ctrl-1", "ctrl-2", "grid-main"],
        )

    def _normalize(self, config: DataPointConfig) -> DataPointConfig:
        def ensure_ids(items, prefix: str) -> None:
            used = set()
            for idx, item in enumerate(items, start=1):
                if not item.id:
                    item.id = f"{prefix}-{idx}"
                if item.id in used:
                    item.id = f"{prefix}-{idx}-dup"
                used.add(item.id)

        ensure_ids(config.generators, "gen")
        ensure_ids(config.consumers, "consumer")
        ensure_ids(config.controllable_consumers, "ctrl")

        if not config.grid.id:
            config.grid.id = "grid-main"

        all_ids = [
            *(g.id for g in config.generators),
            *(c.id for c in config.consumers),
            *(c.id for c in config.controllable_consumers),
            config.grid.id,
        ]

        filtered = [device_id for device_id in config.device_order if device_id in all_ids]
        missing = [device_id for device_id in all_ids if device_id not in filtered]
        config.device_order = [*filtered, *missing]
        return config

    def _migrate_legacy_payload(self, payload: dict) -> dict:
        """Map old grid power fields to the new single-point schema."""
        grid = payload.get("grid")
        if not isinstance(grid, dict):
            return payload

        if "power_state_key" not in grid or not grid.get("power_state_key"):
            # Prefer import key for legacy configs; fallback to export key if needed.
            grid["power_state_key"] = grid.get("import_power_state_key") or grid.get("export_power_state_key") or ""

        if "power_source" not in grid or not grid.get("power_source"):
            grid["power_source"] = grid.get("import_power_source") or grid.get("export_power_source") or "iobroker"

        if "power_sign" not in grid or not grid.get("power_sign"):
            grid["power_sign"] = "import_positive"

        return payload

    def load(self) -> DataPointConfig:
        if not self._path.exists():
            config = self._default()
            self.save(config)
            return config

        payload = json.loads(self._path.read_text(encoding="utf-8"))
        payload = self._migrate_legacy_payload(payload)
        config = DataPointConfig.model_validate(payload)
        normalized = self._normalize(config)
        self.save(normalized)
        return normalized

    def save(self, config: DataPointConfig) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(config.model_dump(mode="json"), ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
