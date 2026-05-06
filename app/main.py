from __future__ import annotations

import asyncio
import subprocess
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import load_settings
from app.models import DataPointConfig
from app.services.datapoint_config import DataPointConfigService
from app.services.forecast_engine import ForecastEngine
from app.services.influx_source import InfluxSource
from app.services.iobroker_source import IoBrokerSource
from app.services.pv_forecast import PvForecastService
from app.services.storage import Storage

settings = load_settings()

_VERSION_FILE = Path(__file__).parent.parent / "VERSION"
APP_VERSION: str = _VERSION_FILE.read_text().strip() if _VERSION_FILE.exists() else "0.0.0"

GITHUB_REPO = "HJS72/EMSServer"

influx = InfluxSource(settings)
iobroker = IoBrokerSource(settings)
pv_service = PvForecastService(settings)
storage = Storage(settings.data_dir)
config_service = DataPointConfigService(settings.data_dir)
engine = ForecastEngine(settings, influx, iobroker, pv_service, storage)
scheduler = AsyncIOScheduler(timezone=settings.timezone)

templates = Jinja2Templates(directory="app/templates")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not scheduler.running:
        scheduler.add_job(engine.build_today_forecast, "cron", minute="3")
        scheduler.start()

    try:
        await engine.build_today_forecast()
    except Exception:
        pass

    yield

    if scheduler.running:
        scheduler.shutdown(wait=False)
    influx.close()


app = FastAPI(title="EMS Forecast Server", version=APP_VERSION, lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request, "version": APP_VERSION})


@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("config.html", {"request": request, "version": APP_VERSION})


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/forecast/today")
async def forecast_today() -> JSONResponse:
    cached = engine.load_cached_forecast()
    if cached is not None:
        return JSONResponse(cached.model_dump(mode="json"))

    try:
        fresh = await asyncio.wait_for(engine.build_today_forecast(), timeout=8.0)
        return JSONResponse(fresh.model_dump(mode="json"))
    except Exception:
        return JSONResponse({"created_at": datetime.now().astimezone().isoformat(), "points": []})


@app.get("/api/actuals/today")
async def actuals_today() -> JSONResponse:
    try:
        actuals = await asyncio.wait_for(engine.build_today_actuals(), timeout=8.0)
        return JSONResponse(actuals.model_dump(mode="json"))
    except Exception:
        return JSONResponse({"created_at": datetime.now().astimezone().isoformat(), "points": []})


@app.get("/api/compare/today")
async def compare_today() -> JSONResponse:
    try:
        compare = await asyncio.wait_for(engine.build_today_compare(), timeout=8.0)
        return JSONResponse(compare.model_dump(mode="json"))
    except Exception:
        return JSONResponse({"created_at": datetime.now().astimezone().isoformat(), "points": []})


@app.get("/api/history")
async def history(days: int = Query(default=14, ge=1, le=365)) -> JSONResponse:
    try:
        payload = await asyncio.wait_for(asyncio.to_thread(engine.build_history_daily, days), timeout=8.0)
        return JSONResponse(payload)
    except Exception:
        return JSONResponse({"actual": [], "forecast": []})


@app.get("/api/config/datapoints")
async def get_datapoint_config() -> JSONResponse:
    config = config_service.load()
    return JSONResponse(config.model_dump(mode="json"))


@app.put("/api/config/datapoints")
async def put_datapoint_config(payload: DataPointConfig) -> JSONResponse:
    config_service.save(payload)
    return JSONResponse({"status": "ok"})


