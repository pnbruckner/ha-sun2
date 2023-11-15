"""Config flow for Sun2 integration."""
from __future__ import annotations

from typing import cast, Any

from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_LOCATION, CONF_UNIQUE_ID
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN
from .helpers import Sun2Data


class Sun2ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Sun2 config flow."""

    VERSION = 1

    async def async_step_import(self, data: dict[str, Any]) -> FlowResult:
        """Import config entry from configuration."""
        location = data.pop(CONF_LOCATION, self.hass.config.location_name)
        service_name = cast(Sun2Data, self.hass.data[DOMAIN]).translations[
            f"component.{DOMAIN}.misc.service_name"
        ]
        title = f"{location} {service_name}"
        if existing_entry := await self.async_set_unique_id(data.pop(CONF_UNIQUE_ID)):
            self.hass.config_entries.async_update_entry(
                existing_entry, title=title, options=data
            )
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(existing_entry.entry_id)
            )
            return self.async_abort(reason="already_configured")

        return self.async_create_entry(data={}, title=title, options=data)
