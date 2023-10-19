"""Constants for Sun2 integration."""
from datetime import timedelta
import logging

DOMAIN = "sun2"

ELEV_STEP = 0.5
MAX_ERR_ELEV = 0.02
MAX_ERR_BIN = 0.001
MAX_ERR_PHASE = 0.005

SUNSET_ELEV = -0.833

HALF_DAY = timedelta(days=0.5)
ONE_DAY = timedelta(days=1)
ONE_SEC = timedelta(seconds=1)

LOGGER = logging.getLogger(__package__)

CONF_DIRECTION = "direction"
CONF_ELEVATION_AT_TIME = "elevation_at_time"
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

SIG_HA_LOC_UPDATED = f"{DOMAIN}_ha_loc_updated"
