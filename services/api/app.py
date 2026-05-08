"""API Service für Device-Management und ioBroker-Integration."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import yaml
from flask import Flask, jsonify, request, send_from_directory
from pydantic import ValidationError

from services.api.control_logic import ControlConfig, ControlPlanRequest, create_control_plan
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
            auto_mode_state_id = _measurement_iobroker_id(device, "auto_mode")
            soc_state_id = _measurement_iobroker_id(device, "vehicle_soc")

            if command_state_id and not section_cfg.get("command_state_id"):
                section_cfg["command_state_id"] = command_state_id
            if status_state_id and not section_cfg.get("status_state_id"):
                section_cfg["status_state_id"] = status_state_id
            if auto_mode_state_id and not section_cfg.get("auto_mode_state_id"):
                section_cfg["auto_mode_state_id"] = auto_mode_state_id
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
