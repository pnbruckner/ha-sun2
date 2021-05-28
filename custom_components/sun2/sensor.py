"""Sun2 Sensor."""
from datetime import datetime, time, timedelta
import logging

import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    CONF_ELEVATION,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_MONITORED_CONDITIONS,
    CONF_TIME_ZONE,
    DEVICE_CLASS_TIMESTAMP,
)
from homeassistant.core import callback
from homeassistant.util import dt as dt_util
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import slugify

from .helpers import (
    async_init_astral_loc,
    astral_event,
    get_local_info,
    nearest_second,
    SIG_LOC_UPDATED,
)

_LOGGER = logging.getLogger(__name__)
_SOLAR_DEPRESSIONS = ("astronomical", "civil", "nautical")
_ELEV_RND = 0.5
_ELEV_MAX_ERR = 0.02
_DELTA = timedelta(minutes=5)
_ONE_DAY = timedelta(days=1)

ATTR_NEXT_CHANGE = "next_change"


def next_midnight(dt):
    return datetime.combine(dt.date() + _ONE_DAY, time(), dt.tzinfo)


class Sun2Sensor(Entity):
    """Sun2 Sensor."""

    def __init__(self, hass, sensor_type, icon, info, default_solar_depression=0):
        """Initialize sensor."""
        self.hass = hass
        if any(sol_dep in sensor_type for sol_dep in _SOLAR_DEPRESSIONS):
            self._solar_depression, self._event = sensor_type.rsplit("_", 1)
        else:
            self._solar_depression = default_solar_depression
            self._event = sensor_type
        self._icon = icon
        self._name = self._orig_name = sensor_type.replace("_", " ").title()
        self._state = None
        self._yesterday = None
        self._today = None
        self._tomorrow = None

        self._use_local_info = info is None
        if self._use_local_info:
            self._info = get_local_info(hass)
        else:
            self._info = info

        self._unsub_loc_updated = None
        self._unsub_update = None

    @property
    def _info(self):
        return self.__info

    @_info.setter
    def _info(self, info):
        self.__info = info
        self._tzinfo = dt_util.get_time_zone(info[2])
        async_init_astral_loc(self.hass, info)

    @property
    def should_poll(self):
        """Do not poll."""
        return False

    @property
    def name(self):
        """Return the name of the entity."""
        return self._name

    @property
    def state(self):
        """Return the state of the entity."""
        return self._state

    def _device_state_attributes(self):
        return {
            "yesterday": self._yesterday,
            "today": self._today,
            "tomorrow": self._tomorrow,
        }

    @property
    def device_state_attributes(self):
        """Return device specific state attributes."""
        return self._device_state_attributes()

    @property
    def icon(self):
        """Return the icon to use in the frontend."""
        return self._icon

    def _setup_fixed_updating(self):
        # Default behavior is to update every midnight.
        # Override for sensor types that should update at a different time,
        # or that have a more dynamic update schedule (in which case override
        # with a method that does nothing and set up the update at the end of
        # an override of _update instead.)

        @callback
        def async_update_at_midnight(now):
            next_midn = next_midnight(now.astimezone(self._tzinfo))
            self._unsub_update = async_track_point_in_utc_time(
                self.hass, async_update_at_midnight, next_midn
            )
            self.async_schedule_update_ha_state(True)

        next_midn = next_midnight(dt_util.now(self._tzinfo))
        self._unsub_update = async_track_point_in_utc_time(
            self.hass, async_update_at_midnight, next_midn
        )

    def _loc_updated(self):
        if self._unsub_update:
            self._unsub_update()
            self._unsub_update = None
        self._info = get_local_info(self.hass)
        self._setup_fixed_updating()
        self.async_schedule_update_ha_state(True)

    async def async_loc_updated(self):
        """Location updated."""
        self._loc_updated()

    async def async_added_to_hass(self):
        """Subscribe to update signal and set up fixed updating."""
        slug = slugify(self._orig_name)
        object_id = self.entity_id.split('.')[1]
        if slug != object_id and object_id.endswith(slug):
            prefix = object_id[:-len(slug)].replace("_", " ").strip().title()
            self._name = f"{prefix} {self._orig_name}"
        if self._use_local_info:
            self._unsub_loc_updated = async_dispatcher_connect(
                self.hass, SIG_LOC_UPDATED, self.async_loc_updated
            )
        self._setup_fixed_updating()

    async def async_will_remove_from_hass(self):
        """Disconnect from update signal and cancel fixed updating."""
        if self._unsub_loc_updated:
            self._unsub_loc_updated()
        if self._unsub_update:
            self._unsub_update()
        self._name = self._orig_name

    def _get_astral_event(self, event, date_or_dt):
        return astral_event(self._info, event, date_or_dt, self._solar_depression)

    def _get_data(self, date_or_dt):
        return self._get_astral_event(self._event, date_or_dt)

    def _update(self):
        today = dt_util.now(self._tzinfo).date()
        self._yesterday = self._get_data(today - _ONE_DAY)
        self._state = self._today = self._get_data(today)
        self._tomorrow = self._get_data(today + _ONE_DAY)

    async def async_update(self):
        """Update state."""
        self._update()


