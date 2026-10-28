"""Support for the Škoda parking position."""

from typing import Any, override

from skoda_public_api.models.enums import VehicleCapability

from homeassistant.components.device_tracker import (
    SourceType,
    TrackerEntity,
    TrackerEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SkodaConfigEntry, SkodaUpdateCoordinator
from .entity import SkodaEntity

PARALLEL_UPDATES = 0

LOCATION_DESCRIPTION = TrackerEntityDescription(
    key="parking_position",
    translation_key="location",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkodaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Škoda device tracker from ConfigEntry runtime_data."""
    coordinator = entry.runtime_data.coordinator
    vehicle_response = coordinator.data.vehicle_response if coordinator.data else None
    capabilities = (
        vehicle_response.supported_capabilities() if vehicle_response else set()
    )

    if VehicleCapability.PARKING_POSITION in capabilities:
        async_add_entities([SkodaDeviceTracker(coordinator)])


class SkodaDeviceTracker(SkodaEntity, TrackerEntity):
    """Last known parking position of the vehicle.

    The API only reports coordinates while the car is parked; while driving the
    state becomes unknown until the car parks again.
    """

    _attr_source_type = SourceType.GPS

    def __init__(self, coordinator: SkodaUpdateCoordinator) -> None:
        """Initialize the device tracker."""
        self.entity_description = LOCATION_DESCRIPTION
        super().__init__(coordinator, coordinator.vin)

    @property
    @override
    def latitude(self) -> float | None:
        """Return the latitude of the parked vehicle."""
        position = self.open_api_parking_position
        if position is None or position.gps_coordinates is None:
            return None
        return position.gps_coordinates.latitude

    @property
    @override
    def longitude(self) -> float | None:
        """Return the longitude of the parked vehicle."""
        position = self.open_api_parking_position
        if position is None or position.gps_coordinates is None:
            return None
        return position.gps_coordinates.longitude

    @property
    @override
    def entity_picture(self) -> str | None:
        """Return the vehicle render from the API."""
        return self.open_api_vehicle.render_url

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the formatted address of the parking position."""
        position = self.open_api_parking_position
        if position is None or position.formatted_address is None:
            return {}
        return {"address": position.formatted_address}
