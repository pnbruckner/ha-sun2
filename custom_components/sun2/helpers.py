"""Sun2 Helpers."""
from datetime import timedelta

from homeassistant.const import EVENT_CORE_CONFIG_UPDATE
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import dispatcher_send
from homeassistant.helpers.sun import get_astral_location

SIG_LOC_UPDATED = 'sun2_loc_updated'

_LOC = None
_HASS = None


def _update_location(event):
    global _LOC
    _LOC = get_astral_location(_HASS)
    dispatcher_send(_HASS, SIG_LOC_UPDATED)


@callback
def async_init_astral_loc(hass):
    """Initialize astral Location."""
    global _LOC, _HASS
    if not _LOC:
        _HASS = hass
        _LOC = get_astral_location(hass)
        hass.bus.async_listen(EVENT_CORE_CONFIG_UPDATE, _update_location)


def astral_loc():
    """Return astral Location."""
    return _LOC


def nearest_second(time):
    """Round time to nearest second."""
    return (time.replace(microsecond=0) +
            timedelta(seconds=0 if time.microsecond < 500000 else 1))
