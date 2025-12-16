"""Constants for Sun2 integration."""
from datetime import timedelta
import logging

DOMAIN = "sun2"

ELEV_STEP = 0.5
SUNSET_ELEV = -0.267

MAX_UPDATE_TIME = timedelta(milliseconds=50)

ONE_DAY = timedelta(days=1)

LOGGER = logging.getLogger(__package__)

CONF_ABOVE_GROUND = "above_ground"
CONF_DIRECTION = "direction"
CONF_DISTANCE = "distance"
CONF_ELEVATION_AT_TIME = "elevation_at_time"
CONF_LOCATION_TEXT = "location_text"
CONF_OBS_ELV = "observer_elevation"
CONF_RELATIVE_HEIGHT = "relative_height"
CONF_SUNRISE_OBSTRUCTION = "sunrise_obstruction"
CONF_SUNSET_OBSTRUCTION = "sunset_obstruction"
CONF_TIME_AT_ELEVATION = "time_at_elevation"

ATTR_BLUE_HOUR = "blue_hour"
ATTR_DAYLIGHT = "daylight"
ATTR_GOLDEN_HOUR = "golden_hour"
ATTR_NEXT_CHANGE = "next_change"
ATTR_RISING = "rising"
ATTR_TODAY = "today"
ATTR_TODAY_HMS = "today_hms"
ATTR_TOMORROW = "tomorrow"
ATTR_TOMORROW_HMS = "tomorrow_hms"
ATTR_YESTERDAY = "yesterday"
ATTR_YESTERDAY_HMS = "yesterday_hms"

ICON_ABOVE = "mdi:white-balance-sunny"
ICON_AZIMUTH = "mdi:sun-angle"
ICON_BELOW = "mdi:moon-waxing-crescent"
ICON_DAY = "mdi:weather-sunny"
ICON_NIGHT = "mdi:weather-night"
ICON_RISING = "mdi:weather-sunset-up"
ICON_SETTING = "mdi:weather-sunset-down"

SIG_HA_LOC_UPDATED = f"{DOMAIN}_ha_loc_updated"
SIG_ASTRAL_DATA_UPDATED = f"{DOMAIN}_astral_data_updated-{{}}"

STATE_ASTRO_TW = "astronomical_twilight"
STATE_CIVIL_TW = "civil_twilight"
STATE_DAY = "day"
STATE_DAWN = "dawn"
STATE_DUSK = "dusk"
STATE_G_HR_1 = "golden_hour_1"
STATE_G_HR_2 = "golden_hour_2"
STATE_NADIR = "nadir"
STATE_NAUT_DAWN = "nautical_dawn"
STATE_NAUT_DUSK = "nautical_dusk"
STATE_NAUT_TW = "nautical_twilight"
STATE_NIGHT = "night"
STATE_NIGHT_END = "night_end"
STATE_NIGHT_START = "night_start"
STATE_RIS_END = "sunrise_end"
STATE_RIS_START = "sunrise_start"
STATE_SET_END = "sunset_end"
STATE_SET_START = "sunset_start"
STATE_SOL_NOON = "solar_noon"
