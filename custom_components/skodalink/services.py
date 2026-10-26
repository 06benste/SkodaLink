"""Services for SkodaLink."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
import voluptuous as vol

from .const import (
    CONF_SPIN,
    DOMAIN,
    MAX_TARGET_TEMPERATURE,
    MIN_TARGET_TEMPERATURE,
    SERVICE_REFRESH,
    SERVICE_START_AIR_CONDITIONING,
    SERVICE_START_AUXILIARY_HEATING,
    SERVICE_UPDATE_CHARGING_PROFILE,
)

if TYPE_CHECKING:
    from .coordinator import SkodaCoordinator

ATTR_WITHOUT_EXTERNAL_POWER = "without_external_power"
ATTR_SPIN = "spin"
ATTR_DURATION = "duration"
ATTR_START_MODE = "start_mode"
ATTR_PROFILE_ID = "profile_id"
ATTR_TARGET_SOC = "target_state_of_charge"
ATTR_MAX_CHARGING_CURRENT = "max_charging_current"
ATTR_MIN_BATTERY_SOC = "min_battery_state_of_charge"
ATTR_MIN_BATTERY_SOC_ENABLED = "min_battery_state_of_charge_enabled"
ATTR_AUTO_UNLOCK_PLUG = "auto_unlock_plug"

TEMPERATURE = vol.All(
    vol.Coerce(float), vol.Range(min=MIN_TARGET_TEMPERATURE, max=MAX_TARGET_TEMPERATURE)
)

BASE_SCHEMA = vol.Schema({vol.Required(ATTR_DEVICE_ID): cv.string})

START_AC_SCHEMA = BASE_SCHEMA.extend(
    {
        vol.Optional(ATTR_TEMPERATURE): TEMPERATURE,
        vol.Optional(ATTR_WITHOUT_EXTERNAL_POWER): cv.boolean,
    }
)

START_AUX_SCHEMA = BASE_SCHEMA.extend(
    {
        vol.Optional(ATTR_SPIN): cv.string,
        vol.Optional(ATTR_TEMPERATURE): TEMPERATURE,
        vol.Optional(ATTR_DURATION): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
        vol.Optional(ATTR_START_MODE): vol.In(["heating", "ventilation"]),
    }
)

UPDATE_PROFILE_SCHEMA = BASE_SCHEMA.extend(
    {
        vol.Optional(ATTR_PROFILE_ID): vol.Coerce(int),
        vol.Optional(ATTR_TARGET_SOC): vol.All(
            vol.Coerce(int), vol.Range(min=50, max=100)
        ),
        vol.Optional(ATTR_MAX_CHARGING_CURRENT): vol.In(["reduced", "maximum"]),
        vol.Optional(ATTR_MIN_BATTERY_SOC_ENABLED): cv.boolean,
        vol.Optional(ATTR_MIN_BATTERY_SOC): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=100)
        ),
        vol.Optional(ATTR_AUTO_UNLOCK_PLUG): cv.boolean,
    }
)


def _coordinator(hass: HomeAssistant, device_id: str) -> SkodaCoordinator:
    """Find the coordinator of the vehicle behind a device id."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="device_not_found",
            translation_placeholders={"device_id": device_id},
        )
    vins = {ident[1] for ident in device.identifiers if ident[0] == DOMAIN}
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        for vin, coordinator in entry.runtime_data.coordinators.items():
            if vin in vins:
                return coordinator
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="device_not_found",
        translation_placeholders={"device_id": device_id},
    )


async def _start_air_conditioning(call: ServiceCall) -> None:
    coordinator = _coordinator(call.hass, call.data[ATTR_DEVICE_ID])
    await coordinator.async_execute(
        coordinator.api.start_air_conditioning,
        temperature=call.data.get(ATTR_TEMPERATURE),
        without_external_power=call.data.get(ATTR_WITHOUT_EXTERNAL_POWER),
    )


async def _start_auxiliary_heating(call: ServiceCall) -> None:
    coordinator = _coordinator(call.hass, call.data[ATTR_DEVICE_ID])
    spin = call.data.get(ATTR_SPIN) or coordinator.config_entry.options.get(CONF_SPIN)
    if not spin:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="spin_required"
        )
    duration = call.data.get(ATTR_DURATION)
    start_mode = call.data.get(ATTR_START_MODE)
    await coordinator.async_execute(
        coordinator.api.start_auxiliary_heating,
        spin=spin,
        temperature=call.data.get(ATTR_TEMPERATURE),
        duration=duration * 60 if duration else None,
        start_mode=start_mode.upper() if start_mode else None,
    )


async def _update_charging_profile(call: ServiceCall) -> None:
    coordinator = _coordinator(call.hass, call.data[ATTR_DEVICE_ID])
    data = coordinator.data
    profiles: list[dict[str, Any]] = data.get("chargingProfiles.profiles") or []
    profile_id = call.data.get(ATTR_PROFILE_ID)
    if profile_id is None:
        profile_id = data.get("chargingProfiles.currentVehiclePositionProfile.id")
    profile = next((p for p in profiles if p.get("id") == profile_id), None)
    if profile is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="profile_not_found",
            translation_placeholders={"profile_id": str(profile_id)},
        )

    # The vehicle applies the profile as a whole: send it back complete.
    updated = copy.deepcopy(profile)
    settings = updated.setdefault("settings", {})
    if ATTR_TARGET_SOC in call.data:
        settings["targetStateOfChargeInPercent"] = call.data[ATTR_TARGET_SOC]
    if ATTR_MAX_CHARGING_CURRENT in call.data:
        settings["maxChargingCurrent"] = call.data[ATTR_MAX_CHARGING_CURRENT].upper()
    if ATTR_AUTO_UNLOCK_PLUG in call.data:
        settings["autoUnlockPlugWhenCharged"] = (
            "PERMANENT" if call.data[ATTR_AUTO_UNLOCK_PLUG] else "OFF"
        )
    if ATTR_MIN_BATTERY_SOC in call.data or ATTR_MIN_BATTERY_SOC_ENABLED in call.data:
        min_soc = settings.setdefault("minBatteryStateOfCharge", {})
        if ATTR_MIN_BATTERY_SOC in call.data:
            min_soc["minimumBatteryStateOfChargeInPercent"] = call.data[
                ATTR_MIN_BATTERY_SOC
            ]
            min_soc.setdefault("enabled", True)
        if ATTR_MIN_BATTERY_SOC_ENABLED in call.data:
            min_soc["enabled"] = call.data[ATTR_MIN_BATTERY_SOC_ENABLED]

    await coordinator.async_execute(
        coordinator.api.update_charging_profile, profile_id, updated
    )


async def _refresh(call: ServiceCall) -> None:
    coordinator = _coordinator(call.hass, call.data[ATTR_DEVICE_ID])
    await coordinator.async_refresh()


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration services."""
    hass.services.async_register(
        DOMAIN, SERVICE_START_AIR_CONDITIONING, _start_air_conditioning, START_AC_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_START_AUXILIARY_HEATING,
        _start_auxiliary_heating,
        START_AUX_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_CHARGING_PROFILE,
        _update_charging_profile,
        UPDATE_PROFILE_SCHEMA,
    )
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, _refresh, BASE_SCHEMA)
