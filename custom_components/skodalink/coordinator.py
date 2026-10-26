"""Data update coordinator for SkodaLink."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    SkodaApi,
    SkodaApiError,
    SkodaAuthError,
    SkodaForbiddenError,
    SkodaNotFoundError,
    SkodaOperationError,
    SkodaRateLimitError,
)
from .const import (
    API_KEY_EXPIRY_WARNING,
    API_KEYS_URL,
    COMMAND_REFRESH_DELAYS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

if TYPE_CHECKING:
    from . import SkodaConfigEntry

_LOGGER = logging.getLogger(__name__)

# Maps the prefix of a VehicleError type to the response part it affects.
ERROR_PART = {
    "VEHICLE_STATUS": "status",
    "FUEL_STATUS": "fuelStatus",
    "ODOMETER": "odometer",
    "PARKING_POSITION": "parkingPosition",
    "AIR_CONDITIONING": "airConditioning",
    "AUXILIARY_HEATING": "auxiliaryHeating",
    "ACTIVE_VENTILATION": "activeVentilation",
    "CHARGING_PROFILES": "chargingProfiles",
    "CHARGING": "charging",
    "OPERATIONS": "operations",
    "RENDER": "renderUrl",
}


def dig(data: Any, path: str) -> Any:
    """Return a nested value from a dict using a dotted path, or None."""
    for key in path.split("."):
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


@dataclass
class VehicleData:
    """State of one vehicle as returned by the API."""

    vehicle: dict[str, Any]
    errors: list[dict[str, Any]] = field(default_factory=list)
    api_key_expires_at: datetime | None = None
    rate_limit_limit: int | None = None
    rate_limit_remaining: int | None = None
    last_updated: datetime | None = None

    def get(self, path: str) -> Any:
        """Return a value by dotted path."""
        return dig(self.vehicle, path)

    def has(self, part: str) -> bool:
        """Return True if the given top-level part is present."""
        return self.vehicle.get(part) is not None

    @property
    def operations(self) -> set[str]:
        """Return the names of the supported remote operations."""
        return {
            op["name"]
            for op in self.vehicle.get("operations") or []
            if isinstance(op, dict) and "name" in op
        }

    def supports(self, operation: str) -> bool:
        """Return True if the vehicle supports a remote operation."""
        return operation in self.operations


def _error_part(error_type: str) -> str | None:
    for prefix, part in ERROR_PART.items():
        if error_type.startswith(f"{prefix}_"):
            return part
    return None


class SkodaCoordinator(DataUpdateCoordinator[VehicleData]):
    """Polls one vehicle."""

    config_entry: SkodaConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: SkodaApi,
        vin: str,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{vin}",
            update_interval=timedelta(minutes=scan_interval),
        )
        self.api = api
        self.vin = vin
        self._pending_refreshes: list[CALLBACK_TYPE] = []

    async def _async_update_data(self) -> VehicleData:
        try:
            result = await self.api.get_vehicle(self.vin)
        except SkodaAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        except SkodaForbiddenError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="vehicle_not_authorized",
                translation_placeholders={"vin": self.vin},
            ) from err
        except SkodaNotFoundError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="vehicle_not_found",
                translation_placeholders={"vin": self.vin},
            ) from err
        except SkodaRateLimitError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="rate_limited",
                translation_placeholders={"retry_after": str(err.retry_after or "?")},
            ) from err
        except SkodaApiError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        vehicle = dict(result.vehicle)
        # Parts that are temporarily unavailable are omitted by the API; keep the
        # last known value so that entities do not flap between polls.
        if self.data is not None:
            for error in result.errors:
                error_type = str(error.get("type", ""))
                if not error_type.endswith("_UNAVAILABLE"):
                    continue
                part = _error_part(error_type)
                if part and part not in vehicle and part in self.data.vehicle:
                    vehicle[part] = self.data.vehicle[part]

        if result.errors:
            _LOGGER.debug("Partial data for %s: %s", self.vin, result.errors)

        data = VehicleData(
            vehicle=vehicle,
            errors=result.errors,
            api_key_expires_at=result.api_key_expires_at,
            rate_limit_limit=result.rate_limit_limit,
            rate_limit_remaining=result.rate_limit_remaining,
            last_updated=dt_util.utcnow(),
        )
        self._check_key_expiry(data.api_key_expires_at)
        return data

    @callback
    def _check_key_expiry(self, expires_at: datetime | None) -> None:
        issue_id = f"api_key_expiring_{self.config_entry.entry_id}"
        if expires_at is None:
            return
        remaining = expires_at - dt_util.utcnow()
        if remaining < API_KEY_EXPIRY_WARNING:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="api_key_expiring",
                translation_placeholders={
                    "title": self.config_entry.title,
                    "expires": dt_util.as_local(expires_at).strftime("%Y-%m-%d %H:%M"),
                    "url": API_KEYS_URL,
                },
                learn_more_url=API_KEYS_URL,
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    async def async_execute(
        self,
        operation: Callable[..., Awaitable[None]],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Run a remote command and schedule state refreshes afterwards."""
        try:
            await operation(self.vin, *args, **kwargs)
        except SkodaAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        except SkodaForbiddenError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="operation_forbidden",
                translation_placeholders={"error": str(err)},
            ) from err
        except SkodaOperationError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="operation_not_possible",
                translation_placeholders={"error": str(err)},
            ) from err
        except SkodaRateLimitError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_rate_limited",
                translation_placeholders={"error": str(err)},
            ) from err
        except SkodaApiError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        self.schedule_command_refresh()

    @callback
    def schedule_command_refresh(self) -> None:
        """Re-read the vehicle a few times after a command was accepted."""
        self.cancel_pending_refreshes()

        @callback
        def _refresh(_now: datetime) -> None:
            self.hass.async_create_task(self.async_request_refresh())

        self._pending_refreshes = [
            async_call_later(self.hass, delay, _refresh)
            for delay in COMMAND_REFRESH_DELAYS
        ]

    @callback
    def cancel_pending_refreshes(self) -> None:
        """Cancel scheduled post-command refreshes."""
        for cancel in self._pending_refreshes:
            cancel()
        self._pending_refreshes = []

    async def async_shutdown(self) -> None:
        """Cancel timers on shutdown."""
        self.cancel_pending_refreshes()
        await super().async_shutdown()
