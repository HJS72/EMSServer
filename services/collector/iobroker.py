"""Asynchroner Client fuer die ioBroker simple-api."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx

logger = logging.getLogger(__name__)


class IoBrokerClient:
    """Liest und schreibt ioBroker States ueber die simple-api (HTTP)."""

    def __init__(self, host: str, port: int = 8087, timeout: int = 5) -> None:
        self._base = f"http://{host}:{port}"
        self._timeout = timeout

    async def get_bulk(self, state_ids: List[str]) -> List[Dict[str, Any]]:
        """Liest mehrere States auf einmal via /getBulk.

        Rueckgabe: Liste von {"id": ..., "val": ..., "ts": ..., "ack": ..., "q": ...}
        """
        if not state_ids:
            return []
        query = "&".join(state_ids)
        url = f"{self._base}/getBulk?{query}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list):
                logger.warning("Unerwartetes getBulk-Format: %s", type(data))
                return []
            return data

    async def set_value(self, state_id: str, value: Any) -> bool:
        """Schreibt einen Sollwert in einen ioBroker State."""
        url = f"{self._base}/set/{state_id}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(url, params={"value": str(value)})
            resp.raise_for_status()
            return "true" in resp.text.lower()
