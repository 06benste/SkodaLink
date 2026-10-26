"""Air conditioning (climatisation) for SkodaLink."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import SkodaConfigEntry
from .const import (
    DEFAULT_TARGET_TEMPERATURE,
    MAX_TARGET_TEMPERATURE,
    MIN_TARGET_TEMPERATURE,
    OP_START_AIR_CONDITIONING,
    OP_STOP_AIR_CONDITIONING,
    TARGET_TEMPERATURE_STEP,
)
from .entity import SkodaEntity

PARALLEL_UPDATES = 1

DESCRIPTION = EntityDescription(
    key="air_conditioning", translation_key="air_conditioning"
)

RUNNING_STATES = {"COOLING", "HEATING", "HEATING_AUXILIARY", "VENTILATION"}

ACTION_MAP = {
    "OFF": HVACAction.OFF,
    "COMPLETED": HVACAction.IDLE,
    "COOLING": HVACAction.COOLING,
    "HEATING": HVACAction.HEATING,
    "HEATING_AUXILIARY": HVACAction.HEATING,
    "VENTILATION": HVACAction.FAN,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkodaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the climate entity."""
    async_add_entities(
        SkodaClimate(coordinator, DESCRIPTION, ("airConditioning",))
        for coordinator in entry.runtime_data.coordinators.values()
        if coordinator.data.supports(OP_START_AIR_CONDITIONING)
    )


class SkodaClimate(SkodaEntity, ClimateEntity, RestoreEntity):
    """Remote climatisation of the vehicle."""

    _attr_name = None
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT_COOL]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = MIN_TARGET_TEMPERATURE
    _attr_max_temp = MAX_TARGET_TEMPERATURE
    _attr_target_temperature_step = TARGET_TEMPERATURE_STEP
    _attr_translation_key = "air_conditioning"

    _pending_target: float | None = None

    async def async_added_to_hass(self) -> None:
        """Restore a target temperature chosen while the car was offline."""
        await super().async_added_to_hass()
        if self._car_target() is None and (state := await self.async_get_last_state()):
            restored = state.attributes.get(ATTR_TEMPERATURE)
            if isinstance(restored, (int, float)):
                self._pending_target = float(restored)

    def _car_target(self) -> float | None:
        target = self.data.get("airConditioning.targetTemperature")
        if not isinstance(target, dict) or target.get("value") is None:
            return None
        value = float(target["value"])
        if target.get("unit") == "FAHRENHEIT":
            value = round((value - 32) * 5 / 9 * 2) / 2
        return value

    @property
    def _state(self) -> str | None:
        return self.data.get("airConditioning.state")

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return the current mode."""
        state = self._state
        if state is None or state in ("UNKNOWN", "UNSUPPORTED"):
            return None
        return HVACMode.HEAT_COOL if state in RUNNING_STATES else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return what the AC is doing."""
        return ACTION_MAP.get(self._state or "")

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        if self._pending_target is not None:
            return self._pending_target
        return self._car_target() or DEFAULT_TARGET_TEMPERATURE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        return {
            "state": self._state,
            "estimated_target_reached_at": self.data.get(
                "airConditioning.estimatedReachOfTargetTemperatureAt"
            ),
            "without_external_power": self.data.get(
                "airConditioning.airConditioningWithoutExternalPower"
            ),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        # Once the car reports the temperature we asked for, drop the local value.
        if (
            self._pending_target is not None
            and self._car_target() == self._pending_target
        ):
            self._pending_target = None
        super()._handle_coordinator_update()

    async def _start(self, temperature: float | None = None) -> None:
        temperature = (
            temperature if temperature is not None else self.target_temperature
        )
        await self.coordinator.async_execute(
            self.coordinator.api.start_air_conditioning, temperature=temperature
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Start or stop the AC."""
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
        else:
            await self.async_turn_on()

    async def async_turn_on(self) -> None:
        """Start climatisation."""
        await self._start()

    async def async_turn_off(self) -> None:
        """Stop climatisation."""
        if not self.data.supports(OP_STOP_AIR_CONDITIONING):
            return
        await self.coordinator.async_execute(self.coordinator.api.stop_air_conditioning)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature (restarts climatisation if running)."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        self._pending_target = float(temperature)
        mode = kwargs.get(ATTR_HVAC_MODE)
        if mode == HVACMode.OFF:
            await self.async_turn_off()
        elif HVACMode.HEAT_COOL in (mode, self.hvac_mode):
            await self._start(float(temperature))
        self.async_write_ha_state()
