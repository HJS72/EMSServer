"""Steuerlogik fuer steuerbare Verbraucher auf Basis eines Ueberschuss-Forecasts."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field


class ForecastSlot(BaseModel):
    """Ein Forecast-Zeitschritt mit erwartetem Ueberschuss."""

    ts: str
    surplus_w: float = Field(default=0.0)


class WaterHeatPumpConfig(BaseModel):
    enabled: bool = True
    power_w: float = 1200.0
    temp_current_c: float = 50.0
    temp_min_c: float = 47.0
    temp_max_c: float = 58.0
    heat_gain_c_per_slot: float = 1.0
    cool_loss_c_per_slot: float = 0.2
    command_state_id: Optional[str] = None
    status_state_id: Optional[str] = None


class ClimateConfig(BaseModel):
    enabled: bool = True
    power_w: float = 900.0
    temp_current_c: float = 27.0
    temp_min_c: float = 22.0
    temp_max_c: float = 26.0
    cool_gain_c_per_slot: float = 0.8
    heat_gain_c_per_slot: float = 0.2
    command_state_id: Optional[str] = None
    status_state_id: Optional[str] = None


class WallboxConfig(BaseModel):
    enabled: bool = True
    auto_mode: bool = True
    auto_mode_state_id: Optional[str] = None
    min_power_w: float = 1400.0
    max_power_w: float = 22000.0
    phase_switch_power_w: float = 4200.0
    phase_switch_buffer_slots: int = 1
    vehicle_soc_pct: float = 20.0
    vehicle_target_soc_pct: float = 80.0
    vehicle_capacity_kwh: float = 60.0
    charge_efficiency: float = 0.92
    command_state_id: Optional[str] = None
    status_state_id: Optional[str] = None


class ControlConfig(BaseModel):
    """Persistierbare Grundkonfiguration fuer die Steuerlogik."""

    interval_minutes: int = 15
    publish_to_iobroker: bool = False
    iobroker_host: Optional[str] = None
    iobroker_port: int = 8087
    dhw: Optional[WaterHeatPumpConfig] = None
    climate: Optional[ClimateConfig] = None
    wallbox: Optional[WallboxConfig] = None


class ControlPlanRequest(BaseModel):
    slots: List[ForecastSlot]
    interval_minutes: int = 15
    publish_to_iobroker: bool = False
    iobroker_host: str
    iobroker_port: int = 8087
    dhw: Optional[WaterHeatPumpConfig] = None
    climate: Optional[ClimateConfig] = None
    wallbox: Optional[WallboxConfig] = None


@dataclass
class _DeviceAction:
    on: bool
    power_w: float
    reason: str


class ControlPlanSlotResult(BaseModel):
    ts: str
    surplus_w: float
    remaining_surplus_w: float
    dhw_on: bool = False
    dhw_power_w: float = 0.0
    dhw_temp_c: Optional[float] = None
    climate_on: bool = False
    climate_power_w: float = 0.0
    climate_temp_c: Optional[float] = None
    wallbox_on: bool = False
    wallbox_power_w: float = 0.0
    wallbox_phase_mode: str = "off"
    wallbox_soc_pct: Optional[float] = None
    notes: List[str] = Field(default_factory=list)


class ControlPlanResponse(BaseModel):
    interval_minutes: int
    slots: List[ControlPlanSlotResult]
    summary: Dict[str, Any]
    iobroker_writeback: Dict[str, Any]


def _extract_windows(slots: List[ControlPlanSlotResult], key: str) -> List[Dict[str, str]]:
    windows: List[Dict[str, str]] = []
    start: Optional[str] = None
    previous_ts: Optional[str] = None
    for slot in slots:
        active = bool(getattr(slot, key))
        if active and start is None:
            start = slot.ts
        if not active and start is not None:
            windows.append({"from": start, "to": previous_ts or slot.ts})
            start = None
        previous_ts = slot.ts
    if start is not None:
        windows.append({"from": start, "to": previous_ts or start})
    return windows


async def _get_iobroker_value(host: str, port: int, state_id: str) -> Any:
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.get(f"http://{host}:{port}/get/{state_id}")
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            return data.get("val")
        return None


async def _set_iobroker_value(host: str, port: int, state_id: str, value: Any) -> bool:
    value_str = json.dumps(value, separators=(",", ":")) if isinstance(value, (dict, list)) else str(value)
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.get(
            f"http://{host}:{port}/set/{state_id}",
            params={"value": value_str},
        )
        resp.raise_for_status()
        return "true" in resp.text.lower()


def _plan_dhw(
    cfg: WaterHeatPumpConfig,
    available_w: float,
    at_end_of_horizon: bool,
    current_temp_c: float,
) -> _DeviceAction:
    if not cfg.enabled:
        return _DeviceAction(on=False, power_w=0.0, reason="disabled")

    if current_temp_c < cfg.temp_min_c and available_w >= cfg.power_w:
        return _DeviceAction(on=True, power_w=cfg.power_w, reason="below_min_use_surplus")

    if at_end_of_horizon and current_temp_c < cfg.temp_max_c and available_w >= cfg.power_w:
        return _DeviceAction(on=True, power_w=cfg.power_w, reason="tail_surplus_to_max")

    return _DeviceAction(on=False, power_w=0.0, reason="within_window")


def _plan_climate(cfg: ClimateConfig, available_w: float, current_temp_c: float) -> _DeviceAction:
    if not cfg.enabled:
        return _DeviceAction(on=False, power_w=0.0, reason="disabled")

    if current_temp_c > cfg.temp_max_c and available_w >= cfg.power_w:
        return _DeviceAction(on=True, power_w=cfg.power_w, reason="above_max_cool_to_min")

    return _DeviceAction(on=False, power_w=0.0, reason="within_window")


def _plan_wallbox(
    cfg: WallboxConfig,
    available_w: float,
    current_soc_pct: float,
    current_phase_mode: str,
) -> _DeviceAction:
    if not cfg.enabled or not cfg.auto_mode:
        return _DeviceAction(on=False, power_w=0.0, reason="disabled_or_not_auto")

    if cfg.vehicle_capacity_kwh <= 0:
        return _DeviceAction(on=False, power_w=0.0, reason="invalid_vehicle_capacity")

    if current_soc_pct >= cfg.vehicle_target_soc_pct:
        return _DeviceAction(on=False, power_w=0.0, reason="target_soc_reached")

    if available_w < cfg.min_power_w:
        return _DeviceAction(on=False, power_w=0.0, reason="not_enough_surplus")

    power_w = max(cfg.min_power_w, min(cfg.max_power_w, available_w))
    next_phase_mode = "three" if power_w >= cfg.phase_switch_power_w else "single"
    if current_phase_mode in ("single", "three") and next_phase_mode != current_phase_mode:
        return _DeviceAction(on=True, power_w=power_w, reason="phase_switch_pending")

    return _DeviceAction(on=True, power_w=power_w, reason="charge_with_available_surplus")


async def create_control_plan(payload: ControlPlanRequest) -> ControlPlanResponse:
    slots = payload.slots
    interval_h = payload.interval_minutes / 60.0
    tail_start_index = max(0, len(slots) - 4)

    dhw_cfg = payload.dhw
    climate_cfg = payload.climate
    wallbox_cfg = payload.wallbox

    if wallbox_cfg and wallbox_cfg.auto_mode_state_id:
        try:
            auto_mode_value = await _get_iobroker_value(
                payload.iobroker_host,
                payload.iobroker_port,
                wallbox_cfg.auto_mode_state_id,
            )
            wallbox_cfg.auto_mode = bool(auto_mode_value)
        except Exception:
            # Wenn der externe Auto-Mode-State gerade nicht erreichbar ist,
            # bleibt der zuletzt gesetzte Wert bestehen.
            pass

    dhw_temp = dhw_cfg.temp_current_c if dhw_cfg else None
    climate_temp = climate_cfg.temp_current_c if climate_cfg else None
    wallbox_soc = wallbox_cfg.vehicle_soc_pct if wallbox_cfg else None
    wallbox_phase_mode = "off"
    wallbox_buffer_remaining = 0

    results: List[ControlPlanSlotResult] = []

    for idx, slot in enumerate(slots):
        notes: List[str] = []
        available_w = max(0.0, slot.surplus_w)

        wallbox_action = _DeviceAction(False, 0.0, "not_configured")
        if wallbox_cfg and wallbox_soc is not None:
            wallbox_action = _plan_wallbox(
                wallbox_cfg,
                available_w=available_w,
                current_soc_pct=wallbox_soc,
                current_phase_mode=wallbox_phase_mode,
            )

            if wallbox_action.on:
                desired_phase = "three" if wallbox_action.power_w >= wallbox_cfg.phase_switch_power_w else "single"
                if wallbox_phase_mode in ("single", "three") and desired_phase != wallbox_phase_mode:
                    wallbox_buffer_remaining = max(
                        wallbox_buffer_remaining,
                        max(0, wallbox_cfg.phase_switch_buffer_slots),
                    )
                    notes.append("wallbox_phase_switch_buffer_active")

                wallbox_phase_mode = desired_phase
                used_wallbox_power = min(available_w, wallbox_action.power_w)
                available_w = max(0.0, available_w - used_wallbox_power)

                charged_kwh = used_wallbox_power * interval_h / 1000.0 * wallbox_cfg.charge_efficiency
                soc_delta = (charged_kwh / wallbox_cfg.vehicle_capacity_kwh) * 100.0
                wallbox_soc = min(100.0, wallbox_soc + soc_delta)
            else:
                wallbox_phase_mode = "off"

        block_others_due_to_phase_switch = wallbox_buffer_remaining > 0
        if block_others_due_to_phase_switch:
            notes.append("other_devices_blocked_during_wallbox_phase_switch")

        dhw_action = _DeviceAction(False, 0.0, "not_configured")
        if dhw_cfg and dhw_temp is not None and not block_others_due_to_phase_switch:
            dhw_action = _plan_dhw(
                dhw_cfg,
                available_w=available_w,
                at_end_of_horizon=idx >= tail_start_index,
                current_temp_c=dhw_temp,
            )
            if dhw_action.on:
                used_dhw_power = min(available_w, dhw_action.power_w)
                available_w = max(0.0, available_w - used_dhw_power)
                dhw_temp = min(dhw_cfg.temp_max_c, dhw_temp + dhw_cfg.heat_gain_c_per_slot)
            else:
                dhw_temp = max(dhw_cfg.temp_min_c - 20.0, dhw_temp - dhw_cfg.cool_loss_c_per_slot)

        climate_action = _DeviceAction(False, 0.0, "not_configured")
        if climate_cfg and climate_temp is not None and not block_others_due_to_phase_switch:
            climate_action = _plan_climate(
                climate_cfg,
                available_w=available_w,
                current_temp_c=climate_temp,
            )
            if climate_action.on:
                used_climate_power = min(available_w, climate_action.power_w)
                available_w = max(0.0, available_w - used_climate_power)
                climate_temp = max(climate_cfg.temp_min_c, climate_temp - climate_cfg.cool_gain_c_per_slot)
            else:
                climate_temp = climate_temp + climate_cfg.heat_gain_c_per_slot

        results.append(
            ControlPlanSlotResult(
                ts=slot.ts,
                surplus_w=slot.surplus_w,
                remaining_surplus_w=available_w,
                dhw_on=dhw_action.on,
                dhw_power_w=dhw_action.power_w if dhw_action.on else 0.0,
                dhw_temp_c=dhw_temp,
                climate_on=climate_action.on,
                climate_power_w=climate_action.power_w if climate_action.on else 0.0,
                climate_temp_c=climate_temp,
                wallbox_on=wallbox_action.on,
                wallbox_power_w=wallbox_action.power_w if wallbox_action.on else 0.0,
                wallbox_phase_mode=wallbox_phase_mode,
                wallbox_soc_pct=wallbox_soc,
                notes=notes,
            )
        )

        if wallbox_buffer_remaining > 0:
            wallbox_buffer_remaining -= 1

    summary: Dict[str, Any] = {
        "dhw_windows": _extract_windows(results, "dhw_on"),
        "climate_windows": _extract_windows(results, "climate_on"),
        "wallbox_windows": _extract_windows(results, "wallbox_on"),
        "final_dhw_temp_c": dhw_temp,
        "final_climate_temp_c": climate_temp,
        "final_wallbox_soc_pct": wallbox_soc,
    }

    writeback: Dict[str, Any] = {
        "enabled": payload.publish_to_iobroker,
        "writes": [],
        "errors": [],
    }

    if payload.publish_to_iobroker and results:
        first = results[0]
        async def _write_safe(state_id: str, value: Any) -> None:
            try:
                ok = await _set_iobroker_value(
                    payload.iobroker_host,
                    payload.iobroker_port,
                    state_id,
                    value,
                )
                writeback["writes"].append({"state_id": state_id, "ok": ok})
            except Exception as exc:
                writeback["errors"].append(f"{state_id}: {exc}")

        if dhw_cfg and dhw_cfg.command_state_id:
            await _write_safe(dhw_cfg.command_state_id, int(first.dhw_on))
        if dhw_cfg and dhw_cfg.status_state_id:
            await _write_safe(dhw_cfg.status_state_id, summary["dhw_windows"])

        if climate_cfg and climate_cfg.command_state_id:
            await _write_safe(climate_cfg.command_state_id, int(first.climate_on))
        if climate_cfg and climate_cfg.status_state_id:
            await _write_safe(climate_cfg.status_state_id, summary["climate_windows"])

        if wallbox_cfg and wallbox_cfg.command_state_id:
            await _write_safe(wallbox_cfg.command_state_id, int(first.wallbox_on))
        if wallbox_cfg and wallbox_cfg.status_state_id:
            status_payload = {
                "windows": summary["wallbox_windows"],
                "final_soc_pct": summary["final_wallbox_soc_pct"],
            }
            await _write_safe(wallbox_cfg.status_state_id, status_payload)

    return ControlPlanResponse(
        interval_minutes=payload.interval_minutes,
        slots=results,
        summary=summary,
        iobroker_writeback=writeback,
    )
