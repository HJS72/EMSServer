"""SQLite-Hilfsfunktionen: Verbindung, Schema-Init und einfache Abfragen."""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS devices (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    type              TEXT NOT NULL,
    enabled           INTEGER NOT NULL DEFAULT 1,
    min_power_w       REAL,
    max_power_w       REAL,
    soc_min           REAL,
    soc_max           REAL,
    control_state_id  TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS device_constraints (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    weekday_mask  INTEGER NOT NULL DEFAULT 127,  -- Bitmask Mo=1..So=64, 127=alle
    start_time    TEXT,   -- HH:MM
    end_time      TEXT,   -- HH:MM
    season_from   TEXT,   -- MM-DD
    season_to     TEXT,   -- MM-DD
    temp_min      REAL,
    temp_max      REAL
);

CREATE TABLE IF NOT EXISTS priorities (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario  TEXT NOT NULL DEFAULT 'default',
    rank      INTEGER NOT NULL,
    objective TEXT NOT NULL,  -- battery_evening | wwp | ev | climate
    weight    REAL NOT NULL DEFAULT 1.0,
    active    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS targets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type  TEXT NOT NULL UNIQUE,
    value        REAL NOT NULL,
    valid_from   TEXT,
    valid_to     TEXT,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS modes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    mode        TEXT NOT NULL CHECK(mode IN
                    ('AUTO', 'PLAN_ONLY', 'MANUAL_OVERRIDE', 'SAFE_FALLBACK')),
    changed_by  TEXT NOT NULL DEFAULT 'system',
    changed_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS forecast_runs (
    run_id           TEXT PRIMARY KEY,
    model_version    TEXT,
    horizon_minutes  INTEGER,
    interval_minutes INTEGER,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    status           TEXT NOT NULL DEFAULT 'pending',
    metrics_json     TEXT
);

CREATE TABLE IF NOT EXISTS optimizer_runs (
    run_id           TEXT PRIMARY KEY,
    forecast_run_id  TEXT REFERENCES forecast_runs(run_id),
    objective_value  REAL,
    status           TEXT NOT NULL DEFAULT 'pending',
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    plan_hash        TEXT
);

CREATE TABLE IF NOT EXISTS dispatch_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL DEFAULT (datetime('now')),
    device_id  TEXT NOT NULL,
    command    TEXT NOT NULL,
    value      REAL,
    status     TEXT NOT NULL DEFAULT 'pending',
    message    TEXT
);
"""

DEFAULT_DATA_SQL = """
INSERT OR IGNORE INTO priorities (scenario, rank, objective, weight, active) VALUES
    ('default', 1, 'battery_evening', 1.0, 1),
    ('default', 2, 'wwp',             1.0, 1),
    ('default', 3, 'ev',              1.0, 1),
    ('default', 4, 'climate',         0.5, 1);

INSERT OR IGNORE INTO targets (target_type, value) VALUES
    ('battery_evening_soc', 90.0),
    ('ev_departure_soc',    80.0),
    ('wwp_temp_min',        55.0),
    ('climate_temp_max',    26.0);

INSERT OR IGNORE INTO modes (mode, changed_by) VALUES ('PLAN_ONLY', 'setup');
"""


def get_connection(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(path: str) -> None:
    conn = get_connection(path)
    conn.executescript(SCHEMA_SQL)
    conn.executescript(DEFAULT_DATA_SQL)
    conn.commit()
    conn.close()
    logger.info("SQLite Schema initialisiert: %s", path)
