"""Config flow for Sun2 integration."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_NAME, CONF_UNIQUE_ID
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN


class Sun2ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Sun2 config flow."""

    VERSION = 1

    async def async_step_import(self, data: dict[str, Any]) -> FlowResult:
        """Import config entry from configuration."""
        unique_id = data.pop(CONF_UNIQUE_ID)
        name = data.get(CONF_NAME, self.hass.config.location_name)
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(title=name, data=data)