class Sun2PointInTimeSensor(Sun2Sensor):
    """Sun2 Point in Time Sensor."""

    def __init__(self, hass, sensor_type, icon, info):
        """Initialize sensor."""
        super().__init__(hass, sensor_type, icon, info, "civil")

    @property
    def device_class(self):
        """Return the class of this device."""
        return DEVICE_CLASS_TIMESTAMP

    def _update(self):
        super()._update()
        if self._state != "none":
            self._state = self._state.isoformat()


def _hours_to_hms(hours):
    try:
        return str(timedelta(hours=hours)).split(".")[0]
    except TypeError:
        return None


class Sun2PeriodOfTimeSensor(Sun2Sensor):
    """Sun2 Period of Time Sensor."""

    def __init__(self, hass, sensor_type, icon, info):
        """Initialize sensor."""
        super().__init__(hass, sensor_type, icon, info, 0.833)

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return "hr"

    def _device_state_attributes(self):
        data = super()._device_state_attributes()
        data.update(
            {
                "yesterday_hms": _hours_to_hms(data["yesterday"]),
                "today_hms": _hours_to_hms(data["today"]),
                "tomorrow_hms": _hours_to_hms(data["tomorrow"]),
            }
        )
        return data

    def _get_data(self, date_or_dt):
        if "daylight" in self._event:
            start = self._get_astral_event("dawn", date_or_dt)
            end = self._get_astral_event("dusk", date_or_dt)
        else:
            start = self._get_astral_event("dusk", date_or_dt)
            end = self._get_astral_event("dawn", date_or_dt + _ONE_DAY)
        if "none" in (start, end):
            return None
        return (end - start).total_seconds() / 3600

    def _update(self):
        super()._update()
        if self._state is not None:
            self._state = round(self._state, 3)


class Sun2MinMaxElevationSensor(Sun2Sensor):
    """Sun2 Min/Max Elevation Sensor."""

    def __init__(self, hass, sensor_type, icon, info, is_min):
        """Initialize sensor."""
        super().__init__(hass, sensor_type, icon, info)
        self._event = "solar_midnight" if is_min else "solar_noon"

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return "°"

    def _get_data(self, date_or_dt):
        event_time = self._get_astral_event(self._event, date_or_dt)
        return self._get_astral_event("solar_elevation", event_time)

    def _update(self):
        super()._update()
        if self._state is not None:
            self._state = round(self._state, 3)


class Sun2MinElevationSensor(Sun2MinMaxElevationSensor):
    """Sun2 Min Elevation Sensor."""

    def __init__(self, hass, sensor_type, icon, info):
        """Initialize sensor."""
        super().__init__(hass, sensor_type, icon, info, is_min=True)


class Sun2MaxElevationSensor(Sun2MinMaxElevationSensor):
    """Sun2 Max Elevation Sensor."""

    def __init__(self, hass, sensor_type, icon, info):
        """Initialize sensor."""
        super().__init__(hass, sensor_type, icon, info, is_min=False)


