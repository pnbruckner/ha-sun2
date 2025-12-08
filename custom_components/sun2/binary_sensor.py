"""Sun2 Binary Sensor."""
from __future__ import annotations

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

from .const import (
    ATTR_NEXT_CHANGE,
    ICON_ABOVE,
    ICON_BELOW,
    LOGGER,
    ONE_DAY,
    SUNSET_ELEV,
)
from .helpers import (
    Sun2Entity,
    Sun2EntityParams,
    Sun2EntityWithElvAdjs,
    Sun2EntrySetup,
    nearest_second,
    translate,
)


class Sun2ElevationSensor(Sun2EntityWithElvAdjs, BinarySensorEntity):
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
            assert threshold == "horizon"
            self._threshold = SUNSET_ELEV
        else:
            self._threshold = threshold

    def _update(self, cur_dttm: datetime) -> None:
        """Update state."""
        self._attr_is_on = self._get_cur_state(cur_dttm)
        self._attr_icon = ICON_ABOVE if self._attr_is_on else ICON_BELOW

        if nxt_chg := self._get_nxt_chg():
            self._schedule_update(nxt_chg)
            nxt_chg = self._as_tz(nxt_chg)
            # It's ok that nxt_chg is now in location's time zone and cur_dttm is in
            # UTC. nxt_chg's value will be automatically converted to UTC during the
            # subtraction operation.
            if nxt_chg - cur_dttm > ONE_DAY and self.hass.state == CoreState.running:
                LOGGER.warning(
                    "%s: Sun elevation will not reach %f again until %s",
                    self._log_name,
                    self._threshold,
                    nxt_chg.date(),
                )
        elif self.hass.state == CoreState.running:
            LOGGER.error(
                "%s: Sun elevation never reaches %f at this location",
                self._log_name,
                self._threshold,
            )
        self._attr_extra_state_attributes = {ATTR_NEXT_CHANGE: nxt_chg}

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
                return cur_elv <= self._threshold - self._set_elv_adj
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

    def _get_nxt_chg(self) -> datetime | None:
        """Get next time sun crosses threshold."""
        # Find next time sun crosses threshold. Note that it's possible that might not
        # happen today, or even tomorrow, depending on location & time of year. Move to
        # next part of solar elevation curve, and if that doesn't cross threshold, keep
        # moving to the next part of the curve until a crossing is found, but don't look
        # more than one year into the future.
        for _ in range(365 * 2):
            self._rising = not self._rising
            if self._rising:
                self._dt += ONE_DAY
            if nxt_chg := self._time_at_elevation(self._threshold):
                return nxt_chg
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
