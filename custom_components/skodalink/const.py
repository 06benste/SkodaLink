"""Constants for the SkodaLink integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "skodalink"
MANUFACTURER: Final = "Škoda"

BASE_URL: Final = "https://public.api.connect.skoda-auto.cz"
API_KEYS_URL: Final = "https://go.skoda.eu/api-keys"

CONF_VINS: Final = "vins"
CONF_SPIN: Final = "spin"

DEFAULT_SCAN_INTERVAL: Final = 10  # minutes
MIN_SCAN_INTERVAL: Final = 1
MAX_SCAN_INTERVAL: Final = 240

# Seconds to wait after a remote command before re-reading the vehicle state.
# The car needs some time to execute the request and report back.
COMMAND_REFRESH_DELAYS: Final = (20, 90)

# Seconds an optimistic value is shown while waiting for the car to confirm it.
PENDING_TIMEOUT: Final = 180

# Raise a repair issue when the API key expires within this period.
API_KEY_EXPIRY_WARNING: Final = timedelta(days=7)

# Remote operations, named as the operationIds of the API.
OP_START_CHARGING: Final = "startCharging"
OP_STOP_CHARGING: Final = "stopCharging"
OP_SET_CHARGING_LIMIT: Final = "setChargingLimit"
OP_SET_CHARGE_MODE: Final = "setChargeMode"
OP_UPDATE_CHARGING_PROFILE: Final = "updateChargingProfile"
OP_START_AIR_CONDITIONING: Final = "startAirConditioning"
OP_STOP_AIR_CONDITIONING: Final = "stopAirConditioning"
OP_START_AUXILIARY_HEATING: Final = "startAuxiliaryHeating"
OP_STOP_AUXILIARY_HEATING: Final = "stopAuxiliaryHeating"
OP_START_ACTIVE_VENTILATION: Final = "startActiveVentilation"
OP_STOP_ACTIVE_VENTILATION: Final = "stopActiveVentilation"

DEFAULT_TARGET_TEMPERATURE: Final = 21.0
MIN_TARGET_TEMPERATURE: Final = 16.0
MAX_TARGET_TEMPERATURE: Final = 29.5
TARGET_TEMPERATURE_STEP: Final = 0.5

DEFAULT_AUX_DURATION: Final = 600  # seconds

CHARGE_MODES: Final = [
    "MANUAL",
    "TIMER",
    "TIMER_CHARGING_WITH_CLIMATISATION",
    "PREFERRED_CHARGING_TIMES",
    "ONLY_OWN_CURRENT",
    "IMMEDIATE_DISCHARGING",
    "HOME_STORAGE_CHARGING",
]

SERVICE_START_AIR_CONDITIONING: Final = "start_air_conditioning"
SERVICE_START_AUXILIARY_HEATING: Final = "start_auxiliary_heating"
SERVICE_UPDATE_CHARGING_PROFILE: Final = "update_charging_profile"
SERVICE_REFRESH: Final = "refresh"
