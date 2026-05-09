"""API Service für Device-Management und ioBroker-Integration."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
import yaml
from flask import Flask, jsonify, request, send_from_directory
from influxdb_client import InfluxDBClient
from pydantic import ValidationError

from services.api.control_logic import ControlConfig, ControlPlanRequest, create_control_plan
from shared.config import load_config
from shared.device_models import (
    Device,
    DeviceConfig,
    DeviceType,
    MeasurementMapping,
    get_device_template,
)

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

# ============================================================================
# GLOBALE KONFIGURATION
# ============================================================================

DEVICES_CONFIG_FILE = Path("/etc/ems/devices.json")  # oder lokal in dev
CONTROL_CONFIG_FILE = Path("/etc/ems/control_config.json")
IOBROKER_HOST = "10.13.30.201"  # oder aus env
IOBROKER_PORT = 8087
FORECAST_HISTORY_FILE = Path("/var/lib/ems/open_meteo_history.json")
DASHBOARD_TIMEZONE = ZoneInfo("Europe/Berlin")
FORECAST_CONFIG_FILE = Path("/etc/ems/forecast_config.json")


# ============================================================================
# HILFSFUNKTIONEN
# ============================================================================

def load_devices_config() -> DeviceConfig:
    """Lade Device-Konfiguration aus JSON."""
    if DEVICES_CONFIG_FILE.exists():
        with open(DEVICES_CONFIG_FILE) as f:
            data = json.load(f)
            return DeviceConfig(**data)
    return DeviceConfig()


def save_devices_config(config: DeviceConfig) -> None:
    """Speichere Device-Konfiguration in JSON."""
    DEVICES_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DEVICES_CONFIG_FILE, "w") as f:
        json.dump(config.dict(), f, indent=2)


def load_control_config() -> Dict[str, Any]:
    """Lade persistierte Steuerlogik-Konfiguration."""
    if CONTROL_CONFIG_FILE.exists():
        with open(CONTROL_CONFIG_FILE) as f:
            data = json.load(f)
            cfg = ControlConfig(**data)
            return cfg.model_dump(exclude_none=True)

    # Sinnvolle Standardwerte, wenn noch keine Konfiguration vorhanden ist.
    return ControlConfig(
        iobroker_host=IOBROKER_HOST,
        iobroker_port=IOBROKER_PORT,
    ).model_dump(exclude_none=True)


def save_control_config(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validiere und speichere Steuerlogik-Konfiguration."""
    cfg = ControlConfig(**data)
    serialized = cfg.model_dump(exclude_none=True)
    serialized.setdefault("iobroker_host", IOBROKER_HOST)
    serialized.setdefault("iobroker_port", IOBROKER_PORT)

    CONTROL_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONTROL_CONFIG_FILE, "w") as f:
        json.dump(serialized, f, indent=2)

    return serialized


def _measurement_iobroker_id(device: Device, measurement_key: str) -> Optional[str]:
    measurement = device.measurements.get(measurement_key)
    if not measurement:
        return None
    return measurement.iobroker_id or None


def _state_value_from_snapshot(states: Dict[str, Any], state_id: Optional[str]) -> Any:
    if not state_id:
        return None
    state_data = states.get(state_id)
    if isinstance(state_data, dict):
        return state_data.get("val")
    return None


def _coerce_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_forecast_location() -> Dict[str, Any]:
    """Lädt Forecast-Standortparameter für UI/Visualisierung."""
    location = {
        "latitude": None,
        "longitude": None,
        "timezone": "Europe/Berlin",
    }
    if not FORECAST_CONFIG_FILE.exists():
        return location
    try:
        raw = json.loads(FORECAST_CONFIG_FILE.read_text())
        source = raw.get("open_meteo", raw) if isinstance(raw, dict) else {}
        lat = _coerce_float(source.get("latitude"))
        lon = _coerce_float(source.get("longitude"))
        if lat is not None:
            location["latitude"] = lat
        if lon is not None:
            location["longitude"] = lon
        tz = source.get("timezone")
        if isinstance(tz, str) and tz:
            location["timezone"] = tz
    except Exception as e:
        logger.warning(f"Konnte Forecast-Standort nicht laden: {e}")

    return location


