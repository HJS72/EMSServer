# Forecast Service

Aufgabe:
- Lastprognose fuer Resttag in 15-30 min Slots
- PV-Prognose via Web-API plus lokale Korrektur
- Persistenz in InfluxDB und Metadaten in SQLite

Start-MVP:
- Lastprognose: P50
- PV-Prognose: externe API + einfacher Bias

## Open-Meteo Integration (mit Selbstlernen)

Dieses Repository enthaelt jetzt einen Generator fuer Forecast-Slots auf Basis von Open-Meteo:

- Script: `scripts/generate_open_meteo_forecast.py`
- Provider: `services/forecast/open_meteo_provider.py`
- Beispiel-Config: `config/forecast_config.example.json`

Der Generator schreibt standardmaessig nach `/etc/ems/latest_forecast.json` mit folgendem Schema:

```
{
	"provider": "open-meteo",
	"generated_at": "...",
	"model": {"gain": 1.0, "bias": 0.0, "samples": 0},
	"slots": [{"ts": "...", "surplus_w": 1234.5, ...}]
}
```

### PV-Anlagen pro Konfiguration

Mehrere PV-Anlagen werden ueber `open_meteo.pv_systems` konfiguriert.

- Pro Eintrag: `name`, `pv_kwp`, `panel_tilt_deg`, `panel_azimuth_deg`
- Optional pro Eintrag: `system_efficiency`, `temp_coeff_per_deg`
- Die Prognose wird je Anlage berechnet und danach zu einer Gesamtleistung aufsummiert.

Wenn `pv_systems` fehlt, arbeitet der Provider rueckwaertskompatibel mit dem alten Single-Array-Format (`pv_kwp`, `panel_tilt_deg`, `panel_azimuth_deg`).

### Selbstlernender Teil

Der Provider nutzt ein lineares Online-Modell:

- Rohschaetzung aus GTI + Temperatur (aggregiert ueber alle PV-Anlagen) -> `pv_w_raw`
- Korrektur: `pv_w = gain * pv_w_raw + bias`
- Lernen aus Historie: Vergleich von vorigem Forecast-Slot mit aktuellem Ist-PV-Wert aus ioBroker

Persistenz:

- Modellparameter in `model_path` (Default: `/var/lib/ems/open_meteo_model.json`)
- Forecast-Historie in `history_path` (Default: `/var/lib/ems/open_meteo_history.json`)

### Schnellstart

1. Beispieldatei nach `/etc/ems/forecast_config.json` kopieren und anpassen.
2. Script ausfuehren:

```
python scripts/generate_open_meteo_forecast.py --config /etc/ems/forecast_config.json
```

3. Optional per systemd-Timer alle 15 Minuten ausfuehren.
4. Bestehender Control-Plan-Runner kann `latest_forecast.json` unveraendert verwenden.
