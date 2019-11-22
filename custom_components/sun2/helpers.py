"""Sun2 Helpers."""
from homeassistant.const import EVENT_CORE_CONFIG_UPDATE
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import dispatcher_send
from homeassistant.helpers.sun import get_astral_location

SIG_LOC_UPDATED = 'sun2_loc_updated'

loc = None

_hass = None

def _update_location(event=None):
    global loc
    loc = get_astral_location(_hass)
    dispatcher_send(_hass, SIG_LOC_UPDATED)

@callback
def async_init_astral_loc(hass):
    global loc, _hass
    if not loc:
        _hass = hass
        loc = get_astral_location(hass)
        hass.bus.async_listen(EVENT_CORE_CONFIG_UPDATE, _update_location)
