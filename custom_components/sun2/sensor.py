"""Sun2 Sensor."""
from datetime import timedelta
import logging

from astral import AstralError
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    CONF_MONITORED_CONDITIONS, DEVICE_CLASS_TIMESTAMP,
    EVENT_CORE_CONFIG_UPDATE)
from homeassistant.core import callback
from homeassistant.util import dt as dt_util
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import (
    async_track_time_change, async_track_point_in_time)
from homeassistant.helpers.sun import get_astral_location

_LOGGER = logging.getLogger(__name__)
_SOLAR_DEPRESSIONS = ('astronomical', 'civil', 'nautical')
_ELEV_RND = 0.5
_ELEV_MAX_ERR = 0.02
_PEAK_MARGIN = timedelta(minutes=15)
_ONE_DAY = timedelta(days=1)


class Sun2Sensor(Entity):
    """Sun2 Sensor."""

    def __init__(self, hass, sensor_type, icon, default_solar_depression):
        """Initialize sensor."""
        if any(sol_dep in sensor_type for sol_dep in _SOLAR_DEPRESSIONS):
            self._solar_depression, self._event = sensor_type.rsplit('_', 1)
        else:
            self._solar_depression = default_solar_depression
            self._event = sensor_type
        self._icon = icon
        self._name = sensor_type.replace('_', ' ').title()
        self._loc = get_astral_location(hass)
        self._state = None
        self._yesterday = None
        self._today = None
        self._tomorrow = None

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
            'yesterday': self._yesterday,
            'today': self._today,
            'tomorrow': self._tomorrow,
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
        # Default behavior is to update every local midnight.
        # Override for sensor types that should update at a different time,
        # or that have a more dynamic update schedule (in which case override
        # with a method that does nothing and set up the update at the end of
        # an override of _update instead.)
        @callback
        def async_update_at_midnight(now):
            self.async_schedule_update_ha_state(True)
        async_track_time_change(self.hass, async_update_at_midnight, 0, 0, 0)

    async def async_added_to_hass(self):
        """Set up sensor and fixed updating."""
        @callback
        def async_update_location(event=None):
            self._loc = get_astral_location(self.hass)
            self.async_schedule_update_ha_state(True)
        self.hass.bus.async_listen(
            EVENT_CORE_CONFIG_UPDATE, async_update_location)
        self._setup_fixed_updating()

    def _get_astral_event(self, event, date_or_dt):
        try:
            self._loc.solar_depression = self._solar_depression
            return getattr(self._loc, event)(date_or_dt)
        except AstralError:
            return 'none'

    def _get_data(self, date_or_dt):
        return self._get_astral_event(self._event, date_or_dt)

    def _update(self):
        today = dt_util.now().date()
        self._yesterday = self._get_data(today-timedelta(days=1))
        self._state = self._today = self._get_data(today)
        self._tomorrow = self._get_data(today+timedelta(days=1))

    async def async_update(self):
        """Update state."""
        self._update()


class Sun2PointInTimeSensor(Sun2Sensor):
    """Sun2 Point in Time Sensor."""

    def __init__(self, hass, sensor_type, icon):
        """Initialize sensor."""
        super().__init__(hass, sensor_type, icon, 'civil')

    @property
    def device_class(self):
        """Return the class of this device."""
        return DEVICE_CLASS_TIMESTAMP

    def _update(self):
        super()._update()
        if self._state != 'none':
            self._state = self._state.isoformat()


def _hours_to_hms(hours):
    try:
        return str(timedelta(hours=hours)).split('.')[0]
    except TypeError:
        return None


class Sun2PeriodOfTimeSensor(Sun2Sensor):
    """Sun2 Period of Time Sensor."""

    def __init__(self, hass, sensor_type, icon):
        """Initialize sensor."""
        super().__init__(hass, sensor_type, icon, 0.833)

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return 'hr'

    def _device_state_attributes(self):
        data = super()._device_state_attributes()
        data.update({
            'yesterday_hms': _hours_to_hms(data['yesterday']),
            'today_hms': _hours_to_hms(data['today']),
            'tomorrow_hms': _hours_to_hms(data['tomorrow']),
        })
        return data

    def _get_data(self, date_or_dt):
        if 'daylight' in self._event:
            start = self._get_astral_event('dawn', date_or_dt)
            end = self._get_astral_event('dusk', date_or_dt)
        else:
            start = self._get_astral_event('dusk', date_or_dt)
            end = self._get_astral_event('dawn', date_or_dt + timedelta(days=1))
        if 'none' in (start, end):
            return None
        return (end - start).total_seconds()/3600

    def _update(self):
        super()._update()
        if self._state is not None:
            self._state = round(self._state, 3)


