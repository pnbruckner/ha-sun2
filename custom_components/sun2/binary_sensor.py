"""Sun2 Binary Sensor."""
from __future__ import annotations

from datetime import datetime
from numbers import Real
from typing import Any, Mapping, cast

import voluptuous as vol

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
    DOMAIN as BINARY_SENSOR_DOMAIN,
    PLATFORM_SCHEMA,
)
from homeassistant.const import (
    CONF_ABOVE,
    CONF_ELEVATION,
    CONF_ENTITY_NAMESPACE,
    CONF_MONITORED_CONDITIONS,
    CONF_NAME,
)
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util

from .const import ATTR_NEXT_CHANGE, LOGGER, MAX_ERR_BIN, ONE_DAY, ONE_SEC, SUNSET_ELEV
from .helpers import (
    LOC_PARAMS,
    LocParams,
    Num,
    Sun2Entity,
    get_loc_params,
    nearest_second,
)

DEFAULT_ELEVATION_ABOVE = SUNSET_ELEV
DEFAULT_ELEVATION_NAME = "Above Horizon"

ABOVE_ICON = "mdi:white-balance-sunny"
BELOW_ICON = "mdi:moon-waxing-crescent"

_SENSOR_TYPES = [CONF_ELEVATION]


# elevation
# elevation: <threshold>
# elevation:
#   above: <threshold>
#   name: <friendly_name>


def _val_cfg(config: str | ConfigType) -> ConfigType:
    """Validate configuration."""
    if isinstance(config, str):
        config = {config: {}}
    else:
        if CONF_ELEVATION in config:
            value = config[CONF_ELEVATION]
            if isinstance(value, Real):
                config[CONF_ELEVATION] = {CONF_ABOVE: value}
    if CONF_ELEVATION in config:
        options = config[CONF_ELEVATION]
        for key in options:
            if key not in [CONF_ELEVATION, CONF_ABOVE, CONF_NAME]:
                raise vol.Invalid(f"{key} not allowed for {CONF_ELEVATION}")
        if CONF_ABOVE not in options:
            options[CONF_ABOVE] = DEFAULT_ELEVATION_ABOVE
        if CONF_NAME not in options:
            above = options[CONF_ABOVE]
            if above == DEFAULT_ELEVATION_ABOVE:
                name = DEFAULT_ELEVATION_NAME
            else:
                name = "Above "
                if above < 0:
                    name += f"minus {-above}"
                else:
                    name += f"{above}"
            options[CONF_NAME] = name
    return config


_BINARY_SENSOR_SCHEMA = vol.All(
    vol.Any(
        vol.In(_SENSOR_TYPES),
        vol.Schema(
            {
                vol.Required(vol.In(_SENSOR_TYPES)): vol.Any(
                    vol.Coerce(float),
                    vol.Schema(
                        {
                            vol.Optional(CONF_ABOVE): vol.Coerce(float),
                            vol.Optional(CONF_NAME): cv.string,
                        }
                    ),
                ),
            }
        ),
    ),
    _val_cfg,
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_MONITORED_CONDITIONS): vol.All(
            cv.ensure_list, [_BINARY_SENSOR_SCHEMA]
        ),
        **LOC_PARAMS,
    }
)


