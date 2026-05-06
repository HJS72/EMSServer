from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import logging

import httpx

from app.config import Settings


class PvForecastService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._log = logging.getLogger(__name__)

    async def hourly_forecast_today(self) -> dict[int, float]:
        if self.settings.pv_provider.lower() != "forecast_solar":
            return {hour: 0.0 for hour in range(24)}

        lat = self.settings.pv_lat
        lon = self.settings.pv_lon
        decl = self.settings.pv_declination
        azimuth = self.settings.pv_azimuth
        kwp = self.settings.pv_kwp

        url = f"https://api.forecast.solar/estimate/{lat}/{lon}/{decl}/{azimuth}/{kwp}"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            # Keep API endpoints stable when forecast.solar rate-limits or is unreachable.
            self._log.warning("PV forecast unavailable, falling back to zeros: %s", exc)
            return {hour: 0.0 for hour in range(24)}

        periods = payload.get("result", {}).get("watt_hours_period", {})
        by_hour: dict[int, float] = defaultdict(float)
        now_local = datetime.now().astimezone()

        for ts, wh in periods.items():
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(now_local.tzinfo)
            if dt.date() != now_local.date():
                continue
            by_hour[dt.hour] += float(wh) / 1000.0

        for hour in range(24):
            by_hour[hour] = max(0.0, by_hour.get(hour, 0.0))

        return dict(by_hour)
