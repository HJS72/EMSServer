"""Open-Meteo PV forecast with lightweight self-learning calibration."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo


@dataclass
class PVSystemConfig:
    name: str
    pv_kwp: float
    panel_tilt_deg: float
    panel_azimuth_deg: float
    system_efficiency: Optional[float] = None
    temp_coeff_per_deg: Optional[float] = None


@dataclass
class OpenMeteoConfig:
    latitude: float
    longitude: float
    timezone: str = "Europe/Berlin"
    forecast_days: int = 2
    pv_kwp: float = 10.0
    panel_tilt_deg: float = 35.0
    panel_azimuth_deg: float = 0.0
    temp_coeff_per_deg: float = -0.004
    system_efficiency: float = 0.93
    base_load_w: float = 300.0
    min_surplus_w: float = 0.0
    model_path: str = "/var/lib/ems/open_meteo_model.json"
    history_path: str = "/var/lib/ems/open_meteo_history.json"
    pv_systems: List[PVSystemConfig] = field(default_factory=list)


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _parse_ts(ts: str, naive_tz: Optional[ZoneInfo] = None) -> datetime:
    if ts.endswith("Z"):
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)
    parsed = datetime.fromisoformat(ts)
    if parsed.tzinfo is None:
        base_tz = naive_tz or UTC
        return parsed.replace(tzinfo=base_tz).astimezone(UTC)
    return parsed.astimezone(UTC)


def _to_iso_z(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class LinearCalibrator:
    """Online linear correction for model output: actual ~= gain * pred + bias."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.gain = 1.0
        self.bias = 0.0
        self.lr = 0.02
        self.count = 0
        self.max_abs_error_w = 2500.0
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
            self.gain = float(data.get("gain", 1.0))
            self.bias = float(data.get("bias", 0.0))
            self.lr = float(data.get("lr", 0.02))
            self.count = int(data.get("count", 0))
            self.max_abs_error_w = float(data.get("max_abs_error_w", 2500.0))
        except Exception:
            # Keep defaults if file is missing or invalid.
            self.gain = 1.0
            self.bias = 0.0
            self.lr = 0.02
            self.count = 0
            self.max_abs_error_w = 2500.0

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "gain": self.gain,
                    "bias": self.bias,
                    "lr": self.lr,
                    "count": self.count,
                    "max_abs_error_w": self.max_abs_error_w,
                    "updated_at": _to_iso_z(_now_utc()),
                },
                indent=2,
            )
        )

    def apply(self, predicted_w: float) -> float:
        corrected = self.gain * predicted_w + self.bias
        return max(0.0, corrected)

    def update(self, predicted_w: float, actual_w: float) -> None:
        pred = max(0.0, float(predicted_w))
        actual = max(0.0, float(actual_w))
        corrected = self.apply(pred)
        error = actual - corrected

        # Ignore extreme outliers to keep learning stable.
        if abs(error) > self.max_abs_error_w:
            return

        # Stochastic gradient descent for y = gain*x + bias.
        self.gain += self.lr * error * pred / 1_000_000.0
        self.bias += self.lr * error

        # Keep model in realistic bounds.
        self.gain = min(1.5, max(0.2, self.gain))
        self.bias = min(2000.0, max(-2000.0, self.bias))

        self.count += 1


