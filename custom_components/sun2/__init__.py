"""Sun2 integration."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.const import (
    CONF_BINARY_SENSORS,
    CONF_NAME,
    CONF_SENSORS,
    CONF_UNIQUE_ID,
    Platform,
)
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .binary_sensor import SUN2_BINARY_SENSOR_SCHEMA
from .const import DOMAIN, LOGGER
from .helpers import LOC_PARAMS
from .sensor import SUN2_SENSOR_SCHEMA


def _unique_names(configs: list[dict]) -> list[dict]:
    """Check that names are unique."""
    names = [config.get(CONF_NAME) for config in configs]
    if len(names) != len(set(names)):
        raise vol.Invalid("Names must be unique")
    return configs


PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]

SUN2_CONFIG = vol.All(
    vol.Schema(
        {
            vol.Required(CONF_UNIQUE_ID): cv.string,
            vol.Optional(CONF_NAME): cv.string,
            vol.Optional(CONF_BINARY_SENSORS): vol.All(
                cv.ensure_list, [SUN2_BINARY_SENSOR_SCHEMA]
            ),
            vol.Optional(CONF_SENSORS): vol.All(cv.ensure_list, [SUN2_SENSOR_SCHEMA]),
            **LOC_PARAMS,
        }
    ),
    cv.has_at_least_one_key(CONF_BINARY_SENSORS, CONF_SENSORS),
)

CONFIG_SCHEMA = vol.Schema(
    {
        vol.Optional(DOMAIN, default=list): vol.All(
            cv.ensure_list, [SUN2_CONFIG], _unique_names
        ),
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Setup composite integration."""
    regd = {
        entry.unique_id: entry.entry_id
        for entry in hass.config_entries.async_entries(DOMAIN)
    }
    cfgs = {cfg[CONF_UNIQUE_ID]: cfg for cfg in config[DOMAIN]}

    for uid in set(regd) - set(cfgs):
        await hass.config_entries.async_remove(regd[uid])
    for uid in set(cfgs) - set(regd):
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}, data=cfgs[uid]
            )
        )
    for uid in set(cfgs) & set(regd):
        # TODO: UPDATE
        LOGGER.warning("Already configured: %s", uid)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
