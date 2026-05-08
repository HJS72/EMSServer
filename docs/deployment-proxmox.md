# Deployment auf Proxmox CT (Debian)

## Empfehlung

Start mit 2 CT statt sofort mehrerer Micro-CT:

1. CT-A (Core Runtime)
- Collector
- Forecast
- Optimizer
- Dispatcher
- SQLite

2. CT-B (Data + UI)
- InfluxDB
- Grafana
- API/UI (optional auch in CT-A moeglich)

Warum 2 CT:
- klare Trennung von Rechenlogik und Daten/UI
- einfache Backups und Updates
- weniger Betriebsaufwand als 4-5 CT

## Netzwerk

- ioBroker `simple-api` nur im lokalen Netz freigeben
- API/UI mit Reverse Proxy und optional Auth absichern
- NTP synchronisiert fuer korrekte Zeitreihen

## Betriebsmodell

- Services als systemd Units
- strukturierte Logs via journald
- taegliche SQLite-Backups
- Influx Snapshot/Backup nach Zeitplan

## Skalierungspaed

Wenn Last steigt:

1. Forecast in eigenen CT verschieben
2. Optimizer in eigenen CT verschieben
3. SQLite bei Bedarf durch PostgreSQL ersetzen

## Verfuegbarkeit

- Fallback ohne externe Forecast-API
- letzte gueltige Konfiguration cachen
- Safety-Modes fuer Ausfaelle von ioBroker oder Internet