class Sun2MaxElevationSensor(Sun2Sensor):
    """Sun2 Max Elevation Sensor."""

    def __init__(self, hass, sensor_type, icon):
        """Initialize sensor."""
        super().__init__(hass, sensor_type, icon, 0)

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return '°'

    def _get_data(self, date_or_dt):
        solar_noon = self._get_astral_event('solar_noon', date_or_dt)
        return self._get_astral_event('solar_elevation', solar_noon)

    def _update(self):
        super()._update()
        if self._state is not None:
            self._state = round(self._state, 3)


def _nearest_multiple(x, multiple):
    return int(round(x / multiple)) * multiple


def _nearest_second(time):
    return time.replace(microsecond=0) + timedelta(seconds=
        0 if time.microsecond < 500000 else 1)


def _calc_nxt_time(time0, elev0, time1, elev1, trg_elev):
    return _nearest_second(
        time0 + (time1 - time0) * ((trg_elev - elev0) / (elev1 - elev0)))


class Sun2ElevationSensor(Sun2Sensor):
    """Sun2 Elevation Sensor."""

    def __init__(self, hass, sensor_type, icon):
        """Initialize sensor."""
        super().__init__(hass, sensor_type, icon, 0)
        self._event = 'solar_elevation'
        self._sol_noon = None
        self._sol_midn = None
        self._nxt_nxt_time = None
        self._prv_time = None
        self._prv_elev = None

    @property
    def device_state_attributes(self):
        """Return device specific state attributes."""
        return None

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return '°'

    def _setup_fixed_updating(self):
        pass

    def _get_nxt_time(self, time1, elev1, trg_elev, max_time):
        time0 = self._prv_time
        elev0 = self._prv_elev
        nxt_elev = trg_elev + 1.5 * _ELEV_MAX_ERR
        while abs(nxt_elev - trg_elev) >= _ELEV_MAX_ERR:
            if elev1 == elev0:
                return None
            nxt_time = _calc_nxt_time(time0, elev0, time1, elev1, trg_elev)
            if nxt_time in (time0, time1):
                break
            if nxt_time > max_time:
                return None
            nxt_elev = self._loc.solar_elevation(nxt_time)
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

    def _update(self):
        # Astral package ignores microseconds, so round to nearest second
        # before continuing.
        cur_time = _nearest_second(dt_util.now())
        cur_elev = self._loc.solar_elevation(cur_time)
        self._state = f'{cur_elev:0.1f}'
        _LOGGER.debug('Raw elevation = %f -> %s', cur_elev, self._state)

        # Find the next solar midnight AFTER the current time, and the solar
        # noon that precedes it. This only needs to be done once a day when we
        # reach or pass the previously determined solar midnight.
        if not self._sol_midn or cur_time >= self._sol_midn:
            date = cur_time.date()
            # solar_midnight() returns the solar midnight (which is when the
            # sun reaches its lowest point) nearest to the start of today. Note
            # that it may have occurred yesterday.
            self._sol_midn = self._loc.solar_midnight(date)
            if self._sol_midn > cur_time:
                self._sol_noon = self._loc.solar_noon(date - _ONE_DAY)
            else:
                self._sol_midn = self._loc.solar_midnight(date + _ONE_DAY)
                if self._sol_midn > cur_time:
                    self._sol_noon = self._loc.solar_noon(date)
                else:
                    self._sol_midn = self._loc.solar_midnight(
                        date + 2 * _ONE_DAY)
                    self._sol_noon = self._loc.solar_noon(date + _ONE_DAY)

        if self._nxt_nxt_time:
            # We hit the special case of being too near solar noon or solar
            # midnight.
            nxt_time = self._nxt_nxt_time
            self._nxt_nxt_time = None
        elif not self._prv_time:
            # We don't have a previous point yet, so figure out when next
            # update should be based on where we are relative to the next
            # solar noon or solar midnight.
            if self._sol_noon - _PEAK_MARGIN <= cur_time <= self._sol_noon:
                nxt_time = self._sol_noon
                self._nxt_nxt_time = self._sol_noon + _PEAK_MARGIN
            elif self._sol_midn - _PEAK_MARGIN <= cur_time <= self._sol_midn:
                nxt_time = self._sol_midn
                self._nxt_nxt_time = self._sol_midn + _PEAK_MARGIN
            else:
                nxt_time = cur_time + timedelta(minutes=4)
        else:
            # Extrapolate based on previous point and current point to find
            # next point. When we get too near the next peak (at solar noon or
            # solar midnight), the slope will be too shallow to extrapolate. In
            # this case just make the next point the peak, and the point after
            # it the same amount of time after the peak as we are now before
            # the peak.
            rnd_elev = _nearest_multiple(cur_elev, _ELEV_RND)
            if cur_time < self._sol_noon:
                nxt_time = self._get_nxt_time(
                    cur_time, cur_elev,
                    rnd_elev + _ELEV_RND, self._sol_noon - _PEAK_MARGIN)
                if not nxt_time:
                    nxt_time = self._sol_noon
                    self._nxt_nxt_time = self._sol_noon + (self._sol_noon
                                                           - cur_time)
            else:
                nxt_time = self._get_nxt_time(
                    cur_time, cur_elev,
                    rnd_elev - _ELEV_RND, self._sol_midn - _PEAK_MARGIN)
                if not nxt_time:
                    nxt_time = self._sol_midn
                    self._nxt_nxt_time = self._sol_midn + (self._sol_midn
                                                           - cur_time)

        self._prv_time = cur_time
        self._prv_elev = cur_elev

        @callback
        def async_update(now):
            self.async_schedule_update_ha_state(True)
        async_track_point_in_time(self.hass, async_update, nxt_time)


