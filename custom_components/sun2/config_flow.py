"""Config flow for Sun2 integration."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_LOCATION, CONF_UNIQUE_ID
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.translation import async_get_translations

from .const import DOMAIN


async def config_entry_params(
    hass: HomeAssistant, data: dict[str, Any]
) -> dict[str, Any]:
    """Get config entry parameters from configuration data."""
    data = data.copy()
    translations = await async_get_translations(
        hass, hass.config.language, "service_name", [DOMAIN], False
    )
    location = data.pop(CONF_LOCATION, hass.config.location_name)
    title = f"{location} {translations[f'component.{DOMAIN}.service_name']}"
    return {"title": title, "options": data}


class Sun2ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Sun2 config flow."""

    VERSION = 1

    async def async_step_import(self, data: dict[str, Any]) -> FlowResult:
        """Import config entry from configuration."""
        await self.async_set_unique_id(data.pop(CONF_UNIQUE_ID))
        self._abort_if_unique_id_configured()

        params = await config_entry_params(self.hass, data)
        return self.async_create_entry(data={}, **params)
