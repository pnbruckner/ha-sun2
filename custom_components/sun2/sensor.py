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

DOMAIN = 'sun2'

_DT_TYPES = {
    'dawn': 'mdi:weather-sunset-up',
    'dusk': 'mdi:weather-sunset-down',
    'solar_noon': 'mdi:weather-sunny',
    'sunrise': 'mdi:weather-sunset-up',
    'sunset': 'mdi:weather-sunset-down',
}

_TD_TYPES = {
    'daylight': 'mdi:weather-sunny',
    'night': 'mdi:weather-night',
}

_SENSOR_TYPES = list(_DT_TYPES) + list(_TD_TYPES)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_MONITORED_CONDITIONS): vol.All(
        cv.ensure_list, [vol.In(_SENSOR_TYPES)]),
})


async def async_setup_platform(
        hass, config, async_add_entities, discovery_info=None):
    """Set up sensors."""
    async_add_entities([Sun2Sensor(event)
                        for event in config[CONF_MONITORED_CONDITIONS]])


class Sun2Sensor(Entity):
    """Sun2 Sensor."""

    def __init__(self, event):
        """Initialize sensor."""
        self._event = event
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
    def device_class(self):
        """Return the class of this device."""
        if self._event in _DT_TYPES:
            return DEVICE_CLASS_TIMESTAMP
        return None

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        if self._event in _TD_TYPES:
            return 'hr'
        return None

    @property
    def icon(self):
        """Return the icon to use in the frontend."""
        return _DT_TYPES.get(self._event, _TD_TYPES.get(self._event))

    async def async_added_to_hass(self):
        """Set up sensor."""
        @callback
        def async_update_location(event=None):
            self._location = get_astral_location(self.hass)
            self.async_schedule_update_ha_state(True)
        self.hass.bus.async_listen(
            EVENT_CORE_CONFIG_UPDATE, async_update_location)

        @callback
        def async_update_at_midnight(now):
            self.async_schedule_update_ha_state(True)
        async_track_time_change(self.hass, async_update_at_midnight, 0, 0, 0)

        async_update_location()

    def _get_astral_event(self, date):
        try:
            if self._event in _DT_TYPES:
                return getattr(self._location, self._event)(date)
            start, end = getattr(self._location, self._event)(date)
            return (end - start).total_seconds()/3600
        except AstralError:
            return 'none'

    async def async_update(self):
        """Update state."""
        today = dt_util.now().date()
        self._yesterday = self._get_astral_event(today-timedelta(days=1))
        self._today = self._get_astral_event(today)
        self._tomorrow = self._get_astral_event(today+timedelta(days=1))
        if self._event in _DT_TYPES:
            self._state = self._today.isoformat()
        else:
            self._state = round(self._today, 3)
