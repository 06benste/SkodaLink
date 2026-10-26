"""Sensors for SkodaLink."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfLength,
    UnitOfPower,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import SkodaConfigEntry
from .const import CHARGE_MODES
from .coordinator import VehicleData
from .entity import SkodaEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


def _engine(data: VehicleData, electric: bool) -> dict[str, Any] | None:
    """Return the primary/secondary engine range block of the wanted kind."""
    for key in ("primaryEngineRange", "secondaryEngineRange"):
        engine = data.get(f"fuelStatus.{key}")
        if not isinstance(engine, dict):
            continue
        if (engine.get("engineType") == "ELECTRIC") == electric:
            return engine
    return None


def _engine_value(data: VehicleData, electric: bool, field: str) -> Any:
    engine = _engine(data, electric)
    return engine.get(field) if engine else None


def _electric_range(data: VehicleData) -> float | None:
    meters = data.get("charging.status.battery.remainingCruisingRangeInMeters")
    if meters is not None:
        return round(meters / 1000, 1)
    return _engine_value(data, True, "remainingRangeInKm")


def _battery_level(data: VehicleData) -> Any:
    soc = data.get("charging.status.battery.stateOfChargeInPercent")
    if soc is not None:
        return soc
    return _engine_value(data, True, "currentSoCInPercent")


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    return dt_util.parse_datetime(str(value))


def _last_captured(data: VehicleData) -> datetime | None:
    stamps = [
        ts
        for part in data.vehicle.values()
        if isinstance(part, dict)
        and (ts := _timestamp(part.get("carCapturedTimestamp"))) is not None
    ]
    return max(stamps) if stamps else None


def _enum(path: str) -> Callable[[VehicleData], Any]:
    def _value(data: VehicleData) -> Any:
        value = data.get(path)
        return value.lower() if isinstance(value, str) else None

    return _value


def _profiles_attrs(data: VehicleData) -> dict[str, Any]:
    profiles = data.get("chargingProfiles.profiles") or []
    current = data.get("chargingProfiles.currentVehiclePositionProfile") or {}
    return {
        "profile_id": current.get("id"),
        "target_state_of_charge": current.get("targetStateOfChargeInPercent"),
        "next_charging_time": current.get("nextChargingTime"),
        "profiles": [
            {"id": p.get("id"), "name": p.get("name"), **(p.get("settings") or {})}
            for p in profiles
        ],
    }


def _parking_attrs(data: VehicleData) -> dict[str, Any]:
    return {
        "state": data.get("parkingPosition.state"),
        "latitude": data.get("parkingPosition.gpsCoordinates.latitude"),
        "longitude": data.get("parkingPosition.gpsCoordinates.longitude"),
    }


def _errors_attrs(data: VehicleData) -> dict[str, Any]:
    return {
        "errors": [
            {"type": e.get("type"), "description": e.get("description")}
            for e in data.errors
        ],
        "rate_limit_limit": data.rate_limit_limit,
        "rate_limit_remaining": data.rate_limit_remaining,
    }


@dataclass(frozen=True, kw_only=True)
class SkodaSensorEntityDescription(SensorEntityDescription):
    """Describes a SkodaLink sensor."""

    parts: tuple[str, ...]
    value_fn: Callable[[VehicleData], Any]
    # Only create the entity when this returns True for the first data set.
    exists_fn: Callable[[VehicleData], bool] | None = None
    attr_fn: Callable[[VehicleData], dict[str, Any]] | None = None


def _value_present(fn: Callable[[VehicleData], Any]) -> Callable[[VehicleData], bool]:
    return lambda data: fn(data) is not None


SENSORS: tuple[SkodaSensorEntityDescription, ...] = (
    # ---------------------------------------------------------- odometer
    SkodaSensorEntityDescription(
        key="odometer",
        translation_key="odometer",
        parts=("odometer",),
        value_fn=lambda d: d.get("odometer.mileageInKm"),
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
    ),
    # ----------------------------------------------------- fuel and range
    SkodaSensorEntityDescription(
        key="total_range",
        translation_key="total_range",
        parts=("fuelStatus",),
        value_fn=lambda d: d.get("fuelStatus.totalRangeInKm"),
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    SkodaSensorEntityDescription(
        key="fuel_level",
        translation_key="fuel_level",
        parts=("fuelStatus",),
        value_fn=lambda d: _engine_value(d, False, "currentFuelLevelInPercent"),
        exists_fn=lambda d: _engine(d, False) is not None,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    SkodaSensorEntityDescription(
        key="combustion_range",
        translation_key="combustion_range",
        parts=("fuelStatus",),
        value_fn=lambda d: _engine_value(d, False, "remainingRangeInKm"),
        exists_fn=lambda d: _engine(d, False) is not None,
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    SkodaSensorEntityDescription(
        key="adblue_range",
        translation_key="adblue_range",
        parts=("fuelStatus",),
        value_fn=lambda d: d.get("fuelStatus.adBlueRange"),
        exists_fn=lambda d: (
            d.get("fuelStatus.adBlueRange") is not None
            or d.get("fuelStatus.carType") == "DIESEL"
        ),
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    SkodaSensorEntityDescription(
        key="car_type",
        translation_key="car_type",
        parts=("fuelStatus",),
        value_fn=_enum("fuelStatus.carType"),
        device_class=SensorDeviceClass.ENUM,
        options=["hybrid", "gasoline", "diesel", "cng", "lpg", "electric", "unknown"],
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SkodaSensorEntityDescription(
        key="electric_range",
        translation_key="electric_range",
        parts=("charging", "fuelStatus"),
        value_fn=_electric_range,
        exists_fn=_value_present(_electric_range),
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    SkodaSensorEntityDescription(
        key="battery_level",
        translation_key="battery_level",
        parts=("charging", "fuelStatus"),
        value_fn=_battery_level,
        exists_fn=_value_present(_battery_level),
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # ---------------------------------------------------------- charging
    SkodaSensorEntityDescription(
        key="charging_state",
        translation_key="charging_state",
        parts=("charging",),
        value_fn=_enum("charging.status.state"),
        device_class=SensorDeviceClass.ENUM,
        options=[
            "connect_cable",
            "charging",
            "conserving",
            "ready_for_charging",
            "discharging",
            "charging_interrupted",
        ],
    ),
    SkodaSensorEntityDescription(
        key="charge_type",
        translation_key="charge_type",
        parts=("charging",),
        value_fn=_enum("charging.status.chargeType"),
        device_class=SensorDeviceClass.ENUM,
        options=["ac", "dc", "off"],
    ),
    SkodaSensorEntityDescription(
        key="charging_power",
        translation_key="charging_power",
        parts=("charging",),
        value_fn=lambda d: d.get("charging.status.chargePowerInKw"),
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SkodaSensorEntityDescription(
        key="charging_rate",
        translation_key="charging_rate",
        parts=("charging",),
        value_fn=lambda d: d.get("charging.status.chargingRateInKilometersPerHour"),
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    SkodaSensorEntityDescription(
        key="remaining_charging_time",
        translation_key="remaining_charging_time",
        parts=("charging",),
        value_fn=lambda d: d.get(
            "charging.status.remainingTimeToFullyChargedInMinutes"
        ),
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
    ),
    SkodaSensorEntityDescription(
        key="fully_charged_at",
        translation_key="fully_charged_at",
        parts=("charging",),
        value_fn=lambda d: _timestamp(d.get("charging.status.fullyChargedAt")),
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SkodaSensorEntityDescription(
        key="target_state_of_charge",
        translation_key="target_state_of_charge",
        parts=("charging",),
        value_fn=lambda d: d.get("charging.settings.targetStateOfChargeInPercent"),
        native_unit_of_measurement=PERCENTAGE,
    ),
    SkodaSensorEntityDescription(
        key="charge_mode",
        translation_key="charge_mode",
        parts=("charging",),
        value_fn=_enum("charging.settings.preferredChargeMode"),
        device_class=SensorDeviceClass.ENUM,
        options=[m.lower() for m in CHARGE_MODES],
    ),
    SkodaSensorEntityDescription(
        key="max_charge_current",
        translation_key="max_charge_current",
        parts=("charging",),
        value_fn=lambda d: d.get("charging.settings.maxChargeCurrentAcAmpere"),
        exists_fn=lambda d: (
            d.get("charging.settings.maxChargeCurrentAcAmpere") is not None
        ),
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SkodaSensorEntityDescription(
        key="charging_profile",
        translation_key="charging_profile",
        parts=("chargingProfiles",),
        value_fn=lambda d: d.get("chargingProfiles.currentVehiclePositionProfile.name"),
        attr_fn=_profiles_attrs,
    ),
    # -------------------------------------------------------- climate
    SkodaSensorEntityDescription(
        key="air_conditioning_state",
        translation_key="air_conditioning_state",
        parts=("airConditioning",),
        value_fn=_enum("airConditioning.state"),
        device_class=SensorDeviceClass.ENUM,
        options=[
            "off",
            "cooling",
            "heating",
            "heating_auxiliary",
            "ventilation",
            "completed",
            "unknown",
            "unsupported",
        ],
    ),
    SkodaSensorEntityDescription(
        key="air_conditioning_target_reached_at",
        translation_key="air_conditioning_target_reached_at",
        parts=("airConditioning",),
        value_fn=lambda d: _timestamp(
            d.get("airConditioning.estimatedReachOfTargetTemperatureAt")
        ),
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SkodaSensorEntityDescription(
        key="auxiliary_heating_state",
        translation_key="auxiliary_heating_state",
        parts=("auxiliaryHeating",),
        value_fn=_enum("auxiliaryHeating.state"),
        device_class=SensorDeviceClass.ENUM,
        options=[
            "off",
            "preheating",
            "heating_auxiliary",
            "ventilation",
            "unknown",
            "unsupported",
        ],
    ),
    SkodaSensorEntityDescription(
        key="auxiliary_heating_target_temperature",
        translation_key="auxiliary_heating_target_temperature",
        parts=("auxiliaryHeating",),
        value_fn=lambda d: d.get("auxiliaryHeating.targetTemperature.value"),
        exists_fn=lambda d: d.get("auxiliaryHeating.targetTemperature") is not None,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SkodaSensorEntityDescription(
        key="auxiliary_heating_duration",
        translation_key="auxiliary_heating_duration",
        parts=("auxiliaryHeating",),
        value_fn=lambda d: d.get("auxiliaryHeating.durationInSeconds"),
        exists_fn=lambda d: d.get("auxiliaryHeating.durationInSeconds") is not None,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SkodaSensorEntityDescription(
        key="active_ventilation_state",
        translation_key="active_ventilation_state",
        parts=("activeVentilation",),
        value_fn=_enum("activeVentilation.state"),
        device_class=SensorDeviceClass.ENUM,
        options=["off", "preheating", "ventilation", "unknown", "unsupported"],
    ),
    # ---------------------------------------------------------- location
    SkodaSensorEntityDescription(
        key="parking_address",
        translation_key="parking_address",
        parts=("parkingPosition",),
        value_fn=lambda d: d.get("parkingPosition.formattedAddress"),
        attr_fn=_parking_attrs,
    ),
    # ------------------------------------------------------- diagnostics
    SkodaSensorEntityDescription(
        key="last_captured",
        translation_key="last_captured",
        parts=(),
        value_fn=_last_captured,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SkodaSensorEntityDescription(
        key="last_updated",
        translation_key="last_updated",
        parts=(),
        value_fn=lambda d: d.last_updated,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SkodaSensorEntityDescription(
        key="api_key_expires_at",
        translation_key="api_key_expires_at",
        parts=(),
        value_fn=lambda d: d.api_key_expires_at,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SkodaSensorEntityDescription(
        key="api_rate_limit_remaining",
        translation_key="api_rate_limit_remaining",
        parts=(),
        value_fn=lambda d: d.rate_limit_remaining,
        attr_fn=_errors_attrs,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkodaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    entities: list[SkodaSensor] = []
    for coordinator in entry.runtime_data.coordinators.values():
        data = coordinator.data
        for description in SENSORS:
            if description.parts and not any(data.has(p) for p in description.parts):
                continue
            if description.exists_fn and not description.exists_fn(data):
                continue
            entities.append(SkodaSensor(coordinator, description, description.parts))
    async_add_entities(entities)


class SkodaSensor(SkodaEntity, SensorEntity):
    """A SkodaLink sensor."""

    entity_description: SkodaSensorEntityDescription

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        value = self.entity_description.value_fn(self.data)
        options = self.entity_description.options
        if options is not None and value is not None and value not in options:
            _LOGGER.debug("Unknown value %s for %s", value, self.entity_description.key)
            return None
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if self.entity_description.attr_fn is None:
            return None
        return self.entity_description.attr_fn(self.data)
