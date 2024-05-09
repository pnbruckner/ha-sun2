"""Sun2 config validation."""
from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any, cast

from astral import SunDirection
import voluptuous as vol

from homeassistant.const import (
    CONF_BINARY_SENSORS,
    CONF_ELEVATION,
    CONF_ICON,
    CONF_LATITUDE,
    CONF_LOCATION,
    CONF_LONGITUDE,
    CONF_NAME,
    CONF_SENSORS,
    CONF_TIME_ZONE,
    CONF_UNIQUE_ID,
)
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_ABOVE_GROUND,
    CONF_DIRECTION,
    CONF_DISTANCE,
    CONF_ELEVATION_AT_TIME,
    CONF_OBS_ELV,
    CONF_RELATIVE_HEIGHT,
    CONF_SUNRISE_OBSTRUCTION,
    CONF_SUNSET_OBSTRUCTION,
    CONF_TIME_AT_ELEVATION,
    DOMAIN,
)
from .helpers import Num, init_translations

_LOGGER = logging.getLogger(__name__)
_COERCE_NUM = vol.Any(vol.Coerce(int), vol.Coerce(float))

PACKAGE_MERGE_HINT = "list"
SUN_DIRECTIONS = [dir.lower() for dir in SunDirection.__members__]
SUN2_LOCATION_BASE_SCHEMA = vol.Schema(
    {
        vol.Inclusive(CONF_LATITUDE, "location"): cv.latitude,
        vol.Inclusive(CONF_LONGITUDE, "location"): cv.longitude,
        vol.Inclusive(CONF_TIME_ZONE, "location"): cv.time_zone,
        vol.Optional(CONF_OBS_ELV): vol.Any(
            _COERCE_NUM, dict, msg="expected a number or a dictionary"
        ),
    }
)

_SUN2_BINARY_SENSOR_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_UNIQUE_ID): cv.string,
        vol.Required(CONF_ELEVATION): vol.Any(
            vol.All(vol.Lower, "horizon"),
            vol.Coerce(float),
            msg="must be a number or the word horizon",
        ),
        vol.Optional(CONF_NAME): cv.string,
    }
)

_ELEVATION_AT_TIME_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_UNIQUE_ID): cv.string,
        vol.Required(CONF_ELEVATION_AT_TIME): vol.Any(
            vol.All(cv.string, cv.entity_domain("input_datetime")),
            cv.time,
            msg="expected time string or input_datetime entity ID",
        ),
        vol.Optional(CONF_NAME): cv.string,
    }
)

_TIME_AT_ELEVATION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_UNIQUE_ID): cv.string,
        vol.Required(CONF_TIME_AT_ELEVATION): vol.All(
            vol.Coerce(float), vol.Range(min=-90, max=90), msg="invalid elevation"
        ),
        vol.Optional(CONF_DIRECTION, default=SUN_DIRECTIONS[0]): vol.In(SUN_DIRECTIONS),
        vol.Optional(CONF_ICON): cv.icon,
        vol.Optional(CONF_NAME): cv.string,
    }
)


def _sensor(config: ConfigType) -> ConfigType:
    """Validate sensor config."""
    if CONF_ELEVATION_AT_TIME in config:
        return cast(ConfigType, _ELEVATION_AT_TIME_SCHEMA(config))
    if CONF_TIME_AT_ELEVATION in config:
        return cast(ConfigType, _TIME_AT_ELEVATION_SCHEMA(config))
    raise vol.Invalid(f"expected {CONF_ELEVATION_AT_TIME} or {CONF_TIME_AT_ELEVATION}")


_SUN2_LOCATION_SCHEMA = SUN2_LOCATION_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_UNIQUE_ID): cv.string,
        vol.Inclusive(CONF_LOCATION, "location"): cv.string,
        vol.Optional(CONF_ELEVATION): _COERCE_NUM,
        vol.Optional(CONF_BINARY_SENSORS): vol.All(
            cv.ensure_list, [_SUN2_BINARY_SENSOR_SCHEMA]
        ),
        vol.Optional(CONF_SENSORS): vol.All(cv.ensure_list, [_sensor]),
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
            [_SUN2_LOCATION_SCHEMA],
            _unique_locations_names,
        ),
    },
    extra=vol.ALLOW_EXTRA,
)


_OBSTRUCTION_CONFIG = {
    vol.Required(CONF_DISTANCE): _COERCE_NUM,
    vol.Required(CONF_RELATIVE_HEIGHT): _COERCE_NUM,
}
_OBS_ELV_DICT = {
    vol.Optional(CONF_ABOVE_GROUND): _COERCE_NUM,
    vol.Optional(CONF_SUNRISE_OBSTRUCTION): _OBSTRUCTION_CONFIG,
    vol.Optional(CONF_SUNSET_OBSTRUCTION): _OBSTRUCTION_CONFIG,
}
_OBS_ELV_KEYS = [option.schema for option in _OBS_ELV_DICT]
_OBS_ELV_INVALID_LEN_MSG = f"use exactly two of: {', '.join(_OBS_ELV_KEYS)}"
_OBS_ELV_DICT_SCHEMA = vol.All(
    vol.Schema(_OBS_ELV_DICT), vol.Length(2, 2, msg=_OBS_ELV_INVALID_LEN_MSG)
)


