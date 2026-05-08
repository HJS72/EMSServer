"""Thin wrapper um den offiziellen influxdb-client."""
from __future__ import annotations

import logging
from typing import Sequence

from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS
from influxdb_client.client.write.point import Point

logger = logging.getLogger(__name__)


class InfluxWriter:
    def __init__(self, url: str, token: str, org: str) -> None:
        self._client = InfluxDBClient(url=url, token=token, org=org)
        self._write_api = self._client.write_api(write_options=SYNCHRONOUS)
        self.org = org

    def write_points(self, bucket: str, points: Sequence[Point]) -> None:
        if not points:
            return
        try:
            self._write_api.write(bucket=bucket, org=self.org, record=list(points))
        except Exception:
            logger.exception("InfluxDB write fehlgeschlagen (bucket=%s)", bucket)

    def close(self) -> None:
        self._write_api.close()
        self._client.close()
