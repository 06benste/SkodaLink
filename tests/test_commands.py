"""Tests for remote commands, services and diagnostics."""

from __future__ import annotations

from http import HTTPStatus
from unittest.mock import patch

from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
)
from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN, SERVICE_SET_VALUE
from homeassistant.components.select import (
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF, SERVICE_TURN_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.skodalink.const import BASE_URL, CONF_SPIN, DOMAIN
from custom_components.skodalink.diagnostics import async_get_config_entry_diagnostics

from .conftest import API_KEY, ENYAQ_VIN, SUPERB_VIN


@pytest.fixture(autouse=True)
def no_delayed_refresh():
    """Do not schedule post-command refreshes."""
    with patch(
        "custom_components.skodalink.coordinator.SkodaCoordinator.schedule_command_refresh"
    ) as mock:
        yield mock


def _url(vin: str, path: str) -> str:
    return f"{BASE_URL}/api/v1/vehicles/{vin}/{path}"


def _last_call(aioclient_mock: AiohttpClientMocker, method: str, url: str):
    for call in reversed(aioclient_mock.mock_calls):
        if call[0].lower() == method and str(call[1]) == url:
            return call
    raise AssertionError(f"{method} {url} not called")


async def test_charging_commands(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    no_delayed_refresh,
) -> None:
    """Charging switch, limit and mode call the API."""
    aioclient_mock.post(_url(ENYAQ_VIN, "charging/stop"), status=HTTPStatus.ACCEPTED)
    aioclient_mock.put(_url(ENYAQ_VIN, "charging/limit"), status=HTTPStatus.ACCEPTED)
    aioclient_mock.put(_url(ENYAQ_VIN, "charging/mode"), status=HTTPStatus.ACCEPTED)

    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: "switch.my_enyaq_charging"},
        blocking=True,
    )
    call = _last_call(aioclient_mock, "post", _url(ENYAQ_VIN, "charging/stop"))
    assert call[3]["X-API-Key"] == API_KEY
    assert no_delayed_refresh.called

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: "number.my_enyaq_charge_limit", "value": 90},
        blocking=True,
    )
    call = _last_call(aioclient_mock, "put", _url(ENYAQ_VIN, "charging/limit"))
    assert call[2] == {"targetStateOfChargeInPercent": 90}
    assert hass.states.get("number.my_enyaq_charge_limit").state == "90"

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: "select.my_enyaq_charge_mode", "option": "timer"},
        blocking=True,
    )
    call = _last_call(aioclient_mock, "put", _url(ENYAQ_VIN, "charging/mode"))
    assert call[2] == {"chargeMode": "TIMER"}
    assert hass.states.get("select.my_enyaq_charge_mode").state == "timer"


async def test_climate(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Climate starts with the chosen temperature and stops."""
    start = _url(SUPERB_VIN, "air-conditioning/start")
    aioclient_mock.post(start, status=HTTPStatus.ACCEPTED)
    aioclient_mock.post(
        _url(SUPERB_VIN, "air-conditioning/stop"), status=HTTPStatus.ACCEPTED
    )

    # Car is off: only remember the temperature.
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: "climate.superb", "temperature": 23},
        blocking=True,
    )
    assert not any(str(c[1]) == start for c in aioclient_mock.mock_calls)
    assert hass.states.get("climate.superb").attributes["temperature"] == 23

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: "climate.superb", "hvac_mode": "heat_cool"},
        blocking=True,
    )
    call = _last_call(aioclient_mock, "post", start)
    assert call[2] == {"targetTemperature": {"value": 23.0, "unit": "CELSIUS"}}

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: "climate.superb", "hvac_mode": "off"},
        blocking=True,
    )
    _last_call(aioclient_mock, "post", _url(SUPERB_VIN, "air-conditioning/stop"))


async def test_auxiliary_heating_needs_spin(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The heater switch needs the S-PIN from the options."""
    url = _url(SUPERB_VIN, "auxiliary-heating/start")
    aioclient_mock.post(url, status=HTTPStatus.ACCEPTED)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: "switch.superb_auxiliary_heating"},
            blocking=True,
        )

    # Changing the options reloads the entry.
    hass.config_entries.async_update_entry(
        setup_integration, options={CONF_SPIN: "1234"}
    )
    await hass.async_block_till_done()
    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "switch.superb_auxiliary_heating"},
        blocking=True,
    )
    call = _last_call(aioclient_mock, "post", url)
    assert call[2] == {
        "spin": "1234",
        "targetTemperature": {"value": 22.0, "unit": "CELSIUS"},
        "durationInSeconds": 1200,
        "startMode": "HEATING",
    }


