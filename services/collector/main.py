"""Collector-Service: Pollt ioBroker, schreibt Roh- und Aggregatwerte nach InfluxDB."""
from __future__ import annotations

import asyncio
import logging
import signal
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List

from influxdb_client.client.write.point import Point

from shared.config import DataPoint, EMSConfig, load_config
from shared.influx_client import InfluxWriter
from .iobroker import IoBrokerClient

logger = logging.getLogger(__name__)


class Collector:
    def __init__(self, config_path: str | None = None) -> None:
        self.cfg: EMSConfig = load_config(config_path)
        self.influx = InfluxWriter(
            url=self.cfg.influxdb.url,
            token=self.cfg.influxdb.token,
            org=self.cfg.influxdb.org,
        )
        self.iob = IoBrokerClient(
            host=self.cfg.iobroker.host,
            port=self.cfg.iobroker.port,
            timeout=self.cfg.iobroker.timeout,
        )
        # Puffer fuer laufende Aggregation: alias -> [float, ...]
        self._buffer: Dict[str, List[float]] = defaultdict(list)
        self._last_agg: float = time.monotonic()
        self._running = True
        self._alias_map: Dict[str, DataPoint] = {dp.alias: dp for dp in self.cfg.datapoints}
        self._id_map: Dict[str, DataPoint] = {dp.id: dp for dp in self.cfg.datapoints}

    def stop(self) -> None:
        self._running = False

    async def run(self) -> None:
        logger.info(
            "Collector gestartet | site=%s | poll=%ds | agg=%ds",
            self.cfg.site,
            self.cfg.collector.poll_interval_s,
            self.cfg.collector.agg_interval_s,
        )
        while self._running:
            try:
                await self._poll_once()
            except Exception:
                logger.exception("Poll-Zyklus fehlgeschlagen")
            await asyncio.sleep(self.cfg.collector.poll_interval_s)

    async def _poll_once(self) -> None:
        state_ids = [dp.id for dp in self.cfg.datapoints]
        now = datetime.now(timezone.utc)

        try:
            results = await self.iob.get_bulk(state_ids)
        except Exception:
            logger.exception("ioBroker getBulk fehlgeschlagen")
            return

        raw_points: List[Point] = []
        for item in results:
            state_id = item.get("id")
            raw_val = item.get("val")
            dp = self._id_map.get(state_id)

            if dp is None or raw_val is None:
                continue
            try:
                value = float(raw_val) * dp.scale
            except (ValueError, TypeError):
                logger.debug("Nicht-numerischer Wert fuer %s: %r", state_id, raw_val)
                continue

            raw_points.append(
                Point(dp.measurement)
                .tag("site", self.cfg.site)
                .tag("device_id", dp.device_id)
                .tag("device_type", dp.device_type)
                .tag("source", "iobroker")
                .field("value", value)
                .field("unit", dp.unit)
                .time(now)
            )
            self._buffer[dp.alias].append(value)

        if raw_points:
            self.influx.write_points(self.cfg.influxdb.bucket_raw, raw_points)
            logger.debug("Raw: %d Punkte geschrieben", len(raw_points))

        # Aggregation ausfuehren wenn Intervall abgelaufen
        elapsed = time.monotonic() - self._last_agg
        if elapsed >= self.cfg.collector.agg_interval_s:
            self._flush_aggregations(now)
            self._last_agg = time.monotonic()

    def _flush_aggregations(self, ts: datetime) -> None:
        agg_points: List[Point] = []
        for alias, values in self._buffer.items():
            if not values:
                continue
            dp = self._alias_map.get(alias)
            if dp is None:
                continue
            avg = sum(values) / len(values)
            agg_points.append(
                Point(dp.measurement)
                .tag("site", self.cfg.site)
                .tag("device_id", dp.device_id)
                .tag("device_type", dp.device_type)
                .tag("source", "iobroker")
                .tag("interval", "15m")
                .field("value", avg)
                .field("unit", dp.unit)
                .field("sample_count", len(values))
                .time(ts)
            )
        if agg_points:
            self.influx.write_points(self.cfg.influxdb.bucket_agg, agg_points)
            logger.info("Agg: %d Punkte geschrieben (15m-Mittel)", len(agg_points))
        self._buffer.clear()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    )

    collector = Collector()
    loop = asyncio.new_event_loop()

    def _shutdown(signum: int, _frame: object) -> None:
        logger.info("Shutdown-Signal empfangen (%d)", signum)
        collector.stop()
        loop.call_soon_threadsafe(loop.stop)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        loop.run_until_complete(collector.run())
    finally:
        collector.influx.close()
        loop.close()
        logger.info("Collector beendet")


if __name__ == "__main__":
    main()
