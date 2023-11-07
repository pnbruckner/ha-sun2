"""Sun2 integration."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.const import (
    CONF_BINARY_SENSORS,
    CONF_NAME,
    CONF_SENSORS,
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


SUN2_CONFIG = vol.All(
    vol.Schema(
        {
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
    LOGGER.debug("%s", config)

    return True