def _nearest_multiple(value, multiple):
    return int(round(value / multiple)) * multiple


def _calc_nxt_time(time0, elev0, time1, elev1, trg_elev):
    return nearest_second(
        time0 + (time1 - time0) * ((trg_elev - elev0) / (elev1 - elev0))
    )


class Sun2ElevationSensor(Sun2Sensor):
    """Sun2 Elevation Sensor."""

    def __init__(self, hass, sensor_type, icon, info):
        """Initialize sensor."""
        super().__init__(hass, sensor_type, icon, info)
        self._reset()

    def _reset(self):
        self._prv_sol_midn = None
        self._sol_noon = None
        self._sol_midn = None
        self._prv_time = None
        self._prv_elev = None
        self._next_change = None

    @property
    def device_state_attributes(self):
        """Return device specific state attributes."""
        return {ATTR_NEXT_CHANGE: self._next_change}

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return "°"

    def _loc_updated(self):
        """Location updated."""
        self._reset()
        super()._loc_updated()

    def _setup_fixed_updating(self):
        pass

    def _get_nxt_time(self, time1, elev1, trg_elev, min_time, max_time):
        if self._prv_time < min_time:
            return None
        time0 = self._prv_time
        elev0 = self._prv_elev
        nxt_elev = trg_elev + 1.5 * _ELEV_MAX_ERR
        while abs(nxt_elev - trg_elev) >= _ELEV_MAX_ERR:
            try:
                nxt_time = _calc_nxt_time(time0, elev0, time1, elev1, trg_elev)
            except ZeroDivisionError:
                return None
            if nxt_time < min_time or nxt_time > max_time:
                return None
            if nxt_time in (time0, time1):
                break
            nxt_elev = astral_event(self._info, "solar_elevation", nxt_time)
            if nxt_time > time1:
                time0 = time1
                elev0 = elev1
                time1 = nxt_time
                elev1 = nxt_elev
            elif elev0 < trg_elev < nxt_elev or elev0 > trg_elev > nxt_elev:
                time1 = nxt_time
                elev1 = nxt_elev
            else:
                time0 = nxt_time
                elev0 = nxt_elev
        return nxt_time

    def _set_nxt_time(self, cur_time):
        if self._sol_noon - _DELTA <= cur_time < self._sol_noon:
            return self._sol_noon
        elif self._sol_midn - _DELTA <= cur_time:
            return self._sol_midn
        else:
            return cur_time + _DELTA

    def _update(self):
        # Astral package ignores microseconds, so round to nearest second
        # before continuing.
        cur_time = nearest_second(dt_util.now(self._tzinfo))
        cur_elev = astral_event(self._info, "solar_elevation", cur_time)
        self._state = f"{cur_elev:0.1f}"
        _LOGGER.debug("Raw elevation = %f -> %s", cur_elev, self._state)

        # Find the next solar midnight AFTER the current time, and the solar noon and
        # solar midnight that precede it. This only needs to be done once a day when we
        # reach or pass the previously determined solar midnight.
        if not self._sol_midn or cur_time >= self._sol_midn:
            date = cur_time.date()
            # solar_midnight() returns the solar midnight (which is when the
            # sun reaches its lowest point) nearest to the start of today. Note
            # that it may have occurred yesterday.
            self._sol_midn = astral_event(self._info, "solar_midnight", date)
            while self._sol_midn <= cur_time:
                date += _ONE_DAY
                self._sol_midn = astral_event(self._info, "solar_midnight", date)
            self._sol_noon = astral_event(self._info, "solar_noon", date - _ONE_DAY)
            self._prv_sol_midn = astral_event(
                self._info, "solar_midnight", date - _ONE_DAY
            )
            _LOGGER.debug(
                "Solar midnight/noon/midnight: %s/%0.2f, %s/%0.2f, %s/%0.2f",
                self._prv_sol_midn,
                astral_event(self._info, "solar_elevation", self._prv_sol_midn),
                self._sol_noon,
                astral_event(self._info, "solar_elevation", self._sol_noon),
                self._sol_midn,
                astral_event(self._info, "solar_elevation", self._sol_midn),
            )

        if self._prv_time:
            # Extrapolate based on previous point and current point to find
            # next point.
            rnd_elev = _nearest_multiple(cur_elev, _ELEV_RND)
            if cur_time < self._sol_noon:
                nxt_time = self._get_nxt_time(
                    cur_time,
                    cur_elev,
                    rnd_elev + _ELEV_RND,
                    self._prv_sol_midn,
                    self._sol_noon,
                )
            else:
                nxt_time = self._get_nxt_time(
                    cur_time,
                    cur_elev,
                    rnd_elev - _ELEV_RND,
                    self._sol_noon,
                    self._sol_midn,
                )
        else:
            nxt_time = None

        if not nxt_time:
            nxt_time = self._set_nxt_time(cur_time)

        self._prv_time = cur_time
        self._prv_elev = cur_elev

        self._next_change = dt_util.as_local(nxt_time)

        @callback
        def async_update(now):
            self._unsub_update = None
            self.async_schedule_update_ha_state(True)

        self._unsub_update = async_track_point_in_utc_time(
            self.hass, async_update, nxt_time
        )


