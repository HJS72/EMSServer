# EMS Forecast Server (ohne Docker)

Statistik- und Vorhersagesystem fuer Stromverbrauch und PV-Erzeugung auf Linux/Proxmox CT.

## Features

- Native Linux-Service mit systemd (kein Docker)
- OTA-Update von GitHub ueber systemd Timer
- Datenquelle InfluxDB (inkl. ioBroker Influx Adapter)
- Optionaler ioBroker-Direktzugriff (simple-api) als Fallback fuer aktuelle Werte
- PV-Prognose aus dem Internet (forecast.solar)
- Stundengenaue Tagesprognose (24h)
- Visualisierung mit Soll/Ist-Vergleich und Historie im Browser

## Architektur

- FastAPI Backend auf Port 8080
- Prognose-Engine:
  - Verbrauch: stundenweise Mittelwerte aus Historie, Wochentag gewichtet
  - PV: externe Online-Prognose (stundlich)
- Dashboard mit drei Ansichten:
  - Tagesprognose
  - Soll/Ist je Stunde
  - Historische Tagessummen

## Installation auf Proxmox CT

1. Repository klonen

   git clone <dein-repo-url>
   cd EMSServer

2. Python Umgebung und Abhaengigkeiten installieren

   chmod +x scripts/install.sh
   ./scripts/install.sh

3. Konfiguration setzen

   cp .env.example .env
   nano .env

4. systemd Services installieren

   chmod +x scripts/install_systemd.sh
   ./scripts/install_systemd.sh

5. Status pruefen

   systemctl status ems-server
   systemctl status ems-updater.timer

6. Dashboard aufrufen

   http://<ct-ip>:8080

## Wichtige Umgebungsvariablen

- INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET
- INFLUX_MEASUREMENT, INFLUX_TAG_KEY, INFLUX_VALUE_FIELD
- STATE_CONSUMPTION_KEY, STATE_PV_KEY
- PV_FORECAST_LAT, PV_FORECAST_LON, PV_FORECAST_KWP
- GITHUB_BRANCH, SERVICE_NAME

Wenn dein Influx-Schema abweicht, nutze INFLUX_CONSUMPTION_QUERY und INFLUX_PV_QUERY fuer eigene Flux-Abfragen.

## OTA Verhalten

- Timer startet alle 5 Minuten
- update.sh zieht Fast-Forward Updates vom konfigurierten Branch
- Nach erfolgreichem Pull werden Python Pakete aktualisiert und der Service neu gestartet

## API Endpunkte

- GET /api/health
- GET /api/forecast/today
- GET /api/actuals/today
- GET /api/compare/today
- GET /api/history?days=14

## Hinweise

- Die Prognose basiert auf historischen Lastprofilen plus externer PV-Prognose.
- Fuer bessere Genauigkeit sollten Lastdaten lueckenlos in Influx vorhanden sein.
- Fuer sehr individuelle Datenschemata empfiehlt sich die Nutzung eigener Flux Queries in .env.
