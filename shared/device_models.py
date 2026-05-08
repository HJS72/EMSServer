"""Device-Modelle für das EMS-System."""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel


class DeviceType(str, Enum):
    """Gerätetypen im EMS-System."""
    GRID = "grid"           # Stromnetz
    PRODUCER = "producer"   # Erzeuger (PV, Wind, etc.)
    CONSUMER = "consumer"   # Verbraucher (Last, Wärmepumpe, etc.)
    DHW = "dhw"             # Brauchwasser-Waermepumpe / Warmwasser
    CLIMATE = "climate"     # Klimaanlage / Raumkuehlung
    WALLBOX = "wallbox"     # Wallbox / EV-Ladepunkt
    BATTERY = "battery"     # Speicher
    HYBRID = "hybrid"       # Hybrid-Wechselrichter mit integrierter Batterie
    EV = "ev"               # Elektrofahrzeug


class MeasurementMapping(BaseModel):
    """Abbildung eines Messwertes zu einem ioBroker State."""
    name: str                # Bezeichnung (z.B. "Leistung", "Tagesenergie")
    iobroker_id: str        # ioBroker State-ID
    unit: str               # Einheit (W, Wh, etc.)
    writable: bool = False  # Kann geschrieben werden?
    scale: float = 1.0      # Skalierungsfaktor
    required: bool = True   # Erforderlich für diesen Device-Typ?
    allow_negative: bool = False  # Negative Werte werden unveraendert uebernommen
    invert_sign: bool = False     # Vorzeichen vor Speicherung invertieren


class Device(BaseModel):
    """Ein Gerät im EMS-System."""
    id: str                               # eindeutige ID
    name: str                             # Anzeigename
    type: DeviceType                      # Gerätetyp
    location: str = ""                    # Standort/Beschreibung
    measurements: Dict[str, MeasurementMapping]  # Messwerte
    enabled: bool = True
    metadata: Dict[str, str] = {}         # Beliebige zusätzliche Infos


