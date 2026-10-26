"""Tests for the config flow."""

from __future__ import annotations

from http import HTTPStatus

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_API_KEY, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.skodalink.const import CONF_SPIN, CONF_VINS, DOMAIN

from .conftest import API_KEY, ENYAQ_VIN, HEADERS, SUPERB_VIN, load_fixture, vehicle_url


@pytest.fixture(autouse=True)
def no_setup():
    """Do not set up the entry after the flow."""
    from unittest.mock import patch

    with patch("custom_components.skodalink.async_setup_entry", return_value=True):
        yield


async def test_user_flow(hass: HomeAssistant, mock_api: AiohttpClientMocker) -> None:
    """A valid key and VINs create an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_KEY: f" {API_KEY} ", CONF_VINS: f"{SUPERB_VIN.lower()}, {ENYAQ_VIN}"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Superb, My Enyaq"
    assert result["data"] == {CONF_API_KEY: API_KEY, CONF_VINS: [SUPERB_VIN, ENYAQ_VIN]}
    # The flow only asks for the basic info part.
    assert all("include=info" in str(call[1]) for call in mock_api.mock_calls)


@pytest.mark.parametrize(
    ("status", "body", "field", "error"),
    [
        (HTTPStatus.UNAUTHORIZED, {}, "base", "invalid_auth"),
        (
            HTTPStatus.UNAUTHORIZED,
            {
                "type": "https://public.api.connect.skoda-auto.cz/problems/api-key-expired"
            },
            "base",
            "api_key_expired",
        ),
        (HTTPStatus.FORBIDDEN, {}, CONF_VINS, "vehicle_not_authorized"),
        (HTTPStatus.NOT_FOUND, {}, CONF_VINS, "vehicle_not_found"),
        (HTTPStatus.TOO_MANY_REQUESTS, {}, "base", "rate_limited"),
        (HTTPStatus.SERVICE_UNAVAILABLE, {}, "base", "cannot_connect"),
        (HTTPStatus.INTERNAL_SERVER_ERROR, {}, "base", "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    status: HTTPStatus,
    body: dict,
    field: str,
    error: str,
) -> None:
    """API errors are shown and the flow can recover."""
    aioclient_mock.get(vehicle_url(SUPERB_VIN), status=status, json=body)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY, CONF_VINS: SUPERB_VIN}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {field: error}

    aioclient_mock.clear_requests()
    aioclient_mock.get(
        vehicle_url(SUPERB_VIN), json=load_fixture("superb_mhev.json"), headers=HEADERS
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY, CONF_VINS: SUPERB_VIN}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("vins", "error"), [("TOO-SHORT", "invalid_vin"), (" , ", "no_vins")]
)
async def test_user_flow_invalid_vin(
    hass: HomeAssistant, vins: str, error: str
) -> None:
    """VINs are validated locally."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY, CONF_VINS: vins}
    )
    assert result["errors"] == {CONF_VINS: error}


async def test_vehicle_already_configured(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: AiohttpClientMocker
) -> None:
    """A VIN can only be in one entry."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY, CONF_VINS: SUPERB_VIN}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "vehicle_already_configured"


async def test_reauth(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: AiohttpClientMocker
) -> None:
    """Reauth stores the new key."""
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "new-key"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_API_KEY] == "new-key"


async def test_reconfigure(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: AiohttpClientMocker
) -> None:
    """Reconfigure can change the vehicles."""
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "other-key", CONF_VINS: SUPERB_VIN}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data == {CONF_API_KEY: "other-key", CONF_VINS: [SUPERB_VIN]}
    assert config_entry.unique_id == SUPERB_VIN
    assert config_entry.title == "Superb"


async def test_options(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Options store interval and S-PIN."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 15, CONF_SPIN: "1234"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_SCAN_INTERVAL: 15, CONF_SPIN: "1234"}
