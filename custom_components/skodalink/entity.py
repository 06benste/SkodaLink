"""Base entity for SkodaLink."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import SkodaCoordinator, VehicleData


class SkodaEntity(CoordinatorEntity[SkodaCoordinator]):
    """Entity bound to one vehicle."""

    _attr_has_entity_name = True

    # Top-level parts of the vehicle response this entity depends on; the
    # entity is available while any of them is present.
    _parts: tuple[str, ...] = ()

    def __init__(
        self,
        coordinator: SkodaCoordinator,
        description: EntityDescription,
        parts: tuple[str, ...] = (),
    ) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._parts = parts
        self.vin = coordinator.vin
        self._attr_unique_id = f"{self.vin}_{description.key}"
        vehicle = coordinator.data.vehicle
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.vin)},
            manufacturer=MANUFACTURER,
            name=vehicle.get("name") or self.vin,
            serial_number=self.vin,
            configuration_url="https://www.skoda-auto.com/connectivity/myskoda",
        )

    @property
    def data(self) -> VehicleData:
        """Return the latest vehicle data."""
        return self.coordinator.data

    @property
    def available(self) -> bool:
        """Entity is available when its part of the response is present."""
        if not super().available:
            return False
        return not self._parts or any(self.data.has(p) for p in self._parts)
