"""Sun2 Binary Sensor."""
from datetime import timedelta
import logging

import voluptuous as vol

try:
    from homeassistant.components.binary_sensor import BinarySensorEntity
except ImportError:
    from homeassistant.components.binary_sensor import BinarySensorDevice

    BinarySensorEntity = BinarySensorDevice
from homeassistant.components.binary_sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    CONF_ABOVE,
    CONF_ELEVATION,
    CONF_ENTITY_NAMESPACE,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_MONITORED_CONDITIONS,
    CONF_NAME,
    CONF_TIME_ZONE,
)
from homeassistant.core import callback, CoreState
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .helpers import (
    ATTR_NEXT_CHANGE,
    astral_event,
    nearest_second,
)
from .sun2_sensor import Sun2SensorBase

_LOGGER = logging.getLogger(__name__)

DEFAULT_ELEVATION_ABOVE = -0.833
DEFAULT_ELEVATION_NAME = "Above Horizon"

ABOVE_ICON = "mdi:white-balance-sunny"
BELOW_ICON = "mdi:moon-waxing-crescent"

_ONE_DAY = timedelta(days=1)
_ONE_SEC = timedelta(seconds=1)

_SENSOR_TYPES = [CONF_ELEVATION]


# elevation
# elevation: <threshold>
# elevation:
#   above: <threshold>
#   name: <friendly_name>


def _val_cfg(config):
    if isinstance(config, str):
        config = {config: {}}
    else:
        if CONF_ELEVATION in config:
            value = config[CONF_ELEVATION]
            if isinstance(value, float):
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
        vol.Inclusive(CONF_LATITUDE, "location"): cv.latitude,
        vol.Inclusive(CONF_LONGITUDE, "location"): cv.longitude,
        vol.Inclusive(CONF_TIME_ZONE, "location"): cv.time_zone,
        vol.Inclusive(CONF_ELEVATION, "location"): vol.Coerce(float),
    }
)


