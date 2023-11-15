"""Sun2 config validation."""
from __future__ import annotations

from typing import cast

import voluptuous as vol

from homeassistant.const import (
    CONF_ABOVE,
    CONF_BINARY_SENSORS,
    CONF_ELEVATION,
    CONF_LOCATION,
    CONF_NAME,
    CONF_SENSORS,
    CONF_UNIQUE_ID,
)
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.translation import async_get_translations
from homeassistant.helpers.typing import ConfigType

from .binary_sensor import (
    DEFAULT_ELEVATION_ABOVE,
    SUN2_BINARY_SENSOR_SCHEMA,
    val_bs_cfg,
)
from .const import CONF_ELEVATION_AT_TIME, DOMAIN
from .helpers import LOC_PARAMS, Sun2Data
from .sensor import (
    _eat_defaults,
    _tae_defaults,
    ELEVATION_AT_TIME_SCHEMA,
    TIME_AT_ELEVATION_SCHEMA,
)

_SUN2_LOCATION_CONFIG = vol.Schema(
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


def _unique_locations_names(configs: list[dict]) -> list[dict]:
    """Check that location names are unique."""
    names = [config.get(CONF_LOCATION) for config in configs]
    if len(names) != len(set(names)):
        raise vol.Invalid(f"{CONF_LOCATION} values must be unique")
    return configs


_SUN2_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Optional(DOMAIN): vol.All(
            lambda config: config or [],
            cv.ensure_list,
            [_SUN2_LOCATION_CONFIG],
            _unique_locations_names,
        ),
    },
    extra=vol.ALLOW_EXTRA,
)


def _val_bs_name(hass: HomeAssistant, config: str | ConfigType) -> ConfigType:
    """Validate binary_sensor name."""
    if CONF_ELEVATION in config:
        options = config[CONF_ELEVATION]
        if CONF_NAME not in options:
            above = options[CONF_ABOVE]
            if above == DEFAULT_ELEVATION_ABOVE:
                name = cast(Sun2Data, hass.data[DOMAIN]).translations[
                    f"component.{DOMAIN}.misc.above_horizon"
                ]
            else:
                above_str = cast(Sun2Data, hass.data[DOMAIN]).translations[
                    f"component.{DOMAIN}.misc.above"
                ]
                if above < 0:
                    minus_str = cast(Sun2Data, hass.data[DOMAIN]).translations[
                        f"component.{DOMAIN}.misc.minus"
                    ]
                    name = f"{above_str} {minus_str} {-above}"
                else:
                    name = f"{above_str} {above}"
            options[CONF_NAME] = name
    return config


async def async_validate_config(
    hass: HomeAssistant, config: ConfigType
) -> ConfigType | None:
    """Validate configuration."""
    hass.data[DOMAIN] = Sun2Data(
        locations={},
        translations=await async_get_translations(
            hass, hass.config.language, "misc", [DOMAIN], False
        ),
    )

    config = _SUN2_CONFIG_SCHEMA(config)
    if DOMAIN not in config:
        return config
    if not config[DOMAIN]:
        config[DOMAIN] = [{CONF_UNIQUE_ID: "home"}]
        return config

    for loc_config in config[DOMAIN]:
        if CONF_BINARY_SENSORS in loc_config:
            loc_config[CONF_BINARY_SENSORS] = [
                _val_bs_name(hass, val_bs_cfg(cfg))
                for cfg in loc_config[CONF_BINARY_SENSORS]
            ]
        if CONF_SENSORS in loc_config:
            sensor_configs = []
            for sensor_config in loc_config[CONF_SENSORS]:
                if CONF_ELEVATION_AT_TIME in sensor_config:
                    sensor_configs.append(_eat_defaults(sensor_config))
                else:
                    sensor_configs.append(_tae_defaults(sensor_config))
            loc_config[CONF_SENSORS] = sensor_configs
    return config
