"""Sun2 Sensor."""
from datetime import timedelta

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
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.sun import get_astral_location

_SOLAR_DEPRESSIONS = ('astronomical', 'civil', 'nautical')


class Sun2Sensor(Entity):
    """Sun2 Sensor."""

    def __init__(self, sensor_type, icon, default_solar_depression):
        """Initialize sensor."""
        if any(sol_dep in sensor_type for sol_dep in _SOLAR_DEPRESSIONS):
            self._solar_depression, self._event = sensor_type.rsplit('_', 1)
        else:
            self._solar_depression = default_solar_depression
            self._event = sensor_type
        self._icon = icon
        self._name = sensor_type.replace('_', ' ').title()
        self._location = None
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
            self._location = get_astral_location(self.hass)
            self.async_schedule_update_ha_state(True)
        self.hass.bus.async_listen(
            EVENT_CORE_CONFIG_UPDATE, async_update_location)
        self._setup_fixed_updating()
        async_update_location()

    def _get_astral_event(self, event, date_or_dt):
        try:
            self._location.solar_depression = self._solar_depression
            return getattr(self._location, event)(date_or_dt)
        except AstralError:
            return 'none'

    def _get_data(self, date):
        return self._get_astral_event(self._event, date)

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

    def __init__(self, sensor_type, icon):
        """Initialize sensor."""
        super().__init__(sensor_type, icon, 'civil')

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

    def __init__(self, sensor_type, icon):
        """Initialize sensor."""
        super().__init__(sensor_type, icon, 0.833)

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

    def _get_data(self, date):
        if 'daylight' in self._event:
            start = self._get_astral_event('dawn', date)
            end = self._get_astral_event('dusk', date)
        else:
            start = self._get_astral_event('dusk', date)
            end = self._get_astral_event('dawn', date + timedelta(days=1))
        if 'none' in (start, end):
            return None
        return (end - start).total_seconds()/3600

    def _update(self):
        super()._update()
        if self._state is not None:
            self._state = round(self._state, 3)


class Sun2MaxElevationSensor(Sun2Sensor):
    """Sun2 Max Elevation Sensor."""

    def __init__(self, sensor_type, icon):
        """Initialize sensor."""
        super().__init__(sensor_type, icon, 0)

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return '°'

    def _get_data(self, date):
        solar_noon = self._get_astral_event('solar_noon', date)
        return self._get_astral_event('solar_elevation', solar_noon)

    def _update(self):
        super()._update()
        if self._state is not None:
            self._state = round(self._state, 3)


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
}

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_MONITORED_CONDITIONS): vol.All(
        cv.ensure_list, [vol.In(_SENSOR_TYPES)]),
})


async def async_setup_platform(
        hass, config, async_add_entities, discovery_info=None):
    """Set up sensors."""
    async_add_entities([_SENSOR_TYPES[event][0](event, _SENSOR_TYPES[event][1])
                        for event in config[CONF_MONITORED_CONDITIONS]])