_SENSOR_TYPES = {
    # Points in time
    "solar_midnight": (Sun2PointInTimeSensor, "mdi:weather-night"),
    "astronomical_dawn": (Sun2PointInTimeSensor, "mdi:weather-sunset-up"),
    "nautical_dawn": (Sun2PointInTimeSensor, "mdi:weather-sunset-up"),
    "dawn": (Sun2PointInTimeSensor, "mdi:weather-sunset-up"),
    "sunrise": (Sun2PointInTimeSensor, "mdi:weather-sunset-up"),
    "solar_noon": (Sun2PointInTimeSensor, "mdi:weather-sunny"),
    "sunset": (Sun2PointInTimeSensor, "mdi:weather-sunset-down"),
    "dusk": (Sun2PointInTimeSensor, "mdi:weather-sunset-down"),
    "nautical_dusk": (Sun2PointInTimeSensor, "mdi:weather-sunset-down"),
    "astronomical_dusk": (Sun2PointInTimeSensor, "mdi:weather-sunset-down"),
    # Time periods
    "daylight": (Sun2PeriodOfTimeSensor, "mdi:weather-sunny"),
    "civil_daylight": (Sun2PeriodOfTimeSensor, "mdi:weather-sunny"),
    "nautical_daylight": (Sun2PeriodOfTimeSensor, "mdi:weather-sunny"),
    "astronomical_daylight": (Sun2PeriodOfTimeSensor, "mdi:weather-sunny"),
    "night": (Sun2PeriodOfTimeSensor, "mdi:weather-night"),
    "civil_night": (Sun2PeriodOfTimeSensor, "mdi:weather-night"),
    "nautical_night": (Sun2PeriodOfTimeSensor, "mdi:weather-night"),
    "astronomical_night": (Sun2PeriodOfTimeSensor, "mdi:weather-night"),
    # Min/Max elevation
    "min_elevation": (Sun2MinElevationSensor, "mdi:weather-night"),
    "max_elevation": (Sun2MaxElevationSensor, "mdi:weather-sunny"),
    # Elevation
    "elevation": (Sun2ElevationSensor, "mdi:weather-sunny"),
}

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_MONITORED_CONDITIONS): vol.All(
            cv.ensure_list, [vol.In(_SENSOR_TYPES)]
        ),
        vol.Inclusive(CONF_LATITUDE, "location"): cv.latitude,
        vol.Inclusive(CONF_LONGITUDE, "location"): cv.longitude,
        vol.Inclusive(CONF_TIME_ZONE, "location"): cv.time_zone,
        vol.Inclusive(CONF_ELEVATION, "location"): vol.Coerce(float),
    }
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
    async_add_entities(
        [
            _SENSOR_TYPES[event][0](hass, event, _SENSOR_TYPES[event][1], info)
            for event in config[CONF_MONITORED_CONDITIONS]
        ],
        True,
    )
