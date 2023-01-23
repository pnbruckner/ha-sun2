"""Sun2 Sensor."""
from __future__ import annotations

from abc import abstractmethod
from collections.abc import Mapping, MutableMapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import ceil, floor
from typing import Any, Generic, Optional, TypeVar, Union, cast

from astral import SunDirection

import voluptuous as vol

from homeassistant.components.sensor import (
    DOMAIN as SENSOR_DOMAIN,
    PLATFORM_SCHEMA,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    ATTR_ICON,
    CONF_ENTITY_NAMESPACE,
    CONF_MONITORED_CONDITIONS,
    DEGREE,
)

# UnitOfTime was new in 2023.1
try:
    from homeassistant.const import UnitOfTime

    time_hours = UnitOfTime.HOURS
except ImportError:
    from homeassistant.const import TIME_HOURS

    time_hours = TIME_HOURS  # type: ignore[assignment]

from homeassistant.core import CALLBACK_TYPE, CoreState, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_BLUE_HOUR,
    ATTR_DAYLIGHT,
    ATTR_GOLDEN_HOUR,
    ATTR_NEXT_CHANGE,
    ATTR_RISING,
    ATTR_TODAY,
    ATTR_TODAY_HMS,
    ATTR_TOMORROW,
    ATTR_TOMORROW_HMS,
    ATTR_YESTERDAY,
    ATTR_YESTERDAY_HMS,
    HALF_DAY,
    MAX_ERR_ELEV,
    ELEV_STEP,
    LOGGER,
    MAX_ERR_PHASE,
    ONE_DAY,
    SUNSET_ELEV,
)
from .helpers import (
    LOC_PARAMS,
    LocData,
    LocParams,
    Num,
    Sun2Entity,
    get_loc_params,
    hours_to_hms,
    nearest_second,
    next_midnight,
)

_SOLAR_DEPRESSIONS = ("astronomical", "civil", "nautical")
_DELTA = timedelta(minutes=5)


_T = TypeVar("_T")


