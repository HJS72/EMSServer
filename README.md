# EMSServer v2

Energie-Prognose- und Steuerungssystem fuer Verbrauch, PV-Ueberschuss und priorisierte Lasten.

## Ziel

Das System prognostiziert fuer den Rest des aktuellen Tages in 15-30 Minuten Intervallen:

- Stromverbrauch (gesamt und relevante Teilverbraeuche)
- PV-Erzeugung (je Anlage)
- Netzbezug/-einspeisung
- erwartete Ueberschuesse

Auf Basis der Prognose werden Lasten priorisiert gesteuert:

1. PV-Batterie bis Abend moeglichst voll
2. Brauchwasserwaermepumpe (April-September)
3. Elektroauto-Ladung bis Zielzeit
4. Schlafzimmer-Klima bei Extremtemperaturen

## Architektur (Version B mit SQLite)

Details siehe:

- docs/architecture-v2.md
- docs/data-model.md
- docs/deployment-proxmox.md
- docs/roadmap.md

## Datenquellen

- ioBroker `simple-api` lokal erreichbar
- Wetter/PV-Prognose ueber externe Web-APIs

## Laufzeit

- Bevorzugt Proxmox CT (Debian)
- Single-CT oder Multi-CT (empfohlen: 2 CT)

---

## Deployment (Produktiv)

### Infrastruktur

| Komponente   | Host         | IP              | Port  |
|--------------|--------------|-----------------|-------|
| EMSCore      | EMSCore      | 10.13.30.220    | —     |
| InfluxDB 2.x | EMSDataUI    | 10.13.30.221    | 8086  |
| Grafana      | EMSDataUI    | 10.13.30.221    | 3000  |
| ioBroker     | —            | 10.13.30.201    | 8087  |

### Grafana

- **URL:** http://10.13.30.221:3000
- **Benutzer:** `admin`
- **Passwort:** `admin`
- **Dashboard:** EMS Übersicht → http://10.13.30.221:3000/d/ems-overview/ems-uebersicht

> Passwort nach erstem Login unter *Profile → Change Password* ändern.

### InfluxDB

- **URL:** http://10.13.30.221:8086
- **Organisation:** `ems`
- **Buckets:** `ems_raw`, `ems_agg`, `ems_forecast`, `ems_control`
- **Token:** in `/etc/ems/secrets.env` auf EMSCore (10.13.30.220)

### Collector (EMSCore)

```bash
# Status
ssh root@10.13.30.220 'systemctl status ems-collector'

# Logs live
ssh root@10.13.30.220 'journalctl -u ems-collector -f'

# Neustart
ssh root@10.13.30.220 'systemctl restart ems-collector'
```

### Konfiguration

- Collector-Konfiguration: `/etc/ems/config.yaml` auf EMSCore
- Code: `/opt/ems/EMSServer/services/collector/`
- ioBroker simple-api: `/getBulk/id1/id2/id3` (Pfad-Format mit Schrägstrichen)
