"""The SkodaLink integration (MyŠkoda Public API)."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    issue_registry as ir,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import SkodaApi
from .const import CONF_VINS, DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import SkodaCoordinator
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.DEVICE_TRACKER,
    Platform.IMAGE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class SkodaRuntimeData:
    """Runtime data stored on the config entry."""

    api: SkodaApi
    coordinators: dict[str, SkodaCoordinator]


type SkodaConfigEntry = ConfigEntry[SkodaRuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration (register services)."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SkodaConfigEntry) -> bool:
    """Set up SkodaLink from a config entry."""
    api = SkodaApi(async_get_clientsession(hass), entry.data[CONF_API_KEY])
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    coordinators: dict[str, SkodaCoordinator] = {}
    for vin in entry.data[CONF_VINS]:
        coordinator = SkodaCoordinator(hass, entry, api, vin, scan_interval)
        await coordinator.async_config_entry_first_refresh()
        coordinators[vin] = coordinator

    entry.runtime_data = SkodaRuntimeData(api=api, coordinators=coordinators)

    # Remove devices for vehicles that are no longer configured.
    device_registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        vins = {ident[1] for ident in device.identifiers if ident[0] == DOMAIN}
        if vins and not vins & set(coordinators):
            device_registry.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id
            )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: SkodaConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SkodaConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: SkodaConfigEntry) -> None:
    """Clean up the key-expiry repair issue."""
    ir.async_delete_issue(hass, DOMAIN, f"api_key_expiring_{entry.entry_id}")
