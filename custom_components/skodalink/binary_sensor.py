"""Binary sensors for SkodaLink."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SkodaConfigEntry
from .coordinator import VehicleData
from .entity import SkodaEntity

PARALLEL_UPDATES = 0


def _is(
    path: str, on: str, off: str | tuple[str, ...]
) -> Callable[[VehicleData], bool | None]:
    """Map a string state to on/off; anything else (UNKNOWN, ...) is None."""
    offs = (off,) if isinstance(off, str) else off

    def _value(data: VehicleData) -> bool | None:
        value = data.get(path)
        if value == on:
            return True
        if value in offs:
            return False
        return None

    return _value


def _supported(path: str) -> Callable[[VehicleData], bool]:
    return lambda d: d.get(path) not in (None, "UNSUPPORTED")


def _unlocked(data: VehicleData) -> bool | None:
    reliable = data.get("status.overall.reliableLockStatus")
    if reliable == "LOCKED":
        return False
    if reliable == "UNLOCKED":
        return True
    locked = data.get("status.overall.locked")
    if locked == "YES":
        return False
    if locked == "NO":
        return True
    return None


def _bool(path: str) -> Callable[[VehicleData], bool | None]:
    def _value(data: VehicleData) -> bool | None:
        value = data.get(path)
        return value if isinstance(value, bool) else None

    return _value


@dataclass(frozen=True, kw_only=True)
class SkodaBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a SkodaLink binary sensor."""

    part: str
    value_fn: Callable[[VehicleData], bool | None]
    exists_fn: Callable[[VehicleData], bool] | None = None


BINARY_SENSORS: tuple[SkodaBinarySensorEntityDescription, ...] = (
    SkodaBinarySensorEntityDescription(
        key="lock",
        translation_key="lock",
        part="status",
        value_fn=_unlocked,
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    SkodaBinarySensorEntityDescription(
        key="doors",
        translation_key="doors",
        part="status",
        value_fn=_is("status.overall.doors", "OPEN", "CLOSED"),
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    SkodaBinarySensorEntityDescription(
        key="windows",
        translation_key="windows",
        part="status",
        value_fn=_is("status.overall.windows", "OPEN", "CLOSED"),
        exists_fn=_supported("status.overall.windows"),
        device_class=BinarySensorDeviceClass.WINDOW,
    ),
    SkodaBinarySensorEntityDescription(
        key="trunk",
        translation_key="trunk",
        part="status",
        value_fn=_is("status.detail.trunk", "OPEN", "CLOSED"),
        device_class=BinarySensorDeviceClass.OPENING,
    ),
    SkodaBinarySensorEntityDescription(
        key="bonnet",
        translation_key="bonnet",
        part="status",
        value_fn=_is("status.detail.bonnet", "OPEN", "CLOSED"),
        device_class=BinarySensorDeviceClass.OPENING,
    ),
    SkodaBinarySensorEntityDescription(
        key="sunroof",
        translation_key="sunroof",
        part="status",
        value_fn=_is("status.detail.sunroof", "OPEN", "CLOSED"),
        exists_fn=_supported("status.detail.sunroof"),
        device_class=BinarySensorDeviceClass.WINDOW,
    ),
    SkodaBinarySensorEntityDescription(
        key="lights",
        translation_key="lights",
        part="status",
        value_fn=_is("status.overall.lights", "ON", "OFF"),
        device_class=BinarySensorDeviceClass.LIGHT,
    ),
    SkodaBinarySensorEntityDescription(
        key="parked",
        translation_key="parked",
        part="parkingPosition",
        value_fn=_is("parkingPosition.state", "IN_MOTION", "PARKED"),
        device_class=BinarySensorDeviceClass.MOVING,
    ),
    SkodaBinarySensorEntityDescription(
        key="charging",
        translation_key="charging",
        part="charging",
        value_fn=lambda d: (
            None
            if d.get("charging.status.state") is None
            else d.get("charging.status.state") == "CHARGING"
        ),
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
    ),
    SkodaBinarySensorEntityDescription(
        key="plug_connected",
        translation_key="plug_connected",
        part="charging",
        value_fn=_is(
            "charging.status.plugConnectionState", "CONNECTED", "DISCONNECTED"
        ),
        device_class=BinarySensorDeviceClass.PLUG,
    ),
    SkodaBinarySensorEntityDescription(
        key="plug_locked",
        translation_key="plug_locked",
        part="charging",
        value_fn=_is("charging.status.plugLockState", "UNLOCKED", "LOCKED"),
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    SkodaBinarySensorEntityDescription(
        key="in_saved_location",
        translation_key="in_saved_location",
        part="charging",
        value_fn=_bool("charging.isVehicleInSavedLocation"),
        device_class=BinarySensorDeviceClass.PRESENCE,
    ),
    SkodaBinarySensorEntityDescription(
        key="charging_care_mode",
        translation_key="charging_care_mode",
        part="charging",
        value_fn=_is("charging.settings.chargingCareMode", "ACTIVATED", "DEACTIVATED"),
        exists_fn=lambda d: d.get("charging.settings.chargingCareMode") is not None,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SkodaBinarySensorEntityDescription(
        key="auto_unlock_plug",
        translation_key="auto_unlock_plug",
        part="charging",
        value_fn=_is("charging.settings.autoUnlockPlugWhenCharged", "PERMANENT", "OFF"),
        exists_fn=lambda d: (
            d.get("charging.settings.autoUnlockPlugWhenCharged") is not None
        ),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SkodaBinarySensorEntityDescription(
        key="window_heating_front",
        translation_key="window_heating_front",
        part="airConditioning",
        value_fn=_is("airConditioning.windowHeating.front", "ON", "OFF"),
        exists_fn=_supported("airConditioning.windowHeating.front"),
        device_class=BinarySensorDeviceClass.HEAT,
    ),
    SkodaBinarySensorEntityDescription(
        key="window_heating_rear",
        translation_key="window_heating_rear",
        part="airConditioning",
        value_fn=_is("airConditioning.windowHeating.rear", "ON", "OFF"),
        exists_fn=_supported("airConditioning.windowHeating.rear"),
        device_class=BinarySensorDeviceClass.HEAT,
    ),
    SkodaBinarySensorEntityDescription(
        key="air_conditioning_without_external_power",
        translation_key="air_conditioning_without_external_power",
        part="airConditioning",
        value_fn=_bool("airConditioning.airConditioningWithoutExternalPower"),
        exists_fn=lambda d: (
            d.get("airConditioning.airConditioningWithoutExternalPower") is not None
        ),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SkodaBinarySensorEntityDescription(
        key="air_conditioning_at_unlock",
        translation_key="air_conditioning_at_unlock",
        part="airConditioning",
        value_fn=_bool("airConditioning.airConditioningAtUnlock"),
        exists_fn=lambda d: (
            d.get("airConditioning.airConditioningAtUnlock") is not None
        ),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkodaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    entities: list[SkodaBinarySensor] = []
    for coordinator in entry.runtime_data.coordinators.values():
        data = coordinator.data
        for description in BINARY_SENSORS:
            if not data.has(description.part):
                continue
            if description.exists_fn and not description.exists_fn(data):
                continue
            entities.append(
                SkodaBinarySensor(coordinator, description, (description.part,))
            )
    async_add_entities(entities)


class SkodaBinarySensor(SkodaEntity, BinarySensorEntity):
    """A SkodaLink binary sensor."""

    entity_description: SkodaBinarySensorEntityDescription

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        return self.entity_description.value_fn(self.data)