def obs_elv_from_options(
    hass: HomeAssistant, options: Mapping[str, Any]
) -> ConfigType | Num:
    """Return observer_elevation config from options."""
    if obs_elv_option := options.get(CONF_OBS_ELV):
        east_obs_elv, west_obs_elv = obs_elv_option

        if isinstance(east_obs_elv, Num) and isinstance(west_obs_elv, Num):  # type: ignore[misc, arg-type]
            assert east_obs_elv == west_obs_elv
            return cast(Num, east_obs_elv)

        obs_elv: ConfigType = {}
        if isinstance(east_obs_elv, Num):  # type: ignore[misc, arg-type]
            obs_elv[CONF_ABOVE_GROUND] = east_obs_elv
        else:
            obs_elv[CONF_SUNRISE_OBSTRUCTION] = {
                CONF_DISTANCE: east_obs_elv[1],
                CONF_RELATIVE_HEIGHT: east_obs_elv[0],
            }
        if isinstance(west_obs_elv, Num):  # type: ignore[misc, arg-type]
            obs_elv[CONF_ABOVE_GROUND] = west_obs_elv
        else:
            obs_elv[CONF_SUNSET_OBSTRUCTION] = {
                CONF_DISTANCE: west_obs_elv[1],
                CONF_RELATIVE_HEIGHT: west_obs_elv[0],
            }
        return obs_elv

    return options.get(CONF_ELEVATION, hass.config.elevation)


def _obs_elv(
    obstruction: Mapping[str, Num] | None, above_ground: Num | None
) -> Num | list[Num]:
    """Determine observer elevation from obstruction or elevation above ground level."""
    if obstruction:
        return [obstruction[CONF_RELATIVE_HEIGHT], obstruction[CONF_DISTANCE]]
    assert above_ground is not None
    return above_ground


def options_from_obs_elv(
    hass: HomeAssistant, loc_config: ConfigType, idx: int | None = None
) -> None:
    """Validate observer elevation option in location config.

    If deprecated elevation option is present, warn or raise exception,
    but leave as-is (i.e., do not convert to observer elevation option.)
    Just continue to use elevation option until user replaces deprecated
    option with new option.

    Otherwise, convert to list[Num | list[Num]] where
    list[0] is east (sunrise) observer_elevation,
    list[1] is west (sunset) observer_elevation,
    observer_elevation is Num or list[Num] where
    Num is elevation above ground level or
    list[0] is height of obstruction relative to observer
    list[1] is distance to obstruction from observer
    """
    east_obs_elv: Num | list[Num]
    west_obs_elv: Num | list[Num]

    try:
        if CONF_ELEVATION in loc_config:
            cv.has_at_most_one_key(CONF_ELEVATION, CONF_OBS_ELV)(loc_config)
            # Pass in copy of config so elevation option does not get removed.
            cv.deprecated(CONF_ELEVATION, CONF_OBS_ELV)(dict(loc_config))
            return

        if CONF_OBS_ELV not in loc_config:
            # TODO: Make this a repair issue???
            _LOGGER.warning(
                "New config option %s missing @ data[%s][%s], "
                "will use system general elevation setting",
                CONF_OBS_ELV,
                DOMAIN,
                idx,
            )
            east_obs_elv = west_obs_elv = hass.config.elevation

        elif isinstance(obs := loc_config[CONF_OBS_ELV], Num):  # type: ignore[misc, arg-type]
            east_obs_elv = west_obs_elv = obs

        else:
            try:
                _OBS_ELV_DICT_SCHEMA(obs)
            except vol.Invalid as err:
                err.prepend([CONF_OBS_ELV])
                raise
            above_ground = obs.get(CONF_ABOVE_GROUND)
            east_obs_elv = _obs_elv(obs.get(CONF_SUNRISE_OBSTRUCTION), above_ground)
            west_obs_elv = _obs_elv(obs.get(CONF_SUNSET_OBSTRUCTION), above_ground)

    except vol.Invalid as err:
        if idx is not None:
            err.prepend([DOMAIN, idx])
        raise

    loc_config[CONF_OBS_ELV] = [east_obs_elv, west_obs_elv]


async def async_validate_config(
    hass: HomeAssistant, config: ConfigType
) -> ConfigType | None:
    """Validate configuration."""
    await init_translations(hass)

    config = _SUN2_CONFIG_SCHEMA(config)
    if DOMAIN not in config:
        return config

    for idx, loc_config in enumerate(config[DOMAIN]):
        options_from_obs_elv(hass, loc_config, idx)
    return config
