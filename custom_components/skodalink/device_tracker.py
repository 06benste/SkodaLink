"""Device tracker (parking position) for SkodaLink."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import TrackerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SkodaConfigEntry
from .entity import SkodaEntity

PARALLEL_UPDATES = 0

DESCRIPTION = EntityDescription(key="location", translation_key="location")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkodaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the device tracker."""
    async_add_entities(
        SkodaTracker(coordinator, DESCRIPTION, ("parkingPosition",))
        for coordinator in entry.runtime_data.coordinators.values()
        if coordinator.data.has("parkingPosition")
    )


class SkodaTracker(SkodaEntity, TrackerEntity):
    """Last known parking position.

    While the car is moving the API reports no coordinates; the last known
    position is kept and the ``in_motion`` attribute is set instead.
    """

    _attr_name = None
    _last: tuple[float, float] | None = None

    def _coordinates(self) -> tuple[float, float] | None:
        coords = self.data.get("parkingPosition.gpsCoordinates")
        if isinstance(coords, dict) and "latitude" in coords and "longitude" in coords:
            self._last = (coords["latitude"], coords["longitude"])
        return self._last

    @property
    def latitude(self) -> float | None:
        """Return latitude."""
        coords = self._coordinates()
        return coords[0] if coords else None

    @property
    def longitude(self) -> float | None:
        """Return longitude."""
        coords = self._coordinates()
        return coords[1] if coords else None

    @property
    def location_accuracy(self) -> float:
        """Return the GPS accuracy (unknown, assume a few metres)."""
        return 10

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        return {
            "in_motion": self.data.get("parkingPosition.state") == "IN_MOTION",
            "address": self.data.get("parkingPosition.formattedAddress"),
        }
