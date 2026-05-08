#!/usr/bin/env python3
"""Generate / update latest forecast slots from Open-Meteo."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, Optional
from urllib.parse import quote
from urllib.request import urlopen

# Ensure repository root is importable when script is executed directly.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.forecast.open_meteo_provider import build_surplus_slots, load_config


DEFAULT_CONFIG_PATHS = [
    Path("/etc/ems/forecast_config.json"),
    Path("config/forecast_config.json"),
]


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


def _find_config_path(cli_path: Optional[str]) -> Path:
    if cli_path:
        p = Path(cli_path)
        if not p.exists():
            raise FileNotFoundError(f"config not found: {p}")
        return p

    for candidate in DEFAULT_CONFIG_PATHS:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "no forecast config found. tried: "
        + ", ".join(str(p) for p in DEFAULT_CONFIG_PATHS)
    )


def _read_iobroker_value(host: str, port: int, state_id: str) -> Optional[float]:
    state_id_encoded = quote(state_id, safe="")
    url = f"http://{host}:{port}/get/{state_id_encoded}"
    with urlopen(url, timeout=8) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    if not isinstance(payload, dict):
        return None
    val = payload.get("val")
    if val in (None, ""):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _load_forecast_file(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    slots = data.get("slots")
    if not isinstance(slots, list) or not slots:
        return None
    return data


def _load_fallback_forecast(output_path: Path, raw_cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    fallback_cfg = raw_cfg.get("fallback", {})
    if not isinstance(fallback_cfg, dict):
        fallback_cfg = {}
    if not fallback_cfg.get("enabled", True):
        return None

    candidate_paths = [
        Path(fallback_cfg.get("cache_path", "/var/lib/ems/latest_forecast_ok.json")),
        output_path,
    ]
    for p in candidate_paths:
        data = _load_forecast_file(p)
        if data is not None:
            return data
    return None


def _mark_fallback(payload: Dict[str, Any], reason: str) -> Dict[str, Any]:
    out = dict(payload)
    meta = out.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    meta["fallback_active"] = True
    meta["fallback_reason"] = reason
    out["meta"] = meta
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate forecast slots from Open-Meteo")
    parser.add_argument("--config", help="path to forecast_config.json")
    parser.add_argument("--output", help="override output path")
    args = parser.parse_args()

    cfg_path = _find_config_path(args.config)
    raw = _load_json(cfg_path)

    provider_raw = raw.get("open_meteo", raw)
    cfg = load_config(provider_raw)

    output_path = Path(args.output or raw.get("output_path", "/etc/ems/latest_forecast.json"))

    actual_pv_w: Optional[float] = None
    learn_raw = raw.get("learning", {})
    if isinstance(learn_raw, dict) and learn_raw.get("enabled", True):
        state_id = learn_raw.get("actual_pv_state_id")
        host = str(learn_raw.get("iobroker_host", "127.0.0.1"))
        port = int(learn_raw.get("iobroker_port", 8087))
        if state_id:
            try:
                actual_pv_w = _read_iobroker_value(host, port, str(state_id))
            except Exception:
                actual_pv_w = None

    fallback_cfg = raw.get("fallback", {})
    if not isinstance(fallback_cfg, dict):
        fallback_cfg = {}
    cache_path = Path(fallback_cfg.get("cache_path", "/var/lib/ems/latest_forecast_ok.json"))

    result: Dict[str, Any]
    try:
        result = build_surplus_slots(cfg, actual_pv_w=actual_pv_w)
        # Cache most recent valid forecast for emergency fallback.
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(result, indent=2))
    except Exception as exc:
        fallback = _load_fallback_forecast(output_path, raw)
        if fallback is None:
            raise
        result = _mark_fallback(fallback, reason=f"open-meteo-failed: {exc}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2))

    archive_enabled = bool(raw.get("archive", {}).get("enabled", False))
    if archive_enabled:
        archive_dir = Path(raw.get("archive", {}).get("path", "/etc/ems/archive"))
        archive_dir.mkdir(parents=True, exist_ok=True)
        ts = result.get("generated_at", "unknown").replace(":", "-")
        archive_path = archive_dir / f"forecast-{ts}.json"
        archive_path.write_text(json.dumps(result, indent=2))

    print(
        "forecast written",
        str(output_path),
        "slots=",
        len(result.get("slots", [])),
        "samples=",
        result.get("model", {}).get("samples"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
