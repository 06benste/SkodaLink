"""Async client for the MyŠkoda Public API.

API reference: https://public.api.connect.skoda-auto.cz/docs
Authentication is a per-user API key (created in the MyŠkoda app) sent in the
``X-API-Key`` header. Keys are bound to selected vehicles and expire.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from json import loads as json_loads
import logging
from typing import Any

import aiohttp

from .const import BASE_URL

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=60)

PROBLEM_PREFIX = "https://public.api.connect.skoda-auto.cz/problems/"


class SkodaApiError(Exception):
    """Generic API error."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        problem_type: str | None = None,
        retry_after: int | None = None,
    ) -> None:
        """Initialise the error."""
        super().__init__(message)
        self.status = status
        self.problem_type = problem_type
        self.retry_after = retry_after

    @property
    def problem(self) -> str | None:
        """Short problem name (e.g. ``api-key-expired``)."""
        if self.problem_type and self.problem_type.startswith(PROBLEM_PREFIX):
            return self.problem_type.removeprefix(PROBLEM_PREFIX)
        return None


class SkodaConnectionError(SkodaApiError):
    """Raised when the API can not be reached."""


class SkodaAuthError(SkodaApiError):
    """Raised when the API key is invalid or expired (401)."""


class SkodaForbiddenError(SkodaApiError):
    """Raised when the key does not cover the vehicle or operation (403)."""


class SkodaNotFoundError(SkodaApiError):
    """Raised when the vehicle is unknown (404)."""


class SkodaOperationError(SkodaApiError):
    """Raised when the vehicle can not execute an operation (412/422)."""


class SkodaRateLimitError(SkodaApiError):
    """Raised when the rate limit is hit or the vehicle declines requests (429)."""


@dataclass
class ApiResult:
    """Parsed vehicle response together with interesting headers."""

    vehicle: dict[str, Any]
    errors: list[dict[str, Any]] = field(default_factory=list)
    api_key_expires_at: datetime | None = None
    rate_limit_limit: int | None = None
    rate_limit_remaining: int | None = None
    rate_limit_reset: int | None = None


@dataclass
class RateLimitInfo:
    """Last seen rate-limit / key-expiry headers."""

    api_key_expires_at: datetime | None = None
    limit: int | None = None
    remaining: int | None = None
    reset: int | None = None


