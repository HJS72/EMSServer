# Datenmodell (Startvorschlag)

## InfluxDB Buckets

1. `ems_raw`
- hochfrequente Messwerte (5-10 s)
- Retention z. B. 30 Tage

2. `ems_agg`
- Aggregationen 1 min, 5 min, 15 min
- Retention z. B. 2 Jahre

3. `ems_forecast`
- Last-, PV- und Netto-Prognosen je Slot
- Retention z. B. 180 Tage

4. `ems_control`
- Sollwerte, Kommandos, Ausfuehrungsstatus, Ist-vs-Plan
- Retention z. B. 365 Tage

## Messkonvention

- Measurement-Beispiele:
  - `power`
  - `energy`
  - `weather`
  - `forecast_load`
  - `forecast_pv`
  - `plan_device`
  - `dispatch_result`

- Tags:
  - `site`
  - `device_id`
  - `device_type` (pv, battery, ev, hp, climate, base_load)
  - `phase` optional
  - `source` (iobroker, api, model)

- Fields:
  - `value`
  - `unit`
  - `quality`
  - `confidence`
  - `quantile` (p10, p50, p90)

## SQLite Tabellen (Minimum)

1. `devices`
- id, name, type, enabled, min_power_w, max_power_w
- soc_min, soc_max, ramp_limits, control_state_id

2. `device_constraints`
- device_id, weekday_mask, start_time, end_time
- season_from, season_to, temp_min, temp_max

3. `priorities`
- scenario, rank, objective, weight, active

4. `targets`
- target_type (battery_evening_soc, ev_departure_soc, ww_temp, climate_temp)
- value, valid_from, valid_to

5. `modes`
- mode (AUTO, PLAN_ONLY, MANUAL_OVERRIDE, SAFE_FALLBACK)
- changed_by, changed_at

6. `forecast_runs`
- run_id, model_version, horizon_minutes, interval_minutes
- created_at, status, metrics_json

7. `optimizer_runs`
- run_id, forecast_run_id, objective_value, status
- created_at, plan_hash

8. `dispatch_log`
- ts, device_id, command, value, status, message

## Feature-Basis fuer Lastprognose

- Zeit: Slotindex, Stunde, Wochentag, Feiertag, Brueckentag
- Wetter: Aussentemperatur, gefuehlte Temp., Bewoelkung, Strahlung
- Historie: Last der letzten 1h/3h/24h, gleicher Wochentag letzte Wochen
- Betriebskontext: aktive Verbraucher, EV verbunden, Warmwasserstatus