class Sun2SensorEntity(Sun2Entity, SensorEntity, Generic[_T]):
    """Sun2 Sensor Entity."""

    _attr_native_value: _T | None  # type: ignore[assignment]
    _yesterday: _T | None = None
    _today: _T | None = None
    _tomorrow: _T | None = None

    @abstractmethod
    def __init__(
        self,
        loc_params: LocParams | None,
        namespace: str | None,
        entity_description: SensorEntityDescription,
        default_solar_depression: Num | str = 0,
    ) -> None:
        """Initialize sensor."""
        key = entity_description.key
        name = key.replace("_", " ").title()
        if namespace:
            name = f"{namespace} {name}"
        entity_description.name = name
        self.entity_description = entity_description
        super().__init__(loc_params, SENSOR_DOMAIN, key)

        if any(key.startswith(sol_dep + "_") for sol_dep in _SOLAR_DEPRESSIONS):
            self._solar_depression, self._event = key.rsplit("_", 1)
        else:
            self._solar_depression = default_solar_depression
            self._event = key

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return entity specific state attributes."""
        return {
            ATTR_YESTERDAY: self._yesterday,
            ATTR_TODAY: self._today,
            ATTR_TOMORROW: self._tomorrow,
        }

    def _setup_fixed_updating(self) -> None:
        """Set up fixed updating."""
        # Default behavior is to update every midnight.
        # Override for sensor types that should update at a different time,
        # or that have a more dynamic update schedule (in which case override
        # with a method that does nothing and set up the update at the end of
        # an override of _update instead.)

        @callback
        def async_schedule_update_at_midnight(now: datetime) -> None:
            """Schedule an update at midnight."""
            next_midn = next_midnight(now.astimezone(self._loc_data.tzi))
            self._unsub_update = async_track_point_in_utc_time(
                self.hass, async_schedule_update_at_midnight, next_midn
            )
            self.async_schedule_update_ha_state(True)

        next_midn = next_midnight(dt_util.now(self._loc_data.tzi))
        self._unsub_update = async_track_point_in_utc_time(
            self.hass, async_schedule_update_at_midnight, next_midn
        )

    def _update(self, cur_dttm: datetime) -> None:
        """Update state."""
        cur_date = cur_dttm.date()
        self._yesterday = cast(Optional[_T], self._astral_event(cur_date - ONE_DAY))
        self._attr_native_value = self._today = cast(
            Optional[_T], self._astral_event(cur_date)
        )
        self._tomorrow = cast(Optional[_T], self._astral_event(cur_date + ONE_DAY))


class Sun2PointInTimeSensor(Sun2SensorEntity[Union[datetime, str]]):
    """Sun2 Point in Time Sensor."""

    def __init__(
        self,
        loc_params: LocParams | None,
        namespace: str | None,
        sensor_type: str,
        icon: str | None,
    ) -> None:
        """Initialize sensor."""
        entity_description = SensorEntityDescription(
            key=sensor_type,
            device_class=SensorDeviceClass.TIMESTAMP,
            icon=icon,
        )
        super().__init__(loc_params, namespace, entity_description, "civil")

    def _update(self, cur_dttm: datetime) -> None:
        """Update state."""
        super()._update(cur_dttm)
        # A state of None will get converted to "unknown", which is not appropriate for
        # this sensor. Use the word "none" instead.
        if self._attr_native_value is None:
            self._attr_native_value = "none"


class Sun2PeriodOfTimeSensor(Sun2SensorEntity[float]):
    """Sun2 Period of Time Sensor."""

    def __init__(
        self,
        loc_params: LocParams | None,
        namespace: str | None,
        sensor_type: str,
        icon: str | None,
    ) -> None:
        """Initialize sensor."""
        entity_description = SensorEntityDescription(
            key=sensor_type,
            icon=icon,
            native_unit_of_measurement=time_hours,
        )
        # SensorDeviceClass.DURATION was new in 2022.5
        with suppress(AttributeError):
            entity_description.device_class = SensorDeviceClass.DURATION
        super().__init__(loc_params, namespace, entity_description, -SUNSET_ELEV)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return entity specific state attributes."""
        data = dict(super().extra_state_attributes or {})
        data.update(
            {
                ATTR_YESTERDAY_HMS: hours_to_hms(data[ATTR_YESTERDAY]),
                ATTR_TODAY_HMS: hours_to_hms(data[ATTR_TODAY]),
                ATTR_TOMORROW_HMS: hours_to_hms(data[ATTR_TOMORROW]),
            }
        )
        return data

    def _astral_event(
        self,
        date_or_dttm: date | datetime,
        event: str | None = None,
        /,
        **kwargs: Mapping[str, Any],
    ) -> float | None:
        """Return astral event result."""
        start: datetime | None
        end: datetime | None
        if self._event == "daylight":
            start = super()._astral_event(date_or_dttm, "dawn")
            end = super()._astral_event(date_or_dttm, "dusk")
        else:
            start = super()._astral_event(date_or_dttm, "dusk")
            end = super()._astral_event(date_or_dttm + ONE_DAY, "dawn")
        if not start or not end:
            return None
        return (end - start).total_seconds() / 3600

    def _update(self, cur_dttm: datetime) -> None:
        """Update state."""
        super()._update(cur_dttm)
        if self._attr_native_value is not None:
            self._attr_native_value = round(self._attr_native_value, 3)


class Sun2MinMaxElevationSensor(Sun2SensorEntity[float]):
    """Sun2 Min/Max Elevation Sensor."""

    def __init__(
        self,
        loc_params: LocParams | None,
        namespace: str | None,
        sensor_type: str,
        icon: str | None,
    ) -> None:
        """Initialize sensor."""
        entity_description = SensorEntityDescription(
            key=sensor_type,
            icon=icon,
            native_unit_of_measurement=DEGREE,
            state_class=SensorStateClass.MEASUREMENT,
        )
        super().__init__(loc_params, namespace, entity_description)
        self._event = {
            "min_elevation": "solar_midnight",
            "max_elevation": "solar_noon",
        }[sensor_type]

    def _astral_event(
        self,
        date_or_dttm: date | datetime,
        event: str | None = None,
        /,
        **kwargs: Mapping[str, Any],
    ) -> float | None:
        """Return astral event result."""
        return cast(
            Optional[float],
            super()._astral_event(
                cast(datetime, super()._astral_event(date_or_dttm)), "solar_elevation"
            ),
        )

    def _update(self, cur_dttm: datetime) -> None:
        """Update state."""
        super()._update(cur_dttm)
        if self._attr_native_value is not None:
            self._attr_native_value = round(self._attr_native_value, 3)