# Template für jeden Device-Typ
DEVICE_TEMPLATES = {
    DeviceType.GRID: {
        "name": "Grid-Anschluss",
        "measurements": {
            "power": MeasurementMapping(
                name="Leistung",
                iobroker_id="",
                unit="W",
                writable=False,
                required=True,
                allow_negative=True,
            ),
            "power_import": MeasurementMapping(
                name="Leistung Bezug (+)",
                iobroker_id="",
                unit="W",
                writable=False,
                required=False,
            ),
            "power_export": MeasurementMapping(
                name="Leistung Einspeisung (-)",
                iobroker_id="",
                unit="W",
                writable=False,
                required=False,
                allow_negative=True,
            ),
            "energy_import_today": MeasurementMapping(
                name="Tagesenergie Bezug",
                iobroker_id="",
                unit="Wh",
                writable=False,
                required=True,
            ),
            "energy_export_today": MeasurementMapping(
                name="Tagesenergie Einspeisung",
                iobroker_id="",
                unit="Wh",
                writable=False,
                required=True,
            ),
        },
    },
    DeviceType.PRODUCER: {
        "name": "PV-Anlage / Erzeuger",
        "measurements": {
            "power": MeasurementMapping(
                name="Leistung",
                iobroker_id="",
                unit="W",
                writable=False,
                required=True,
                allow_negative=True,
            ),
            "energy_today": MeasurementMapping(
                name="Tagesenergie",
                iobroker_id="",
                unit="Wh",
                writable=False,
                required=True,
            ),
            "energy_total": MeasurementMapping(
                name="Gesamtenergie",
                iobroker_id="",
                unit="Wh",
                writable=False,
                required=False,
            ),
        },
    },
    DeviceType.CONSUMER: {
        "name": "Verbraucher / Last",
        "measurements": {
            "power": MeasurementMapping(
                name="Leistung",
                iobroker_id="",
                unit="W",
                writable=False,
                required=True,
            ),
            "energy_today": MeasurementMapping(
                name="Tagesenergie",
                iobroker_id="",
                unit="Wh",
                writable=False,
                required=False,
            ),
        },
    },
    DeviceType.DHW: {
        "name": "Brauchwasser-Waermepumpe",
        "description": "Steuerbarer Warmwasser-Verbraucher mit Temperaturfenster und Freigabe.",
        "measurements": {
            "power": MeasurementMapping(
                name="Leistung",
                iobroker_id="",
                unit="W",
                writable=False,
                required=True,
            ),
            "temp_water": MeasurementMapping(
                name="Warmwassertemperatur",
                iobroker_id="",
                unit="°C",
                writable=False,
                required=True,
            ),
            "enabled": MeasurementMapping(
                name="Freigabe EIN/AUS",
                iobroker_id="",
                unit="bool",
                writable=True,
                required=False,
            ),
            "temp_min": MeasurementMapping(
                name="Temperatur Minimum",
                iobroker_id="",
                unit="°C",
                writable=False,
                required=False,
            ),
            "temp_max": MeasurementMapping(
                name="Temperatur Maximum",
                iobroker_id="",
                unit="°C",
                writable=False,
                required=False,
            ),
            "windows": MeasurementMapping(
                name="Geplante Laufzeiten",
                iobroker_id="",
                unit="json",
                writable=False,
                required=False,
            ),
            "energy_today": MeasurementMapping(
                name="Tagesenergie",
                iobroker_id="",
                unit="Wh",
                writable=False,
                required=False,
            ),
        },
    },
    DeviceType.CLIMATE: {
        "name": "Klimaanlage / Kuehlung",
        "description": "Steuerbarer Verbraucher fuer Kuehlung mit Temperaturfenster und Freigabe.",
        "measurements": {
            "power": MeasurementMapping(
                name="Leistung",
                iobroker_id="",
                unit="W",
                writable=False,
                required=True,
            ),
            "temp_room": MeasurementMapping(
                name="Raumtemperatur",
                iobroker_id="",
                unit="°C",
                writable=False,
                required=True,
            ),
            "enabled": MeasurementMapping(
                name="Freigabe EIN/AUS",
                iobroker_id="",
                unit="bool",
                writable=True,
                required=False,
            ),
            "temp_min": MeasurementMapping(
                name="Temperatur Minimum",
                iobroker_id="",
                unit="°C",
                writable=False,
                required=False,
            ),
            "temp_max": MeasurementMapping(
                name="Temperatur Maximum",
                iobroker_id="",
                unit="°C",
                writable=False,
                required=False,
            ),
            "windows": MeasurementMapping(
                name="Geplante Laufzeiten",
                iobroker_id="",
                unit="json",
                writable=False,
                required=False,
            ),
            "energy_today": MeasurementMapping(
                name="Tagesenergie",
                iobroker_id="",
                unit="Wh",
                writable=False,
                required=False,
            ),
        },
    },
    DeviceType.WALLBOX: {
        "name": "Wallbox / EV-Ladepunkt",
        "description": "Steuerbarer Ladepunkt mit Auto-Modus, Ladeleistung und SoC-Bezug.",
        "measurements": {
            "charging_power": MeasurementMapping(
                name="Ladeleistung",
                iobroker_id="",
                unit="W",
                writable=False,
                required=True,
            ),
            "vehicle_soc": MeasurementMapping(
                name="Fahrzeug SoC",
                iobroker_id="",
                unit="%",
                writable=False,
                required=True,
            ),
            "auto_mode": MeasurementMapping(
                name="Auto-Modus",
                iobroker_id="",
                unit="bool",
                writable=True,
                required=False,
            ),
            "enabled": MeasurementMapping(
                name="Freigabe EIN/AUS",
                iobroker_id="",
                unit="bool",
                writable=True,
                required=False,
            ),
            "power_setpoint": MeasurementMapping(
                name="Ladeleistung Sollwert",
                iobroker_id="",
                unit="W",
                writable=True,
                required=False,
            ),
            "phase_mode": MeasurementMapping(
                name="Phasenmodus",
                iobroker_id="",
                unit="text",
                writable=False,
                required=False,
            ),
            "plan": MeasurementMapping(
                name="Ladeplan / Status",
                iobroker_id="",
                unit="json",
                writable=False,
                required=False,
            ),
            "energy_today": MeasurementMapping(
                name="Tagesenergie",
                iobroker_id="",
                unit="Wh",
                writable=False,
                required=False,
            ),
        },
    },
    DeviceType.BATTERY: {
        "name": "Batterie-Speicher",
        "measurements": {
            "power": MeasurementMapping(
                name="Leistung",
                iobroker_id="",
                unit="W",
                writable=False,
                required=True,
                allow_negative=True,
            ),
            "soc": MeasurementMapping(
                name="Ladezustand (SoC)",
                iobroker_id="",
                unit="%",
                writable=False,
                required=True,
            ),
            "power_setpoint": MeasurementMapping(
                name="Sollwert Leistung",
                iobroker_id="",
                unit="W",
                writable=True,
                required=False,
            ),
        },
    },
    DeviceType.HYBRID: {
        "name": "Hybrid-Wechselrichter mit Batterie",
        "description": "Ein Gerät mit integrierter PV-Anlage und Batterie-Speicher",
        "measurements": {
            # PV-Seite
            "pv_power": MeasurementMapping(
                name="PV-Leistung (rein)",
                iobroker_id="",
                unit="W",
                writable=False,
                required=True,
                allow_negative=False,
            ),
            "pv_energy_today": MeasurementMapping(
                name="PV-Energie heute",
                iobroker_id="",
                unit="Wh",
                writable=False,
                required=False,
            ),
            "pv_energy_total": MeasurementMapping(
                name="PV-Energie gesamt",
                iobroker_id="",
                unit="Wh",
                writable=False,
                required=False,
            ),
            # Batterie-Seite
            "batt_power": MeasurementMapping(
                name="Batterie Lade-/Entladeleistung (+ L, - E)",
                iobroker_id="",
                unit="W",
                writable=False,
                required=True,
                allow_negative=True,
            ),
            "batt_soc": MeasurementMapping(
                name="Batterie SoC (Ladezustand)",
                iobroker_id="",
                unit="%",
                writable=False,
                required=True,
            ),
            "batt_soc_min": MeasurementMapping(
                name="Batterie SoC min (Konfiguration)",
                iobroker_id="",
                unit="%",
                writable=False,
                required=False,
            ),
            "batt_energy_max": MeasurementMapping(
                name="Batterie max Energie",
                iobroker_id="",
                unit="Wh",
                writable=False,
                required=False,
            ),
            # Netz-Seite (optional)
            "grid_power": MeasurementMapping(
                name="Netzleistung (+ Bezug, - Einspeisung)",
                iobroker_id="",
                unit="W",
                writable=False,
                required=False,
                allow_negative=True,
            ),
            # Gesamtleistung
            "total_power": MeasurementMapping(
                name="Gesamtleistung (AC-Ausgang)",
                iobroker_id="",
                unit="W",
                writable=False,
                required=False,
                allow_negative=True,
            ),
        },
    },
}


class DeviceConfig(BaseModel):
    """Gesamt-Device-Konfiguration."""
    devices: List[Device] = []
    metadata: Dict[str, str] = {}


def get_device_template(device_type: DeviceType) -> Dict:
    """Template für neues Device basierend auf Typ."""
    return DEVICE_TEMPLATES.get(device_type, {})
