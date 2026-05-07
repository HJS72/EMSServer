from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
import logging
from typing import Any

import httpx

from app.config import Settings
from app.services.datapoint_config import DataPointConfigService


class PvForecastService:
    def __init__(self, settings: Settings, config_service: DataPointConfigService) -> None:
        self.settings = settings
        self.config_service = config_service
        self._log = logging.getLogger(__name__)

    async def _fetch_hourly_forecast(self, lat: float, lon: float, decl: float, azimuth: float, kwp: float) -> dict[int, float]:
        url = f"https://api.forecast.solar/estimate/{lat}/{lon}/{decl}/{azimuth}/{kwp}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()

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

    def _configured_pv_systems(self) -> list[dict[str, Any]]:
        systems: list[dict[str, Any]] = []
        try:
            config = self.config_service.load()
            for gen in config.generators:
                if not getattr(gen, "forecast_enabled", True):
                    continue

                lat = getattr(gen, "forecast_lat", None)
                lon = getattr(gen, "forecast_lon", None)
                kwp = getattr(gen, "forecast_kwp", None)
                azimuth = getattr(gen, "forecast_azimuth", None)
                declination = getattr(gen, "forecast_declination", None)

                if None in (lat, lon, kwp, azimuth, declination):
                    continue
                if float(kwp) <= 0:
                    continue

                systems.append(
                    {
                        "name": gen.name or gen.id,
                        "lat": float(lat),
                        "lon": float(lon),
                        "kwp": float(kwp),
                        "azimuth": float(azimuth),
                        "declination": float(declination),
                    }
                )
        except Exception as exc:
            self._log.warning("Could not load datapoint config for PV systems, using env fallback: %s", exc)

        if systems:
            return systems

        return [
            {
                "name": "default-env",
                "lat": self.settings.pv_lat,
                "lon": self.settings.pv_lon,
                "kwp": self.settings.pv_kwp,
                "azimuth": self.settings.pv_azimuth,
                "declination": self.settings.pv_declination,
            }
        ]

    async def hourly_forecast_today(self) -> dict[int, float]:
        if self.settings.pv_provider.lower() != "forecast_solar":
            return {hour: 0.0 for hour in range(24)}

        systems = self._configured_pv_systems()
        tasks = [
            self._fetch_hourly_forecast(
                lat=system["lat"],
                lon=system["lon"],
                decl=system["declination"],
                azimuth=system["azimuth"],
                kwp=system["kwp"],
            )
            for system in systems
        ]

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        merged: dict[int, float] = {hour: 0.0 for hour in range(24)}
        successful = 0
        for idx, response in enumerate(responses):
            if isinstance(response, Exception):
                self._log.warning("PV forecast unavailable for %s: %s", systems[idx]["name"], response)
                continue
            successful += 1
            for hour in range(24):
                merged[hour] += max(0.0, float(response.get(hour, 0.0)))

        if successful == 0:
            self._log.warning("PV forecast unavailable for all systems, falling back to zeros")
            return {hour: 0.0 for hour in range(24)}

        return merged

    async def is_connected(self) -> bool:
        if self.settings.pv_provider.lower() != "forecast_solar":
            return False

        systems = self._configured_pv_systems()
        if not systems:
            return False

        probe = systems[0]
        url = (
            f"https://api.forecast.solar/estimate/"
            f"{probe['lat']}/{probe['lon']}/{probe['declination']}/{probe['azimuth']}/{probe['kwp']}"
        )

        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
            return isinstance(payload.get("result", {}).get("watt_hours_period", {}), dict)
        except Exception:
            return False