@dataclass
class CurveParameters:
    """
    Parameters that describe current portion of elevation curve.

    The ends of the current portion of the curve are bounded by a pair of solar
    midnight and solar noon, such that tL_dttm <= cur_dttm < tR_dttm. rising is True if
    tR_elev > tL_elev (i.e., tL represents a solar midnight and tR represents a solar
    noon.) mid_date is the date of the midpoint between tL & tR. nxt_noon is the solar
    noon for tomorrow (i.e., cur_date + 1.)
    """

    tL_dttm: datetime
    tL_elev: Num
    tR_dttm: datetime
    tR_elev: Num
    mid_date: date
    nxt_noon: datetime
    rising: bool


class Sun2CPSensorEntity(Sun2SensorEntity[_T]):
    """Sun2 Sensor Entity with elevation curve methods."""

    _cp: CurveParameters | None = None

    @abstractmethod
    def __init__(
        self,
        loc_params: LocParams | None,
        namespace: str | None,
        entity_description: SensorEntityDescription,
        default_solar_depression: Num | str = 0,
    ) -> None:
        """Initialize sensor."""
        super().__init__(
            loc_params, namespace, entity_description, default_solar_depression
        )
        self._event = "solar_elevation"

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return entity specific state attributes."""
        if hasattr(self, "_attr_extra_state_attributes"):
            return self._attr_extra_state_attributes
        return None

    async def _async_loc_updated(self, loc_data: LocData) -> None:
        """Location updated."""
        self._cp = None
        await super()._async_loc_updated(loc_data)

    def _setup_fixed_updating(self) -> None:
        """Set up fixed updating."""
        pass

    def _attrs_at_elev(self, elev: Num) -> MutableMapping[str, Any]:
        """Return attributes at elevation."""
        assert self._cp

        if self._cp.rising:
            if elev < -18:
                icon = "mdi:weather-night"
            elif elev < SUNSET_ELEV:
                icon = "mdi:weather-sunset-up"
            else:
                icon = "mdi:weather-sunny"
        else:
            if elev > SUNSET_ELEV:
                icon = "mdi:weather-sunny"
            elif elev > -18:
                icon = "mdi:weather-sunset-down"
            else:
                icon = "mdi:weather-night"
        return {ATTR_ICON: icon}

    def _set_attrs(self, attrs: MutableMapping[str, Any], nxt_chg: datetime) -> None:
        """Set attributes."""
        self._attr_icon = cast(Optional[str], attrs.pop(ATTR_ICON, "mdi:weather-sunny"))
        attrs[ATTR_NEXT_CHANGE] = dt_util.as_local(nxt_chg)
        self._attr_extra_state_attributes = attrs

    def _get_curve_params(self, cur_dttm: datetime, cur_elev: Num) -> CurveParameters:
        """Calculate elevation curve parameters."""
        cur_date = cur_dttm.date()

        # Find the highest and lowest points on the elevation curve that encompass
        # current time, where it is ok for the current time to be the same as the
        # first of these two points.
        # Note that the astral solar_midnight event will always come before the astral
        # solar_noon event for any given date, even if it actually falls on the previous
        # day.
        hi_dttm = cast(datetime, self._astral_event(cur_date, "solar_noon"))
        lo_dttm = cast(datetime, self._astral_event(cur_date, "solar_midnight"))
        nxt_noon = cast(datetime, self._astral_event(cur_date + ONE_DAY, "solar_noon"))
        if cur_dttm < lo_dttm:
            tL_dttm = cast(
                datetime, self._astral_event(cur_date - ONE_DAY, "solar_noon")
            )
            tR_dttm = lo_dttm
        elif cur_dttm < hi_dttm:
            tL_dttm = lo_dttm
            tR_dttm = hi_dttm
        else:
            lo_dttm = cast(
                datetime, self._astral_event(cur_date + ONE_DAY, "solar_midnight")
            )
            if cur_dttm < lo_dttm:
                tL_dttm = hi_dttm
                tR_dttm = lo_dttm
            else:
                tL_dttm = lo_dttm
                tR_dttm = nxt_noon
        tL_elev = cast(float, self._astral_event(tL_dttm))
        tR_elev = cast(float, self._astral_event(tR_dttm))
        rising = tR_elev > tL_elev

        LOGGER.debug(
            "%s: tL = %s/%0.3f, cur = %s/%0.3f, tR = %s/%0.3f, rising = %s",
            self.name,
            tL_dttm,
            tL_elev,
            cur_dttm,
            cur_elev,
            tR_dttm,
            tR_elev,
            rising,
        )

        mid_date = (tL_dttm + (tR_dttm - tL_dttm) / 2).date()
        return CurveParameters(
            tL_dttm, tL_elev, tR_dttm, tR_elev, mid_date, nxt_noon, rising
        )

    def _get_dttm_at_elev(
        self, t0_dttm: datetime, t1_dttm: datetime, elev: Num, max_err: Num
    ) -> datetime | None:
        """Get datetime at elevation."""
        assert self._cp

        msg_base = f"{self.name}: trg = {elev:+7.3f}: "
        t0_elev = cast(float, self._astral_event(t0_dttm))
        t1_elev = cast(float, self._astral_event(t1_dttm))
        est_elev = elev + 1.5 * max_err
        est = 0
        while abs(est_elev - elev) >= max_err:
            est += 1
            msg = (
                msg_base
                + f"t0 = {t0_dttm}/{t0_elev:+7.3f}, t1 = {t1_dttm}/{t1_elev:+7.3f} ->"
            )
            try:
                est_dttm = nearest_second(
                    t0_dttm
                    + (t1_dttm - t0_dttm) * ((elev - t0_elev) / (t1_elev - t0_elev))
                )
            except ZeroDivisionError:
                LOGGER.debug("%s ZeroDivisionError", msg)
                return None
            if est_dttm < self._cp.tL_dttm or est_dttm > self._cp.tR_dttm:
                LOGGER.debug("%s outside range", msg)
                return None
            est_elev = cast(float, self._astral_event(est_dttm))
            LOGGER.debug(
                "%s est = %s/%+7.3f[%+7.3f/%2i]",
                msg,
                est_dttm,
                est_elev,
                est_elev - elev,
                est,
            )
            if est_dttm in (t0_dttm, t1_dttm):
                break
            if est_dttm > t1_dttm:
                t0_dttm = t1_dttm
                t0_elev = t1_elev
                t1_dttm = est_dttm
                t1_elev = est_elev
            elif t0_elev < elev < est_elev or t0_elev > elev > est_elev:
                t1_dttm = est_dttm
                t1_elev = est_elev
            else:
                t0_dttm = est_dttm
                t0_elev = est_elev
        return est_dttm


class Sun2ElevationSensor(Sun2CPSensorEntity[float]):
    """Sun2 Elevation Sensor."""

    _prv_dttm: datetime | None = None

    def __init__(
        self,
        loc_params: LocParams | None,
        namespace: str | None,
        sensor_type: str,
        icon: str | None,
    ) -> None:
        """Initialize sensor."""
        entity_description = SensorEntityDescription(
            key=sensor_type,
            icon=icon,
            native_unit_of_measurement=DEGREE,
            state_class=SensorStateClass.MEASUREMENT,
        )
        super().__init__(loc_params, namespace, entity_description)

    @property
    def native_value(self) -> str:
        """Return the value reported by the sensor."""
        return f"{self._attr_native_value:0.1f}"

    def _update(self, cur_dttm: datetime) -> None:
        """Update state."""
        # Astral package ignores microseconds, so round to nearest second
        # before continuing.
        cur_dttm = nearest_second(cur_dttm)
        cur_elev = cast(float, self._astral_event(cur_dttm))
        self._attr_native_value = rnd_elev = round(cur_elev, 1)
        LOGGER.debug(
            "%s: Raw elevation = %f -> %s", self.name, cur_elev, self.native_value
        )

        if not self._cp or cur_dttm >= self._cp.tR_dttm:
            self._prv_dttm = None
            self._cp = self._get_curve_params(cur_dttm, cur_elev)

        if self._prv_dttm:
            # Extrapolate based on previous point and current point to find next point.
            # But if that crosses sunrise/sunset elevation, then make next point the
            # sunrise/sunset elevation so icon updates at the right time.
            if self._cp.rising:
                elev = floor((rnd_elev + ELEV_STEP) / ELEV_STEP) * ELEV_STEP
                if rnd_elev < SUNSET_ELEV and elev > SUNSET_ELEV + MAX_ERR_ELEV:
                    elev = SUNSET_ELEV + MAX_ERR_ELEV
            else:
                elev = ceil((rnd_elev - ELEV_STEP) / ELEV_STEP) * ELEV_STEP
                if rnd_elev > SUNSET_ELEV and elev < SUNSET_ELEV - MAX_ERR_ELEV:
                    elev = SUNSET_ELEV - MAX_ERR_ELEV
            nxt_dttm = self._get_dttm_at_elev(
                self._prv_dttm, cur_dttm, elev, MAX_ERR_ELEV
            )
        else:
            nxt_dttm = None

        if not nxt_dttm:
            if self._cp.tR_dttm - _DELTA <= cur_dttm < self._cp.tR_dttm:
                nxt_dttm = self._cp.tR_dttm
            else:
                nxt_dttm = cur_dttm + _DELTA

        self._set_attrs(self._attrs_at_elev(cur_elev), nxt_dttm)

        self._prv_dttm = cur_dttm

        @callback
        def async_schedule_update(now: datetime) -> None:
            """Schedule entity update."""
            self._unsub_update = None
            self.async_schedule_update_ha_state(True)

        self._unsub_update = async_track_point_in_utc_time(
            self.hass, async_schedule_update, nxt_dttm
        )


@dataclass(frozen=True)
class PhaseData:
    """Unique data to each subclass that is determined once at initialization."""

    rising_elevs: Sequence[Num]
    rising_states: Sequence[tuple[Num, str]]
    falling_elevs: Sequence[Num]
    falling_states: Sequence[tuple[Num, str]]


@dataclass
class Update:
    """Scheduled update."""

    remove: CALLBACK_TYPE
    when: datetime
    state: str | None
    attrs: MutableMapping[str, Any] | None


class Sun2PhaseSensorBase(Sun2CPSensorEntity[str]):
    """Sun2 Phase Sensor Base."""

    @abstractmethod
    def __init__(
        self,
        loc_params: LocParams | None,
        namespace: str | None,
        sensor_type: str,
        icon: str | None,
        phase_data: PhaseData,
    ) -> None:
        """Initialize sensor."""
        entity_description = SensorEntityDescription(key=sensor_type, icon=icon)
        # SensorDeviceClass.ENUM & SensorEntityDescription.options were new in 2023.1
        with suppress(AttributeError):
            entity_description.device_class = SensorDeviceClass.ENUM
            options = [state[1] for state in phase_data.rising_states]
            for state in phase_data.falling_states:
                if state[1] not in options:
                    options.append(state[1])
            entity_description.options = options
        super().__init__(loc_params, namespace, entity_description)
        self._d = phase_data
        self._updates: list[Update] = []

    def _state_at_elev(self, elev: Num) -> str:
        """Return state at elevation."""
        assert self._cp

        if self._cp.rising:
            return list(filter(lambda x: elev >= x[0], self._d.rising_states))[-1][1]
        else:
            return list(filter(lambda x: elev <= x[0], self._d.falling_states))[-1][1]

    @callback
    def _async_do_update(self, now: datetime) -> None:
        """Update entity from scheduled update."""
        update = self._updates.pop(0)
        if self._updates:
            self._attr_native_value = update.state
            self._set_attrs(
                cast(MutableMapping[str, Any], update.attrs), self._updates[0].when
            )
            self.async_write_ha_state()
        else:
            # The last one means it's time to determine the next set of scheduled
            # updates.
            self.async_schedule_update_ha_state(True)

    def _setup_update_at_time(
        self,
        update_dttm: datetime,
        state: str | None = None,
        attrs: MutableMapping[str, Any] | None = None,
    ) -> None:
        """Setu up update at given time."""
        self._updates.append(
            Update(
                async_track_point_in_utc_time(
                    self.hass, self._async_do_update, update_dttm
                ),
                update_dttm,
                state,
                attrs,
            )
        )

    def _setup_update_at_elev(self, elev: Num) -> None:
        """Set up update when sun reaches given elevation."""
        assert self._cp

        # Try to find a close approximation for when the sun will reach the given
        # elevation. This should allow _get_dttm_at_elev to converge more quickly.
        try:

            def get_est_dttm(offset: timedelta | None = None) -> datetime:
                """Get estimated time when sun gets to given elevation.

                Note that astral's time_at_elevation method is not very accurate
                and can sometimes return None, especially near solar noon or solar
                midnight.
                """
                assert self._cp

                return nearest_second(
                    cast(
                        datetime,
                        self._astral_event(
                            self._cp.mid_date + offset if offset else self._cp.mid_date,
                            "time_at_elevation",
                            elevation=elev,  # type: ignore[arg-type]
                            direction=SunDirection.RISING
                            if self._cp.rising
                            else SunDirection.SETTING,
                        ),
                    )
                )

            est_dttm = get_est_dttm()
            if not self._cp.tL_dttm <= est_dttm < self._cp.tR_dttm:
                est_dttm = get_est_dttm(
                    ONE_DAY if est_dttm < self._cp.tL_dttm else -ONE_DAY
                )
                if not self._cp.tL_dttm <= est_dttm < self._cp.tR_dttm:
                    raise ValueError
        except (TypeError, ValueError) as exc:
            if isinstance(exc, TypeError):
                # time_at_elevation doesn't always work around solar midnight & solar
                # noon.
                LOGGER.debug(
                    "%s: time_at_elevation(%0.3f) returned None", self.name, elev
                )
            else:
                LOGGER.debug(
                    "%s: time_at_elevation(%0.3f) outside [tL, tR): %s",
                    self.name,
                    elev,
                    est_dttm,
                )
            t0_dttm = self._cp.tL_dttm
            t1_dttm = self._cp.tR_dttm
        else:
            t0_dttm = max(est_dttm - _DELTA, self._cp.tL_dttm)
            t1_dttm = min(est_dttm + _DELTA, self._cp.tR_dttm)
        update_dttm = self._get_dttm_at_elev(t0_dttm, t1_dttm, elev, MAX_ERR_PHASE)
        if update_dttm:
            self._setup_update_at_time(
                update_dttm, self._state_at_elev(elev), self._attrs_at_elev(elev)
            )
        else:
            if self.hass.state == CoreState.running:
                LOGGER.error(
                    "%s: Failed to find the time at elev: %0.3f", self.name, elev
                )

    def _setup_updates(self, cur_dttm: datetime, cur_elev: Num) -> None:
        """Set up updates for next portion of elevation curve."""
        assert self._cp

        if self._cp.rising:
            for elev in self._d.rising_elevs:
                if cur_elev < elev < self._cp.tR_elev:
                    self._setup_update_at_elev(elev)
        else:
            for elev in self._d.falling_elevs:
                if cur_elev > elev > self._cp.tR_elev:
                    self._setup_update_at_elev(elev)

    def _update(self, cur_dttm: datetime) -> None:
        """Update state."""
        # Updates are determined only once per section of elevation curve (between a
        # pair of points at solar noon and solar midnight.) Once those updates have
        # been performed (or canceled, e.g., if location parameters are changed),
        # self._updates will be empty and it will be time to fill it again for the next
        # section of the elevation curve.
        if self._updates:
            return

        start_update = dt_util.now()

        # Astral package ignores microseconds, so round to nearest second
        # before continuing.
        cur_dttm = nearest_second(cur_dttm)
        cur_elev = cast(float, self._astral_event(cur_dttm))

        self._cp = self._get_curve_params(cur_dttm, cur_elev)

        self._attr_native_value = None
        self._setup_updates(cur_dttm, cur_elev)
        # This last update will not directly update the state, but will rather
        # reschedule aysnc_update() with self._updates being empty so as to make this
        # method run again to create a new schedule of udpates. Therefore we do not
        # need to provide state and attribute values.
        self._setup_update_at_time(self._cp.tR_dttm)

        # _setup_updates may have already determined the state.
        if not self._attr_native_value:
            self._attr_native_value = self._state_at_elev(cur_elev)
        self._set_attrs(self._attrs_at_elev(cur_elev), self._updates[0].when)

        def cancel_updates() -> None:
            """Cancel pending updates."""
            for update in self._updates:
                update.remove()
            self._updates = []

        self._unsub_update = cancel_updates

        LOGGER.debug("%s: _update time: %s", self.name, dt_util.now() - start_update)


class Sun2PhaseSensor(Sun2PhaseSensorBase):
    """Sun2 Phase Sensor."""

    def __init__(
        self,
        loc_params: LocParams | None,
        namespace: str | None,
        sensor_type: str,
        icon: str | None,
    ) -> None:
        """Initialize sensor."""
        phases = (
            (-90, "Night"),
            (-18, "Astronomical Twilight"),
            (-12, "Nautical Twilight"),
            (-6, "Civil Twilight"),
            (SUNSET_ELEV, "Day"),
            (90, None),
        )
        elevs, states = cast(
            tuple[tuple[Num], tuple[Optional[str]]],
            zip(*phases),
        )
        rising_elevs = sorted([*elevs[1:-1], -4, 6])
        rising_states = phases[:-1]
        falling_elevs = rising_elevs[::-1]
        falling_states = tuple(
            cast(
                tuple[tuple[Num, str]],
                zip(elevs[1:], states[:-1]),
            )
        )[::-1]
        super().__init__(
            loc_params,
            namespace,
            sensor_type,
            icon,
            PhaseData(rising_elevs, rising_states, falling_elevs, falling_states),
        )

    def _attrs_at_elev(self, elev: Num) -> MutableMapping[str, Any]:
        """Return attributes at elevation."""
        assert self._cp

        attrs = super()._attrs_at_elev(elev)
        if self._cp.rising:
            blue_hour = -6 <= elev < -4
            golden_hour = -4 <= elev < 6
        else:
            blue_hour = -6 < elev <= -4
            golden_hour = -4 < elev <= 6
        attrs[ATTR_BLUE_HOUR] = blue_hour
        attrs[ATTR_GOLDEN_HOUR] = golden_hour
        attrs[ATTR_RISING] = self._cp.rising
        return attrs


class Sun2DeconzDaylightSensor(Sun2PhaseSensorBase):
    """Sun2 deCONZ Phase Sensor."""

    def __init__(
        self,
        loc_params: LocParams | None,
        namespace: str | None,
        sensor_type: str,
        icon: str | None,
    ) -> None:
        """Initialize sensor."""
        phases = (
            (-90, "nadir", None),
            (-18, "night_end", "night_start"),
            (-12, "nautical_dawn", "nautical_dusk"),
            (-6, "dawn", "dusk"),
            (SUNSET_ELEV, "sunrise_start", "sunset_end"),
            (-0.3, "sunrise_end", "sunset_start"),
            (6, "golden_hour_1", "golden_hour_2"),
            (90, None, "solar_noon"),
        )
        elevs, r_states, f_states = cast(
            tuple[tuple[Num], tuple[Optional[str]], tuple[Optional[str]]],
            zip(*phases),
        )
        rising_elevs = elevs[1:-1]
        rising_states = tuple(
            cast(
                tuple[tuple[Num, str]],
                zip(elevs[:-1], r_states[:-1]),
            )
        )
        falling_elevs = rising_elevs[::-1]
        falling_states = tuple(
            cast(
                tuple[tuple[Num, str]],
                zip(elevs[1:], f_states[1:]),
            )
        )[::-1]
        super().__init__(
            loc_params,
            namespace,
            sensor_type,
            icon,
            PhaseData(rising_elevs, rising_states, falling_elevs, falling_states),
        )

    def _attrs_at_elev(self, elev: Num) -> MutableMapping[str, Any]:
        """Return attributes at elevation."""
        assert self._cp

        attrs = super()._attrs_at_elev(elev)
        if self._cp.rising:
            daylight = SUNSET_ELEV <= elev
        else:
            daylight = SUNSET_ELEV < elev
        attrs[ATTR_DAYLIGHT] = daylight
        return attrs

    def _setup_updates(self, cur_dttm: datetime, cur_elev: Num) -> None:
        """Set up updates for next portion of elevation curve."""
        assert self._cp

        if self._cp.rising:
            nadir_dttm = self._cp.tR_dttm - HALF_DAY
            if cur_dttm < nadir_dttm:
                self._attr_native_value = self._d.falling_states[-1][1]
                nadir_elev = cast(float, self._astral_event(nadir_dttm))
                self._setup_update_at_time(
                    nadir_dttm,
                    self._d.rising_states[0][1],
                    self._attrs_at_elev(nadir_elev),
                )
        else:
            nadir_dttm = self._cp.nxt_noon - HALF_DAY
            if cur_dttm >= nadir_dttm:
                self._attr_native_value = self._d.rising_states[0][1]
        super()._setup_updates(cur_dttm, cur_elev)


@dataclass
class SensorParams:
    """Parameters for sensor types."""

    cls: type
    icon: str | None


_SENSOR_TYPES = {
    # Points in time
    "solar_midnight": SensorParams(Sun2PointInTimeSensor, "mdi:weather-night"),
    "astronomical_dawn": SensorParams(Sun2PointInTimeSensor, "mdi:weather-sunset-up"),
    "nautical_dawn": SensorParams(Sun2PointInTimeSensor, "mdi:weather-sunset-up"),
    "dawn": SensorParams(Sun2PointInTimeSensor, "mdi:weather-sunset-up"),
    "sunrise": SensorParams(Sun2PointInTimeSensor, "mdi:weather-sunset-up"),
    "solar_noon": SensorParams(Sun2PointInTimeSensor, "mdi:weather-sunny"),
    "sunset": SensorParams(Sun2PointInTimeSensor, "mdi:weather-sunset-down"),
    "dusk": SensorParams(Sun2PointInTimeSensor, "mdi:weather-sunset-down"),
    "nautical_dusk": SensorParams(Sun2PointInTimeSensor, "mdi:weather-sunset-down"),
    "astronomical_dusk": SensorParams(Sun2PointInTimeSensor, "mdi:weather-sunset-down"),
    # Time periods
    "daylight": SensorParams(Sun2PeriodOfTimeSensor, "mdi:weather-sunny"),
    "civil_daylight": SensorParams(Sun2PeriodOfTimeSensor, "mdi:weather-sunny"),
    "nautical_daylight": SensorParams(Sun2PeriodOfTimeSensor, "mdi:weather-sunny"),
    "astronomical_daylight": SensorParams(Sun2PeriodOfTimeSensor, "mdi:weather-sunny"),
    "night": SensorParams(Sun2PeriodOfTimeSensor, "mdi:weather-night"),
    "civil_night": SensorParams(Sun2PeriodOfTimeSensor, "mdi:weather-night"),
    "nautical_night": SensorParams(Sun2PeriodOfTimeSensor, "mdi:weather-night"),
    "astronomical_night": SensorParams(Sun2PeriodOfTimeSensor, "mdi:weather-night"),
    # Min/Max elevation
    "min_elevation": SensorParams(Sun2MinMaxElevationSensor, "mdi:weather-night"),
    "max_elevation": SensorParams(Sun2MinMaxElevationSensor, "mdi:weather-sunny"),
    # Elevation
    "elevation": SensorParams(Sun2ElevationSensor, None),
    # Phase
    "sun_phase": SensorParams(Sun2PhaseSensor, None),
    "deconz_daylight": SensorParams(Sun2DeconzDaylightSensor, None),
}

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_MONITORED_CONDITIONS): vol.All(
            cv.ensure_list, [vol.In(_SENSOR_TYPES)]
        ),
        **LOC_PARAMS,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up sensors."""
    loc_params = get_loc_params(config)
    namespace = config.get(CONF_ENTITY_NAMESPACE)
    async_add_entities(
        [
            _SENSOR_TYPES[sensor_type].cls(
                loc_params, namespace, sensor_type, _SENSOR_TYPES[sensor_type].icon
            )
            for sensor_type in config[CONF_MONITORED_CONDITIONS]
        ],
        True,
    )
