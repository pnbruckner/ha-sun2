"""Sun2 Helpers."""
from datetime import timedelta

try:
    from astral import AstralError
except ImportError:
    AstralError = TypeError
from homeassistant.const import EVENT_CORE_CONFIG_UPDATE
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import dispatcher_send
from homeassistant.helpers.sun import get_astral_location

SIG_LOC_UPDATED = 'sun2_loc_updated'

_LOC = None
_ELEV = None
_HASS = None

def _get_astral_location():
    global _LOC, _ELEV
    try:
        _LOC, _ELEV = get_astral_location(_HASS)
    except TypeError:
        _LOC = get_astral_location(_HASS)


def _update_location(event):
    _get_astral_location()
    dispatcher_send(_HASS, SIG_LOC_UPDATED)


@callback
def async_init_astral_loc(hass):
    """Initialize astral Location."""
    global _HASS
    if not _LOC:
        _HASS = hass
        _get_astral_location()
        hass.bus.async_listen(EVENT_CORE_CONFIG_UPDATE, _update_location)


def astral_event(event, date_or_dt, depression=None):
    """Return astral event result."""
    if depression is not None:
        _LOC.solar_depression = depression
    try:
        if _ELEV is not None:
            if event in ('solar_midnight', 'solar_noon'):
                return getattr(_LOC, event.replace('solar_', ''))(date_or_dt)
            else:
                return getattr(_LOC, event)(date_or_dt, observer_elevation=_ELEV)
        return getattr(_LOC, event)(date_or_dt)
    except AstralError:
        return 'none'


def nearest_second(time):
    """Round time to nearest second."""
    return (time.replace(microsecond=0) +
            timedelta(seconds=0 if time.microsecond < 500000 else 1))
