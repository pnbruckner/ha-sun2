"""Sun2 Binary Sensor."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import cast

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
from homeassistant.core import CoreState, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .const import ATTR_NEXT_CHANGE, LOGGER, MAX_ERR_BIN, ONE_DAY, ONE_SEC, SUNSET_ELEV
from .helpers import (
    Num,
    Sun2Entity,
    Sun2EntityParams,
    Sun2EntrySetup,
    nearest_second,
    translate,
)

ABOVE_ICON = "mdi:white-balance-sunny"
BELOW_ICON = "mdi:moon-waxing-crescent"


class Sun2ElevationSensor(Sun2Entity, BinarySensorEntity):
    """Sun2 Elevation Sensor."""

    def __init__(
        self, sun2_entity_params: Sun2EntityParams, name: str, threshold: float | str
    ) -> None:
        """Initialize sensor."""
        self.entity_description = BinarySensorEntityDescription(
            key=CONF_ELEVATION, name=name
        )
        super().__init__(sun2_entity_params)
        self._event = "solar_elevation"

        if isinstance(threshold, str):
            self._threshold = SUNSET_ELEV
        else:
            self._threshold = threshold

    def _find_nxt_dttm(
        self, t0_dttm: datetime, t0_elev: Num, t1_dttm: datetime, t1_elev: Num
    ) -> datetime:
        """Find time elevation crosses threshold between 2 points on elevation curve."""
        # Do a binary search for time between t0 & t1 where elevation is
        # nearest threshold, but also above (or equal to) it if current
        # elevation is below it (i.e., current state is False), or below it if
        # current elevation is above (or equal to) it (i.e., current state is
        # True.)

        slope = 1 if t1_elev > t0_elev else -1

        # Find mid point and throw away fractional seconds since astral package
        # ignores microseconds.
        tn_dttm = nearest_second(t0_dttm + (t1_dttm - t0_dttm) / 2)
        tn_elev = cast(float, self._astral_event(tn_dttm))

        while not (
            (
                self._attr_is_on
                and tn_elev <= self._threshold
                or not self._attr_is_on
                and tn_elev > self._threshold
            )
            and abs(tn_elev - self._threshold) <= MAX_ERR_BIN
        ):
            if (tn_elev - self._threshold) * slope > 0:
                if t1_dttm == tn_dttm:
                    break
                t1_dttm = tn_dttm
            else:
                if t0_dttm == tn_dttm:
                    break
                t0_dttm = tn_dttm
            tn_dttm = nearest_second(t0_dttm + (t1_dttm - t0_dttm) / 2)
            tn_elev = cast(float, self._astral_event(tn_dttm))

        # Did we go too far?
        if self._attr_is_on and tn_elev > self._threshold:
            tn_dttm -= slope * ONE_SEC
            if cast(float, self._astral_event(tn_dttm)) > self._threshold:
                raise RuntimeError("Couldn't find next update time")
        elif not self._attr_is_on and tn_elev <= self._threshold:
            tn_dttm += slope * ONE_SEC
            if cast(float, self._astral_event(tn_dttm)) <= self._threshold:
                raise RuntimeError("Couldn't find next update time")

        return tn_dttm

    def _get_nxt_dttm(self, cur_dttm: datetime) -> datetime | None:
        """Get next time sensor should change state."""
        # Find next segment of elevation curve, between a pair of solar noon &
        # solar midnight, where it crosses the threshold, but in the opposite
        # direction (i.e., where output should change state.) Note that this
        # might be today, tomorrow, days away, or never, depending on location,
        # time of year and specified threshold.

        # Start by finding the next five solar midnight & solar noon "events"
        # since current time might be anywhere from before today's solar
        # midnight (if it is this morning) to after tomorrow's solar midnight
        # (if it is this evening.)
        date = cur_dttm.date()
        evt_dttm1 = cast(datetime, self._astral_event(date, "solar_midnight"))
        evt_dttm2 = cast(datetime, self._astral_event(date, "solar_noon"))
        evt_dttm3 = cast(datetime, self._astral_event(date + ONE_DAY, "solar_midnight"))
        evt_dttm4 = cast(datetime, self._astral_event(date + ONE_DAY, "solar_noon"))
        evt_dttm5 = cast(
            datetime, self._astral_event(date + 2 * ONE_DAY, "solar_midnight")
        )

        # See if segment we're looking for falls between any of these events.
        # If not move ahead a day and try again, but don't look more than a
        # a year ahead.
        end_date = date + 366 * ONE_DAY
        while date < end_date:
            if cur_dttm < evt_dttm1:
                if self._attr_is_on:
                    t0_dttm = cur_dttm
                    t1_dttm = evt_dttm1
                else:
                    t0_dttm = evt_dttm1
                    t1_dttm = evt_dttm2
            elif cur_dttm < evt_dttm2:
                if not self._attr_is_on:
                    t0_dttm = cur_dttm
                    t1_dttm = evt_dttm2
                else:
                    t0_dttm = evt_dttm2
                    t1_dttm = evt_dttm3
            elif cur_dttm < evt_dttm3:
                if self._attr_is_on:
                    t0_dttm = cur_dttm
                    t1_dttm = evt_dttm3
                else:
                    t0_dttm = evt_dttm3
                    t1_dttm = evt_dttm4
            else:  # noqa: PLR5501
                if not self._attr_is_on:
                    t0_dttm = cur_dttm
                    t1_dttm = evt_dttm4
                else:
                    t0_dttm = evt_dttm4
                    t1_dttm = evt_dttm5

            t0_elev = cast(float, self._astral_event(t0_dttm))
            t1_elev = cast(float, self._astral_event(t1_dttm))

            # Did we find it?
            # Note, if t1_elev > t0_elev, then we're looking for an elevation
            # ABOVE threshold. In this case we can't use this range if the
            # threshold is EQUAL to the elevation at t1, because this range
            # does NOT include any points with a higher elevation value. For
            # all other cases it's ok for the threshold to equal the elevation
            # at t0 or t1.
            if (
                t0_elev <= self._threshold < t1_elev
                or t1_elev <= self._threshold <= t0_elev
            ):
                nxt_dttm = self._find_nxt_dttm(t0_dttm, t0_elev, t1_dttm, t1_elev)
                if nxt_dttm - cur_dttm > ONE_DAY:
                    if self.hass.state == CoreState.running:
                        LOGGER.warning(
                            "%s: Sun elevation will not reach %f again until %s",
                            self.name,
                            self._threshold,
                            nxt_dttm.date(),
                        )
                return nxt_dttm

            # Shift one day ahead.
            date += ONE_DAY
            evt_dttm1 = evt_dttm3
            evt_dttm2 = evt_dttm4
            evt_dttm3 = evt_dttm5
            evt_dttm4 = cast(datetime, self._astral_event(date + ONE_DAY, "solar_noon"))
            evt_dttm5 = cast(
                datetime, self._astral_event(date + 2 * ONE_DAY, "solar_midnight")
            )

        # Didn't find one.
        return None

    def _update(self, cur_dttm: datetime) -> None:
        """Update state."""
        cur_elev = cast(float, self._astral_event(cur_dttm))
        self._attr_is_on = cur_elev > self._threshold
        self._attr_icon = ABOVE_ICON if self._attr_is_on else BELOW_ICON
        LOGGER.debug(
            "%s: threshold = %f, elevation = %f", self.name, self._threshold, cur_elev
        )

        nxt_dttm = self._get_nxt_dttm(cur_dttm)

        @callback
        def schedule_update(now: datetime) -> None:
            """Schedule state update."""
            self._unsub_update = None
            self.async_schedule_update_ha_state(True)

        if nxt_dttm:
            self._unsub_update = async_track_point_in_utc_time(
                self.hass, schedule_update, nxt_dttm
            )
            nxt_dttm = dt_util.as_local(nxt_dttm)
        elif self.hass.state == CoreState.running:
            LOGGER.error(
                "%s: Sun elevation never reaches %f at this location",
                self.name,
                self._threshold,
            )
        self._attr_extra_state_attributes = {ATTR_NEXT_CHANGE: nxt_dttm}


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
            yield Sun2ElevationSensor(
                self._sun2_entity_params,
                self._elevation_name(config.get(CONF_NAME), threshold),
                threshold,
            )

    def _elevation_name(self, name: str | None, threshold: float | str) -> str:
        """Return elevation sensor name."""
        if name:
            return name
        if isinstance(threshold, str):
            return translate(self._hass, "above_horizon")
        if threshold < 0:
            return translate(
                self._hass, "above_neg_elev", {"elevation": str(-threshold)}
            )
        return translate(self._hass, "above_pos_elev", {"elevation": str(threshold)})


async_setup_entry = Sun2BinarySensorEntrySetup.async_setup_entry
