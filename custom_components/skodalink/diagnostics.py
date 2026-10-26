"""Diagnostics for SkodaLink."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from . import SkodaConfigEntry
from .const import CONF_SPIN, CONF_VINS

TO_REDACT = {
    CONF_API_KEY,
    CONF_SPIN,
    CONF_VINS,
    "vin",
    "licensePlate",
    "latitude",
    "longitude",
    "formattedAddress",
    "renderUrl",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SkodaConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    vehicles = []
    for index, coordinator in enumerate(entry.runtime_data.coordinators.values()):
        data = coordinator.data
        vehicles.append(
            {
                "index": index,
                "last_update_success": coordinator.last_update_success,
                "vehicle": async_redact_data(data.vehicle, TO_REDACT) if data else None,
                "errors": data.errors if data else None,
                "api_key_expires_at": (
                    data.api_key_expires_at.isoformat()
                    if data and data.api_key_expires_at
                    else None
                ),
                "rate_limit_limit": data.rate_limit_limit if data else None,
                "rate_limit_remaining": data.rate_limit_remaining if data else None,
            }
        )
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "vehicles": vehicles,
    }