class Sun2ElevationSensor(Sun2SensorBase, BinarySensorEntity):
    """Sun2 Elevation Sensor."""

    def __init__(self, hass, ns, name, above, info):
        """Initialize sensor."""
        if ns:
            self._attr_unique_id = f"{ns} {name}"
        else:
            self._attr_unique_id = name
        super().__init__(hass, name, info)

        self._threshold = above
        self._next_change = None

    def _device_state_attributes(self):
        return {ATTR_NEXT_CHANGE: self._next_change}

    @property
    def icon(self):
        """Return the icon to use in the frontend."""
        return ABOVE_ICON if self.is_on else BELOW_ICON

    @property
    def is_on(self):
        """Return true if the binary sensor is on."""
        return self._state

    def _find_nxt_dttm(self, t0_dttm, t0_elev, t1_dttm, t1_elev):
        # Do a binary search for time between t0 & t1 where elevation is
        # nearest threshold, but also above (or equal to) it if current
        # elevation is below it (i.e., current state is False), or below it if
        # current elevation is above (or equal to) it (i.e., current state is
        # True.)

        slope = 1 if t1_elev > t0_elev else -1

        # Find mid point and throw away fractional seconds since astral package
        # ignores microseconds.
        tn_dttm = nearest_second(t0_dttm + (t1_dttm - t0_dttm) / 2)
        tn_elev = astral_event(self._info, "solar_elevation", tn_dttm)

        while not (
            (
                self._state
                and tn_elev <= self._threshold
                or not self._state
                and tn_elev > self._threshold
            )
            and abs(tn_elev - self._threshold) <= 0.01
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
            tn_elev = astral_event(self._info, "solar_elevation", tn_dttm)

        # Did we go too far?
        if self._state and tn_elev > self._threshold:
            tn_dttm -= slope * _ONE_SEC
            if astral_event(self._info, "solar_elevation", tn_dttm) > self._threshold:
                raise RuntimeError("Couldn't find next update time")
        elif not self._state and tn_elev <= self._threshold:
            tn_dttm += slope * _ONE_SEC
            if astral_event(self._info, "solar_elevation", tn_dttm) <= self._threshold:
                raise RuntimeError("Couldn't find next update time")

        return tn_dttm

    def _get_nxt_dttm(self, cur_dttm):
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
        evt_dttm1 = astral_event(self._info, "solar_midnight", date)
        evt_dttm2 = astral_event(self._info, "solar_noon", date)
        evt_dttm3 = astral_event(self._info, "solar_midnight", date + _ONE_DAY)
        evt_dttm4 = astral_event(self._info, "solar_noon", date + _ONE_DAY)
        evt_dttm5 = astral_event(self._info, "solar_midnight", date + 2 * _ONE_DAY)

        # See if segment we're looking for falls between any of these events.
        # If not move ahead a day and try again, but don't look more than a
        # a year ahead.
        end_date = date + 366 * _ONE_DAY
        while date < end_date:
            if cur_dttm < evt_dttm1:
                if self._state:
                    t0_dttm = cur_dttm
                    t1_dttm = evt_dttm1
                else:
                    t0_dttm = evt_dttm1
                    t1_dttm = evt_dttm2
            elif cur_dttm < evt_dttm2:
                if not self._state:
                    t0_dttm = cur_dttm
                    t1_dttm = evt_dttm2
                else:
                    t0_dttm = evt_dttm2
                    t1_dttm = evt_dttm3
            elif cur_dttm < evt_dttm3:
                if self._state:
                    t0_dttm = cur_dttm
                    t1_dttm = evt_dttm3
                else:
                    t0_dttm = evt_dttm3
                    t1_dttm = evt_dttm4
            else:
                if not self._state:
                    t0_dttm = cur_dttm
                    t1_dttm = evt_dttm4
                else:
                    t0_dttm = evt_dttm4
                    t1_dttm = evt_dttm5

            t0_elev = astral_event(self._info, "solar_elevation", t0_dttm)
            t1_elev = astral_event(self._info, "solar_elevation", t1_dttm)

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
                if nxt_dttm - cur_dttm > _ONE_DAY:
                    if self.hass.state == CoreState.running:
                        _LOGGER.warning(
                            "%s: Sun elevation will not reach %f again until %s",
                            self.name,
                            self._threshold,
                            nxt_dttm.date(),
                        )
                return nxt_dttm

            # Shift one day ahead.
            date += _ONE_DAY
            evt_dttm1 = evt_dttm3
            evt_dttm2 = evt_dttm4
            evt_dttm3 = evt_dttm5
            evt_dttm4 = astral_event(self._info, "solar_noon", date + _ONE_DAY)
            evt_dttm5 = astral_event(self._info, "solar_midnight", date + 2 * _ONE_DAY)

        # Didn't find one.
        return None

    async def async_update(self):
        """Update state."""
        cur_dttm = dt_util.now(self._tzinfo)
        cur_elev = astral_event(self._info, "solar_elevation", cur_dttm)
        self._state = cur_elev > self._threshold
        _LOGGER.debug(
            "%s: above = %f, elevation = %f", self.name, self._threshold, cur_elev
        )

        nxt_dttm = self._get_nxt_dttm(cur_dttm)

        @callback
        def async_schedule_update(now):
            self._unsub_update = None
            self.async_schedule_update_ha_state(True)

        if nxt_dttm:
            self._next_change = dt_util.as_local(nxt_dttm)
            self._unsub_update = async_track_point_in_utc_time(
                self.hass, async_schedule_update, nxt_dttm
            )
        else:
            self._next_change = None
            if self.hass.state == CoreState.running:
                _LOGGER.error(
                    "%s: Sun elevation never reaches %f at this location",
                    self.name,
                    self._threshold,
                )


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up sensors."""
    if CONF_LATITUDE in config:
        info = (
            config[CONF_LATITUDE],
            config[CONF_LONGITUDE],
            config[CONF_TIME_ZONE],
            config[CONF_ELEVATION],
        )
    else:
        info = None
    sensors = []
    ns = config.get(CONF_ENTITY_NAMESPACE)
    for cfg in config[CONF_MONITORED_CONDITIONS]:
        if CONF_ELEVATION in cfg:
            options = cfg[CONF_ELEVATION]
            sensors.append(
                Sun2ElevationSensor(hass, ns, options[CONF_NAME], options[CONF_ABOVE], info)
            )
    # Don't force update now. Wait for first update until async_added_to_hass is called
    # when final name is determined.
    async_add_entities(sensors, False)
