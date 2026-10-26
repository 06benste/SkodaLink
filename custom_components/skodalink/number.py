"""Number entities for SkodaLink."""

from __future__ import annotations

from time import monotonic

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SkodaConfigEntry
from .const import OP_SET_CHARGING_LIMIT, PENDING_TIMEOUT
from .entity import SkodaEntity

PARALLEL_UPDATES = 1

CHARGE_LIMIT = NumberEntityDescription(
    key="charge_limit",
    translation_key="charge_limit",
    device_class=NumberDeviceClass.BATTERY,
    native_unit_of_measurement=PERCENTAGE,
    # Vehicles accept 50-100 % in steps of 10.
    native_min_value=50,
    native_max_value=100,
    native_step=10,
    mode=NumberMode.SLIDER,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkodaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up number entities."""
    async_add_entities(
        SkodaChargeLimit(coordinator, CHARGE_LIMIT, ("charging",))
        for coordinator in entry.runtime_data.coordinators.values()
        if coordinator.data.supports(OP_SET_CHARGING_LIMIT)
    )


class SkodaChargeLimit(SkodaEntity, NumberEntity):
    """Target state of charge."""

    _pending: int | None = None
    _pending_since = 0.0

    def _reported(self) -> int | None:
        return self.data.get("charging.settings.targetStateOfChargeInPercent")

    @property
    def native_value(self) -> int | None:
        """Return the target state of charge."""
        if self._pending is not None:
            return self._pending
        return self._reported()

    @callback
    def _handle_coordinator_update(self) -> None:
        # Keep the requested value until the car confirms it (or gives up).
        if self._pending is not None and (
            self._reported() == self._pending
            or monotonic() - self._pending_since > PENDING_TIMEOUT
        ):
            self._pending = None
        super()._handle_coordinator_update()

    async def async_set_native_value(self, value: float) -> None:
        """Set the charge limit."""
        await self.coordinator.async_execute(
            self.coordinator.api.set_charging_limit, int(value)
        )
        self._pending = int(value)
        self._pending_since = monotonic()
        self.async_write_ha_state()
