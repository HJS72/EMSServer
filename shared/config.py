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
    allow_negative: bool = False


class EMSConfig(BaseModel):
    site: str = "home"
    iobroker: IoBrokerConfig
    influxdb: InfluxConfig
    sqlite: SQLiteConfig = Field(default_factory=SQLiteConfig)
    collector: CollectorConfig = Field(default_factory=CollectorConfig)
    datapoints: List[DataPoint] = []


def _load_token_from_secrets_env(path: str = "/etc/ems/secrets.env") -> str | None:
    """Liest EMS_INFLUX_TOKEN aus einer einfachen KEY=VALUE-Datei."""
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip() == "EMS_INFLUX_TOKEN":
                    token = value.strip().strip('"').strip("'")
                    return token or None
    except Exception:
        return None
    return None


def load_config(path: str | None = None) -> EMSConfig:
    config_path = path or os.environ.get("EMS_CONFIG", "/etc/ems/config.yaml")
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    influx_cfg = raw.setdefault("influxdb", {})

    # InfluxDB-Token bevorzugt aus Umgebungsvariable.
    token = os.environ.get("EMS_INFLUX_TOKEN")
    if token:
        influx_cfg["token"] = token
    else:
        current = str(influx_cfg.get("token", "") or "").strip()
        # Fallback fuer Deployments mit Platzhalter in config.yaml.
        if (not current) or current.startswith("__REPLACE_WITH_"):
            fallback = _load_token_from_secrets_env()
            if fallback:
                influx_cfg["token"] = fallback
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

            unit = measurement.get("unit", "")
            scale = float(measurement.get("scale", 1.0))
            is_energy = "energy" in measurement_key.lower()

            # Energie-Werte werden konsistent in kWh gespeichert.
            if is_energy:
                if unit == "Wh":
                    scale = scale / 1000.0
                unit = "kWh"
            
            dp = DataPoint(
                id=iobroker_id,
                alias=alias,
                measurement=f"{device_type}_{measurement_key}",  # z.B. "grid_power", "producer_energy"
                device_id=device_id,
                device_type=device_type,
                unit=unit,
                scale=-scale if measurement.get("invert_sign", False) else scale,
                writable=measurement.get("writable", False),
                allow_negative=measurement.get("allow_negative", False),
            )
            datapoints.append(dp)
    
    return datapoints