def load_config(raw: Dict[str, Any]) -> OpenMeteoConfig:
    required = ("latitude", "longitude")
    missing = [key for key in required if key not in raw]
    if missing:
        raise ValueError(f"missing config keys: {', '.join(missing)}")
    normalized = dict(raw)

    systems_raw = raw.get("pv_systems")
    pv_systems: List[PVSystemConfig] = []
    if isinstance(systems_raw, list) and systems_raw:
        for idx, item in enumerate(systems_raw):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or f"pv{idx + 1}")
            pv_systems.append(
                PVSystemConfig(
                    name=name,
                    pv_kwp=float(item.get("pv_kwp", 0.0)),
                    panel_tilt_deg=float(item.get("panel_tilt_deg", 35.0)),
                    panel_azimuth_deg=float(item.get("panel_azimuth_deg", 0.0)),
                    system_efficiency=(
                        float(item["system_efficiency"])
                        if item.get("system_efficiency") is not None
                        else None
                    ),
                    temp_coeff_per_deg=(
                        float(item["temp_coeff_per_deg"])
                        if item.get("temp_coeff_per_deg") is not None
                        else None
                    ),
                )
            )

    if not pv_systems:
        # Backward compatible single-system mode.
        pv_systems = [
            PVSystemConfig(
                name="pv1",
                pv_kwp=float(raw.get("pv_kwp", 10.0)),
                panel_tilt_deg=float(raw.get("panel_tilt_deg", 35.0)),
                panel_azimuth_deg=float(raw.get("panel_azimuth_deg", 0.0)),
                system_efficiency=float(raw.get("system_efficiency", 0.93)),
                temp_coeff_per_deg=float(raw.get("temp_coeff_per_deg", -0.004)),
            )
        ]

    normalized["pv_systems"] = pv_systems
    return OpenMeteoConfig(**normalized)


def _build_open_meteo_url(cfg: OpenMeteoConfig, pv_system: PVSystemConfig) -> str:
    params = {
        "latitude": cfg.latitude,
        "longitude": cfg.longitude,
        "timezone": cfg.timezone,
        "forecast_days": cfg.forecast_days,
        "minutely_15": "global_tilted_irradiance,temperature_2m",
        "tilt": pv_system.panel_tilt_deg,
        "azimuth": pv_system.panel_azimuth_deg,
    }
    return f"https://api.open-meteo.com/v1/forecast?{urlencode(params)}"


def _fetch_open_meteo(cfg: OpenMeteoConfig, pv_system: PVSystemConfig) -> Dict[str, Any]:
    url = _build_open_meteo_url(cfg, pv_system)
    with urlopen(url, timeout=20) as resp:
        payload = resp.read().decode("utf-8", errors="replace")
    data = json.loads(payload)
    if not isinstance(data, dict) or "minutely_15" not in data:
        raise ValueError("unexpected Open-Meteo response")
    return data


def _pv_from_gti_temp(
    cfg: OpenMeteoConfig,
    pv_system: PVSystemConfig,
    gti_wm2: float,
    temp_c: float,
) -> float:
    eff = pv_system.system_efficiency if pv_system.system_efficiency is not None else cfg.system_efficiency
    temp_coeff = (
        pv_system.temp_coeff_per_deg
        if pv_system.temp_coeff_per_deg is not None
        else cfg.temp_coeff_per_deg
    )
    irr_factor = max(0.0, gti_wm2) / 1000.0
    temp_factor = 1.0 + temp_coeff * (temp_c - 25.0)
    temp_factor = max(0.5, min(1.2, temp_factor))
    return max(0.0, pv_system.pv_kwp * 1000.0 * irr_factor * temp_factor * eff)


def _load_history(path: str) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except Exception:
        pass
    return []


def _save_history(path: str, items: List[Dict[str, Any]], keep: int = 2000) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items[-keep:], indent=2))


def _pick_train_sample(
    history: List[Dict[str, Any]],
    now: datetime,
    grace_minutes: int = 30,
) -> Optional[Tuple[int, Dict[str, Any]]]:
    best_idx: Optional[int] = None
    best_item: Optional[Dict[str, Any]] = None
    best_delta = math.inf
    for idx, item in enumerate(history):
        if item.get("actual_pv_w") is not None:
            continue
        ts = item.get("ts")
        if not isinstance(ts, str):
            continue
        try:
            dt = _parse_ts(ts)
        except Exception:
            continue
        delta_s = (now - dt).total_seconds()
        if delta_s < 0:
            continue
        if delta_s > grace_minutes * 60:
            continue
        if delta_s < best_delta:
            best_delta = delta_s
            best_idx = idx
            best_item = item
    if best_idx is None or best_item is None:
        return None
    return best_idx, best_item