def _merge_control_devices(config: Dict[str, Any]) -> Dict[str, Any]:
    """Ergaenze Steuerkonfiguration aus angelegten Devices und Live-States."""
    devices_config = load_devices_config()
    relevant_types = {
        "dhw": DeviceType.DHW,
        "climate": DeviceType.CLIMATE,
        "wallbox": DeviceType.WALLBOX,
    }

    selected_devices: Dict[str, Device] = {}
    for section, device_type in relevant_types.items():
        device = next(
            (item for item in devices_config.devices if item.enabled and item.type == device_type),
            None,
        )
        if device:
            selected_devices[section] = device

    if not selected_devices:
        return config

    states = get_iobroker_states_sync()

    for section, device in selected_devices.items():
        section_cfg = config.get(section)
        if not isinstance(section_cfg, dict):
            section_cfg = {}
        config[section] = section_cfg

        section_cfg.setdefault("device_id", device.id)

        if section == "dhw":
            command_state_id = _measurement_iobroker_id(device, "enabled")
            status_state_id = _measurement_iobroker_id(device, "windows")
            temp_state_id = _measurement_iobroker_id(device, "temp_water")

            if command_state_id and not section_cfg.get("command_state_id"):
                section_cfg["command_state_id"] = command_state_id
            if status_state_id and not section_cfg.get("status_state_id"):
                section_cfg["status_state_id"] = status_state_id
            if "temp_current_c" not in section_cfg:
                live_temp = _coerce_float(_state_value_from_snapshot(states, temp_state_id))
                if live_temp is not None:
                    section_cfg["temp_current_c"] = live_temp

        elif section == "climate":
            command_state_id = _measurement_iobroker_id(device, "enabled")
            status_state_id = _measurement_iobroker_id(device, "windows")
            temp_state_id = _measurement_iobroker_id(device, "temp_room")

            if command_state_id and not section_cfg.get("command_state_id"):
                section_cfg["command_state_id"] = command_state_id
            if status_state_id and not section_cfg.get("status_state_id"):
                section_cfg["status_state_id"] = status_state_id
            if "temp_current_c" not in section_cfg:
                live_temp = _coerce_float(_state_value_from_snapshot(states, temp_state_id))
                if live_temp is not None:
                    section_cfg["temp_current_c"] = live_temp

        elif section == "wallbox":
            command_state_id = _measurement_iobroker_id(device, "enabled")
            status_state_id = _measurement_iobroker_id(device, "plan")
            soc_state_id = _measurement_iobroker_id(device, "vehicle_soc")

            if command_state_id and not section_cfg.get("command_state_id"):
                section_cfg["command_state_id"] = command_state_id
            if status_state_id and not section_cfg.get("status_state_id"):
                section_cfg["status_state_id"] = status_state_id
            if "vehicle_soc_pct" not in section_cfg:
                live_soc = _coerce_float(_state_value_from_snapshot(states, soc_state_id))
                if live_soc is not None:
                    section_cfg["vehicle_soc_pct"] = live_soc

    return config


def _slugify(value: str) -> str:
    """Konvertiert Text in eine stabile ID-kompatible Form."""
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def generate_device_id(name: str, device_type: str, existing_ids: List[str]) -> str:
    """Erzeugt automatisch eine eindeutige Device-ID."""
    base = _slugify(name) or _slugify(device_type) or "device"
    candidate = base
    idx = 2
    existing = set(existing_ids)
    while candidate in existing:
        candidate = f"{base}_{idx}"
        idx += 1
    return candidate


async def get_iobroker_states() -> Dict[str, Any]:
    """Hole alle States von ioBroker getStates API."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"http://{IOBROKER_HOST}:{IOBROKER_PORT}/getStates")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"Fehler beim Abrufen von ioBroker States: {e}")
        return {}


def get_iobroker_states_sync() -> Dict[str, Any]:
    """Synchrone Wrapper-Funktion für Flask."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(get_iobroker_states())
    except Exception as e:
        logger.error(f"Fehler bei ioBroker-Abfrage: {e}")
        return {}


def build_iobroker_tree(states: Dict[str, Any]) -> Dict[str, Any]:
    """Baut aus ioBroker State-IDs einen hierarchischen Objektbaum."""
    root: Dict[str, Any] = {"name": "root", "children": {}, "leaf": False}
    for state_id, state_data in states.items():
        parts = state_id.split(".")
        node = root
        for part in parts:
            node["children"].setdefault(
                part,
                {"name": part, "children": {}, "leaf": False},
            )
            node = node["children"][part]

        node["leaf"] = True
        node["id"] = state_id
        if isinstance(state_data, dict):
            node["val"] = state_data.get("val")
            common = state_data.get("common", {}) if isinstance(state_data.get("common"), dict) else {}
            node["unit"] = common.get("unit", "")
            node["displayName"] = common.get("name", "")

    return root


# ============================================================================
# API ENDPOINTS - STATISCHE DATEIEN
# ============================================================================

