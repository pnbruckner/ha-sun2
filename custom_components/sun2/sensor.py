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


class Sun2Sensor(Entity):
    """Sun2 Sensor."""

    def __init__(self, event, icon):
        """Initialize sensor."""
        self._event = event
        self._icon = icon
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
        return self._event.replace('_', ' ').title()

    @property
    def state(self):
        """Return the state of the entity."""
        return self._state

    @property
    def device_state_attributes(self):
        """Return device specific state attributes."""
        return {
            'yesterday': self._yesterday,
            'today': self._today,
            'tomorrow': self._tomorrow,
        }

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

    def _get_astral_event(self, date):
        try:
            self._location.solar_depression = 'civil'
            return getattr(self._location, self._event)(date)
        except AstralError:
            return None

    def _update(self):
        today = dt_util.now().date()
        self._yesterday = self._get_astral_event(today-timedelta(days=1))
        self._state = self._today = self._get_astral_event(today)
        self._tomorrow = self._get_astral_event(today+timedelta(days=1))

    async def async_update(self):
        """Update state."""
        self._update()


class Sun2Datetime(Sun2Sensor):
    """Sun2 datetime Sensor."""

    @property
    def device_class(self):
        """Return the class of this device."""
        return DEVICE_CLASS_TIMESTAMP

    def _update(self):
        super()._update()
        if self._state is not None:
            self._state = self._state.isoformat()


class Sun2Hours(Sun2Sensor):
    """Sun2 Hours Sensor."""

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return 'hr'

    def _get_astral_event(self, date):
        result = super()._get_astral_event(date)
        if result is None:
            return None
        start, end = result
        return (end - start).total_seconds()/3600

    def _update(self):
        super()._update()
        if self._state is not None:
            self._state = round(self._state, 3)


_SENSOR_TYPES = {
    'dawn': (Sun2Datetime, 'mdi:weather-sunset-up'),
    'daylight': (Sun2Hours, 'mdi:weather-sunny'),
    'dusk': (Sun2Datetime, 'mdi:weather-sunset-down'),
    'night': (Sun2Hours, 'mdi:weather-night'),
    'solar_noon': (Sun2Datetime, 'mdi:weather-sunny'),
    'sunrise': (Sun2Datetime, 'mdi:weather-sunset-up'),
    'sunset': (Sun2Datetime, 'mdi:weather-sunset-down'),
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
