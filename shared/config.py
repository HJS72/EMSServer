"""Konfigurationsmodelle und Loader fuer den EMS-Server."""
from __future__ import annotations

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