@app.route("/", methods=["GET"])
def index():
    """Serviere Device Manager UI."""
    return send_from_directory(".", "device_manager.html")


@app.route("/device-manager", methods=["GET"])
def device_manager():
    """Serviere Device Manager UI (Alternative URL)."""
    return send_from_directory(".", "device_manager.html")


# ============================================================================
# API ENDPOINTS - DEVICES
# ============================================================================

@app.route("/api/devices", methods=["GET"])
def list_devices():
    """Alle Devices auflisten."""
    try:
        config = load_devices_config()
        return jsonify([d.dict() for d in config.devices])
    except Exception as e:
        logger.error(f"Fehler beim Laden von Devices: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/devices", methods=["POST"])
def create_device():
    """Neues Device erstellen."""
    try:
        data = dict(request.json or {})
        config = load_devices_config()

        if not data.get("id"):
            data["id"] = generate_device_id(
                name=data.get("name", "device"),
                device_type=data.get("type", "device"),
                existing_ids=[d.id for d in config.devices],
            )

        device = Device(**data)

        # Check für Duplikate
        if any(d.id == device.id for d in config.devices):
            return jsonify({"error": f"Device mit ID '{device.id}' existiert bereits"}), 400
        
        config.devices.append(device)
        save_devices_config(config)
        
        return jsonify(device.dict()), 201
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Fehler beim Erstellen von Device: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/devices/<device_id>", methods=["GET"])
def get_device(device_id: str):
    """Einzelnes Device abrufen."""
    try:
        config = load_devices_config()
        device = next((d for d in config.devices if d.id == device_id), None)
        if not device:
            return jsonify({"error": "Device nicht gefunden"}), 404
        return jsonify(device.dict())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/devices/<device_id>", methods=["PUT"])
