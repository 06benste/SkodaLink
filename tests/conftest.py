"""Fixtures for SkodaLink tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.skodalink.const import BASE_URL, CONF_VINS, DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"

SUPERB_VIN = "TMBJB9NY5RF999999"
ENYAQ_VIN = "TMBJC7NY1RF000001"
API_KEY = "test-api-key"
HEADERS = {
    "X-API-Key-Expires-At": "2027-06-01T00:00:00Z",
    "RateLimit-Limit": "100",
    "RateLimit-Remaining": "97",
    "RateLimit-Reset": "30",
}


def load_fixture(name: str) -> dict[str, Any]:
    """Load a JSON fixture."""
    return json.loads((FIXTURES / name).read_text())


def vehicle_url(vin: str) -> str:
    """Return the vehicle endpoint URL."""
    return f"{BASE_URL}/api/v1/vehicles/{vin}"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations."""


@pytest.fixture
def mock_api(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Mock both vehicles."""
    aioclient_mock.get(
        vehicle_url(SUPERB_VIN), json=load_fixture("superb_mhev.json"), headers=HEADERS
    )
    aioclient_mock.get(
        vehicle_url(ENYAQ_VIN), json=load_fixture("enyaq.json"), headers=HEADERS
    )
    return aioclient_mock


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Config entry with both vehicles."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Superb, My Enyaq",
        unique_id=",".join(sorted([SUPERB_VIN, ENYAQ_VIN])),
        data={CONF_API_KEY: API_KEY, CONF_VINS: [SUPERB_VIN, ENYAQ_VIN]},
    )


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: AiohttpClientMocker
) -> MockConfigEntry:
    """Set up the integration."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
