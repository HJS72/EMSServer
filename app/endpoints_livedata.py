"""Live data endpoints for configured elements."""

from fastapi.responses import JSONResponse

from app.services.datapoint_config import DataPointConfigService
from app.services.influx_source import InfluxSource
from app.services.iobroker_source import IoBrokerSource


async def get_livedata_all(
    config_service: DataPointConfigService,
    influx: InfluxSource,
    iobroker: IoBrokerSource,
) -> JSONResponse:
    """Liefert aktuelle Live-Daten aller konfigurierten Elemente."""
    config = config_service.load()
    result = {
        "consumers": [],
        "controllable_consumers": [],
        "generators": [],
        "grid": {"import_value": None, "export_value": None},
    }

    async def get_current_value(state_key: str, source: str) -> float | None:
        """Abrufen des aktuellen Werts aus influx oder iobroker."""
        if not state_key:
            return None
        try:
            if source == "iobroker":
                return await iobroker.get_state_value(state_key)
            else:  # influx
                return await influx.get_latest_value(state_key)
        except Exception:
            return None

    # Verbraucher
    for consumer in config.consumers:
        value = await get_current_value(consumer.state_key, consumer.source)
        result["consumers"].append({
            "name": consumer.name,
            "state_key": consumer.state_key,
            "source": consumer.source,
            "value_kwh": value,
        })

    # Steuerbare Verbraucher
    for cc in config.controllable_consumers:
        value = await get_current_value(cc.state_key, cc.source)
        result["controllable_consumers"].append({
            "name": cc.name,
            "state_key": cc.state_key,
            "source": cc.source,
            "value_kwh": value,
        })

    # Erzeuger
    for gen in config.generators:
        value = await get_current_value(gen.state_key, gen.source)
        result["generators"].append({
            "name": gen.name,
            "state_key": gen.state_key,
            "has_battery": gen.has_battery,
            "source": gen.source,
            "value_kwh": value,
        })

    # Grid
    result["grid"]["import_value"] = await get_current_value(
        config.grid.import_state_key, config.grid.import_source
    )
    result["grid"]["export_value"] = await get_current_value(
        config.grid.export_state_key, config.grid.export_source
    )

    return JSONResponse(result)
