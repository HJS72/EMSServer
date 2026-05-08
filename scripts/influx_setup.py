#!/usr/bin/env python3
"""InfluxDB 2.x: Buckets und Retention anlegen.

Aufruf:
    EMS_INFLUX_TOKEN=mytoken python scripts/influx_setup.py \
        --url http://10.13.30.221:8086 --org ems

Oder mit config.yaml:
    EMS_CONFIG=/etc/ems/config.yaml python scripts/influx_setup.py
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from influxdb_client import InfluxDBClient
from influxdb_client.domain.bucket_retention_rules import BucketRetentionRules

BUCKETS = [
    # (name, retention_days)  0 = unbegrenzt
    ("ems_raw",      30),
    ("ems_agg",      730),
    ("ems_forecast", 180),
    ("ems_control",  365),
]


def setup_buckets(url: str, token: str, org: str) -> None:
    client = InfluxDBClient(url=url, token=token, org=org)
    buckets_api = client.buckets_api()

    for name, days in BUCKETS:
        existing = buckets_api.find_bucket_by_name(name)
        if existing:
            print(f"  [OK] Bucket '{name}' existiert bereits.")
            continue

        retention = (
            [BucketRetentionRules(type="expire", every_seconds=days * 86400)]
            if days > 0
            else []
        )
        buckets_api.create_bucket(bucket_name=name, retention_rules=retention, org=org)
        label = f"{days}d" if days else "unbegrenzt"
        print(f"  [+] Bucket '{name}' angelegt (Retention: {label}).")

    client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="InfluxDB Buckets anlegen")
    parser.add_argument("--url",   default=os.environ.get("EMS_INFLUX_URL",   "http://10.13.30.221:8086"))
    parser.add_argument("--token", default=os.environ.get("EMS_INFLUX_TOKEN", ""))
    parser.add_argument("--org",   default=os.environ.get("EMS_INFLUX_ORG",   "ems"))
    args = parser.parse_args()

    if not args.token:
        # Fallback: aus config.yaml lesen
        try:
            from shared.config import load_config
            cfg = load_config()
            args.url   = cfg.influxdb.url
            args.token = cfg.influxdb.token
            args.org   = cfg.influxdb.org
        except Exception as e:
            sys.exit(f"Kein Token angegeben und config.yaml nicht lesbar: {e}")

    print(f"Verbinde mit {args.url} (org={args.org}) ...")
    setup_buckets(args.url, args.token, args.org)
    print("Fertig.")


if __name__ == "__main__":
    main()