@app.get("/api/livedata/all")
async def livedata_all() -> JSONResponse:
    config = config_service.load()
    calculation_sources = {"calculation", "calculation_db"}
    result = {
        "devices": [],
        "consumers": [],
        "controllable_consumers": [],
        "generators": [],
        "grid": {"import_value": None, "export_value": None, "import_power": None, "export_power": None},
    }

    async def get_value(state_key: str, source: str) -> float | None:
        if not state_key:
            return None
        try:
            if source == "iobroker":
                return await asyncio.wait_for(iobroker.get_current_value(state_key), timeout=3.0)
            if source in calculation_sources:
                return None
            else:
                return await asyncio.wait_for(influx.get_latest_value(state_key), timeout=3.5)
        except Exception:
            return None

    async def calculate_energy_from_power(power_state_key: str, power_source: str) -> float | None:
        if not power_state_key:
            return None

        now = datetime.now().astimezone()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        try:
            if power_source == "iobroker":
                points = await asyncio.wait_for(
                    asyncio.to_thread(
                        iobroker.get_history,
                        power_state_key,
                        start,
                        now,
                        "average",
                        96,
                    ),
                    timeout=4.0,
                )
            else:
                points = await asyncio.wait_for(
                    asyncio.to_thread(influx.hourly_series, power_state_key, start, now, ""),
                    timeout=4.0,
                )
        except Exception:
            return None

        if not points:
            return None

        points = sorted(points, key=lambda p: p.time)
        if len(points) == 1:
            return round(max(0.0, float(points[0].value)) / 1000.0, 3)

        total_kwh = 0.0
        prev = points[0]
        for point in points[1:]:
            dt_h = (point.time - prev.time).total_seconds() / 3600.0
            if dt_h <= 0:
                prev = point
                continue
            p0 = max(0.0, float(prev.value))
            p1 = max(0.0, float(point.value))
            total_kwh += ((p0 + p1) / 2.0) * dt_h / 1000.0
            prev = point

        return round(total_kwh, 3)

    async def maybe_write_calculated_value(state_key: str, source: str, value: float | None) -> None:
        if source != "calculation_db" or not state_key or value is None:
            return
        try:
            await asyncio.wait_for(asyncio.to_thread(influx.write_value, state_key, value), timeout=3.0)
        except Exception:
            return

    async def build_consumer(consumer):
        power_val = await get_value(consumer.power_state_key, consumer.power_source)
        if consumer.source in calculation_sources:
            val = await calculate_energy_from_power(consumer.power_state_key, consumer.power_source)
            await maybe_write_calculated_value(consumer.state_key, consumer.source, val)
        else:
            val = await get_value(consumer.state_key, consumer.source)
        return {
            "id": consumer.id,
            "name": consumer.name, 
            "state_key": consumer.state_key, 
            "source": consumer.source, 
            "value_kwh": val,
            "power_state_key": consumer.power_state_key,
            "power_source": consumer.power_source,
            "power_w": power_val
        }

    async def build_controllable(cc):
        power_val = await get_value(cc.power_state_key, cc.power_source)
        if cc.source in calculation_sources:
            val = await calculate_energy_from_power(cc.power_state_key, cc.power_source)
            await maybe_write_calculated_value(cc.state_key, cc.source, val)
        else:
            val = await get_value(cc.state_key, cc.source)
        return {
            "id": cc.id,
            "name": cc.name, 
            "state_key": cc.state_key, 
            "source": cc.source, 
            "value_kwh": val,
            "power_state_key": cc.power_state_key,
            "power_source": cc.power_source,
            "power_w": power_val
        }

    async def build_generator(gen):
        pv_power_key = gen.pv_power_state_key or gen.power_state_key
        pv_power_source = gen.pv_power_source or gen.power_source
        power_val = await get_value(pv_power_key, pv_power_source)
        if gen.source in calculation_sources:
            val = await calculate_energy_from_power(pv_power_key, pv_power_source)
            await maybe_write_calculated_value(gen.state_key, gen.source, val)
        else:
            val = await get_value(gen.state_key, gen.source)

        battery_soc = None
        battery_power_raw = None
        battery_capacity_wh = None
        battery_charge_w = None
        battery_discharge_w = None
        battery_eta_hours = None
        battery_eta_mode = None

        if gen.has_battery:
            battery_soc = await get_value(gen.battery_soc_state_key, gen.battery_soc_source)
            battery_power_raw = await get_value(gen.battery_power_state_key, gen.battery_power_source)
            battery_capacity_wh = await get_value(gen.battery_capacity_wh_state_key, "iobroker")

            if battery_power_raw is not None:
                p = float(battery_power_raw)
                if gen.battery_power_sign == "discharge_positive":
                    p = -p
                battery_charge_w = max(0.0, p)
                battery_discharge_w = max(0.0, -p)

            capacity = float(gen.battery_capacity_kwh or 0.0)
            if battery_capacity_wh is not None:
                capacity_from_wh = float(battery_capacity_wh) / 1000.0
                if capacity_from_wh > 0:
                    capacity = capacity_from_wh
            rest_soc = max(0.0, min(100.0, float(gen.battery_rest_soc_percent or 0.0)))
            if battery_soc is not None and capacity > 0:
                soc = max(0.0, min(100.0, float(battery_soc)))
                if battery_charge_w and battery_charge_w > 0:
                    remaining_kwh = capacity * (100.0 - soc) / 100.0
                    battery_eta_hours = remaining_kwh / (battery_charge_w / 1000.0) if battery_charge_w > 0 else None
                    battery_eta_mode = "full"
                elif battery_discharge_w and battery_discharge_w > 0:
                    usable_soc = max(0.0, soc - rest_soc)
                    available_kwh = capacity * usable_soc / 100.0
                    battery_eta_hours = available_kwh / (battery_discharge_w / 1000.0) if battery_discharge_w > 0 else None
                    battery_eta_mode = "empty"

        return {
            "id": gen.id,
            "name": gen.name, 
            "state_key": gen.state_key, 
            "has_battery": gen.has_battery, 
            "source": gen.source, 
            "value_kwh": val,
            "power_state_key": gen.power_state_key,
            "power_source": gen.power_source,
            "power_w": power_val,
            "pv_power_state_key": gen.pv_power_state_key,
            "pv_power_source": gen.pv_power_source,
            "battery_soc_state_key": gen.battery_soc_state_key,
            "battery_soc_source": gen.battery_soc_source,
            "battery_power_state_key": gen.battery_power_state_key,
            "battery_power_source": gen.battery_power_source,
            "battery_capacity_wh_state_key": gen.battery_capacity_wh_state_key,
            "battery_power_sign": gen.battery_power_sign,
            "battery_rest_soc_percent": gen.battery_rest_soc_percent,
            "battery_capacity_kwh": gen.battery_capacity_kwh,
            "battery_capacity_wh": battery_capacity_wh,
            "battery_soc": battery_soc,
            "battery_power_raw_w": battery_power_raw,
            "battery_charge_w": battery_charge_w,
            "battery_discharge_w": battery_discharge_w,
            "battery_eta_hours": battery_eta_hours,
            "battery_eta_mode": battery_eta_mode,
        }

    consumer_tasks = [build_consumer(consumer) for consumer in config.consumers]
    controllable_tasks = [build_controllable(cc) for cc in config.controllable_consumers]
    generator_tasks = [build_generator(gen) for gen in config.generators]

    result["consumers"] = list(await asyncio.gather(*consumer_tasks)) if consumer_tasks else []
    result["controllable_consumers"] = list(await asyncio.gather(*controllable_tasks)) if controllable_tasks else []
    result["generators"] = list(await asyncio.gather(*generator_tasks)) if generator_tasks else []

    result["grid"]["import_value"] = await get_value(config.grid.import_state_key, config.grid.import_source)
    result["grid"]["export_value"] = await get_value(config.grid.export_state_key, config.grid.export_source)
    raw_power = await get_value(config.grid.power_state_key, config.grid.power_source)
    if raw_power is None:
        import_power_w = None
        export_power_w = None
    elif config.grid.power_sign == "export_positive":
        # positiv = Einspeisung, negativ = Bezug
        export_power_w = max(0.0, float(raw_power))
        import_power_w = max(0.0, -float(raw_power))
    else:
        # "import_positive": positiv = Bezug, negativ = Einspeisung (default)
        import_power_w = max(0.0, float(raw_power))
        export_power_w = max(0.0, -float(raw_power))
    result["grid"]["import_power"] = import_power_w
    result["grid"]["export_power"] = export_power_w

    id_to_device = {}
    for item in result["generators"]:
        id_to_device[item["id"]] = {
            "id": item["id"],
            "type": "pv_battery" if item.get("has_battery") else "pv",
            "name": item["name"],
            "value_kwh": item["value_kwh"],
            "power_w": item["power_w"],
            "battery_soc": item.get("battery_soc"),
            "battery_charge_w": item.get("battery_charge_w"),
            "battery_discharge_w": item.get("battery_discharge_w"),
            "battery_eta_hours": item.get("battery_eta_hours"),
            "battery_eta_mode": item.get("battery_eta_mode"),
        }
    for item in result["consumers"]:
        id_to_device[item["id"]] = {
            "id": item["id"],
            "type": "consumer",
            "name": item["name"],
            "value_kwh": item["value_kwh"],
            "power_w": item["power_w"],
        }
    for item in result["controllable_consumers"]:
        id_to_device[item["id"]] = {
            "id": item["id"],
            "type": "controllable_consumer",
            "name": item["name"],
            "value_kwh": item["value_kwh"],
            "power_w": item["power_w"],
        }

    id_to_device[config.grid.id] = {
        "id": config.grid.id,
        "type": "grid",
        "name": "Netz",
        "import_value_kwh": result["grid"]["import_value"],
        "export_value_kwh": result["grid"]["export_value"],
        "import_power_w": result["grid"]["import_power"],
        "export_power_w": result["grid"]["export_power"],
    }

    for device_id in config.device_order:
        if device_id in id_to_device:
            result["devices"].append(id_to_device[device_id])

    return JSONResponse(result)


@app.get("/api/update/check")
async def update_check() -> JSONResponse:
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                headers={"Accept": "application/vnd.github+json"},
            )
            resp.raise_for_status()
            latest_tag: str = resp.json().get("tag_name", "").lstrip("v")
    except Exception as exc:
        return JSONResponse({"error": str(exc), "current": APP_VERSION, "latest": None, "update_available": False})

    def _ver(v: str) -> tuple[int, ...]:
        try:
            return tuple(int(x) for x in v.split("."))
        except ValueError:
            return (0,)

    update_available = _ver(latest_tag) > _ver(APP_VERSION)
    return JSONResponse({"current": APP_VERSION, "latest": latest_tag, "update_available": update_available})


@app.post("/api/update/apply")
async def update_apply() -> JSONResponse:
    script = Path(__file__).parent.parent / "scripts" / "update.sh"
    if not script.exists():
        return JSONResponse({"error": "update.sh not found"}, status_code=500)
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                ["bash", str(script)],
                capture_output=True,
                text=True,
                timeout=120,
            ),
        )
        if result.returncode == 0:
            return JSONResponse({"status": "ok", "output": result.stdout[-2000:]})
        return JSONResponse({"status": "error", "output": result.stderr[-2000:]}, status_code=500)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
