from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    timezone: str

    influx_url: str
    influx_token: str
    influx_org: str
    influx_bucket: str
    influx_measurement: str
    influx_tag_key: str
    influx_value_field: str
    influx_consumption_query: str
    influx_pv_query: str
    influx_grid_import_query: str
    influx_grid_export_query: str

    iobroker_url: str
    iobroker_username: str
    iobroker_password: str

    pv_provider: str
    pv_lat: float
    pv_lon: float
    pv_kwp: float
    pv_azimuth: float
    pv_declination: float

    state_consumption_key: str
    state_pv_key: str
    state_grid_import_key: str
    state_grid_export_key: str

    forecast_hours: int
    history_days: int
    data_dir: Path



def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()



def load_settings() -> Settings:
    data_dir = Path(_env("DATA_DIR", "./data"))
    data_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        host=_env("HOST", "0.0.0.0"),
        port=int(_env("PORT", "8080")),
        timezone=_env("TZ", "Europe/Berlin"),
        influx_url=_env("INFLUX_URL", "http://127.0.0.1:8086"),
        influx_token=_env("INFLUX_TOKEN", ""),
        influx_org=_env("INFLUX_ORG", ""),
        influx_bucket=_env("INFLUX_BUCKET", "iobroker"),
        influx_measurement=_env("INFLUX_MEASUREMENT", "iobroker"),
        influx_tag_key=_env("INFLUX_TAG_KEY", "id"),
        influx_value_field=_env("INFLUX_VALUE_FIELD", "value"),
        influx_consumption_query=_env("INFLUX_CONSUMPTION_QUERY", ""),
        influx_pv_query=_env("INFLUX_PV_QUERY", ""),
        influx_grid_import_query=_env("INFLUX_GRID_IMPORT_QUERY", ""),
        influx_grid_export_query=_env("INFLUX_GRID_EXPORT_QUERY", ""),
        iobroker_url=_env("IOBROKER_URL", "http://127.0.0.1:8087"),
        iobroker_username=_env("IOBROKER_USERNAME", ""),
        iobroker_password=_env("IOBROKER_PASSWORD", ""),
        pv_provider=_env("PV_FORECAST_PROVIDER", "forecast_solar"),
        pv_lat=float(_env("PV_FORECAST_LAT", "48.137")),
        pv_lon=float(_env("PV_FORECAST_LON", "11.575")),
        pv_kwp=float(_env("PV_FORECAST_KWP", "10.0")),
        pv_azimuth=float(_env("PV_FORECAST_AZIMUTH", "180")),
        pv_declination=float(_env("PV_FORECAST_DECLINATION", "35")),
        state_consumption_key=_env("STATE_CONSUMPTION_KEY", "house.power.consumption"),
        state_pv_key=_env("STATE_PV_KEY", "house.power.pv"),
        state_grid_import_key=_env("STATE_GRID_IMPORT_KEY", "EMS.Grid.Energie.in"),
        state_grid_export_key=_env("STATE_GRID_EXPORT_KEY", "EMS.Grid.Energie.out"),
        forecast_hours=int(_env("FORECAST_HOURS", "24")),
        history_days=int(_env("HISTORY_DAYS", "30")),
        data_dir=data_dir,
    )
