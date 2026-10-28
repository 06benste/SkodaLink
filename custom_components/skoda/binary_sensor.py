"""Support for Škoda binary sensors (doors, windows, locks, lights)."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from skoda_public_api.models.enums import (
    LockState,
    MovementState,
    OnOffState,
    OpenCloseState,
    VehicleCapability,
    YesNoState,
)
from skoda_public_api.models.vehicle_status import VehicleStatus

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SkodaConfigEntry, SkodaUpdateCoordinator
from .entity import SkodaEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SkodaBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a Škoda binary sensor entity."""

    value_fn: Callable[[SkodaEntity], bool | None]
    required_capabilities: frozenset[VehicleCapability] = frozenset()

    def is_supported(self, capabilities: set[VehicleCapability]) -> bool:
        """Return whether the vehicle's capabilities satisfy this entity's requirements."""
        return self.required_capabilities <= capabilities


def _open_close(state: OpenCloseState | None) -> bool | None:
    if state == OpenCloseState.OPEN:
        return True
    if state == OpenCloseState.CLOSED:
        return False
    return None


def _status_fn(
    getter: Callable[[VehicleStatus], OpenCloseState],
) -> Callable[[SkodaEntity], bool | None]:
    def _value(entity: SkodaEntity) -> bool | None:
        status = entity.open_api_status
        return _open_close(getter(status)) if status is not None else None

    return _value


def _unlocked_value(entity: SkodaEntity) -> bool | None:
    """Return True when unlocked (the lock device class treats "on" as unlocked)."""
    status = entity.open_api_status
    if status is None:
        return None
    overall = status.overall
    if overall.reliable_lock_status == LockState.LOCKED:
        return False
    if overall.reliable_lock_status == LockState.UNLOCKED:
        return True
    if overall.locked == YesNoState.YES:
        return False
    if overall.locked == YesNoState.NO:
        return True
    return None


def _lights_value(entity: SkodaEntity) -> bool | None:
    status = entity.open_api_status
    if status is None:
        return None
    if status.overall.lights == OnOffState.ON:
        return True
    if status.overall.lights == OnOffState.OFF:
        return False
    return None


def _moving_value(entity: SkodaEntity) -> bool | None:
    position = entity.open_api_parking_position
    if position is None:
        return None
    return position.state == MovementState.IN_MOTION


_STATUS = frozenset({VehicleCapability.STATUS})

BINARY_SENSOR_TYPES: tuple[SkodaBinarySensorEntityDescription, ...] = (
    SkodaBinarySensorEntityDescription(
        key="lock",
        translation_key="lock",
        device_class=BinarySensorDeviceClass.LOCK,
        required_capabilities=_STATUS,
        value_fn=_unlocked_value,
    ),
    SkodaBinarySensorEntityDescription(
        key="doors",
        translation_key="doors",
        device_class=BinarySensorDeviceClass.DOOR,
        required_capabilities=_STATUS,
        value_fn=_status_fn(lambda s: s.overall.doors),
    ),
    SkodaBinarySensorEntityDescription(
        key="windows",
        translation_key="windows",
        device_class=BinarySensorDeviceClass.WINDOW,
        required_capabilities=_STATUS,
        value_fn=_status_fn(lambda s: s.overall.windows),
    ),
    SkodaBinarySensorEntityDescription(
        key="trunk",
        translation_key="trunk",
        device_class=BinarySensorDeviceClass.OPENING,
        icon="mdi:car-back",
        required_capabilities=_STATUS,
        value_fn=_status_fn(lambda s: s.detail.trunk),
    ),
    SkodaBinarySensorEntityDescription(
        key="bonnet",
        translation_key="bonnet",
        device_class=BinarySensorDeviceClass.OPENING,
        icon="mdi:car-lifted-pickup",
        required_capabilities=_STATUS,
        value_fn=_status_fn(lambda s: s.detail.bonnet),
    ),
    SkodaBinarySensorEntityDescription(
        key="sunroof",
        translation_key="sunroof",
        device_class=BinarySensorDeviceClass.WINDOW,
        icon="mdi:car-select",
        required_capabilities=frozenset({VehicleCapability.SUNROOF}),
        value_fn=_status_fn(lambda s: s.detail.sunroof),
    ),
    SkodaBinarySensorEntityDescription(
        key="lights",
        translation_key="lights",
        device_class=BinarySensorDeviceClass.LIGHT,
        required_capabilities=_STATUS,
        value_fn=_lights_value,
    ),
    SkodaBinarySensorEntityDescription(
        key="moving",
        translation_key="moving",
        device_class=BinarySensorDeviceClass.MOVING,
        required_capabilities=frozenset({VehicleCapability.PARKING_POSITION}),
        value_fn=_moving_value,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkodaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Škoda binary sensors from ConfigEntry runtime_data."""
    coordinator = entry.runtime_data.coordinator
    vehicle_response = coordinator.data.vehicle_response if coordinator.data else None
    capabilities = (
        vehicle_response.supported_capabilities() if vehicle_response else set()
    )

    async_add_entities(
        SkodaBinarySensor(coordinator, description)
        for description in BINARY_SENSOR_TYPES
        if description.is_supported(capabilities)
    )


class SkodaBinarySensor(SkodaEntity, BinarySensorEntity):
    """Generic Škoda binary sensor entity, driven by its entity description."""

    entity_description: SkodaBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: SkodaUpdateCoordinator,
        description: SkodaBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor with a coordinator and its entity description."""
        self.entity_description = description
        super().__init__(coordinator, coordinator.vin)

    @property
    @override
    def is_on(self) -> bool | None:
        """Return the state of the binary sensor, computed by the entity description."""
        return self.entity_description.value_fn(self)
