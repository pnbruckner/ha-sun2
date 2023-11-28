"""Sun2 config validation."""
from __future__ import annotations

from collections.abc import Callable
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
    SUNSET_ELEV,
)
from .helpers import init_translations, translate

PACKAGE_MERGE_HINT = "list"
DEFAULT_ELEVATION = SUNSET_ELEV

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

ELEVATION_AT_TIME_SCHEMA = ELEVATION_AT_TIME_SCHEMA_BASE.extend(
    {vol.Required(CONF_UNIQUE_ID): cv.string}
)

val_elevation = vol.All(
    vol.Coerce(float), vol.Range(min=-90, max=90), msg="invalid elevation"
)

TIME_AT_ELEVATION_SCHEMA_BASE = vol.Schema(
    {
        vol.Required(CONF_TIME_AT_ELEVATION): val_elevation,
        vol.Optional(CONF_DIRECTION, default=SunDirection.RISING.name): vol.All(
            vol.Upper, cv.enum(SunDirection)
        ),
        vol.Optional(CONF_ICON): cv.icon,
        vol.Optional(CONF_NAME): cv.string,
    }
)

TIME_AT_ELEVATION_SCHEMA = TIME_AT_ELEVATION_SCHEMA_BASE.extend(
    {vol.Required(CONF_UNIQUE_ID): cv.string}
)


def _sensor(config: ConfigType) -> ConfigType:
    """Validate sensor config."""
    if CONF_ELEVATION_AT_TIME in config:
        return ELEVATION_AT_TIME_SCHEMA(config)
    if CONF_TIME_AT_ELEVATION in config:
        return TIME_AT_ELEVATION_SCHEMA(config)
    raise vol.Invalid(f"expected {CONF_ELEVATION_AT_TIME} or {CONF_TIME_AT_ELEVATION}")


_SUN2_LOCATION_CONFIG = vol.Schema(
    {
        vol.Required(CONF_UNIQUE_ID): cv.string,
        vol.Optional(CONF_LOCATION): cv.string,
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


def val_bs_elevation(hass: HomeAssistant | None = None) -> Callable[[dict], dict]:
    """Validate elevation binary_sensor config."""

    def validate(config: ConfigType) -> ConfigType:
        """Validate the config."""
        if config[CONF_ELEVATION] == "horizon":
            config[CONF_ELEVATION] = DEFAULT_ELEVATION

        if config.get(CONF_NAME):
            return config

        if (elevation := config[CONF_ELEVATION]) == DEFAULT_ELEVATION:
            name = translate(hass, "above_horizon")
        else:
            if elevation < 0:
                name = translate(hass, "above_neg_elev", {"elevation": str(-elevation)})
            else:
                name = translate(hass, "above_pos_elev", {"elevation": str(elevation)})
        config[CONF_NAME] = name
        return config

    return validate


def val_elevation_at_time(hass: HomeAssistant | None = None) -> Callable[[dict], dict]:
    """Validate elevation_at_time sensor config."""

    def validate(config: ConfigType) -> ConfigType:
        """Validate the config."""
        if config.get(CONF_NAME):
            return config

        at_time = config[CONF_ELEVATION_AT_TIME]
        if hass:
            name = translate(hass, "elevation_at", {"elev_time": str(at_time)})
        else:
            name = f"Elevation at {at_time}"
        config[CONF_NAME] = name
        return config

    return validate


_DIR_TO_ICON = {
    SunDirection.RISING: "mdi:weather-sunset-up",
    SunDirection.SETTING: "mdi:weather-sunset-down",
}


def val_time_at_elevation(hass: HomeAssistant | None = None) -> Callable[[dict], dict]:
    """Validate time_at_elevation sensor config."""

    def validate(config: ConfigType) -> ConfigType:
        """Validate the config."""
        direction = SunDirection(config[CONF_DIRECTION])
        if not config.get(CONF_ICON):
            config[CONF_ICON] = _DIR_TO_ICON[direction]

        if config.get(CONF_NAME):
            return config

        elevation = cast(float, config[CONF_TIME_AT_ELEVATION])
        if hass:
            name = translate(
                hass,
                f"{direction.name.lower()}_{'neg' if elevation < 0 else 'pos'}_elev",
                {"elevation": str(abs(elevation))},
            )
        else:
            dir_str = direction.name.title()
            if elevation >= 0:
                elev_str = str(elevation)
            else:
                elev_str = f"minus {-elevation}"
            name = f"{dir_str} at {elev_str} °"
        config[CONF_NAME] = name
        return config

    return validate


async def async_validate_config(
    hass: HomeAssistant, config: ConfigType
) -> ConfigType | None:
    """Validate configuration."""
    await init_translations(hass)

    config = _SUN2_CONFIG_SCHEMA(config)
    if DOMAIN not in config:
        return config

    _val_bs_elevation = val_bs_elevation(hass)
    _val_elevation_at_time = val_elevation_at_time(hass)
    _val_time_at_elevation = val_time_at_elevation(hass)
    for loc_config in config[DOMAIN]:
        if CONF_BINARY_SENSORS in loc_config:
            loc_config[CONF_BINARY_SENSORS] = [
                _val_bs_elevation(cfg) for cfg in loc_config[CONF_BINARY_SENSORS]
            ]
        if CONF_SENSORS in loc_config:
            sensor_configs = []
            for sensor_config in loc_config[CONF_SENSORS]:
                if CONF_ELEVATION_AT_TIME in sensor_config:
                    sensor_configs.append(_val_elevation_at_time(sensor_config))
                else:
                    sensor_configs.append(_val_time_at_elevation(sensor_config))
            loc_config[CONF_SENSORS] = sensor_configs
    return config
