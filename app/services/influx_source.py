from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from influxdb_client import InfluxDBClient
from influxdb_client.client.query_api import QueryApi

from app.config import Settings


@dataclass
class SeriesPoint:
    time: datetime
    value: float


class InfluxSource:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = InfluxDBClient(
            url=settings.influx_url,
            token=settings.influx_token,
            org=settings.influx_org,
            timeout=30_000,
        )
        self._query_api: QueryApi = self._client.query_api()

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _escape_flux_string(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _build_default_query(self, state_key: str, start: datetime, stop: datetime) -> str:
        bucket = self.settings.influx_bucket
        measurement = self.settings.influx_measurement
        tag_key = self.settings.influx_tag_key
        value_field = self.settings.influx_value_field

        start_iso = start.astimezone(timezone.utc).isoformat()
        stop_iso = stop.astimezone(timezone.utc).isoformat()

        bucket_esc = self._escape_flux_string(bucket)
        measurement_esc = self._escape_flux_string(measurement)
        state_key_esc = self._escape_flux_string(state_key)
        value_field_esc = self._escape_flux_string(value_field)

        # ioBroker Influx setups can differ:
        # 1) measurement="iobroker" + tag id="state.id"
        # 2) measurement="state.id" directly (no id tag)
        if tag_key:
            tag_key_esc = self._escape_flux_string(tag_key)
            measurement_filter = f'r["_measurement"] == "{measurement_esc}"'
            state_filter = f'r["{tag_key_esc}"] == "{state_key_esc}"'
        else:
            measurement_filter = f'r["_measurement"] == "{state_key_esc}"'
            state_filter = "true"

        return f'''
from(bucket: "{bucket_esc}")
  |> range(start: {start_iso}, stop: {stop_iso})
    |> filter(fn: (r) => {measurement_filter})
    |> filter(fn: (r) => {state_filter})
    |> filter(fn: (r) => r["_field"] == "{value_field_esc}")
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: true)
  |> keep(columns: ["_time", "_value"])
'''

    def _query_hourly(self, query: str) -> list[SeriesPoint]:
        tables = self._query_api.query(query, org=self.settings.influx_org)
        points: list[SeriesPoint] = []
        for table in tables:
            for record in table.records:
                if record.get_value() is None:
                    continue
                ts = record.get_time()
                if ts is None:
                    continue
                points.append(SeriesPoint(time=ts, value=float(record.get_value())))
        return points

    def hourly_series(self, state_key: str, start: datetime, stop: datetime, custom_query: str = "") -> list[SeriesPoint]:
        query = custom_query.strip() or self._build_default_query(state_key, start, stop)
        return self._query_hourly(query)

    def hourly_history(self, state_key: str, days: int, custom_query: str = "") -> list[SeriesPoint]:
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)
        return self.hourly_series(state_key=state_key, start=start, stop=now, custom_query=custom_query)

    def hourly_today(self, state_key: str, custom_query: str = "") -> list[SeriesPoint]:
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return self.hourly_series(state_key=state_key, start=start, stop=now, custom_query=custom_query)

    async def get_latest_value(self, state_key: str, custom_query: str = "") -> float | None:
        """Get the latest value from today's data."""
        if not state_key:
            return None
        try:
            points = self.hourly_today(state_key, custom_query)
            if points:
                return points[-1].value
            return None
        except Exception:
            return None
