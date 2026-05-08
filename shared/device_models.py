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
    BATTERY = "battery"     # Speicher
    EV = "ev"               # Elektrofahrzeug


class MeasurementMapping(BaseModel):
    """Abbildung eines Messwertes zu einem ioBroker State."""
    name: str                # Bezeichnung (z.B. "Leistung", "Tagesenergie")
    iobroker_id: str        # ioBroker State-ID
    unit: str               # Einheit (W, kWh, etc.)
    writable: bool = False  # Kann geschrieben werden?
    scale: float = 1.0      # Skalierungsfaktor
    required: bool = True   # Erforderlich für diesen Device-Typ?


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
            ),
            "energy_import_today": MeasurementMapping(
                name="Tagesenergie Bezug",
                iobroker_id="",
                unit="kWh",
                writable=False,
                required=True,
            ),
            "energy_export_today": MeasurementMapping(
                name="Tagesenergie Einspeisung",
                iobroker_id="",
                unit="kWh",
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
            ),
            "energy_today": MeasurementMapping(
                name="Tagesenergie",
                iobroker_id="",
                unit="kWh",
                writable=False,
                required=True,
            ),
            "energy_total": MeasurementMapping(
                name="Gesamtenergie",
                iobroker_id="",
                unit="kWh",
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
                unit="kWh",
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
}


class DeviceConfig(BaseModel):
    """Gesamt-Device-Konfiguration."""
    devices: List[Device] = []
    metadata: Dict[str, str] = {}


def get_device_template(device_type: DeviceType) -> Dict:
    """Template für neues Device basierend auf Typ."""
    return DEVICE_TEMPLATES.get(device_type, {})
