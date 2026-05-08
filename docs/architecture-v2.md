# Architektur v2 (Version B angepasst)

## Randbedingungen

- ioBroker Daten ueber lokale `simple-api`
- Zusatzmerkmale (Aussentemperatur, Wochentag, Feiertag, usw.) bereits als Datenpunkte in ioBroker vorhanden
- Konfigurationsdatenbank: SQLite ausreichend
- Prognoseintervall: 15-30 Minuten
- Zielplattform: Proxmox CT mit Debian, optional mehrere CT

## Logische Komponenten

1. Collector Service
- Liest zyklisch aus ioBroker `simple-api`
- Normalisiert Zeitstempel, Einheiten und Qualitaetsflags
- Schreibt Roh- und Aggregatwerte in InfluxDB

2. Forecast Service
- Lastprognose (P10/P50/P90) in 15-30 Minuten Slots bis Tagesende
- PV-Prognose via externer API plus lokaler Bias-Korrektur
- Persistiert Forecasts in InfluxDB und Metadaten in SQLite

3. Optimizer Service
- Rollierende Optimierung (MPC-artig) alle 5-10 Minuten
- Beruecksichtigt Prioritaeten, Regeln und technische Grenzen
- Erzeugt einen Fahrplan je steuerbares Geraet

4. Dispatcher Service
- Uebersetzt Fahrplan in konkrete ioBroker Sollwerte/Kommandos
- Safety-Checks, Timeouts, Fallback-Strategie
- Rueckmeldung von Ausfuehrungserfolg an InfluxDB/SQLite

5. API/UI Service
- REST API fuer Dashboard und Konfiguration
- Visualisierung von Live-, Historie- und Forecast-Daten
- Regeln, Prioritaeten, Betriebsmodi und Overrides

## Datenhaltung

- InfluxDB: Zeitreihen (Messwerte, Features, Forecasts, Ist-vs-Plan)
- SQLite: Konfiguration, Prioritaeten, Geraetestammdaten, Betriebsmodi, Aktionshistorie, Modellversionen

## Warum InfluxDB plus SQLite

- InfluxDB ist optimal fuer hochfrequente Zeitreihen
- SQLite ist leichtgewichtig und robust fuer Konfiguration in CT-Umgebungen
- Trennung verhindert unnoetige Komplexitaet und bleibt skalierbar

## Prognose- und Optimierungszyklus

1. Collector aktualisiert Messwerte (z. B. alle 10 s, Aggregation auf 1/5/15 min)
2. Forecast Service erzeugt neuen Tagesrest-Horizont (15 oder 30 min)
3. Optimizer berechnet aktualisierten Fahrplan
4. Dispatcher schreibt Steuerkommandos nach ioBroker
5. API/UI zeigt Plan und Ist-Abweichungen

## Prioritaeten als Regelwerk

1. Batterie bis Abendziel-SoC
2. Warmwasser April-September bevorzugt bei PV-Ueberschuss
3. EV bis Abfahrtszeit auf Ziel-SoC
4. Schlafzimmer-Kuehlung nur bei Extremtemperatur und verbleibendem Ueberschuss

## Betriebsmodi

- AUTO: Optimierer + Dispatcher aktiv
- PLAN_ONLY: Optimierer aktiv, Dispatcher inaktiv (nur Empfehlungen)
- MANUAL_OVERRIDE: Nutzer priorisiert einzelne Geraete manuell
- SAFE_FALLBACK: feste Sicherheitslogik ohne externe Forecast-Abhaengigkeit
