from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import json

from app.config import Settings
from app.models import CompareResponse, ComparePoint, ForecastResponse, HourPoint, ActualsResponse
from app.services.influx_source import InfluxSource
from app.services.iobroker_source import IoBrokerSource
from app.services.pv_forecast import PvForecastService
from app.services.storage import Storage


class ForecastEngine:
    def __init__(
        self,
        settings: Settings,
        influx: InfluxSource,
        iobroker: IoBrokerSource,
        pv_service: PvForecastService,
        storage: Storage,
    ) -> None:
        self.settings = settings
        self.influx = influx
        self.iobroker = iobroker
        self.pv_service = pv_service
        self.storage = storage

    def _safe_influx_history(self, state_key: str, days: int, custom_query: str = ""):
        try:
            return self.influx.hourly_history(state_key=state_key, days=days, custom_query=custom_query)
        except Exception:
            return []

    def _safe_influx_today(self, state_key: str, custom_query: str = ""):
        try:
            return self.influx.hourly_today(state_key=state_key, custom_query=custom_query)
        except Exception:
            return []

    def _safe_iobroker_history(self, state_key: str, days: int):
        try:
            now = datetime.now().astimezone()
            start = now - timedelta(days=days)
            return self.iobroker.get_history(state_id=state_key, date_from=start, date_to=now, aggregate="average", count=max(24 * days, 24))
        except Exception:
            return []

    def _safe_iobroker_today(self, state_key: str):
        try:
            now = datetime.now().astimezone()
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return self.iobroker.get_history(state_id=state_key, date_from=start, date_to=now, aggregate="average", count=48)
        except Exception:
            return []

    def _hourly_grid_baseline(self) -> dict[int, float]:
        grid_import_history = self._safe_influx_history(
            state_key=self.settings.state_grid_import_key,
            days=self.settings.history_days,
            custom_query=self.settings.influx_grid_import_query,
        )
        if not grid_import_history:
            grid_import_history = self._safe_iobroker_history(self.settings.state_grid_import_key, self.settings.history_days)
        grid_export_history = self._safe_influx_history(
            state_key=self.settings.state_grid_export_key,
            days=self.settings.history_days,
            custom_query=self.settings.influx_grid_export_query,
        )
        if not grid_export_history:
            grid_export_history = self._safe_iobroker_history(self.settings.state_grid_export_key, self.settings.history_days)

        now_local = datetime.now().astimezone()
        grouped: dict[int, list[float]] = defaultdict(list)
        grouped_same_weekday: dict[int, list[float]] = defaultdict(list)
        by_timestamp: dict[datetime, float] = defaultdict(float)

        for point in grid_import_history:
            by_timestamp[point.time] += max(0.0, point.value) / 1000.0
        for point in grid_export_history:
            by_timestamp[point.time] -= max(0.0, point.value) / 1000.0

        for ts, value in by_timestamp.items():
            local_time = ts.astimezone(now_local.tzinfo)
            grouped[local_time.hour].append(value)
            if local_time.weekday() == now_local.weekday():
                grouped_same_weekday[local_time.hour].append(value)

        baseline: dict[int, float] = {}
        for hour in range(24):
            values = grouped.get(hour, [])
            values_same = grouped_same_weekday.get(hour, [])
            if values and values_same:
                baseline[hour] = (sum(values) + 2 * sum(values_same)) / (len(values) + 2 * len(values_same))
            elif values:
                baseline[hour] = sum(values) / len(values)
            else:
                baseline[hour] = 0.0

        return baseline

    def _hourly_consumption_baseline(self) -> dict[int, float]:
        history = []
        if self.settings.state_consumption_key:
            history = self._safe_influx_history(
                state_key=self.settings.state_consumption_key,
                days=self.settings.history_days,
                custom_query=self.settings.influx_consumption_query,
            )
            if not history:
                history = self._safe_iobroker_history(self.settings.state_consumption_key, self.settings.history_days)

        now_local = datetime.now().astimezone()
        grouped: dict[int, list[float]] = defaultdict(list)
        grouped_same_weekday: dict[int, list[float]] = defaultdict(list)

        for point in history:
            local_time = point.time.astimezone(now_local.tzinfo)
            value = max(0.0, point.value) / 1000.0
            grouped[local_time.hour].append(value)
            if local_time.weekday() == now_local.weekday():
                grouped_same_weekday[local_time.hour].append(value)

        baseline: dict[int, float] = {}
        for hour in range(24):
            values = grouped.get(hour, [])
            values_same = grouped_same_weekday.get(hour, [])
            if values and values_same:
                baseline[hour] = (sum(values) + 2 * sum(values_same)) / (len(values) + 2 * len(values_same))
            elif values:
                baseline[hour] = sum(values) / len(values)
            else:
                baseline[hour] = 0.0

        return baseline

    async def build_today_forecast(self) -> ForecastResponse:
        consumption_hourly = self._hourly_consumption_baseline()
        grid_hourly = self._hourly_grid_baseline()
        pv_hourly = await self.pv_service.hourly_forecast_today()

        now = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
        points: list[HourPoint] = []

        for idx in range(self.settings.forecast_hours):
            ts = now.replace(hour=0) + timedelta(hours=idx)
            hour = ts.hour
            consumption = round(max(0.0, consumption_hourly.get(hour, 0.0)), 3)
            pv = round(max(0.0, pv_hourly.get(hour, 0.0)), 3)
            net_grid = round(grid_hourly.get(hour, consumption - pv), 3)
            points.append(
                HourPoint(
                    time=ts,
                    consumption_kwh=consumption,
                    pv_kwh=pv,
                    net_grid_kwh=net_grid,
                )
            )

        response = ForecastResponse(
            created_at=datetime.now().astimezone(),
            source="history+pv_online",
            points=points,
        )

        payload = response.model_dump(mode="json")
        self.storage.save_latest(payload)
        self.storage.save_daily_archive(payload)
        return response

    def load_cached_forecast(self) -> ForecastResponse | None:
        payload = self.storage.load_latest()
        if not payload:
            return None
        return ForecastResponse.model_validate(payload)

    async def build_today_actuals(self) -> ActualsResponse:
        consumption_series = []
        if self.settings.state_consumption_key:
            consumption_series = self._safe_influx_today(
                state_key=self.settings.state_consumption_key,
                custom_query=self.settings.influx_consumption_query,
            )
            if not consumption_series:
                consumption_series = self._safe_iobroker_today(self.settings.state_consumption_key)
        pv_series = []
        if self.settings.state_pv_key:
            pv_series = self._safe_influx_today(
                state_key=self.settings.state_pv_key,
                custom_query=self.settings.influx_pv_query,
            )
            if not pv_series:
                pv_series = self._safe_iobroker_today(self.settings.state_pv_key)
        grid_import_series = self._safe_influx_today(
            state_key=self.settings.state_grid_import_key,
            custom_query=self.settings.influx_grid_import_query,
        )
        if not grid_import_series:
            grid_import_series = self._safe_iobroker_today(self.settings.state_grid_import_key)
        grid_export_series = self._safe_influx_today(
            state_key=self.settings.state_grid_export_key,
            custom_query=self.settings.influx_grid_export_query,
        )
        if not grid_export_series:
            grid_export_series = self._safe_iobroker_today(self.settings.state_grid_export_key)

        now_tz = datetime.now().astimezone().tzinfo
        by_hour_consumption: dict[int, float] = {p.time.astimezone(now_tz).hour: max(0.0, p.value) / 1000.0 for p in consumption_series}
        by_hour_pv: dict[int, float] = {p.time.astimezone(now_tz).hour: max(0.0, p.value) / 1000.0 for p in pv_series}
        by_hour_grid_import: dict[int, float] = {p.time.astimezone(now_tz).hour: max(0.0, p.value) / 1000.0 for p in grid_import_series}
        by_hour_grid_export: dict[int, float] = {p.time.astimezone(now_tz).hour: max(0.0, p.value) / 1000.0 for p in grid_export_series}

        points: list[HourPoint] = []
        day_start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        for hour in range(24):
            consumption = round(by_hour_consumption.get(hour, 0.0), 3)
            pv = round(by_hour_pv.get(hour, 0.0), 3)
            net_grid = round(by_hour_grid_import.get(hour, consumption - pv) - by_hour_grid_export.get(hour, 0.0), 3)
            points.append(
                HourPoint(
                    time=day_start + timedelta(hours=hour),
                    consumption_kwh=consumption,
                    pv_kwh=pv,
                    net_grid_kwh=net_grid,
                )
            )

        try:
            current_consumption = None
            if self.settings.state_consumption_key:
                current_consumption = await self.iobroker.get_current_value(self.settings.state_consumption_key)
            current_pv = None
            if self.settings.state_pv_key:
                current_pv = await self.iobroker.get_current_value(self.settings.state_pv_key)
            now_hour = datetime.now().astimezone().hour
            if current_consumption is not None:
                points[now_hour].consumption_kwh = round(max(0.0, current_consumption) / 1000.0, 3)
            if current_pv is not None:
                points[now_hour].pv_kwh = round(max(0.0, current_pv) / 1000.0, 3)
            if now_hour not in by_hour_grid_import and now_hour not in by_hour_grid_export:
                points[now_hour].net_grid_kwh = round(points[now_hour].consumption_kwh - points[now_hour].pv_kwh, 3)
        except Exception:
            pass

        return ActualsResponse(created_at=datetime.now().astimezone(), points=points)

    async def build_today_compare(self) -> CompareResponse:
        forecast = self.load_cached_forecast()
        if forecast is None:
            forecast = await self.build_today_forecast()

        actuals = await self.build_today_actuals()
        actual_by_hour = {p.time.hour: p for p in actuals.points}

        points: list[ComparePoint] = []
        for p in forecast.points:
            actual = actual_by_hour.get(p.time.hour)
            points.append(
                ComparePoint(
                    time=p.time,
                    forecast_consumption_kwh=p.consumption_kwh,
                    actual_consumption_kwh=actual.consumption_kwh if actual else None,
                    forecast_pv_kwh=p.pv_kwh,
                    actual_pv_kwh=actual.pv_kwh if actual else None,
                )
            )

        return CompareResponse(created_at=datetime.now().astimezone(), points=points)

    def build_history_daily(self, days: int) -> dict[str, list[dict[str, float | str]]]:
        consumption_history = self._safe_influx_history(
            state_key=self.settings.state_consumption_key,
            days=days,
            custom_query=self.settings.influx_consumption_query,
        )
        if not consumption_history:
            consumption_history = self._safe_iobroker_history(self.settings.state_consumption_key, days)
        pv_history = self._safe_influx_history(
            state_key=self.settings.state_pv_key,
            days=days,
            custom_query=self.settings.influx_pv_query,
        )
        if not pv_history:
            pv_history = self._safe_iobroker_history(self.settings.state_pv_key, days)
        grid_import_history = self._safe_influx_history(
            state_key=self.settings.state_grid_import_key,
            days=days,
            custom_query=self.settings.influx_grid_import_query,
        )
        if not grid_import_history:
            grid_import_history = self._safe_iobroker_history(self.settings.state_grid_import_key, days)
        grid_export_history = self._safe_influx_history(
            state_key=self.settings.state_grid_export_key,
            days=days,
            custom_query=self.settings.influx_grid_export_query,
        )
        if not grid_export_history:
            grid_export_history = self._safe_iobroker_history(self.settings.state_grid_export_key, days)

        tz = datetime.now().astimezone().tzinfo
        actual_day_totals: dict[str, dict[str, float]] = defaultdict(lambda: {"consumption_kwh": 0.0, "pv_kwh": 0.0, "net_grid_kwh": 0.0})

        for p in consumption_history:
            day = p.time.astimezone(tz).strftime("%Y-%m-%d")
            actual_day_totals[day]["consumption_kwh"] += max(0.0, p.value) / 1000.0

        for p in pv_history:
            day = p.time.astimezone(tz).strftime("%Y-%m-%d")
            actual_day_totals[day]["pv_kwh"] += max(0.0, p.value) / 1000.0

        for p in grid_import_history:
            day = p.time.astimezone(tz).strftime("%Y-%m-%d")
            actual_day_totals[day]["net_grid_kwh"] += max(0.0, p.value) / 1000.0

        for p in grid_export_history:
            day = p.time.astimezone(tz).strftime("%Y-%m-%d")
            actual_day_totals[day]["net_grid_kwh"] -= max(0.0, p.value) / 1000.0

        actual = [
            {
                "day": day,
                "consumption_kwh": round(values["consumption_kwh"], 3),
                "pv_kwh": round(values["pv_kwh"], 3),
                "net_grid_kwh": round(values["net_grid_kwh"] if values["net_grid_kwh"] else values["consumption_kwh"] - values["pv_kwh"], 3),
            }
            for day, values in sorted(actual_day_totals.items())
        ]

        forecast: list[dict[str, float | str]] = []
        for file in sorted(self.storage.archive_dir.glob("forecast-*.json")):
            try:
                payload = json.loads(file.read_text(encoding="utf-8"))
            except Exception:
                continue

            points = payload.get("points", [])
            day = file.stem.replace("forecast-", "")
            consumption = sum(float(p.get("consumption_kwh", 0.0)) for p in points)
            pv = sum(float(p.get("pv_kwh", 0.0)) for p in points)
            forecast.append(
                {
                    "day": day,
                    "consumption_kwh": round(consumption, 3),
                    "pv_kwh": round(pv, 3),
                    "net_grid_kwh": round(consumption - pv, 3),
                }
            )

        return {"actual": actual, "forecast": forecast[-days:]}
