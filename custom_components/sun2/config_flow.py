"""Config flow for Sun2 integration."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlowWithConfigEntry,
    SOURCE_IMPORT,
)
from homeassistant.const import (
    CONF_ELEVATION,
    CONF_LATITUDE,
    CONF_LOCATION,
    CONF_LONGITUDE,
    CONF_NAME,
    CONF_TIME_ZONE,
    CONF_UNIQUE_ID,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN

_LOCATION_OPTIONS = [CONF_ELEVATION, CONF_LATITUDE, CONF_LONGITUDE, CONF_TIME_ZONE]


class Sun2Flow(ABC):
    """Sun2 flow mixin."""

    def _any_using_ha_loc(self) -> bool:
        """Determine if a config is using Home Assistant location."""
        entries = self.hass.config_entries.async_entries(DOMAIN)
        return any(CONF_LATITUDE not in entry.options for entry in entries)

    @abstractmethod
    def create_entry(self) -> FlowResult:
        """Finish the flow."""

    async def async_step_use_home(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask user if entry should use Home Assistant's name & location."""
        if user_input is not None:
            if user_input["use_home"]:
                self.options = {k: v for k, v in self.options.items() if k not in _LOCATION_OPTIONS}
                return self.create_entry()
                # return await self.async_step_entities()
            return await self.async_step_location()

        schema = {
            vol.Required("use_home", default=CONF_LATITUDE not in self.options): bool
        }
        return self.async_show_form(step_id="use_home", data_schema=vol.Schema(schema))

    async def async_step_location(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle location options."""
        if user_input is not None:
            user_input[CONF_TIME_ZONE] = cv.time_zone(user_input[CONF_TIME_ZONE])
            self.options.update(user_input)
            return self.create_entry()
            # return await self.async_step_entities()

        schema = {
            vol.Required(
                CONF_LATITUDE, default=self.options.get(CONF_LATITUDE) or vol.UNDEFINED
            ): cv.latitude,
            vol.Required(
                CONF_LONGITUDE,
                default=self.options.get(CONF_LONGITUDE) or vol.UNDEFINED,
            ): cv.longitude,
            vol.Required(
                CONF_ELEVATION,
                default=self.options.get(CONF_ELEVATION) or vol.UNDEFINED,
            ): vol.Coerce(float),
            vol.Required(
                CONF_TIME_ZONE,
                default=self.options.get(CONF_TIME_ZONE) or vol.UNDEFINED,
            ): cv.string,
        }
        return self.async_show_form(step_id="location", data_schema=vol.Schema(schema))


class Sun2ConfigFlow(ConfigFlow, Sun2Flow, domain=DOMAIN):
    """Sun2 config flow."""

    VERSION = 1

    _location_name: str
    options: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> Sun2OptionsFlow:
        """Get the options flow for this handler."""
        return Sun2OptionsFlow(config_entry)

    @classmethod
    @callback
    def async_supports_options_flow(cls, config_entry: ConfigEntry) -> bool:
        """Return options flow support for this handler."""
        if config_entry.source == SOURCE_IMPORT:
            return False
        return cls.async_get_options_flow is not ConfigFlow.async_get_options_flow

    async def async_step_import(self, data: dict[str, Any]) -> FlowResult:
        """Import config entry from configuration."""
        self._location_name = data.pop(CONF_LOCATION, self.hass.config.location_name)
        if existing_entry := await self.async_set_unique_id(data.pop(CONF_UNIQUE_ID)):
            if not self.hass.config_entries.async_update_entry(
                existing_entry, title=self._location_name, options=data
            ):
                self.hass.async_create_task(
                    self.hass.config_entries.async_reload(existing_entry.entry_id)
                )
            return self.async_abort(reason="already_configured")

        self.options = data
        return self.create_entry()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Start user config flow."""
        self._location_name = self.hass.config.location_name
        if not self._any_using_ha_loc():
            return await self.async_step_use_home()
        return await self.async_step_location_name()

    async def async_step_location_name(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Get location name."""
        if user_input is not None:
            self._location_name = user_input[CONF_NAME]
            return await self.async_step_location()

        schema = {vol.Required(CONF_NAME): cv.string}
        return self.async_show_form(
            step_id="location_name", data_schema=vol.Schema(schema)
        )

    def create_entry(self) -> FlowResult:
        """Finish the flow."""
        return self.async_create_entry(
            title=self._location_name, data={}, options=self.options
        )


class Sun2OptionsFlow(OptionsFlowWithConfigEntry, Sun2Flow):
    """Sun2 integration options flow."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Start options flow."""
        if CONF_LATITUDE not in self.options or not self._any_using_ha_loc():
            return await self.async_step_use_home()
        return await self.async_step_location()

    def create_entry(self) -> FlowResult:
        """Finish the flow."""
        return self.async_create_entry(title="", data=self.options or {})