def _int_header(headers: Any, name: str) -> int | None:
    value = headers.get(name)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _datetime_header(headers: Any, name: str) -> datetime | None:
    value = headers.get(name)
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class SkodaApi:
    """Thin async wrapper around the MyŠkoda Public API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        base_url: str = BASE_URL,
    ) -> None:
        """Initialise the client."""
        self._session = session
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self.rate_limit = RateLimitInfo()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> tuple[Any, Any]:
        """Perform a request and return (parsed body, headers)."""
        url = f"{self._base_url}{path}"
        headers = {"X-API-Key": self._api_key, "Accept": "application/json"}
        try:
            async with self._session.request(
                method,
                url,
                params=params,
                json=json,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                self._update_rate_limit(resp.headers)
                # Commands answer 202 with an empty body; errors use problem+json.
                body: Any = None
                if text := await resp.text():
                    try:
                        body = json_loads(text)
                    except ValueError:
                        body = None
                if resp.status >= 400:
                    raise self._error_from_response(resp.status, body, resp.headers)
                return body, resp.headers
        except TimeoutError as err:
            raise SkodaConnectionError(f"Timeout calling {method} {path}") from err
        except aiohttp.ClientError as err:
            raise SkodaConnectionError(f"Error calling {method} {path}: {err}") from err

    def _update_rate_limit(self, headers: Any) -> None:
        if (expires := _datetime_header(headers, "X-API-Key-Expires-At")) is not None:
            self.rate_limit.api_key_expires_at = expires
        if (limit := _int_header(headers, "RateLimit-Limit")) is not None:
            self.rate_limit.limit = limit
        if (remaining := _int_header(headers, "RateLimit-Remaining")) is not None:
            self.rate_limit.remaining = remaining
        if (reset := _int_header(headers, "RateLimit-Reset")) is not None:
            self.rate_limit.reset = reset

    @staticmethod
    def _error_from_response(status: int, body: Any, headers: Any) -> SkodaApiError:
        problem_type = None
        detail = f"HTTP {status}"
        if isinstance(body, dict):
            problem_type = body.get("type")
            detail = body.get("detail") or body.get("title") or detail
        kwargs: dict[str, Any] = {
            "status": status,
            "problem_type": problem_type,
            "retry_after": _int_header(headers, "Retry-After"),
        }
        error_cls: type[SkodaApiError]
        if status == 401:
            error_cls = SkodaAuthError
        elif status == 403:
            error_cls = SkodaForbiddenError
        elif status == 404:
            error_cls = SkodaNotFoundError
        elif status in (412, 422):
            error_cls = SkodaOperationError
        elif status == 429:
            error_cls = SkodaRateLimitError
        elif status in (502, 503, 504):
            error_cls = SkodaConnectionError
        else:
            error_cls = SkodaApiError
        return error_cls(detail, **kwargs)

    # ------------------------------------------------------------------ data

    async def get_vehicle(
        self, vin: str, include: list[str] | None = None
    ) -> ApiResult:
        """Return the vehicle and its current state."""
        params = {"include": ",".join(include)} if include else None
        body, _ = await self._request("GET", f"/api/v1/vehicles/{vin}", params=params)
        if not isinstance(body, dict) or not isinstance(body.get("vehicle"), dict):
            raise SkodaApiError("Unexpected response from vehicle endpoint")
        return ApiResult(
            vehicle=body["vehicle"],
            errors=list(body.get("errors") or []),
            api_key_expires_at=self.rate_limit.api_key_expires_at,
            rate_limit_limit=self.rate_limit.limit,
            rate_limit_remaining=self.rate_limit.remaining,
            rate_limit_reset=self.rate_limit.reset,
        )

    # -------------------------------------------------------------- charging

    async def start_charging(self, vin: str) -> None:
        """Start charging."""
        await self._request("POST", f"/api/v1/vehicles/{vin}/charging/start")

    async def stop_charging(self, vin: str) -> None:
        """Stop charging."""
        await self._request("POST", f"/api/v1/vehicles/{vin}/charging/stop")

    async def set_charging_limit(self, vin: str, target_percent: int) -> None:
        """Set the target state of charge."""
        await self._request(
            "PUT",
            f"/api/v1/vehicles/{vin}/charging/limit",
            json={"targetStateOfChargeInPercent": int(target_percent)},
        )

    async def set_charge_mode(self, vin: str, mode: str) -> None:
        """Set the charge mode."""
        await self._request(
            "PUT", f"/api/v1/vehicles/{vin}/charging/mode", json={"chargeMode": mode}
        )

    async def update_charging_profile(
        self, vin: str, profile_id: int, profile: dict[str, Any]
    ) -> None:
        """Replace a charging profile (send the complete profile)."""
        await self._request(
            "PUT",
            f"/api/v1/vehicles/{vin}/charging-profiles/{profile_id}",
            json=profile,
        )

    # ------------------------------------------------------ air conditioning

    async def start_air_conditioning(
        self,
        vin: str,
        *,
        temperature: float | None = None,
        without_external_power: bool | None = None,
    ) -> None:
        """Start air conditioning."""
        payload: dict[str, Any] = {}
        if temperature is not None:
            payload["targetTemperature"] = {
                "value": float(temperature),
                "unit": "CELSIUS",
            }
        if without_external_power is not None:
            payload["airConditioningWithoutExternalPower"] = without_external_power
        await self._request(
            "POST", f"/api/v1/vehicles/{vin}/air-conditioning/start", json=payload
        )

    async def stop_air_conditioning(self, vin: str) -> None:
        """Stop air conditioning."""
        await self._request("POST", f"/api/v1/vehicles/{vin}/air-conditioning/stop")

    async def start_auxiliary_heating(
        self,
        vin: str,
        *,
        spin: str,
        temperature: float | None = None,
        duration: int | None = None,
        start_mode: str | None = None,
    ) -> None:
        """Start auxiliary heating (requires the S-PIN)."""
        payload: dict[str, Any] = {"spin": spin}
        if temperature is not None:
            payload["targetTemperature"] = {
                "value": float(temperature),
                "unit": "CELSIUS",
            }
        if duration is not None:
            payload["durationInSeconds"] = int(duration)
        if start_mode is not None:
            payload["startMode"] = start_mode
        await self._request(
            "POST", f"/api/v1/vehicles/{vin}/auxiliary-heating/start", json=payload
        )

    async def stop_auxiliary_heating(self, vin: str) -> None:
        """Stop auxiliary heating."""
        await self._request("POST", f"/api/v1/vehicles/{vin}/auxiliary-heating/stop")

    async def start_active_ventilation(self, vin: str) -> None:
        """Start active ventilation."""
        await self._request("POST", f"/api/v1/vehicles/{vin}/active-ventilation/start")

    async def stop_active_ventilation(self, vin: str) -> None:
        """Stop active ventilation."""
        await self._request("POST", f"/api/v1/vehicles/{vin}/active-ventilation/stop")