def update_device(device_id: str):
    """Device aktualisieren."""
    try:
        data = request.json
        device = Device(**data)
        
        config = load_devices_config()
        idx = next((i for i, d in enumerate(config.devices) if d.id == device_id), None)
        if idx is None:
            return jsonify({"error": "Device nicht gefunden"}), 404
        
        config.devices[idx] = device
        save_devices_config(config)
        
        return jsonify(device.dict())
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Fehler beim Aktualisieren von Device: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/devices/<device_id>", methods=["DELETE"])
def delete_device(device_id: str):
    """Device löschen."""
    try:
        config = load_devices_config()
        config.devices = [d for d in config.devices if d.id != device_id]
        save_devices_config(config)
        return "", 204
    except Exception as e:
        logger.error(f"Fehler beim Löschen von Device: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# API ENDPOINTS - DEVICE TYPEN UND TEMPLATES
# ============================================================================

@app.route("/api/device-types", methods=["GET"])
def list_device_types():
    """Alle verfügbaren Device-Typen."""
    return jsonify({
        "types": [
            {"id": t.value, "name": get_device_template(t).get("name", t.value)}
            for t in DeviceType
        ]
    })


@app.route("/api/device-template/<device_type>", methods=["GET"])
def get_device_template_endpoint(device_type: str):
    """Template für neuen Device."""
    try:
        dt = DeviceType(device_type)
        template = get_device_template(dt)
        measurements = {
            key: value.model_dump() if hasattr(value, "model_dump") else value.dict()
            for key, value in template.get("measurements", {}).items()
        }
        serialized_template = {
            **template,
            "measurements": measurements,
        }
        return jsonify({
            "type": device_type,
            "template": serialized_template,
            "required_measurements": [
                k for k, v in measurements.items()
                if v.get("required", True)
            ]
        })
    except ValueError:
        return jsonify({"error": f"Unbekannter Device-Typ: {device_type}"}), 400


# ============================================================================
# API ENDPOINTS - iBOBROKER INTEGRATION
# ============================================================================

@app.route("/api/iobroker/states", methods=["GET"])
def list_iobroker_states():
    """Alle ioBroker States auflisten."""
    try:
        states = get_iobroker_states_sync()
        # Nur die interessanten Felder zurückgeben
        result = []
        for state_id, state_data in states.items():
            if isinstance(state_data, dict) and "val" in state_data:
                result.append({
                    "id": state_id,
                    "val": state_data.get("val"),
                    "unit": state_data.get("common", {}).get("unit", ""),
                    "name": state_data.get("common", {}).get("name", ""),
                    "type": state_data.get("common", {}).get("type", ""),
                })
        return jsonify(result[:500])  # Limit zur Performance
    except Exception as e:
        logger.error(f"Fehler beim Abrufen von ioBroker States: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/iobroker/search", methods=["GET"])
def search_iobroker():
    """ioBroker States nach Muster suchen."""
    pattern = request.args.get("q", "")
    if not pattern or len(pattern) < 2:
        return jsonify({"error": "Mindestens 2 Zeichen erforderlich"}), 400
    
    try:
        states = get_iobroker_states_sync()
        pattern_lower = pattern.lower()
        result = []
        for state_id, state_data in states.items():
            if pattern_lower in state_id.lower() and isinstance(state_data, dict) and "val" in state_data:
                result.append({
                    "id": state_id,
                    "val": state_data.get("val"),
                    "unit": state_data.get("common", {}).get("unit", ""),
                    "name": state_data.get("common", {}).get("name", ""),
                })
        return jsonify(result[:100])
    except Exception as e:
        logger.error(f"Fehler bei ioBroker-Suche: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/iobroker/tree", methods=["GET"])
def iobroker_tree():
    """Liefert den ioBroker Objektbaum basierend auf State-IDs."""
    try:
        states = get_iobroker_states_sync()
        tree = build_iobroker_tree(states)
        return jsonify(tree)
    except Exception as e:
        logger.error(f"Fehler beim Aufbau des ioBroker-Objektbaums: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# API ENDPOINTS - STEUERLOGIK (FORECAST -> EMPFEHLUNG -> IOBROKER)
# ============================================================================

@app.route("/api/control/plan", methods=["POST"])
def create_control_plan_endpoint():
    """Erzeuge einen Fahrplan fuer steuerbare Verbraucher.

    Erwartet Forecast-Slots und Geraeteparameter im Request-Body.
    Optional kann der Plan direkt als Status nach ioBroker geschrieben werden.
    """
    try:
        raw = dict(request.json or {})
        base = load_control_config()
        merged = {**base, **raw}
        for key in ("dhw", "climate", "wallbox"):
            base_section = base.get(key) if isinstance(base.get(key), dict) else {}
            raw_section = raw.get(key) if isinstance(raw.get(key), dict) else {}
            if base_section or raw_section:
                merged[key] = {**base_section, **raw_section}

        merged.setdefault("iobroker_host", IOBROKER_HOST)
        merged.setdefault("iobroker_port", IOBROKER_PORT)
        merged = _merge_control_devices(merged)

        payload = ControlPlanRequest(**merged)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(create_control_plan(payload))
        return jsonify(result.model_dump())
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Fehler beim Erstellen des Steuerplans: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/control/config", methods=["GET"])
def get_control_config_endpoint():
    """Liefert die persistierte Konfiguration fuer steuerbare Verbraucher."""
    try:
        return jsonify(load_control_config())
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Fehler beim Laden der Steuer-Konfiguration: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/control/config", methods=["PUT"])
def save_control_config_endpoint():
    """Speichert die persistierte Konfiguration fuer steuerbare Verbraucher."""
    try:
        data = dict(request.json or {})
        return jsonify(save_control_config(data))
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Fehler beim Speichern der Steuer-Konfiguration: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# FORECAST DASHBOARD
# ============================================================================

@app.route("/dashboard", methods=["GET"])
def dashboard():
    """Lade Dashboard HTML."""
    dashboard_path = Path(__file__).parent / "dashboard.html"
    if dashboard_path.exists():
        return send_from_directory(Path(__file__).parent, "dashboard.html")
    return "Dashboard not found", 404


@app.route("/api/forecast/daily", methods=["GET"])
def get_forecast_daily():
    """Liefert Tages-Forecast + historische PV-Messwerte für Dashboard.
    
    Query-Parameter:
    - date: YYYY-MM-DD (default: heute)
    
    Falls Forecast nicht verfügbar: Gibt minimal empty forecast mit actual_slots zurück.
    """
    try:
        # Parse optionales Datum
        date_str = request.args.get("date")
        if date_str:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            target_date = datetime.utcnow().date()
        
        # Lade Forecast für das angeforderte Datum (optional)
        forecast_data = _load_forecast_for_date(target_date)
        if not forecast_data:
            # Kein Forecast vorhanden - nutze Minimal-Struktur
            forecast_data = {
                "slots": [],
                "provider": "none",
                "generated_at": None,
                "model": "none",
            }
        
        # Hole ioBroker-States für aktuelle PV-Leistung (immer, da es sich um Echtzeit-Daten handelt)
        current_pv_w = 0
        try:
            states = get_iobroker_states_sync()
            pv_state_id = "solaredgemodbus.0.PV_Leistung"
            if states.get(pv_state_id):
                state_data = states[pv_state_id]
                if isinstance(state_data, dict):
                    current_pv_w = state_data.get("val", 0)
        except Exception as e:
            logger.warning(f"Aktuelle PV-Leistung nicht verfügbar: {e}")
        
        # Generiere 24h Zeitreihe (0:00 - 23:45)
        full_slots = _generate_24h_slots(forecast_data.get("slots", []), target_date)
        actual_consumption_hourly = _build_actual_consumption_hourly(target_date)
        
        response = {
            "date": target_date.isoformat(),
            "provider": forecast_data.get("provider"),
            "generated_at": forecast_data.get("generated_at"),
            "forecast_location": _load_forecast_location(),
            "forecast_slots": full_slots,
            "actual_slots": _load_actual_slots_for_date(target_date),
            "consumption_hourly": _build_consumption_hourly(full_slots),
            "consumption_actual_hourly": actual_consumption_hourly,
            "consumption_labels": _get_consumption_labels(),
            "current_pv_w": current_pv_w,
            "model": forecast_data.get("model"),
        }
        
        return jsonify(response)
    
    except Exception as e:
        logger.error(f"Fehler bei Forecast-Daily-Endpoint: {e}")
        return jsonify({"error": str(e)}), 500


def _load_forecast_for_date(target_date) -> Optional[Dict[str, Any]]:
    """Lade Forecast für ein bestimmtes Datum.
    
    Versucht in dieser Reihenfolge:
    1. Archive (falls vorhanden)
    2. Aktuelle Forecast (für heute)
    """
    # Für heute und morgen: aktuelle Forecast enthält beide Tage.
    forecast_file = Path("/etc/ems/latest_forecast.json")
    if forecast_file.exists():
        with open(forecast_file) as f:
            current_forecast = json.load(f)
        if _forecast_contains_date(current_forecast, target_date):
            return current_forecast
    
    # Für andere Tage: versuche Archive (mehrere mögliche Pfade)
    for archive_base in ["/etc/ems/archive", "/opt/ems/EMSServer/data/archive"]:
        archive_path = Path(archive_base)
        if archive_path.exists():
            archive_file = archive_path / f"forecast-{target_date.isoformat()}.json"
            if archive_file.exists():
                with open(archive_file) as f:
                    return json.load(f)
    
    return None


def _forecast_contains_date(forecast_data: Dict[str, Any], target_date) -> bool:
    """Prüft, ob eine Forecast-Datei Slots für das angeforderte Datum enthält."""
    for slot in forecast_data.get("slots", []):
        slot_key = _slot_local_key(slot.get("ts"))
        if slot_key is not None and slot_key[0] == target_date:
            return True
    return False


def _generate_24h_slots(slots: List[Dict[str, Any]], target_date) -> List[Dict[str, Any]]:
    """Generiere volle 24h Zeitreihe (0:00 - 23:45) mit 15-Min-Intervallen.
    
    Füllt Lücken mit 0W, wenn Slots nicht verfügbar.
    """
    from datetime import time

    # Erstelle Map nach lokalem Tages-Slot (Datum, Stunde, Minute).
    slot_map: Dict[tuple, Dict[str, Any]] = {}
    for slot in slots:
        slot_key = _slot_local_key(slot.get("ts"))
        if slot_key is not None:
            slot_map[slot_key] = slot
    
    # Generiere alle 96 Slots für 24h (0:00, 0:15, ..., 23:45)
    result = []
    for hour in range(24):
        for minute in [0, 15, 30, 45]:
            dt = datetime.combine(
                target_date,
                time(hour=hour, minute=minute)
            )
            slot_key = (target_date, hour, minute)
            
            slot = slot_map.get(slot_key)
            if slot:
                result.append({
                    "ts": slot["ts"],
                    "pv_w": slot.get("pv_w", 0),
                    "surplus_w": slot.get("surplus_w", 0),
                })
            else:
                # Fülle mit 0W wenn kein Slot vorhanden
                dt_local = dt.replace(tzinfo=DASHBOARD_TIMEZONE)
                result.append({
                    "ts": dt_local.isoformat(),
                    "pv_w": 0,
                    "surplus_w": 0,
                })
    
    return result


def _load_actual_slots_for_date(target_date) -> List[Dict[str, Any]]:
    """Lädt IST-PV-Werte aus Influx. Nur bis zur aktuellen Uhrzeit."""
    actual_by_slot: Dict[tuple, float] = {}
    now_local = datetime.now(DASHBOARD_TIMEZONE)
    
    # Lade Daten für heute und Vergangenheit
    if target_date <= now_local.date():
        try:
            cfg = load_config()
            start_local = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=DASHBOARD_TIMEZONE)
            
            # Bestimme Stop-Zeitpunkt
            if target_date == now_local.date():
                # Heute: nur bis jetzt
                stop_utc = now_local.astimezone(ZoneInfo("UTC")).isoformat()
            else:
                # Vergangenheit: ganzer Tag
                stop_local = start_local + timedelta(days=1)
                stop_utc = stop_local.astimezone(ZoneInfo("UTC")).isoformat()
            
            start_utc = start_local.astimezone(ZoneInfo("UTC")).isoformat()
            
            flux = f'''
from(bucket: "{cfg.influxdb.bucket_raw}")
  |> range(start: {start_utc}, stop: {stop_utc})
  |> filter(fn: (r) => r["_field"] == "value")
  |> filter(fn: (r) => r["_measurement"] == "power" and r["device_id"] == "pv1")
'''
            with InfluxDBClient(url=cfg.influxdb.url, token=cfg.influxdb.token, org=cfg.influxdb.org) as client:
                query_api = client.query_api()
                tables = query_api.query(query=flux, org=cfg.influxdb.org)
                
                for table in tables:
                    for record in table.records:
                        ts = record.get_time()
                        if ts is None:
                            continue
                        local_ts = ts.astimezone(DASHBOARD_TIMEZONE)
                        if local_ts.date() != target_date:
                            continue
                        
                        # Runde auf 15-Minuten-Slot
                        minute = (local_ts.minute // 15) * 15
                        hour = local_ts.hour
                        value = _coerce_float(record.get_value())
                        
                        if value is not None:
                            slot_key = (target_date, hour, minute)
                            actual_by_slot[slot_key] = float(value)
        except Exception as e:
            logger.debug(f"IST-PV aus Influx nicht verfügbar: {e}")
    
    return _empty_actual_slots(target_date, actual_by_slot)


def _empty_actual_slots(target_date, actual_by_slot: Optional[Dict[tuple, float]] = None) -> List[Dict[str, Any]]:
    """Erzeugt 96 Slots fuer einen Tag; nur bis jetzt gefuellt, sonst null."""
    from datetime import time

    actual_map = actual_by_slot or {}
    result: List[Dict[str, Any]] = []
    now_local = datetime.now(DASHBOARD_TIMEZONE)
    
    for hour in range(24):
        for minute in [0, 15, 30, 45]:
            dt = datetime.combine(target_date, time(hour=hour, minute=minute)).replace(tzinfo=DASHBOARD_TIMEZONE)
            ts = dt.isoformat()
            
            # Bestimme ob Wert geladen werden soll
            pv_w = None
            if target_date < now_local.date():
                # Vergangenheit: alle verfuegbaren Werte laden
                pv_w = actual_map.get((target_date, hour, minute))
            elif target_date == now_local.date() and dt <= now_local:
                # Heute bis jetzt: Werte laden
                pv_w = actual_map.get((target_date, hour, minute))
            # sonst: null (Zukunft oder nach aktuellem Zeitpunkt heute)
            
            result.append({
                "ts": ts,
                "pv_w": pv_w,
            })
    return result


def _slot_local_key(ts_value: Any) -> Optional[tuple]:
    """Normalisiert einen Timestamp auf (lokales Datum, Stunde, Minute)."""
    if not isinstance(ts_value, str) or not ts_value:
        return None
    try:
        dt = datetime.fromisoformat(ts_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    local_dt = dt.astimezone(DASHBOARD_TIMEZONE)
    return (local_dt.date(), local_dt.hour, local_dt.minute)


def _build_consumption_hourly(forecast_slots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregiert den bestehenden Control-Plan auf stündliche, gestackte Verbraucherwerte."""
    try:
        base = load_control_config()
        merged = dict(base)
        merged["slots"] = [
            {
                "ts": slot.get("ts"),
                "surplus_w": slot.get("surplus_w", 0.0),
            }
            for slot in forecast_slots
        ]
        merged.setdefault("iobroker_host", IOBROKER_HOST)
        merged.setdefault("iobroker_port", IOBROKER_PORT)
        merged["publish_to_iobroker"] = False
        merged = _merge_control_devices(merged)

        payload = ControlPlanRequest(**merged)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(create_control_plan(payload))
    except Exception as e:
        logger.error(f"Fehler beim Erzeugen der Verbrauchsprognose: {e}")
        return _empty_consumption_hourly()

    hourly: Dict[int, Dict[str, float]] = {
        hour: {
            "dhw_w": 0.0,
            "climate_w": 0.0,
            "wallbox_w": 0.0,
        }
        for hour in range(24)
    }
    counts: Dict[int, int] = {hour: 0 for hour in range(24)}

    for slot in result.slots:
        slot_key = _slot_local_key(slot.ts)
        if slot_key is None:
            continue
        _, hour, _ = slot_key
        hourly[hour]["dhw_w"] += float(slot.dhw_power_w or 0.0)
        hourly[hour]["climate_w"] += float(slot.climate_power_w or 0.0)
        hourly[hour]["wallbox_w"] += float(slot.wallbox_power_w or 0.0)
        counts[hour] += 1

    result_items: List[Dict[str, Any]] = []
    for hour in range(24):
        divisor = counts[hour] or 1
        dhw_w = round(hourly[hour]["dhw_w"] / divisor, 1)
        climate_w = round(hourly[hour]["climate_w"] / divisor, 1)
        wallbox_w = round(hourly[hour]["wallbox_w"] / divisor, 1)
        result_items.append(
            {
                "hour": hour,
                "label": f"{hour:02d}:00",
                "dhw_w": dhw_w,
                "climate_w": climate_w,
                "wallbox_w": wallbox_w,
                "total_w": round(dhw_w + climate_w + wallbox_w, 1),
            }
        )

    return result_items


def _empty_consumption_hourly() -> List[Dict[str, Any]]:
    return [
        {
            "hour": hour,
            "label": f"{hour:02d}:00",
            "dhw_w": 0.0,
            "climate_w": 0.0,
            "wallbox_w": 0.0,
            "total_w": 0.0,
        }
        for hour in range(24)
    ]


def _get_consumption_labels() -> Dict[str, str]:
    """Liefert Label-Namen für Verbrauchsdiagramm aus der Device-Konfiguration."""
    labels = {
        "dhw": "Warmwasser",
        "climate": "Klima",
        "wallbox": "Wallbox",
        "house": "Haus",
        "forecast": "Prognose",
    }

    try:
        devices = [d for d in load_devices_config().devices if d.enabled]

        by_type = {
            DeviceType.DHW: "dhw",
            DeviceType.CLIMATE: "climate",
            DeviceType.WALLBOX: "wallbox",
        }
        for device_type, label_key in by_type.items():
            device = next((d for d in devices if d.type == device_type), None)
            if device and device.name:
                labels[label_key] = device.name

        # Haus-Gesamtverbrauch: bevorzugt Device-ID "gesamtverbrauch".
        house_device = next((d for d in devices if d.id == "gesamtverbrauch"), None)
        if house_device and house_device.name:
            labels["house"] = house_device.name
    except Exception as e:
        logger.warning(f"Konnte Verbrauchs-Labels nicht aus Devices laden: {e}")

    return labels


def _build_actual_consumption_hourly(target_date) -> List[Dict[str, Any]]:
    """Liefert IST-Verbrauch pro 15-Min-Intervall aus Influx.

    Rückgabe pro Intervall:
    - dhw_w, climate_w, wallbox_w: gemessene steuerbare Verbraucher
    - consumers_total_w: Summe steuerbare Verbraucher
    - house_w: gemessener Gesamtverbrauch Haus (Device-ID: gesamtverbrauch)

    Bevorzugt werden 15m-Aggregate (ems_agg). Falls fuer ein Intervall keine
    Aggregatwerte vorliegen, wird auf Rohdaten (ems_raw) zurueckgefallen.
    """
    # 96 15-min intervals per day
    quarterly: Dict[int, Dict[str, float]] = {
        i: {
            "dhw_w": 0.0,
            "climate_w": 0.0,
            "wallbox_w": 0.0,
            "house_w": 0.0,
        }
        for i in range(96)
    }
    counts_agg: Dict[int, Dict[str, int]] = {
        i: {
            "dhw_w": 0,
            "climate_w": 0,
            "wallbox_w": 0,
            "house_w": 0,
        }
        for i in range(96)
    }
    quarterly_raw: Dict[int, Dict[str, float]] = {
        i: {
            "dhw_w": 0.0,
            "climate_w": 0.0,
            "wallbox_w": 0.0,
            "house_w": 0.0,
        }
        for i in range(96)
    }
    counts_raw: Dict[int, Dict[str, int]] = {
        i: {
            "dhw_w": 0,
            "climate_w": 0,
            "wallbox_w": 0,
            "house_w": 0,
        }
        for i in range(96)
    }

    try:
        cfg = load_config()
        start_local = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=DASHBOARD_TIMEZONE)
        stop_local = start_local + timedelta(days=1)
        start_utc = start_local.astimezone(ZoneInfo("UTC")).isoformat()
        stop_utc = stop_local.astimezone(ZoneInfo("UTC")).isoformat()

        flux_agg = f'''
from(bucket: "{cfg.influxdb.bucket_agg}")
  |> range(start: {start_utc}, stop: {stop_utc})
  |> filter(fn: (r) => r["_field"] == "value")
  |> filter(fn: (r) => r["interval"] == "15m")
  |> filter(fn: (r) =>
    r["_measurement"] == "dhw_power" or
    r["_measurement"] == "climate_power" or
    r["_measurement"] == "wallbox_charging_power" or
    (r["_measurement"] == "consumer_power" and r["device_id"] == "gesamtverbrauch")
  )
'''
        flux_raw = f'''
from(bucket: "{cfg.influxdb.bucket_raw}")
  |> range(start: {start_utc}, stop: {stop_utc})
  |> filter(fn: (r) => r["_field"] == "value")
  |> filter(fn: (r) =>
    r["_measurement"] == "dhw_power" or
    r["_measurement"] == "climate_power" or
    r["_measurement"] == "wallbox_charging_power" or
    (r["_measurement"] == "consumer_power" and r["device_id"] == "gesamtverbrauch")
  )
'''

        with InfluxDBClient(url=cfg.influxdb.url, token=cfg.influxdb.token, org=cfg.influxdb.org) as client:
            query_api = client.query_api()
            tables_agg = query_api.query(query=flux_agg, org=cfg.influxdb.org)
            tables_raw = query_api.query(query=flux_raw, org=cfg.influxdb.org)

        def _consume_record(record: Any, sums: Dict[int, Dict[str, float]], cnts: Dict[int, Dict[str, int]]) -> None:
            ts = record.get_time()
            if ts is None:
                return
            local_ts = ts.astimezone(DASHBOARD_TIMEZONE)
            if local_ts.date() != target_date:
                return

            # Calculate 15-min interval index (0-95)
            interval = (local_ts.hour * 4) + (local_ts.minute // 15)
            measurement = record.values.get("_measurement")
            device_id = record.values.get("device_id")
            value = _coerce_float(record.get_value())
            if value is None:
                return

            if measurement == "dhw_power":
                sums[interval]["dhw_w"] += value
                cnts[interval]["dhw_w"] += 1
            elif measurement == "climate_power":
                sums[interval]["climate_w"] += value
                cnts[interval]["climate_w"] += 1
            elif measurement == "wallbox_charging_power":
                sums[interval]["wallbox_w"] += value
                cnts[interval]["wallbox_w"] += 1
            elif measurement == "consumer_power" and device_id == "gesamtverbrauch":
                sums[interval]["house_w"] += value
                cnts[interval]["house_w"] += 1

        for table in tables_agg:
            for record in table.records:
                _consume_record(record, quarterly, counts_agg)

        for table in tables_raw:
            for record in table.records:
                _consume_record(record, quarterly_raw, counts_raw)
    except Exception as e:
        logger.warning(f"IST-Verbrauch aus Influx nicht verfügbar: {e}")

    result: List[Dict[str, Any]] = []

    def _avg_with_fallback(interval: int, key: str) -> float:
        if counts_agg[interval][key] > 0:
            return round(quarterly[interval][key] / counts_agg[interval][key], 1)
        if counts_raw[interval][key] > 0:
            return round(quarterly_raw[interval][key] / counts_raw[interval][key], 1)
        return 0.0

    for interval in range(96):
        hour = interval // 4
        minute = (interval % 4) * 15
        dhw_w = _avg_with_fallback(interval, "dhw_w")
        climate_w = _avg_with_fallback(interval, "climate_w")
        wallbox_w = _avg_with_fallback(interval, "wallbox_w")
        house_w = _avg_with_fallback(interval, "house_w")
        consumers_total_w = round(dhw_w + climate_w + wallbox_w, 1)
        result.append(
            {
                "hour": hour,
                "label": f"{hour:02d}:{minute:02d}",
                "dhw_w": dhw_w,
                "climate_w": climate_w,
                "wallbox_w": wallbox_w,
                "consumers_total_w": consumers_total_w,
                "house_w": house_w,
            }
        )

    return result


# ============================================================================
# HEALTHCHECK
# ============================================================================

@app.route("/api/health", methods=["GET"])
def health():
    """Health-Check."""
    return jsonify({"status": "ok"})


# ============================================================================
# ERROR HANDLER
# ============================================================================

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Nicht gefunden"}), 404


@app.errorhandler(500)
def internal_error(e):
    logger.error(f"Internal server error: {e}")
    return jsonify({"error": "Interner Fehler"}), 500


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="0.0.0.0", port=5000, debug=True)
