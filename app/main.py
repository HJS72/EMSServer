from __future__ import annotations

import asyncio
import subprocess
from contextlib import asynccontextmanager
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
    if cached is None:
        cached = await engine.build_today_forecast()
    return JSONResponse(cached.model_dump(mode="json"))


@app.get("/api/actuals/today")
async def actuals_today() -> JSONResponse:
    actuals = await engine.build_today_actuals()
    return JSONResponse(actuals.model_dump(mode="json"))


@app.get("/api/compare/today")
async def compare_today() -> JSONResponse:
    compare = await engine.build_today_compare()
    return JSONResponse(compare.model_dump(mode="json"))


@app.get("/api/history")
async def history(days: int = Query(default=14, ge=1, le=365)) -> JSONResponse:
    payload = engine.build_history_daily(days=days)
    return JSONResponse(payload)


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
                return await iobroker.get_current_value(state_key)
            else:
                return await influx.get_latest_value(state_key)
        except Exception:
            return None

    for consumer in config.consumers:
        val = await get_value(consumer.state_key, consumer.source)
        power_val = await get_value(consumer.power_state_key, consumer.power_source)
        result["consumers"].append({
            "id": consumer.id,
            "name": consumer.name, 
            "state_key": consumer.state_key, 
            "source": consumer.source, 
            "value_kwh": val,
            "power_state_key": consumer.power_state_key,
            "power_source": consumer.power_source,
            "power_w": power_val
        })

    for cc in config.controllable_consumers:
        val = await get_value(cc.state_key, cc.source)
        power_val = await get_value(cc.power_state_key, cc.power_source)
        result["controllable_consumers"].append({
            "id": cc.id,
            "name": cc.name, 
            "state_key": cc.state_key, 
            "source": cc.source, 
            "value_kwh": val,
            "power_state_key": cc.power_state_key,
            "power_source": cc.power_source,
            "power_w": power_val
        })

    for gen in config.generators:
        val = await get_value(gen.state_key, gen.source)
        power_val = await get_value(gen.power_state_key, gen.power_source)
        result["generators"].append({
            "id": gen.id,
            "name": gen.name, 
            "state_key": gen.state_key, 
            "has_battery": gen.has_battery, 
            "source": gen.source, 
            "value_kwh": val,
            "power_state_key": gen.power_state_key,
            "power_source": gen.power_source,
            "power_w": power_val
        })

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
