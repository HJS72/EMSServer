"""Konfigurationsmodelle und Loader fuer den EMS-Server."""
from __future__ import annotations

import json
import os
from typing import List

import yaml
from pydantic import BaseModel, Field


class IoBrokerConfig(BaseModel):
    host: str
    port: int = 8087
    timeout: int = 5


class InfluxConfig(BaseModel):
    url: str
    token: str
    org: str = "ems"
    bucket_raw: str = "ems_raw"
    bucket_agg: str = "ems_agg"
    bucket_forecast: str = "ems_forecast"
    bucket_control: str = "ems_control"


class SQLiteConfig(BaseModel):
    path: str = "/var/lib/ems/ems.db"


class CollectorConfig(BaseModel):
    poll_interval_s: int = 10
    agg_interval_s: int = 900  # 15 Minuten


class DataPoint(BaseModel):
    id: str           # ioBroker State-ID, z. B. "modbus.0.pv_power"
    alias: str        # interner Name, eindeutig
    measurement: str  # InfluxDB Measurement
    device_id: str
    device_type: str  # pv | battery | ev | hp | climate | grid | base_load | weather | context
    unit: str
    scale: float = 1.0
    writable: bool = False


class EMSConfig(BaseModel):
    site: str = "home"
    iobroker: IoBrokerConfig
    influxdb: InfluxConfig
    sqlite: SQLiteConfig = Field(default_factory=SQLiteConfig)
    collector: CollectorConfig = Field(default_factory=CollectorConfig)
    datapoints: List[DataPoint] = []


def load_config(path: str | None = None) -> EMSConfig:
    config_path = path or os.environ.get("EMS_CONFIG", "/etc/ems/config.yaml")
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    # InfluxDB-Token kann per Umgebungsvariable ueberschrieben werden
    if token := os.environ.get("EMS_INFLUX_TOKEN"):
        raw.setdefault("influxdb", {})["token"] = token
    return EMSConfig(**raw)


def load_device_config(path: str | None = None) -> dict:
    """Lade Device-Konfiguration aus JSON."""
    import json
    device_path = path or os.environ.get("EMS_DEVICES_CONFIG", "/etc/ems/devices.json")
    if not os.path.exists(device_path):
        return {"devices": []}
    with open(device_path) as f:
        return json.load(f)


def devices_to_datapoints(devices_config: dict) -> List[DataPoint]:
    """Konvertiere Device-Config zu Datenpunkten für Collector."""
    datapoints = []
    for device in devices_config.get("devices", []):
        if not device.get("enabled", True):
            continue
        
        device_id = device.get("id")
        device_name = device.get("name")
        device_type = device.get("type")
        
        for measurement_key, measurement in device.get("measurements", {}).items():
            iobroker_id = measurement.get("iobroker_id", "")
            if not iobroker_id:
                continue
            
            # Alias: device_id + measurement_key
            alias = f"{device_id}_{measurement_key}"
            
            dp = DataPoint(
                id=iobroker_id,
                alias=alias,
                measurement=f"{device_type}_{measurement_key}",  # z.B. "grid_power", "producer_energy"
                device_id=device_id,
                device_type=device_type,
                unit=measurement.get("unit", ""),
                scale=measurement.get("scale", 1.0),
                writable=measurement.get("writable", False),
            )
            datapoints.append(dp)
    
    return datapoints