def build_surplus_slots(
    cfg: OpenMeteoConfig,
    actual_pv_w: Optional[float] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build control slots and update calibration from latest available actual."""
    now_utc = now or _now_utc()
    calibrator = LinearCalibrator(cfg.model_path)
    history = _load_history(cfg.history_path)
    try:
        local_tz = ZoneInfo(cfg.timezone)
    except Exception:
        local_tz = UTC

    # Learn from the latest matured forecast slot if current actual is available.
    if actual_pv_w is not None:
        picked = _pick_train_sample(history, now_utc)
        if picked is not None:
            idx, sample = picked
            predicted_raw = float(sample.get("predicted_raw_w", 0.0))
            calibrator.update(predicted_raw, actual_pv_w)
            sample["actual_pv_w"] = max(0.0, float(actual_pv_w))
            sample["error_w"] = sample["actual_pv_w"] - float(sample.get("predicted_w", 0.0))
            sample["trained_at"] = _to_iso_z(now_utc)
            history[idx] = sample

    aggregated: Dict[str, Dict[str, float]] = {}
    for pv_system in cfg.pv_systems:
        data = _fetch_open_meteo(cfg, pv_system)
        mm = data.get("minutely_15", {})
        times = mm.get("time", [])
        gti_list = mm.get("global_tilted_irradiance", [])
        temp_list = mm.get("temperature_2m", [])

        for ts, gti, temp in zip(times, gti_list, temp_list):
            try:
                # Open-Meteo liefert bei timezone=Europe/Berlin lokale Zeit ohne Offset.
                # Diese muss als lokale Zeit interpretiert und nach UTC umgerechnet werden.
                dt = _parse_ts(ts, naive_tz=local_tz)
                if dt < now_utc:
                    continue
                gti_v = float(gti)
                temp_v = float(temp)
            except Exception:
                continue

            raw_part_w = _pv_from_gti_temp(cfg, pv_system, gti_v, temp_v)
            point = aggregated.setdefault(
                _to_iso_z(dt),
                {"raw_pv_w": 0.0, "temp_c": temp_v},
            )
            point["raw_pv_w"] += raw_part_w
            point["temp_c"] = temp_v

    slots: List[Dict[str, Any]] = []
    new_history_items: List[Dict[str, Any]] = []

    for ts in sorted(aggregated.keys()):
        try:
            dt = _parse_ts(ts)
            raw_pv_w = float(aggregated[ts]["raw_pv_w"])
        except Exception:
            continue

        calibrated_pv_w = calibrator.apply(raw_pv_w)
        surplus_w = max(cfg.min_surplus_w, calibrated_pv_w - cfg.base_load_w)

        slot = {
            "ts": _to_iso_z(dt),
            "surplus_w": round(surplus_w, 1),
            "pv_w": round(calibrated_pv_w, 1),
            "pv_w_raw": round(raw_pv_w, 1),
            "base_load_w": cfg.base_load_w,
        }
        slots.append(slot)
        new_history_items.append(
            {
                "ts": slot["ts"],
                "predicted_raw_w": slot["pv_w_raw"],
                "predicted_w": slot["pv_w"],
                "actual_pv_w": None,
                "created_at": _to_iso_z(now_utc),
            }
        )

    # Merge by timestamp, newest prediction overwrites older one.
    merged_by_ts: Dict[str, Dict[str, Any]] = {}
    for item in history:
        ts = item.get("ts")
        if isinstance(ts, str):
            merged_by_ts[ts] = item
    for item in new_history_items:
        merged_by_ts[item["ts"]] = item

    merged_history = sorted(merged_by_ts.values(), key=lambda x: x.get("ts", ""))
    _save_history(cfg.history_path, merged_history)
    calibrator.save()

    return {
        "provider": "open-meteo",
        "generated_at": _to_iso_z(now_utc),
        "model": {
            "gain": round(calibrator.gain, 6),
            "bias": round(calibrator.bias, 3),
            "samples": calibrator.count,
        },
        "pv_systems": [pv.name for pv in cfg.pv_systems],
        "slots": slots,
    }