class Sun2ElevationSensor(Sun2Entity, BinarySensorEntity):
    """Sun2 Elevation Sensor."""

    def __init__(
        self,
        loc_params: LocParams | None,
        namespace: str | None,
        name: str,
        above: float,
    ) -> None:
        """Initialize sensor."""
        object_id = name
        if namespace:
            name = f"{namespace} {name}"
        self.entity_description = BinarySensorEntityDescription(
            key=CONF_ELEVATION, name=name
        )
        super().__init__(loc_params, BINARY_SENSOR_DOMAIN, object_id)
        self._event = "solar_elevation"

        self._threshold: float = above

    def _find_nxt_dttm(
        self, t0_dttm: datetime, t0_elev: Num, t1_dttm: datetime, t1_elev: Num
    ) -> datetime:
        """Find time elevation crosses threshold between two points on elevation curve."""
        # Do a binary search for time between t0 & t1 where elevation is
        # nearest threshold, but also above (or equal to) it if current
        # elevation is below it (i.e., current state is False), or below it if
        # current elevation is above (or equal to) it (i.e., current state is
        # True.)

        slope = 1 if t1_elev > t0_elev else -1

        # Find mid point and throw away fractional seconds since astral package
        # ignores microseconds.
        tn_dttm = nearest_second(t0_dttm + (t1_dttm - t0_dttm) / 2)
        tn_elev = cast(float, self._astral_event(tn_dttm))

        while not (
            (
                self._attr_is_on
                and tn_elev <= self._threshold
                or not self._attr_is_on
                and tn_elev > self._threshold
            )
            and abs(tn_elev - self._threshold) <= MAX_ERR_BIN
        ):

            if (tn_elev - self._threshold) * slope > 0:
                if t1_dttm == tn_dttm:
                    break
                t1_dttm = tn_dttm
            else:
                if t0_dttm == tn_dttm:
                    break
                t0_dttm = tn_dttm
            tn_dttm = nearest_second(t0_dttm + (t1_dttm - t0_dttm) / 2)
            tn_elev = cast(float, self._astral_event(tn_dttm))

        # Did we go too far?
        if self._attr_is_on and tn_elev > self._threshold:
            tn_dttm -= slope * ONE_SEC
            if cast(float, self._astral_event(tn_dttm)) > self._threshold:
                raise RuntimeError("Couldn't find next update time")
        elif not self._attr_is_on and tn_elev <= self._threshold:
            tn_dttm += slope * ONE_SEC
            if cast(float, self._astral_event(tn_dttm)) <= self._threshold:
                raise RuntimeError("Couldn't find next update time")

        return tn_dttm

    def _get_nxt_dttm(self, cur_dttm: datetime) -> datetime | None:
        """Get next time sensor should change state."""
        # Find next segment of elevation curve, between a pair of solar noon &
        # solar midnight, where it crosses the threshold, but in the opposite
        # direction (i.e., where output should change state.) Note that this
        # might be today, tomorrow, days away, or never, depending on location,
        # time of year and specified threshold.

        # Start by finding the next five solar midnight & solar noon "events"
        # since current time might be anywhere from before today's solar
        # midnight (if it is this morning) to after tomorrow's solar midnight
        # (if it is this evening.)
        date = cur_dttm.date()
        evt_dttm1 = cast(datetime, self._astral_event(date, "solar_midnight"))
        evt_dttm2 = cast(datetime, self._astral_event(date, "solar_noon"))
        evt_dttm3 = cast(datetime, self._astral_event(date + ONE_DAY, "solar_midnight"))
        evt_dttm4 = cast(datetime, self._astral_event(date + ONE_DAY, "solar_noon"))
        evt_dttm5 = cast(
            datetime, self._astral_event(date + 2 * ONE_DAY, "solar_midnight")
        )

        # See if segment we're looking for falls between any of these events.
        # If not move ahead a day and try again, but don't look more than a
        # a year ahead.
        end_date = date + 366 * ONE_DAY
        while date < end_date:
            if cur_dttm < evt_dttm1:
                if self._attr_is_on:
                    t0_dttm = cur_dttm
                    t1_dttm = evt_dttm1
                else:
                    t0_dttm = evt_dttm1
                    t1_dttm = evt_dttm2
            elif cur_dttm < evt_dttm2:
                if not self._attr_is_on:
                    t0_dttm = cur_dttm
                    t1_dttm = evt_dttm2
                else:
                    t0_dttm = evt_dttm2
                    t1_dttm = evt_dttm3
            elif cur_dttm < evt_dttm3:
                if self._attr_is_on:
                    t0_dttm = cur_dttm
                    t1_dttm = evt_dttm3
                else:
                    t0_dttm = evt_dttm3
                    t1_dttm = evt_dttm4
            else:
                if not self._attr_is_on:
                    t0_dttm = cur_dttm
                    t1_dttm = evt_dttm4
                else:
                    t0_dttm = evt_dttm4
                    t1_dttm = evt_dttm5

            t0_elev = cast(float, self._astral_event(t0_dttm))
            t1_elev = cast(float, self._astral_event(t1_dttm))

            # Did we find it?
            # Note, if t1_elev > t0_elev, then we're looking for an elevation
            # ABOVE threshold. In this case we can't use this range if the
            # threshold is EQUAL to the elevation at t1, because this range
            # does NOT include any points with a higher elevation value. For
            # all other cases it's ok for the threshold to equal the elevation
            # at t0 or t1.
            if (
                t0_elev <= self._threshold < t1_elev
                or t1_elev <= self._threshold <= t0_elev
            ):

                nxt_dttm = self._find_nxt_dttm(t0_dttm, t0_elev, t1_dttm, t1_elev)
                if nxt_dttm - cur_dttm > ONE_DAY:
                    if self.hass.state == CoreState.running:
                        LOGGER.warning(
                            "%s: Sun elevation will not reach %f again until %s",
                            self.name,
                            self._threshold,
                            nxt_dttm.date(),
                        )
                return nxt_dttm

            # Shift one day ahead.
            date += ONE_DAY
            evt_dttm1 = evt_dttm3
            evt_dttm2 = evt_dttm4
            evt_dttm3 = evt_dttm5
            evt_dttm4 = cast(datetime, self._astral_event(date + ONE_DAY, "solar_noon"))
            evt_dttm5 = cast(
                datetime, self._astral_event(date + 2 * ONE_DAY, "solar_midnight")
            )

        # Didn't find one.
        return None

    def _update(self, cur_dttm: datetime) -> None:
        """Update state."""
        cur_elev = cast(float, self._astral_event(cur_dttm))
        self._attr_is_on = cur_elev > self._threshold
        self._attr_icon = ABOVE_ICON if self._attr_is_on else BELOW_ICON
        LOGGER.debug(
            "%s: above = %f, elevation = %f", self.name, self._threshold, cur_elev
        )

        nxt_dttm = self._get_nxt_dttm(cur_dttm)

        @callback
        def schedule_update(now: datetime) -> None:
            """Schedule state update."""
            self._unsub_update = None
            self.async_schedule_update_ha_state(True)

        if nxt_dttm:
            self._unsub_update = async_track_point_in_utc_time(
                self.hass, schedule_update, nxt_dttm
            )
            nxt_dttm = dt_util.as_local(nxt_dttm)
        else:
            if self.hass.state == CoreState.running:
                LOGGER.error(
                    "%s: Sun elevation never reaches %f at this location",
                    self.name,
                    self._threshold,
                )
        self._attr_extra_state_attributes = {ATTR_NEXT_CHANGE: nxt_dttm}


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up sensors."""
    loc_params = get_loc_params(config)
    namespace = config.get(CONF_ENTITY_NAMESPACE)
    sensors = []
    for cfg in config[CONF_MONITORED_CONDITIONS]:
        if CONF_ELEVATION in cfg:
            options = cfg[CONF_ELEVATION]
            sensors.append(
                Sun2ElevationSensor(
                    loc_params, namespace, options[CONF_NAME], options[CONF_ABOVE]
                )
            )
    # Don't force update now. Wait for first update until async_added_to_hass is called
    # when final name is determined.
    async_add_entities(sensors, True)
