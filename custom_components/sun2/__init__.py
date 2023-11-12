"""Sun2 integration."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.const import (
    CONF_BINARY_SENSORS,
    CONF_LOCATION,
    CONF_SENSORS,
    CONF_UNIQUE_ID,
    Platform,
)
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .binary_sensor import SUN2_BINARY_SENSOR_SCHEMA
from .const import DOMAIN
from .helpers import LOC_PARAMS
from .sensor import ELEVATION_AT_TIME_SCHEMA, TIME_AT_ELEVATION_SCHEMA


def _unique_locations_names(configs: list[dict]) -> list[dict]:
    """Check that location names are unique."""
    names = [config.get(CONF_LOCATION) for config in configs]
    if len(names) != len(set(names)):
        raise vol.Invalid(f"{CONF_LOCATION} values must be unique")
    return configs


PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]

SUN2_CONFIG = vol.Schema(
    {
        vol.Required(CONF_UNIQUE_ID): cv.string,
        vol.Optional(CONF_LOCATION): cv.string,
        vol.Optional(CONF_BINARY_SENSORS): vol.All(
            cv.ensure_list, [SUN2_BINARY_SENSOR_SCHEMA]
        ),
        vol.Optional(CONF_SENSORS): vol.All(
            cv.ensure_list,
            [vol.Any(ELEVATION_AT_TIME_SCHEMA, TIME_AT_ELEVATION_SCHEMA)],
        ),
        **LOC_PARAMS,
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        vol.Optional(DOMAIN, default=list): vol.All(
            cv.ensure_list, [SUN2_CONFIG], _unique_locations_names
        ),
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Setup composite integration."""
    for conf in config[DOMAIN]:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}, data=conf.copy()
            )
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
