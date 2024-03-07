from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util


async def test_test(hass: HomeAssistant):
    print(hass.config.latitude, hass.config.longitude, hass.config.time_zone, dt_util.now())
    await hass.config.async_update(
        latitude=41.5593425366867,
        longitude=-88.20533931255342,
        time_zone="America/Chicago"
    )
    print(hass.config.latitude, hass.config.longitude, hass.config.time_zone, dt_util.now())
