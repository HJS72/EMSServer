"""Standalone-Script: Forecast laden, Control-Plan berechnen, nach ioBroker schreiben.

Wird vom systemd-Timer ems-control-plan.service alle 15 Minuten ausgeführt.
Benötigt /etc/ems/latest_forecast.json (von generate_open_meteo_forecast.py erzeugt)
und /etc/ems/control_config.json für die Geräteparameter.

Exit-Codes:
  0 - Erfolg
  1 - Allgemeiner Fehler
  2 - Konfiguration fehlt
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

# Sicherstellen, dass das Projektverzeichnis im Python-Pfad ist
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx

from services.api.control_logic import ControlConfig, ControlPlanRequest, create_control_plan

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("run_control_plan")

# ============================================================================
# Konfiguration
# ============================================================================

FORECAST_FILE = Path("/etc/ems/latest_forecast.json")
CONTROL_CONFIG_FILE = Path("/etc/ems/control_config.json")
DEVICES_CONFIG_FILE = Path("/etc/ems/devices.json")
IOBROKER_HOST = "10.13.30.201"
IOBROKER_PORT = 8087
DASHBOARD_TIMEZONE = ZoneInfo("Europe/Berlin")

# ============================================================================
# Hilfsfunktionen
# ============================================================================


def load_control_config() -> Dict[str, Any]:
    if CONTROL_CONFIG_FILE.exists():
        with open(CONTROL_CONFIG_FILE) as f:
            data = json.load(f)
        cfg = ControlConfig(**data)
        return cfg.model_dump(exclude_none=True)
    return ControlConfig(
        iobroker_host=IOBROKER_HOST,
        iobroker_port=IOBROKER_PORT,
    ).model_dump(exclude_none=True)


def load_forecast_slots() -> List[Dict[str, Any]]:
    """Lädt die aktuellen Forecast-Slots und gibt nur Slots ab jetzt zurück."""
    if not FORECAST_FILE.exists():
        logger.error(f"Forecast-Datei nicht gefunden: {FORECAST_FILE}")
        sys.exit(2)

    with open(FORECAST_FILE) as f:
        data = json.load(f)

    slots = data.get("slots", [])
    now_utc = datetime.now(ZoneInfo("UTC"))

    future_slots = []
    for slot in slots:
        ts_str = slot.get("ts", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts >= now_utc:
                future_slots.append(slot)
        except ValueError:
            continue

    logger.info(f"Forecast: {len(slots)} Slots gesamt, {len(future_slots)} ab jetzt")
    return future_slots


async def get_iobroker_states(host: str, port: int) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"http://{host}:{port}/getStates")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.warning(f"ioBroker-States nicht abrufbar: {e}")
        return {}


def _coerce_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _measurement_iobroker_id(device: Any, key: str) -> Optional[str]:
    m = device.measurements.get(key)
    if not m:
        return None
    return m.iobroker_id or None


async def merge_live_states(config: Dict[str, Any]) -> Dict[str, Any]:
    """Ergänzt Live-Temperaturen/SOC aus ioBroker in die Steuerkonfiguration."""
    try:
        from services.api.app import load_devices_config
        from shared.device_models import DeviceType
    except ImportError:
        logger.warning("Konnte Device-Konfiguration nicht importieren – überspringe Live-State-Merge")
        return config

    try:
        devices_config = load_devices_config()
    except Exception as e:
        logger.warning(f"Fehler beim Laden der Device-Konfiguration: {e}")
        return config

    host = config.get("iobroker_host", IOBROKER_HOST)
    port = config.get("iobroker_port", IOBROKER_PORT)
    states = await get_iobroker_states(host, port)

    relevant = {
        "dhw": DeviceType.DHW,
        "climate": DeviceType.CLIMATE,
        "wallbox": DeviceType.WALLBOX,
    }

    for section, device_type in relevant.items():
        device = next(
            (d for d in devices_config.devices if d.enabled and d.type == device_type),
            None,
        )
        if not device:
            continue

        section_cfg = config.get(section)
        if not isinstance(section_cfg, dict):
            section_cfg = {}
        config[section] = section_cfg
        section_cfg.setdefault("device_id", device.id)

        if section == "dhw":
            if not section_cfg.get("command_state_id"):
                sid = _measurement_iobroker_id(device, "enabled")
                if sid:
                    section_cfg["command_state_id"] = sid
            if not section_cfg.get("status_state_id"):
                sid = _measurement_iobroker_id(device, "windows")
                if sid:
                    section_cfg["status_state_id"] = sid
            # Immer Live-Temperatur aus ioBroker holen wenn State gemappt
            temp_id = _measurement_iobroker_id(device, "temp_water")
            if temp_id:
                state = states.get(temp_id)
                val = _coerce_float(state.get("val") if isinstance(state, dict) else None)
                if val is not None:
                    section_cfg["temp_current_c"] = val
                    logger.info(f"DHW live temp: {val}°C (state: {temp_id})")
                else:
                    logger.warning(f"DHW temp_water State nicht verfügbar: {temp_id}")

        elif section == "climate":
            if not section_cfg.get("command_state_id"):
                sid = _measurement_iobroker_id(device, "enabled")
                if sid:
                    section_cfg["command_state_id"] = sid
            if not section_cfg.get("status_state_id"):
                sid = _measurement_iobroker_id(device, "windows")
                if sid:
                    section_cfg["status_state_id"] = sid
            # Immer Live-Temperatur aus ioBroker holen wenn State gemappt
            temp_id = _measurement_iobroker_id(device, "temp_room")
            if temp_id:
                state = states.get(temp_id)
                val = _coerce_float(state.get("val") if isinstance(state, dict) else None)
                if val is not None:
                    section_cfg["temp_current_c"] = val
                    logger.info(f"Climate live temp: {val}°C (state: {temp_id})")
                else:
                    logger.warning(f"Climate temp_room State nicht verfügbar: {temp_id}")

        elif section == "wallbox":
            if not section_cfg.get("command_state_id"):
                sid = _measurement_iobroker_id(device, "enabled")
                if sid:
                    section_cfg["command_state_id"] = sid
            if not section_cfg.get("status_state_id"):
                sid = _measurement_iobroker_id(device, "plan")
                if sid:
                    section_cfg["status_state_id"] = sid
            # Immer Live-SOC aus ioBroker holen wenn State gemappt
            soc_id = _measurement_iobroker_id(device, "vehicle_soc")
            if soc_id:
                state = states.get(soc_id)
                val = _coerce_float(state.get("val") if isinstance(state, dict) else None)
                if val is not None:
                    section_cfg["vehicle_soc_pct"] = val
                    logger.info(f"Wallbox live SOC: {val}% (state: {soc_id})")
                else:
                    logger.warning(f"Wallbox vehicle_soc State nicht verfügbar: {soc_id}")

    return config


# ============================================================================
# Hauptlogik
# ============================================================================


async def run() -> None:
    logger.info("=== run_control_plan gestartet ===")

    # 1. Konfiguration laden
    config = load_control_config()
    config.setdefault("iobroker_host", IOBROKER_HOST)
    config.setdefault("iobroker_port", IOBROKER_PORT)
    config["publish_to_iobroker"] = True  # immer schreiben, da wir hier explizit steuern

    logger.info(
        f"ioBroker: {config['iobroker_host']}:{config['iobroker_port']}, "
        f"publish={config['publish_to_iobroker']}"
    )

    # 2. Live-States einmergen (Temperaturen, SOC)
    config = await merge_live_states(config)

    # 3. Forecast-Slots laden
    forecast_slots = load_forecast_slots()
    if not forecast_slots:
        logger.warning("Keine zukünftigen Forecast-Slots vorhanden – breche ab")
        sys.exit(0)

    config["slots"] = forecast_slots

    # 4. Control-Plan erzeugen und nach ioBroker schreiben
    try:
        payload = ControlPlanRequest(**config)
    except Exception as e:
        logger.error(f"Ungültige Control-Plan-Konfiguration: {e}")
        sys.exit(1)

    logger.info(
        f"Starte Control-Plan: {len(forecast_slots)} Slots, "
        f"DHW={bool(payload.dhw and payload.dhw.enabled)}, "
        f"Climate={bool(payload.climate and payload.climate.enabled)}, "
        f"Wallbox={bool(payload.wallbox and payload.wallbox.enabled)}"
    )

    result = await create_control_plan(payload)

    # 5. Ergebnis auswerten
    wb = result.iobroker_writeback
    writes = wb.get("writes", [])
    errors = wb.get("errors", [])

    logger.info(f"Control-Plan abgeschlossen: {len(result.slots)} Slots verarbeitet")
    logger.info(f"ioBroker-Writes: {len(writes)} erfolgreich, {len(errors)} Fehler")

    for w in writes:
        logger.info(f"  WRITE {w.get('state_id')}: ok={w.get('ok')}"
                    + (f" [{w.get('fallback')}]" if w.get("fallback") else ""))
    for err in errors:
        logger.error(f"  ERROR {err}")

    if result.summary:
        s = result.summary
        logger.info(
            f"Summary: DHW-Temp={s.get('final_dhw_temp_c')}°C, "
            f"Climate-Temp={s.get('final_climate_temp_c')}°C, "
            f"Wallbox-SOC={s.get('final_wallbox_soc_pct')}%, "
            f"Battery-SOC={s.get('final_battery_soc_pct')}%"
        )

    if errors:
        logger.warning("Es gab ioBroker-Schreibfehler – prüfe Logs")
        sys.exit(1)

    logger.info("=== run_control_plan erfolgreich beendet ===")


if __name__ == "__main__":
    asyncio.run(run())
