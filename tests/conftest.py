from __future__ import annotations

import pytest

from homeassistant.const import MAJOR_VERSION, MINOR_VERSION
from homeassistant.core import HomeAssistant

from custom_components.sun2.const import DOMAIN

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations."""
    yield


@pytest.fixture(autouse=True)
async def cleanup(hass: HomeAssistant):
    yield
    if (MAJOR_VERSION, MINOR_VERSION) > (2023, 5):
        return
    # Before 2023.5 configs were not unloaded at end of testing, since they are not
    # normally unloaded when HA shuts down. Unload them here to avoid errors about
    # lingering timers.
    for entry in hass.config_entries.async_entries(DOMAIN):
        await hass.config_entries.async_unload(entry.entry_id)
