"""Diagnostics support for the Škoda integration."""

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from .const import CONF_VIN
from .coordinator import SkodaConfigEntry

TO_REDACT = {
    CONF_API_KEY,
    CONF_VIN,
    "licensePlate",
    "gpsCoordinates",
    "formattedAddress",
    "renderUrl",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SkodaConfigEntry
) -> dict[str, Any]:
    """Return the raw API response, so unparsed fields can be inspected.

    The library's models drop any field they don't know about, so this makes
    one extra request and returns the JSON as the API sent it.
    """
    data = entry.runtime_data
    result = await data.openapi.rest_api.get_vehicle(data.vin)

    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "capabilities": sorted(
            capability.value for capability in result.result.supported_capabilities()
        ),
        "raw_vehicle_response": async_redact_data(result.raw_json, TO_REDACT),
    }
