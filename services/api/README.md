# EMS API Service & Device Manager

Backend-API für EMS mit Device-Management und ioBroker-Integration.

## Features

- **Device Management**: Verwaltung von Geräten (Grid, Producer, Consumer, Battery)
- **ioBroker Integration**: Auswahl von States aus ioBroker
- **Device Manager UI**: Web-Interface zur Konfiguration
- **REST API**: Vollständige API für Device-Operationen

## Installation

### 1. Dependencies installieren

```bash
cd /opt/ems/EMSServer
pip install -r requirements.txt
# oder mit spezifischen Packages für API
pip install flask httpx pydantic
```

### 2. Konfiguration

Stelle sicher, dass die folgenden Variablen gesetzt sind:

```bash
# .env oder Environment
export IOBROKER_HOST="10.13.30.201"
export IOBROKER_PORT="8087"
```

## Starten

### Lokal (Development)

```bash
cd services/api
python -m flask run --host=0.0.0.0 --port=5000
```

### Mit Systemd

```bash
# Erstelle einen Service (optional)
sudo tee /etc/systemd/system/ems-api.service > /dev/null <<EOF
[Unit]
Description=EMS API Service
After=network.target

[Service]
Type=simple
User=ems
WorkingDirectory=/opt/ems/EMSServer
ExecStart=/opt/ems/venv/bin/python -m flask run --host=0.0.0.0 --port=5000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ems-api
sudo systemctl start ems-api
```

## Device Manager UI

Öffne im Browser:

```
http://10.13.30.220:5000/
```

oder

```
http://10.13.30.220:5000/device-manager
```

## API Endpoints

### Devices

- `GET /api/devices` - Alle Devices
- `POST /api/devices` - Neues Device erstellen
- `GET /api/devices/<id>` - Device abrufen
- `PUT /api/devices/<id>` - Device aktualisieren
- `DELETE /api/devices/<id>` - Device löschen

### Device Typen

- `GET /api/device-types` - Alle verfügbaren Typen
- `GET /api/device-template/<type>` - Template für Typ

### ioBroker Integration

- `GET /api/iobroker/states` - Alle States auflisten
- `GET /api/iobroker/search?q=<pattern>` - States suchen

### Health

- `GET /api/health` - Service Health-Check

## Device-Typen

### Grid (Stromnetz)

Messwerte für Netzanbindung:
- **power**: Momentanleistung (W)
- **power_import**: Leistung Bezug (+) (W)
- **power_export**: Leistung Einspeisung (-) (W)
- **energy_import_today**: Tagesenergie Bezug (kWh)
- **energy_export_today**: Tagesenergie Einspeisung (kWh)

### Producer (Erzeuger - PV, Wind, etc.)

Messwerte für Erzeuger:
- **power**: Momentanleistung (W)
- **energy_today**: Tagesenergie (kWh)
- **energy_total**: Gesamtenergie (kWh) [optional]

### Consumer (Verbraucher - Last, Wärmepumpe, etc.)

Messwerte für Verbraucher:
- **power**: Momentanleistung (W)
- **energy_today**: Tagesenergie (kWh) [optional]

### Battery (Speicher)

Messwerte für Speicher:
- **power**: Momentanleistung (W)
- **soc**: Ladezustand (%)
- **power_setpoint**: Sollwert Leistung (W) [writable]

## Konfiguration speichern

Devices werden in `/etc/ems/devices.json` gespeichert:

```json
{
  "devices": [
    {
      "id": "grid",
      "name": "Netzanschluss",
      "type": "grid",
      "location": "Zähler in Keller",
      "enabled": true,
      "measurements": {
        "power": {
          "name": "Leistung",
          "iobroker_id": "sonoff.0.TasmotaPower.SML_Power_curr",
          "unit": "W",
          "required": true
        },
        "energy_import_today": {
          "name": "Tagesenergie Bezug",
          "iobroker_id": "sonoff.0.TasmotaPower.SML_Total_in",
          "unit": "kWh",
          "required": true
        }
      }
    }
  ]
}
```

## Troubleshooting

### Fehler: `ModuleNotFoundError: No module named 'shared'`

```bash
# Stelle sicher, dass du aus dem EMSServer-Root startest
cd /opt/ems/EMSServer
export PYTHONPATH=/opt/ems/EMSServer:$PYTHONPATH
python -m flask run --host=0.0.0.0 --port=5000
```

### Fehler: `Connection refused` zu ioBroker

```bash
# Prüfe Verbindung
curl -s http://10.13.30.201:8087/getStates | head -c 200
```

## Logs

```bash
# Systemd Logs
sudo journalctl -u ems-api -f

# Flask Development Logs
# Automatisch sichtbar im Terminal
```

## Nächste Schritte

1. Device Manager UI öffnen
2. Devices anlegen (Grid, Producer, Consumer, Battery)
3. ioBroker States zuordnen
4. Collector neu starten mit neuer Konfiguration
5. Daten in InfluxDB / Grafana Dashboard anzeigen
