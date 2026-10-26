"""Config flow for SkodaLink."""

from __future__ import annotations

from collections.abc import Mapping
import logging
import re
from typing import Any

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_API_KEY, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .api import (
    SkodaApi,
    SkodaApiError,
    SkodaAuthError,
    SkodaConnectionError,
    SkodaForbiddenError,
    SkodaNotFoundError,
    SkodaRateLimitError,
)
from .const import (
    API_KEYS_URL,
    CONF_SPIN,
    CONF_VINS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def parse_vins(raw: str) -> list[str]:
    """Split user input into a de-duplicated list of upper-case VINs."""
    vins: list[str] = []
    for part in re.split(r"[\s,;]+", raw.strip().upper()):
        if part and part not in vins:
            vins.append(part)
    return vins


class SkodaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SkodaLink."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SkodaOptionsFlow:
        """Return the options flow."""
        return SkodaOptionsFlow()

    async def _validate(
        self, api_key: str, vins: list[str]
    ) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        """Check the key against every VIN.

        Returns (errors, placeholders, vehicle names by VIN).
        """
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {"url": API_KEYS_URL}
        names: dict[str, str] = {}
        if not vins:
            return {CONF_VINS: "no_vins"}, placeholders, names
        for vin in vins:
            if not VIN_RE.match(vin):
                placeholders["vin"] = vin
                return {CONF_VINS: "invalid_vin"}, placeholders, names

        api = SkodaApi(async_get_clientsession(self.hass), api_key)
        for vin in vins:
            placeholders["vin"] = vin
            try:
                result = await api.get_vehicle(vin, include=["info"])
            except SkodaAuthError as err:
                errors["base"] = (
                    "api_key_expired"
                    if err.problem == "api-key-expired"
                    else "invalid_auth"
                )
            except SkodaForbiddenError:
                errors[CONF_VINS] = "vehicle_not_authorized"
            except SkodaNotFoundError:
                errors[CONF_VINS] = "vehicle_not_found"
            except SkodaRateLimitError:
                errors["base"] = "rate_limited"
            except SkodaConnectionError:
                errors["base"] = "cannot_connect"
            except SkodaApiError:
                _LOGGER.exception("Unexpected API error while validating %s", vin)
                errors["base"] = "unknown"
            else:
                names[vin] = result.vehicle.get("name") or vin
                continue
            break
        return errors, placeholders, names

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {"url": API_KEYS_URL}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            vins = parse_vins(user_input[CONF_VINS])
            errors, placeholders, names = await self._validate(api_key, vins)
            if not errors:
                await self.async_set_unique_id(",".join(sorted(vins)))
                self._abort_if_unique_id_configured()
                for entry in self._async_current_entries(include_ignore=False):
                    if set(vins) & set(entry.data.get(CONF_VINS, [])):
                        return self.async_abort(reason="vehicle_already_configured")
                return self.async_create_entry(
                    title=", ".join(names.values()),
                    data={CONF_API_KEY: api_key, CONF_VINS: vins},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_API_KEY): PASSWORD_SELECTOR,
                        vol.Required(CONF_VINS): str,
                    }
                ),
                user_input,
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle an expired or revoked API key."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new API key."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {"url": API_KEYS_URL, "title": entry.title}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            errors, extra, _ = await self._validate(api_key, entry.data[CONF_VINS])
            placeholders.update(extra)
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_KEY: api_key}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): PASSWORD_SELECTOR}),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the API key and/or vehicles."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {"url": API_KEYS_URL}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            vins = parse_vins(user_input[CONF_VINS])
            errors, placeholders, names = await self._validate(api_key, vins)
            if not errors:
                for other in self._async_current_entries(include_ignore=False):
                    if other.entry_id != entry.entry_id and set(vins) & set(
                        other.data.get(CONF_VINS, [])
                    ):
                        return self.async_abort(reason="vehicle_already_configured")
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=",".join(sorted(vins)),
                    title=", ".join(names.values()),
                    data_updates={CONF_API_KEY: api_key, CONF_VINS: vins},
                )
        suggested = user_input or {
            CONF_API_KEY: entry.data[CONF_API_KEY],
            CONF_VINS: ", ".join(entry.data[CONF_VINS]),
        }
        return self.async_show_form(
            step_id=SOURCE_RECONFIGURE,
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_API_KEY): PASSWORD_SELECTOR,
                        vol.Required(CONF_VINS): str,
                    }
                ),
                suggested,
            ),
            errors=errors,
            description_placeholders=placeholders,
        )


class SkodaOptionsFlow(OptionsFlow):
    """Options: polling interval and S-PIN."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            data = {
                CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
            }
            if spin := (user_input.get(CONF_SPIN) or "").strip():
                data[CONF_SPIN] = spin
            return self.async_create_entry(data=data)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="min",
                    )
                ),
                vol.Optional(
                    CONF_SPIN,
                    description={"suggested_value": options.get(CONF_SPIN)},
                ): PASSWORD_SELECTOR,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
