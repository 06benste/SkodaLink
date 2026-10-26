"""Switches for SkodaLink."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SkodaConfigEntry
from .api import SkodaApi
from .const import (
    CONF_SPIN,
    DOMAIN,
    OP_START_ACTIVE_VENTILATION,
    OP_START_AUXILIARY_HEATING,
    OP_START_CHARGING,
    OP_STOP_ACTIVE_VENTILATION,
    OP_STOP_AUXILIARY_HEATING,
    OP_STOP_CHARGING,
)
from .coordinator import VehicleData
from .entity import SkodaEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class SkodaSwitchEntityDescription(SwitchEntityDescription):
    """Describes a SkodaLink switch."""

    on_op: str
    off_op: str
    is_on_fn: Callable[[VehicleData], bool | None]
    turn_on_fn: Callable[[SkodaSwitch], Awaitable[None]]
    turn_off_fn: Callable[[SkodaApi], Callable[..., Awaitable[None]]]


def _state_in(path: str, on_states: set[str]) -> Callable[[VehicleData], bool | None]:
    def _value(data: VehicleData) -> bool | None:
        state = data.get(path)
        if state is None or state in ("UNKNOWN", "UNSUPPORTED"):
            return None
        return state in on_states

    return _value


async def _start_charging(entity: SkodaSwitch) -> None:
    await entity.coordinator.async_execute(entity.coordinator.api.start_charging)


async def _start_auxiliary_heating(entity: SkodaSwitch) -> None:
    spin = entity.coordinator.config_entry.options.get(CONF_SPIN)
    if not spin:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="spin_required"
        )
    data = entity.data
    temperature = data.get("auxiliaryHeating.targetTemperature.value")
    if data.get("auxiliaryHeating.targetTemperature.unit") == "FAHRENHEIT":
        temperature = None
    await entity.coordinator.async_execute(
        entity.coordinator.api.start_auxiliary_heating,
        spin=spin,
        temperature=temperature,
        duration=data.get("auxiliaryHeating.durationInSeconds"),
        start_mode=data.get("auxiliaryHeating.startMode"),
    )


async def _start_active_ventilation(entity: SkodaSwitch) -> None:
    await entity.coordinator.async_execute(
        entity.coordinator.api.start_active_ventilation
    )


SWITCHES: tuple[SkodaSwitchEntityDescription, ...] = (
    SkodaSwitchEntityDescription(
        key="charging_switch",
        translation_key="charging",
        on_op=OP_START_CHARGING,
        off_op=OP_STOP_CHARGING,
        is_on_fn=_state_in("charging.status.state", {"CHARGING"}),
        turn_on_fn=_start_charging,
        turn_off_fn=lambda api: api.stop_charging,
    ),
    SkodaSwitchEntityDescription(
        key="auxiliary_heating_switch",
        translation_key="auxiliary_heating",
        on_op=OP_START_AUXILIARY_HEATING,
        off_op=OP_STOP_AUXILIARY_HEATING,
        is_on_fn=_state_in(
            "auxiliaryHeating.state", {"PREHEATING", "HEATING_AUXILIARY", "VENTILATION"}
        ),
        turn_on_fn=_start_auxiliary_heating,
        turn_off_fn=lambda api: api.stop_auxiliary_heating,
    ),
    SkodaSwitchEntityDescription(
        key="active_ventilation_switch",
        translation_key="active_ventilation",
        on_op=OP_START_ACTIVE_VENTILATION,
        off_op=OP_STOP_ACTIVE_VENTILATION,
        is_on_fn=_state_in("activeVentilation.state", {"PREHEATING", "VENTILATION"}),
        turn_on_fn=_start_active_ventilation,
        turn_off_fn=lambda api: api.stop_active_ventilation,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkodaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switches."""
    entities: list[SkodaSwitch] = []
    for coordinator in entry.runtime_data.coordinators.values():
        data = coordinator.data
        for description in SWITCHES:
            if data.supports(description.on_op) or data.supports(description.off_op):
                entities.append(SkodaSwitch(coordinator, description))
    async_add_entities(entities)


class SkodaSwitch(SkodaEntity, SwitchEntity):
    """Start/stop a remote function.

    The switch works even while its state part is missing; the state is
    unknown then.
    """

    entity_description: SkodaSwitchEntityDescription

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        return self.entity_description.is_on_fn(self.data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the function."""
        await self.entity_description.turn_on_fn(self)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the function."""
        await self.coordinator.async_execute(
            self.entity_description.turn_off_fn(self.coordinator.api)
        )
