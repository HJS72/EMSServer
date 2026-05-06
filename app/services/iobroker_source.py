from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

import httpx

from app.config import Settings
from app.services.influx_source import SeriesPoint


class IoBrokerSource:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _auth(self) -> tuple[str, str] | None:
        if self.settings.iobroker_username and self.settings.iobroker_password:
            return (self.settings.iobroker_username, self.settings.iobroker_password)
        return None

    async def get_current_value(self, state_id: str) -> float | None:
        base = self.settings.iobroker_url.rstrip("/")
        url = f"{base}/getPlainValue/{state_id}"

        try:
            async with httpx.AsyncClient(timeout=10.0, auth=self._auth()) as client:
                response = await client.get(url)
                response.raise_for_status()
                raw = response.text.strip()
                if raw == "" or raw.lower() == "null":
                    return None
                try:
                    return float(raw)
                except ValueError:
                    return None
        except Exception:
            return None

    async def get_state_value(self, state_id: str) -> float | None:
        """Alias for get_current_value for compatibility."""
        return await self.get_current_value(state_id)

    def get_history(
        self,
        state_id: str,
        date_from: datetime,
        date_to: datetime,
        aggregate: str = "average",
        count: int = 500,
    ) -> list[SeriesPoint]:
        base = self.settings.iobroker_url.rstrip("/")
        encoded_state = quote(state_id, safe="")
        url = (
            f"{base}/query/{encoded_state}/?dateFrom={quote(date_from.isoformat())}"
            f"&dateTo={quote(date_to.isoformat())}&noHistory=false&aggregate={aggregate}&count={count}"
        )

        try:
            with httpx.Client(timeout=20.0, auth=self._auth()) as client:
                response = client.get(url)
                response.raise_for_status()
                payload = response.json()
        except Exception:
            return []

        points: list[SeriesPoint] = []
        if not isinstance(payload, list):
            return points

        for item in payload:
            if not isinstance(item, dict):
                continue
            value = item.get("val")
            timestamp = item.get("ts")
            if value is None or timestamp is None:
                continue
            try:
                ts = datetime.fromtimestamp(float(timestamp) / 1000.0).astimezone()
                points.append(SeriesPoint(time=ts, value=float(value)))
            except (TypeError, ValueError):
                continue

        return points