_SENSOR_TYPES = {
    # Points in time
    'solar_midnight': (Sun2PointInTimeSensor, 'mdi:weather-night'),
    'astronomical_dawn': (Sun2PointInTimeSensor, 'mdi:weather-sunset-up'),
    'nautical_dawn': (Sun2PointInTimeSensor, 'mdi:weather-sunset-up'),
    'dawn': (Sun2PointInTimeSensor, 'mdi:weather-sunset-up'),
    'sunrise': (Sun2PointInTimeSensor, 'mdi:weather-sunset-up'),
    'solar_noon': (Sun2PointInTimeSensor, 'mdi:weather-sunny'),
    'sunset': (Sun2PointInTimeSensor, 'mdi:weather-sunset-down'),
    'dusk': (Sun2PointInTimeSensor, 'mdi:weather-sunset-down'),
    'nautical_dusk': (Sun2PointInTimeSensor, 'mdi:weather-sunset-down'),
    'astronomical_dusk': (Sun2PointInTimeSensor, 'mdi:weather-sunset-down'),
    # Time periods
    'daylight': (Sun2PeriodOfTimeSensor, 'mdi:weather-sunny'),
    'civil_daylight': (Sun2PeriodOfTimeSensor, 'mdi:weather-sunny'),
    'nautical_daylight': (Sun2PeriodOfTimeSensor, 'mdi:weather-sunny'),
    'astronomical_daylight': (Sun2PeriodOfTimeSensor, 'mdi:weather-sunny'),
    'night': (Sun2PeriodOfTimeSensor, 'mdi:weather-night'),
    'civil_night': (Sun2PeriodOfTimeSensor, 'mdi:weather-night'),
    'nautical_night': (Sun2PeriodOfTimeSensor, 'mdi:weather-night'),
    'astronomical_night': (Sun2PeriodOfTimeSensor, 'mdi:weather-night'),
    # Max elevation
    'max_elevation': (Sun2MaxElevationSensor, 'mdi:weather-sunny'),
    # Elevation
    'elevation': (Sun2ElevationSensor, 'mdi:weather-sunny'),
}

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_MONITORED_CONDITIONS): vol.All(
        cv.ensure_list, [vol.In(_SENSOR_TYPES)]),
})


async def async_setup_platform(
        hass, config, async_add_entities, discovery_info=None):
    """Set up sensors."""
    async_add_entities([_SENSOR_TYPES[event][0](hass, event,
                                                _SENSOR_TYPES[event][1])
                        for event in config[CONF_MONITORED_CONDITIONS]], True)
