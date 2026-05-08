#!/usr/bin/env python3
"""SQLite-Schema initialisieren.

Aufruf:
    python scripts/db_init.py [--db /var/lib/ems/ems.db]
"""
import argparse
import sys
from pathlib import Path

# Repo-Root zum Suchpfad hinzufuegen
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.db import init_schema


def main() -> None:
    parser = argparse.ArgumentParser(description="EMS SQLite-Schema initialisieren")
    parser.add_argument(
        "--db",
        default="/var/lib/ems/ems.db",
        help="Pfad zur SQLite-Datenbankdatei (Standard: /var/lib/ems/ems.db)",
    )
    args = parser.parse_args()
    init_schema(args.db)
    print(f"OK: Schema initialisiert in {args.db}")


if __name__ == "__main__":
    main()
