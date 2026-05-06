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
    name: str
    state_key: str


class ConfigControllableConsumer(BaseModel):
    name: str
    state_key: str
    control_key: str = ""


class ConfigGenerator(BaseModel):
    name: str
    state_key: str
    has_battery: bool = False


class ConfigGrid(BaseModel):
    import_state_key: str = "EMS.Grid.Energie.in"
    export_state_key: str = "EMS.Grid.Energie.out"


class DataPointConfig(BaseModel):
    consumers: list[ConfigConsumer] = Field(default_factory=list)
    controllable_consumers: list[ConfigControllableConsumer] = Field(default_factory=list)
    generators: list[ConfigGenerator] = Field(default_factory=list)
    grid: ConfigGrid = Field(default_factory=ConfigGrid)
