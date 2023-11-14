"""Sun2 integration."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.const import (
    CONF_BINARY_SENSORS,
    CONF_LOCATION,
    CONF_SENSORS,
    CONF_UNIQUE_ID,
    EVENT_CORE_CONFIG_UPDATE,
    Platform,
)
from homeassistant.core import Event, HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.dispatcher import dispatcher_send
from homeassistant.helpers.typing import ConfigType

from .binary_sensor import SUN2_BINARY_SENSOR_SCHEMA
from .const import DOMAIN, SIG_HA_LOC_UPDATED
from .helpers import LOC_PARAMS, LocData, LocParams
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
    hass.data[DOMAIN] = {}

    def update_local_loc_data(event: Event | None = None) -> None:
        """Update local location data from HA's config."""
        hass.data[DOMAIN][None] = loc_data = LocData(
            LocParams(
                hass.config.elevation,
                hass.config.latitude,
                hass.config.longitude,
                str(hass.config.time_zone),
            )
        )
        if event:
            # Signal all instances that location data has changed.
            dispatcher_send(hass, SIG_HA_LOC_UPDATED, loc_data)

    update_local_loc_data()
    hass.bus.async_listen(EVENT_CORE_CONFIG_UPDATE, update_local_loc_data)

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
