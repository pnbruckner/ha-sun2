"""Sun2 Binary Sensor."""
from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import datetime

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import (
    CONF_BINARY_SENSORS,
    CONF_ELEVATION,
    CONF_NAME,
    CONF_UNIQUE_ID,
)
from homeassistant.core import CoreState
from homeassistant.util import dt as dt_util

from .const import ICON_ABOVE, ICON_BELOW, LOGGER, MAX_UPDATE_TIME, ONE_DAY, SUNSET_ELEV
from .helpers import (
    Sun2Entity,
    Sun2EntityParams,
    Sun2EntityWithElvAdjs,
    Sun2EntrySetup,
    nearest_second,
)

# Cause Semaphore to be created to make async_update, and anything protected by
# async_request_call, atomic.
PARALLEL_UPDATES = 1


class Sun2ElevationBinarySensor(Sun2EntityWithElvAdjs, BinarySensorEntity):
    """Sun2 Elevation Binary Sensor."""

    _use_nxt_dir_chg: bool = False

    def __init__(
        self,
        sun2_entity_params: Sun2EntityParams,
        name: str | None,
        threshold: float | str,
    ) -> None:
        """Initialize sensor."""
        self.entity_description = BinarySensorEntityDescription(key=CONF_ELEVATION)
        super().__init__(sun2_entity_params)

        if threshold_is_horizon := isinstance(threshold, str):
            assert threshold == "horizon"
            self._threshold = SUNSET_ELEV
        else:
            self._threshold = threshold
        if name:
            self._attr_name = name
        elif threshold_is_horizon:
            self._attr_translation_key = CONF_ELEVATION + "_hor"
        elif threshold < 0:  # type: ignore[operator]
            self._attr_translation_key = CONF_ELEVATION + "_neg"
            self._attr_translation_placeholders = {"elevation": str(-threshold)}  # type: ignore[operator]
        else:
            self._attr_translation_key = CONF_ELEVATION + "_pos"
            self._attr_translation_placeholders = {"elevation": str(threshold)}
        self._attr_extra_state_attributes = {}

    async def _update(self, cur_dttm: datetime, requested: bool) -> None:
        """Update state."""
        self._attr_is_on = self._get_cur_state(cur_dttm)
        self._attr_icon = ICON_ABOVE if self._attr_is_on else ICON_BELOW

        if nxt_chg := await self._get_nxt_chg():
            if nxt_chg - cur_dttm > ONE_DAY and self.hass.state == CoreState.running:
                LOGGER.warning(
                    "%s: Sun elevation will not reach %f again until %s",
                    self._log_name,
                    self._threshold,
                    self._as_tz(nxt_chg).date(),
                )
        elif self.hass.state == CoreState.running:
            LOGGER.error(
                "%s: Sun elevation never reaches %f at this location",
                self._log_name,
                self._threshold,
            )
        self._schedule_update(nxt_chg)

    def _get_cur_state(self, cur_dttm: datetime) -> bool:
        """Get current sensor state."""
        if self._first_update:
            if (nxt_chg := self._time_at_elevation(self._threshold)) is None:
                # Sun doesn't cross threshold today. Base current state on solar
                # elevation. Since astral package ignores microseconds when determining
                # solar elevation, round current time to nearest second.
                cur_elv = self._solar_elevation(nearest_second(cur_dttm))
                if self._rising:
                    return cur_elv >= self._threshold - self._ris_elv_adj
                return cur_elv > self._threshold - self._set_elv_adj
            # Sun does cross threshold today.
            if cur_dttm < nxt_chg:
                # Sun has not yet crossed threshold on current part of the "solar
                # elevation curve." Set state parameters to be on previous part of
                # the curve so current state and next change are determined
                # correctly.
                self._rising = not self._rising
                if not self._rising:
                    self._dt -= ONE_DAY
        return self._rising

    async def _get_nxt_chg(self) -> datetime | None:
        """Get next time sun crosses threshold."""
        # Find next time sun crosses threshold. Note that it's possible that might not
        # happen today, or even tomorrow, depending on location & time of year. Move to
        # next part of solar elevation curve, and if that doesn't cross threshold, keep
        # moving to the next part of the curve until a crossing is found, but don't look
        # more than one year into the future.
        start = dt_util.utcnow()
        for _ in range(365 * 2):
            self._change_sun_direction()
            if nxt_chg := self._time_at_elevation(self._threshold):
                return nxt_chg
            if dt_util.utcnow() - start > MAX_UPDATE_TIME:
                await asyncio.sleep(0)
                start = dt_util.utcnow()
        return None


class Sun2BinarySensorEntrySetup(Sun2EntrySetup):
    """Binary sensor config entry setup."""

    def _get_entities(self) -> Iterable[Sun2Entity]:
        """Return entities to add."""
        for config in self._entry.options.get(CONF_BINARY_SENSORS, []):
            unique_id = config[CONF_UNIQUE_ID]
            if self._imported:
                unique_id = self._uid_prefix + unique_id
            self._sun2_entity_params.unique_id = unique_id
            threshold = config[CONF_ELEVATION]
            yield Sun2ElevationBinarySensor(
                self._sun2_entity_params, config.get(CONF_NAME), threshold
            )


async_setup_entry = Sun2BinarySensorEntrySetup.async_setup_entry
