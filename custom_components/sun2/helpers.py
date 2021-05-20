"""Sun2 Helpers."""
from datetime import timedelta

try:
    from astral import AstralError
except ImportError:
    AstralError = (TypeError, ValueError)
from homeassistant.const import EVENT_CORE_CONFIG_UPDATE
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import dispatcher_send

SIG_LOC_UPDATED = "sun2_loc_updated"

_HASS = None
_LOC_ELEV = {}


def get_local_info(hass):
    """Get HA's local location config."""
    latitude = hass.config.latitude
    longitude = hass.config.longitude
    timezone = str(hass.config.time_zone)
    elevation = hass.config.elevation
    return latitude, longitude, timezone, elevation


def _get_astral_location(info):
    try:
        from astral import LocationInfo
        from astral.location import Location

        latitude, longitude, timezone, elevation = info
        info = ("", "", timezone, latitude, longitude)
        return Location(LocationInfo(*info)), elevation
    except ImportError:
        from astral import Location

        info = ("", "", *info)
        return Location(info), None


def _update_location(event):
    dispatcher_send(_HASS, SIG_LOC_UPDATED)


# info = (latitude, longitude, timezone, elevation)
# info == None -> Use HA location config
@callback
def async_init_astral_loc(hass, info):
    """Initialize astral Location."""
    global _HASS
    if not _HASS:
        _HASS = hass
        hass.bus.async_listen(EVENT_CORE_CONFIG_UPDATE, _update_location)
    if info not in _LOC_ELEV:
        _LOC_ELEV[info] = _get_astral_location(info)


def astral_event(info, event, date_or_dt, depression=None):
    """Return astral event result."""
    loc, elev = _LOC_ELEV[info]
    if depression is not None:
        loc.solar_depression = depression
    try:
        if elev is not None:
            if event in ("solar_midnight", "solar_noon"):
                return getattr(loc, event.split("_")[1])(date_or_dt)
            else:
                return getattr(loc, event)(date_or_dt, observer_elevation=elev)
        return getattr(loc, event)(date_or_dt)
    except AstralError:
        return "none"


def nearest_second(time):
    """Round time to nearest second."""
    return time.replace(microsecond=0) + timedelta(
        seconds=0 if time.microsecond < 500000 else 1
    )