async def test_command_errors(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A rejected command raises a readable error."""
    aioclient_mock.post(
        _url(ENYAQ_VIN, "charging/stop"),
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
        json={
            "type": "https://public.api.connect.skoda-auto.cz/problems/operation-disabled",
            "detail": "Charging is disabled in workshop mode.",
        },
    )
    with pytest.raises(HomeAssistantError, match="workshop mode"):
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: "switch.my_enyaq_charging"},
            blocking=True,
        )


def _device_id(hass: HomeAssistant, vin: str) -> str:
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, vin)})
    assert device
    return device.id


async def test_services(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Integration services call the API."""
    aioclient_mock.post(
        _url(SUPERB_VIN, "auxiliary-heating/start"), status=HTTPStatus.ACCEPTED
    )
    aioclient_mock.post(
        _url(SUPERB_VIN, "air-conditioning/start"), status=HTTPStatus.ACCEPTED
    )
    aioclient_mock.put(
        _url(ENYAQ_VIN, "charging-profiles/123456"), status=HTTPStatus.ACCEPTED
    )
    superb = _device_id(hass, SUPERB_VIN)

    await hass.services.async_call(
        DOMAIN,
        "start_auxiliary_heating",
        {
            "device_id": superb,
            "spin": "9999",
            "duration": 15,
            "start_mode": "ventilation",
        },
        blocking=True,
    )
    call = _last_call(
        aioclient_mock, "post", _url(SUPERB_VIN, "auxiliary-heating/start")
    )
    assert call[2] == {
        "spin": "9999",
        "durationInSeconds": 900,
        "startMode": "VENTILATION",
    }

    await hass.services.async_call(
        DOMAIN,
        "start_air_conditioning",
        {"device_id": superb, "temperature": 20, "without_external_power": True},
        blocking=True,
    )
    call = _last_call(
        aioclient_mock, "post", _url(SUPERB_VIN, "air-conditioning/start")
    )
    assert call[2] == {
        "targetTemperature": {"value": 20.0, "unit": "CELSIUS"},
        "airConditioningWithoutExternalPower": True,
    }

    await hass.services.async_call(
        DOMAIN,
        "update_charging_profile",
        {
            "device_id": _device_id(hass, ENYAQ_VIN),
            "target_state_of_charge": 100,
            "min_battery_state_of_charge": 30,
            "auto_unlock_plug": True,
        },
        blocking=True,
    )
    call = _last_call(
        aioclient_mock, "put", _url(ENYAQ_VIN, "charging-profiles/123456")
    )
    body = call[2]
    assert body["id"] == 123456
    assert body["timers"] and body["preferredChargingTimes"]
    assert body["settings"] == {
        "maxChargingCurrent": "MAXIMUM",
        "minBatteryStateOfCharge": {
            "enabled": False,
            "minimumBatteryStateOfChargeInPercent": 30,
        },
        "targetStateOfChargeInPercent": 100,
        "autoUnlockPlugWhenCharged": "PERMANENT",
    }

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "update_charging_profile",
            {"device_id": superb, "target_state_of_charge": 80},
            blocking=True,
        )


async def test_diagnostics(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Diagnostics redact secrets and location."""
    diag = await async_get_config_entry_diagnostics(hass, setup_integration)
    assert diag["entry"]["data"]["api_key"] == "**REDACTED**"
    superb = diag["vehicles"][0]["vehicle"]
    assert superb["vin"] == "**REDACTED**"
    assert superb["licensePlate"] == "**REDACTED**"
    assert superb["parkingPosition"]["gpsCoordinates"]["latitude"] == "**REDACTED**"
    assert superb["odometer"]["mileageInKm"] == 18234


async def test_unload_keeps_services_safe(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Services report a clear error when the vehicle is not loaded."""
    device_id = _device_id(hass, SUPERB_VIN)
    await hass.config_entries.async_unload(setup_integration.entry_id)
    assert setup_integration.state is ConfigEntryState.NOT_LOADED
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "refresh", {"device_id": device_id}, blocking=True
        )
