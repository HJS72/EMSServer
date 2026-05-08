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
