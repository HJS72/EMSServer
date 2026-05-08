# Umsetzungsplan (Version B mit SQLite)

## Phase 0 - Grundlagen (Woche 1)

1. Projektgeruest, Konfigschema, Secrets-Konzept
2. Influx Buckets und Retention Policies anlegen
3. SQLite Schema initialisieren
4. ioBroker Connector fuer `simple-api` implementieren

## Phase 1 - Datenerfassung (Woche 2)

1. polling/event-nahe Erfassung fuer alle relevanten Datenpunkte
2. Normalisierung, Qualitaetsflags, Aggregationsjobs
3. Monitoring fuer Luecken und Ausreisser

## Phase 2 - Prognose (Woche 3-4)

1. Lastprognosemodell (15-30 min Intervall)
2. PV-Prognose ueber API (Solcast/Forecast.Solar) + Fallback
3. Ensemble/Bias-Korrektur mit lokalen Ist-Daten
4. Metriken (MAE/MAPE/Bias) in Historie speichern

## Phase 3 - Optimierung und Steuerung (Woche 5-6)

1. Zielfunktion und Nebenbedingungen implementieren
2. Prioritaeten (Batterie, WWP, EV, Klima) als konfigurierbare Regeln
3. Dispatcher mit Safety-Layer und Fallback
4. PLAN_ONLY Modus fuer sichere Inbetriebnahme

## Phase 4 - UI und produktiver Betrieb (Woche 7-8)

1. Live-Dashboard + Forecast + Fahrplan
2. Konfig-UI fuer Regeln, Ziele, Modi
3. Alarmierung und Betriebskennzahlen
4. schrittweise Aktivierung AUTO Modus

## Entscheidungsparameter jetzt

1. Intervall fixieren: 15 oder 30 Minuten
2. Primar-API fuer PV-Forecast festlegen
3. Minimaler Satz steuerbarer Geraete fuer MVP
4. Start in PLAN_ONLY oder direkt AUTO
