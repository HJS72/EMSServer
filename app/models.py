from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class HourPoint(BaseModel):
    time: datetime
    consumption_kwh: float = Field(ge=0)
    pv_kwh: float = Field(ge=0)
    net_grid_kwh: float


class ForecastResponse(BaseModel):
    created_at: datetime
    source: str
    points: list[HourPoint]


class ActualsResponse(BaseModel):
    created_at: datetime
    points: list[HourPoint]


class ComparePoint(BaseModel):
    time: datetime
    forecast_consumption_kwh: float
    actual_consumption_kwh: float | None
    forecast_pv_kwh: float
    actual_pv_kwh: float | None


class CompareResponse(BaseModel):
    created_at: datetime
    points: list[ComparePoint]


class ConfigConsumer(BaseModel):
    id: str = ""
    name: str
    state_key: str
    power_state_key: str = ""  # Leistung in W aus ioBroker
    source: str = "influx"  # "influx" oder "iobroker" für Energie
    power_source: str = "iobroker"  # Leistung kommt typischerweise von ioBroker


class ConfigControllableConsumer(BaseModel):
    id: str = ""
    name: str
    state_key: str
    power_state_key: str = ""  # Leistung in W aus ioBroker
    control_key: str = ""
    source: str = "influx"  # "influx" oder "iobroker" für Energie
    power_source: str = "iobroker"  # Leistung kommt typischerweise von ioBroker


class ConfigGenerator(BaseModel):
    id: str = ""
    name: str
    state_key: str
    power_state_key: str = ""  # Leistung in W aus ioBroker
    has_battery: bool = False
    source: str = "influx"  # "influx" oder "iobroker" für Energie
    power_source: str = "iobroker"  # Leistung kommt typischerweise von ioBroker
    # Optional: separate PV power datapoint (if empty, power_state_key is used).
    pv_power_state_key: str = ""
    pv_power_source: str = "iobroker"
    # Hybrid battery data points.
    battery_soc_state_key: str = ""
    battery_soc_source: str = "iobroker"
    battery_power_state_key: str = ""
    battery_power_source: str = "iobroker"
    battery_capacity_wh_state_key: str = ""
    # "charge_positive": +W means charging, -W means discharging.
    # "discharge_positive": +W means discharging, -W means charging.
    battery_power_sign: str = "charge_positive"
    # Minimum SOC (%) to which discharging is allowed.
    battery_rest_soc_percent: float = 0.0
    # Installed battery capacity for ETA calculation.
    battery_capacity_kwh: float = 0.0
    # Per-installation forecast parameters for forecast.solar.
    forecast_enabled: bool = False
    forecast_lat: float | None = None
    forecast_lon: float | None = None
    forecast_kwp: float | None = None
    forecast_azimuth: float | None = None
    forecast_declination: float | None = None


class ConfigGrid(BaseModel):
    id: str = "grid-main"
    import_state_key: str = "EMS.Grid.Energie.in"
    export_state_key: str = "EMS.Grid.Energie.out"
    power_state_key: str = ""   # Einzelner Leistungs-Datenpunkt (W), Vorzeichen per power_sign
    # "import_positive": positiv = Bezug, negativ = Einspeisung
    # "export_positive": positiv = Einspeisung, negativ = Bezug
    power_sign: str = "import_positive"
    import_source: str = "influx"
    export_source: str = "influx"
    power_source: str = "iobroker"


class DataPointConfig(BaseModel):
    consumers: list[ConfigConsumer] = Field(default_factory=list)
    controllable_consumers: list[ConfigControllableConsumer] = Field(default_factory=list)
    generators: list[ConfigGenerator] = Field(default_factory=list)
    grid: ConfigGrid = Field(default_factory=ConfigGrid)
    device_order: list[str] = Field(default_factory=list)
