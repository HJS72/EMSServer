"""API Service für Device-Management und ioBroker-Integration."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import yaml
from flask import Flask, jsonify, request, send_from_directory
from pydantic import ValidationError

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
        data = request.json
        device = Device(**data)
        
        config = load_devices_config()
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
        return jsonify({
            "type": device_type,
            "template": template,
            "required_measurements": [
                k for k, v in template.get("measurements", {}).items()
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
