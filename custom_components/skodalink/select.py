"""Select entities for SkodaLink."""

from __future__ import annotations

from time import monotonic

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SkodaConfigEntry
from .const import CHARGE_MODES, OP_SET_CHARGE_MODE, PENDING_TIMEOUT
from .entity import SkodaEntity

PARALLEL_UPDATES = 1

CHARGE_MODE = SelectEntityDescription(
    key="charge_mode_select",
    translation_key="charge_mode",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkodaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up select entities."""
    async_add_entities(
        SkodaChargeModeSelect(coordinator, CHARGE_MODE, ("charging",))
        for coordinator in entry.runtime_data.coordinators.values()
        if coordinator.data.supports(OP_SET_CHARGE_MODE)
    )


class SkodaChargeModeSelect(SkodaEntity, SelectEntity):
    """Preferred charge mode."""

    _pending: str | None = None
    _pending_since = 0.0

    def _reported(self) -> str | None:
        mode = self.data.get("charging.settings.preferredChargeMode")
        return mode.lower() if isinstance(mode, str) else None

    @property
    def options(self) -> list[str]:
        """Return the charge modes the vehicle offers."""
        available = self.data.get("charging.settings.availableChargeModes") or []
        modes = [m.lower() for m in available if m in CHARGE_MODES]
        return modes or [m.lower() for m in CHARGE_MODES]

    @property
    def current_option(self) -> str | None:
        """Return the active charge mode."""
        if self._pending is not None:
            return self._pending
        mode = self._reported()
        return mode if mode in self.options else None

    @callback
    def _handle_coordinator_update(self) -> None:
        # Keep the requested value until the car confirms it (or gives up).
        if self._pending is not None and (
            self._reported() == self._pending
            or monotonic() - self._pending_since > PENDING_TIMEOUT
        ):
            self._pending = None
        super()._handle_coordinator_update()

    async def async_select_option(self, option: str) -> None:
        """Change the charge mode."""
        await self.coordinator.async_execute(
            self.coordinator.api.set_charge_mode, option.upper()
        )
        self._pending = option
        self._pending_since = monotonic()
        self.async_write_ha_state()
