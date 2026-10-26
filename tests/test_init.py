"""Tests for setup, entities and coordinator behaviour."""

from __future__ import annotations

from http import HTTPStatus

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.skodalink.const import DOMAIN

from .conftest import ENYAQ_VIN, HEADERS, SUPERB_VIN, load_fixture, vehicle_url


async def test_setup_and_unload(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The entry loads and unloads."""
    entry = setup_integration
    assert entry.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_superb_mhev_entities(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A mild hybrid gets fuel entities but no charging entities."""
    assert hass.states.get("sensor.superb_odometer").state == "18234"
    assert hass.states.get("sensor.superb_fuel_level").state == "72"
    assert hass.states.get("sensor.superb_total_range").state == "640"
    assert hass.states.get("sensor.superb_combustion_range").state == "640"
    assert hass.states.get("sensor.superb_powertrain").state == "gasoline"
    assert hass.states.get("binary_sensor.superb_lock").state == "off"
    assert hass.states.get("binary_sensor.superb_doors").state == "off"
    assert hass.states.get("binary_sensor.superb_windows").state == "off"
    assert hass.states.get("binary_sensor.superb_in_motion").state == "off"
    assert hass.states.get("device_tracker.superb").attributes["latitude"] == 51.5
    assert hass.states.get("climate.superb").attributes["temperature"] == 21.5
    assert hass.states.get("climate.superb").state == "off"
    assert hass.states.get("switch.superb_auxiliary_heating").state == "off"
    assert hass.states.get("image.superb_vehicle_image") is not None
    assert (
        hass.states.get("sensor.superb_api_key_expires").state
        == "2027-06-01T00:00:00+00:00"
    )

    # Not applicable to a mild hybrid / not supported by this vehicle.
    for entity_id in (
        "sensor.superb_battery_level",
        "sensor.superb_electric_range",
        "sensor.superb_charging_state",
        "sensor.superb_adblue_range",
        "binary_sensor.superb_sunroof",
        "binary_sensor.superb_charging",
        "switch.superb_charging",
        "number.superb_charge_limit",
        "select.superb_charge_mode",
        "switch.superb_active_ventilation",
    ):
        assert hass.states.get(entity_id) is None, entity_id


async def test_ev_entities(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """An EV gets charging entities."""
    assert hass.states.get("sensor.my_enyaq_battery_level").state == "71"
    assert hass.states.get("sensor.my_enyaq_electric_range").state == "249.0"
    assert hass.states.get("sensor.my_enyaq_charging_state").state == "charging"
    assert hass.states.get("sensor.my_enyaq_charging_power").state == "10.8"
    assert hass.states.get("binary_sensor.my_enyaq_charging").state == "on"
    assert hass.states.get("binary_sensor.my_enyaq_lock").state == "on"
    assert hass.states.get("binary_sensor.my_enyaq_trunk").state == "on"
    assert hass.states.get("binary_sensor.my_enyaq_charging_cable").state == "on"
    assert hass.states.get("binary_sensor.my_enyaq_front_window_heating").state == "on"
    assert hass.states.get("binary_sensor.my_enyaq_rear_window_heating") is None
    assert hass.states.get("binary_sensor.my_enyaq_in_motion").state == "on"
    assert hass.states.get("number.my_enyaq_charge_limit").state == "80"
    select = hass.states.get("select.my_enyaq_charge_mode")
    assert select.state == "manual"
    assert select.attributes["options"] == ["manual", "timer"]
    assert hass.states.get("switch.my_enyaq_charging").state == "on"
    assert hass.states.get("climate.my_enyaq").state == "heat_cool"
    assert hass.states.get("climate.my_enyaq").attributes["hvac_action"] == "heating"
    profile = hass.states.get("sensor.my_enyaq_charging_profile")
    assert profile.state == "HOME"
    assert profile.attributes["profile_id"] == 123456
    # No coordinates while driving: tracker is unknown, but available.
    assert hass.states.get("device_tracker.my_enyaq").state == "unknown"
    assert hass.states.get("image.my_enyaq_vehicle_image") is None
    # Fuel entities not created for an EV.
    assert hass.states.get("sensor.my_enyaq_fuel_level") is None


async def test_unique_ids(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    setup_integration: MockConfigEntry,
) -> None:
    """Unique ids are based on the VIN."""
    entry = entity_registry.async_get("sensor.superb_odometer")
    assert entry.unique_id == f"{SUPERB_VIN}_odometer"


async def test_partial_data_keeps_last_value(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A part reported as UNAVAILABLE keeps its previous value."""
    data = load_fixture("superb_mhev.json")
    del data["vehicle"]["odometer"]
    data["errors"] = [{"type": "ODOMETER_UNAVAILABLE"}]
    aioclient_mock.clear_requests()
    aioclient_mock.get(vehicle_url(SUPERB_VIN), json=data, headers=HEADERS)
    aioclient_mock.get(
        vehicle_url(ENYAQ_VIN), json=load_fixture("enyaq.json"), headers=HEADERS
    )
    coordinator = setup_integration.runtime_data.coordinators[SUPERB_VIN]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.superb_odometer").state == "18234"

    # A part that disappears without an UNAVAILABLE error becomes unavailable.
    data["errors"] = [{"type": "ODOMETER_DISABLED"}]
    aioclient_mock.clear_requests()
    aioclient_mock.get(vehicle_url(SUPERB_VIN), json=data, headers=HEADERS)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.superb_odometer").state == "unavailable"


async def test_expired_key_starts_reauth(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A 401 triggers the reauth flow."""
    aioclient_mock.clear_requests()
    for vin in (SUPERB_VIN, ENYAQ_VIN):
        aioclient_mock.get(
            vehicle_url(vin),
            status=HTTPStatus.UNAUTHORIZED,
            json={
                "type": "https://public.api.connect.skoda-auto.cz/problems/api-key-expired",
                "title": "Unauthorized",
                "status": 401,
                "detail": "The API key expired.",
            },
        )
    coordinator = setup_integration.runtime_data.coordinators[SUPERB_VIN]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == SOURCE_REAUTH for flow in flows)


async def test_rate_limited_update(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A 429 marks the entities unavailable until the next success."""
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        vehicle_url(SUPERB_VIN),
        status=HTTPStatus.TOO_MANY_REQUESTS,
        headers={"Retry-After": "30"},
    )
    coordinator = setup_integration.runtime_data.coordinators[SUPERB_VIN]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert not coordinator.last_update_success
    assert hass.states.get("sensor.superb_odometer").state == "unavailable"


async def test_key_expiry_issue(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    issue_registry: ir.IssueRegistry,
) -> None:
    """A repair issue is raised when the key is about to expire."""
    soon = (dt_util.utcnow() + dt_util.dt.timedelta(days=2)).isoformat()
    headers = {**HEADERS, "X-API-Key-Expires-At": soon}
    for vin, fixture in ((SUPERB_VIN, "superb_mhev.json"), (ENYAQ_VIN, "enyaq.json")):
        aioclient_mock.get(
            vehicle_url(vin), json=load_fixture(fixture), headers=headers
        )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert issue_registry.async_get_issue(
        DOMAIN, f"api_key_expiring_{config_entry.entry_id}"
    )


async def test_scheduled_update(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The coordinator polls on its interval."""
    calls = aioclient_mock.call_count
    async_fire_time_changed(hass, dt_util.utcnow() + dt_util.dt.timedelta(minutes=11))
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == calls + 2
