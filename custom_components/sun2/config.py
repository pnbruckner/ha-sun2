"""Sun2 config validation."""
from __future__ import annotations

from typing import cast

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
    CONF_DIRECTION,
    CONF_ELEVATION_AT_TIME,
    CONF_TIME_AT_ELEVATION,
    DOMAIN,
)
from .helpers import init_translations

PACKAGE_MERGE_HINT = "list"

LOC_PARAMS = {
    vol.Inclusive(CONF_ELEVATION, "location"): vol.Coerce(float),
    vol.Inclusive(CONF_LATITUDE, "location"): cv.latitude,
    vol.Inclusive(CONF_LONGITUDE, "location"): cv.longitude,
    vol.Inclusive(CONF_TIME_ZONE, "location"): cv.time_zone,
}

_SUN2_BINARY_SENSOR_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_UNIQUE_ID): cv.string,
        vol.Required(CONF_ELEVATION): vol.Any(
            vol.All(vol.Lower, "horizon"),
            vol.Coerce(float),
            msg="must be a float or the word horizon",
        ),
        vol.Optional(CONF_NAME): cv.string,
    }
)

ELEVATION_AT_TIME_SCHEMA_BASE = vol.Schema(
    {
        vol.Required(CONF_ELEVATION_AT_TIME): vol.Any(
            vol.All(cv.string, cv.entity_domain("input_datetime")),
            cv.time,
            msg="expected time string or input_datetime entity ID",
        ),
        vol.Optional(CONF_NAME): cv.string,
    }
)

_ELEVATION_AT_TIME_SCHEMA = ELEVATION_AT_TIME_SCHEMA_BASE.extend(
    {vol.Required(CONF_UNIQUE_ID): cv.string}
)

SUN_DIRECTIONS = [dir.lower() for dir in SunDirection.__members__]

TIME_AT_ELEVATION_SCHEMA_BASE = vol.Schema(
    {
        vol.Required(CONF_TIME_AT_ELEVATION): vol.All(
            vol.Coerce(float), vol.Range(min=-90, max=90), msg="invalid elevation"
        ),
        vol.Optional(CONF_DIRECTION, default=SUN_DIRECTIONS[0]): vol.In(SUN_DIRECTIONS),
        vol.Optional(CONF_ICON): cv.icon,
        vol.Optional(CONF_NAME): cv.string,
    }
)

_TIME_AT_ELEVATION_SCHEMA = TIME_AT_ELEVATION_SCHEMA_BASE.extend(
    {vol.Required(CONF_UNIQUE_ID): cv.string}
)


def _sensor(config: ConfigType) -> ConfigType:
    """Validate sensor config."""
    if CONF_ELEVATION_AT_TIME in config:
        return cast(ConfigType, _ELEVATION_AT_TIME_SCHEMA(config))
    if CONF_TIME_AT_ELEVATION in config:
        return cast(ConfigType, _TIME_AT_ELEVATION_SCHEMA(config))
    raise vol.Invalid(f"expected {CONF_ELEVATION_AT_TIME} or {CONF_TIME_AT_ELEVATION}")


_SUN2_LOCATION_CONFIG = vol.Schema(
    {
        vol.Required(CONF_UNIQUE_ID): cv.string,
        vol.Inclusive(CONF_LOCATION, "location"): cv.string,
        vol.Optional(CONF_BINARY_SENSORS): vol.All(
            cv.ensure_list, [_SUN2_BINARY_SENSOR_SCHEMA]
        ),
        vol.Optional(CONF_SENSORS): vol.All(cv.ensure_list, [_sensor]),
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


async def async_validate_config(
    hass: HomeAssistant, config: ConfigType
) -> ConfigType | None:
    """Validate configuration."""
    await init_translations(hass)

    return cast(ConfigType, _SUN2_CONFIG_SCHEMA(config))
