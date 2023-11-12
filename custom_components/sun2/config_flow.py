"""Config flow for Sun2 integration."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_LOCATION, CONF_UNIQUE_ID
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.translation import async_get_translations

from .const import DOMAIN


class Sun2ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Sun2 config flow."""

    VERSION = 1

    async def async_step_import(self, data: dict[str, Any]) -> FlowResult:
        """Import config entry from configuration."""
        translations = await async_get_translations(
            self.hass, self.hass.config.language, "service_name", [DOMAIN], False
        )
        location = data.pop(CONF_LOCATION, self.hass.config.location_name)
        title = f"{location} {translations[f'component.{DOMAIN}.service_name']}"
        if existing_entry := await self.async_set_unique_id(data.pop(CONF_UNIQUE_ID)):
            self.hass.config_entries.async_update_entry(
                existing_entry, title=title, options=data
            )
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(existing_entry.entry_id)
            )
            return self.async_abort(reason="already_configured")

        return self.async_create_entry(data={}, title=title, options=data)
