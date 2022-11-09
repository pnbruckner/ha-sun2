"""Sun2 Sensor."""
from abc import abstractmethod
from datetime import datetime, time, timedelta
import logging

try:
    from astral import SUN_RISING, SUN_SETTING
except ImportError:
    from astral import SunDirection

    SUN_RISING = SunDirection.RISING
    SUN_SETTING = SunDirection.SETTING
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    ATTR_ICON,
    CONF_ELEVATION,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_MONITORED_CONDITIONS,
    CONF_TIME_ZONE,
    DEVICE_CLASS_TIMESTAMP,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .helpers import (
    ATTR_NEXT_CHANGE,
    astral_event,
    nearest_second,
)
from .sun2_sensor import Sun2SensorBase

_LOGGER = logging.getLogger(__name__)
_SOLAR_DEPRESSIONS = ("astronomical", "civil", "nautical")
_ELEV_RND = 0.5
_ELEV_MAX_ERR = 0.02
_DELTA = timedelta(minutes=5)
_ONE_DAY = timedelta(days=1)
_HALF_DAY = timedelta(days=0.5)

ATTR_RISING = "rising"
ATTR_DAYLIGHT = "daylight"
ATTR_BLUE_HOUR = "blue_hour"
ATTR_GOLDEN_HOUR = "golden_hour"


def next_midnight(dt):
    return datetime.combine(dt.date() + _ONE_DAY, time(), dt.tzinfo)


class Sun2Sensor(Sun2SensorBase, Entity):
    """Sun2 Sensor."""

    @abstractmethod
    def __init__(self, hass, sensor_type, icon, info, default_solar_depression=0):
        """Initialize sensor."""
        super().__init__(hass, sensor_type.replace("_", " ").title(), info)

        if any(sol_dep in sensor_type for sol_dep in _SOLAR_DEPRESSIONS):
            self._solar_depression, self._event = sensor_type.rsplit("_", 1)
        else:
            self._solar_depression = default_solar_depression
            self._event = sensor_type
        self._icon = icon
        self._yesterday = None
        self._today = None
        self._tomorrow = None

    @property
    def state(self):
        """Return the state of the entity."""
        return self._state

    def _device_state_attributes(self):
        return {
            "yesterday": self._yesterday,
            "today": self._today,
            "tomorrow": self._tomorrow,
        }

    @property
    def icon(self):
        """Return the icon to use in the frontend."""
        return self._icon

    def _setup_fixed_updating(self):
        # Default behavior is to update every midnight.
        # Override for sensor types that should update at a different time,
        # or that have a more dynamic update schedule (in which case override
        # with a method that does nothing and set up the update at the end of
        # an override of _update instead.)

        @callback
        def async_schedule_update_at_midnight(now):
            next_midn = next_midnight(now.astimezone(self._tzinfo))
            self._unsub_update = async_track_point_in_utc_time(
                self.hass, async_schedule_update_at_midnight, next_midn
            )
            self.async_schedule_update_ha_state(True)

        next_midn = next_midnight(dt_util.now(self._tzinfo))
        self._unsub_update = async_track_point_in_utc_time(
            self.hass, async_schedule_update_at_midnight, next_midn
        )

    def _get_astral_event(self, event, date_or_dttm):
        return astral_event(self._info, event, date_or_dttm, self._solar_depression)

    def _get_data(self, date_or_dttm):
        return self._get_astral_event(self._event, date_or_dttm)

    def _update(self, cur_dttm):
        cur_date = cur_dttm.date()
        self._yesterday = self._get_data(cur_date - _ONE_DAY)
        self._state = self._today = self._get_data(cur_date)
        self._tomorrow = self._get_data(cur_date + _ONE_DAY)

    async def async_update(self):
        """Update state."""
        self._update(dt_util.now(self._tzinfo))


class Sun2PointInTimeSensor(Sun2Sensor):
    """Sun2 Point in Time Sensor."""

    def __init__(self, hass, sensor_type, icon, info):
        """Initialize sensor."""
        super().__init__(hass, sensor_type, icon, info, "civil")

    @property
    def device_class(self):
        """Return the class of this device."""
        return DEVICE_CLASS_TIMESTAMP

    def _update(self, cur_dttm):
        super()._update(cur_dttm)
        if self._state != "none":
            self._state = self._state.isoformat()


def _hours_to_hms(hours):
    try:
        return str(timedelta(hours=hours)).split(".")[0]
    except TypeError:
        return None


class Sun2PeriodOfTimeSensor(Sun2Sensor):
    """Sun2 Period of Time Sensor."""

    def __init__(self, hass, sensor_type, icon, info):
        """Initialize sensor."""
        super().__init__(hass, sensor_type, icon, info, 0.833)

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return "hr"

    def _device_state_attributes(self):
        data = super()._device_state_attributes()
        data.update(
            {
                "yesterday_hms": _hours_to_hms(data["yesterday"]),
                "today_hms": _hours_to_hms(data["today"]),
                "tomorrow_hms": _hours_to_hms(data["tomorrow"]),
            }
        )
        return data

    def _get_data(self, date_or_dttm):
        if "daylight" in self._event:
            start = self._get_astral_event("dawn", date_or_dttm)
            end = self._get_astral_event("dusk", date_or_dttm)
        else:
            start = self._get_astral_event("dusk", date_or_dttm)
            end = self._get_astral_event("dawn", date_or_dttm + _ONE_DAY)
        if "none" in (start, end):
            return None
        return (end - start).total_seconds() / 3600

    def _update(self, cur_dttm):
        super()._update(cur_dttm)
        if self._state is not None:
            self._state = round(self._state, 3)


class Sun2MinMaxElevationSensor(Sun2Sensor):
    """Sun2 Min/Max Elevation Sensor."""

    @abstractmethod
    def __init__(self, hass, sensor_type, icon, info, is_min):
        """Initialize sensor."""
        super().__init__(hass, sensor_type, icon, info)
        self._event = "solar_midnight" if is_min else "solar_noon"

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return "°"

    def _get_data(self, date_or_dttm):
        event_dttm = self._get_astral_event(self._event, date_or_dttm)
        return self._get_astral_event("solar_elevation", event_dttm)

    def _update(self, cur_dttm):
        super()._update(cur_dttm)
        if self._state is not None:
            self._state = round(self._state, 3)


class Sun2MinElevationSensor(Sun2MinMaxElevationSensor):
    """Sun2 Min Elevation Sensor."""

    def __init__(self, hass, sensor_type, icon, info):
        """Initialize sensor."""
        super().__init__(hass, sensor_type, icon, info, is_min=True)


class Sun2MaxElevationSensor(Sun2MinMaxElevationSensor):
    """Sun2 Max Elevation Sensor."""

    def __init__(self, hass, sensor_type, icon, info):
        """Initialize sensor."""
        super().__init__(hass, sensor_type, icon, info, is_min=False)


def _nearest_multiple(value, multiple):
    return int(round(value / multiple)) * multiple


def _get_dttm_at_elev(info, name, tL_dttm, tR_dttm, t0_dttm, t1_dttm, elev, max_err):
    t0_elev = astral_event(info, "solar_elevation", t0_dttm)
    t1_elev = astral_event(info, "solar_elevation", t1_dttm)
    est_elev = elev + 1.5 * max_err
    while abs(est_elev - elev) >= max_err:
        try:
            est_dttm = nearest_second(
                t0_dttm + (t1_dttm - t0_dttm) * ((elev - t0_elev) / (t1_elev - t0_elev))
            )
            est_elev = astral_event(info, "solar_elevation", est_dttm)
            _LOGGER.debug(
                "%s: trg = %+7.3f: t0 = %s/%+7.3f, t1 = %s/%+7.3f -> est = %s/%+7.3f[%+7.3f]",
                name,
                elev,
                t0_dttm,
                t0_elev,
                t1_dttm,
                t1_elev,
                est_dttm,
                est_elev,
                est_elev - elev,
            )
        except ZeroDivisionError:
            _LOGGER.debug(
                "%s: trg = %+7.3f: t0 = %s/%+7.3f, t1 = %s/%+7.3f -> ZeroDivisionError",
                name,
                elev,
                t0_dttm,
                t0_elev,
                t1_dttm,
                t1_elev,
            )
            return None
        if est_dttm < tL_dttm or est_dttm > tR_dttm:
            _LOGGER.debug(
                "%s: trg = %+7.3f: t0 = %s/%+7.3f, t1 = %s/%+7.3f -> outside range",
                name,
                elev,
                t0_dttm,
                t0_elev,
                t1_dttm,
                t1_elev,
            )
            return None
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


class Sun2ElevationSensor(Sun2Sensor):
    """Sun2 Elevation Sensor."""

    def __init__(self, hass, sensor_type, icon, info):
        """Initialize sensor."""
        super().__init__(hass, sensor_type, icon, info)
        self._reset()

    def _reset(self):
        self._prv_sol_midn = None
        self._sol_noon = None
        self._sol_midn = None
        self._prv_dttm = None
        self._next_change = None

    def _device_state_attributes(self):
        return {ATTR_NEXT_CHANGE: self._next_change}

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return "°"

    def _loc_updated(self):
        """Location updated."""
        self._reset()
        super()._loc_updated()

    def _setup_fixed_updating(self):
        pass

    def _update(self, cur_dttm):
        # Astral package ignores microseconds, so round to nearest second
        # before continuing.
        cur_dttm = nearest_second(cur_dttm)
        cur_elev = astral_event(self._info, "solar_elevation", cur_dttm)
        self._state = f"{cur_elev:0.1f}"
        _LOGGER.debug("%s: Raw elevation = %f -> %s", self.name, cur_elev, self._state)

        # Find the next solar midnight AFTER the current time, and the solar noon and
        # solar midnight that precede it. This only needs to be done once a day when we
        # reach or pass the previously determined solar midnight.
        if not self._sol_midn or cur_dttm >= self._sol_midn:
            date = cur_dttm.date()
            # solar_midnight() returns the solar midnight (which is when the
            # sun reaches its lowest point) nearest to the start of today. Note
            # that it may have occurred yesterday.
            self._sol_midn = astral_event(self._info, "solar_midnight", date)
            while self._sol_midn <= cur_dttm:
                date += _ONE_DAY
                self._sol_midn = astral_event(self._info, "solar_midnight", date)
            self._sol_noon = astral_event(self._info, "solar_noon", date - _ONE_DAY)
            self._prv_sol_midn = astral_event(
                self._info, "solar_midnight", date - _ONE_DAY
            )
            _LOGGER.debug(
                "%s: Solar midnight/noon/midnight: %s/%0.3f, %s/%0.3f, %s/%0.3f",
                self.name,
                self._prv_sol_midn,
                astral_event(self._info, "solar_elevation", self._prv_sol_midn),
                self._sol_noon,
                astral_event(self._info, "solar_elevation", self._sol_noon),
                self._sol_midn,
                astral_event(self._info, "solar_elevation", self._sol_midn),
            )

        def get_nxt_dttm(elev, tL_dttm, tR_dttm):
            if self._prv_dttm < tL_dttm:
                return None
            return _get_dttm_at_elev(
                self._info,
                self.name,
                tL_dttm,
                tR_dttm,
                self._prv_dttm,
                cur_dttm,
                elev,
                _ELEV_MAX_ERR,
            )

        if self._prv_dttm:
            # Extrapolate based on previous point and current point to find
            # next point.
            rnd_elev = _nearest_multiple(cur_elev, _ELEV_RND)
            if cur_dttm < self._sol_noon:
                nxt_dttm = get_nxt_dttm(
                    rnd_elev + _ELEV_RND, self._prv_sol_midn, self._sol_noon
                )
            else:
                nxt_dttm = get_nxt_dttm(
                    rnd_elev - _ELEV_RND, self._sol_noon, self._sol_midn
                )
        else:
            nxt_dttm = None

        if not nxt_dttm:
            if self._sol_noon - _DELTA <= cur_dttm < self._sol_noon:
                nxt_dttm = self._sol_noon
            elif self._sol_midn - _DELTA <= cur_dttm:
                nxt_dttm = self._sol_midn
            else:
                nxt_dttm = cur_dttm + _DELTA

        self._prv_dttm = cur_dttm

        self._next_change = dt_util.as_local(nxt_dttm)

        @callback
        def async_schedule_update(now):
            self._unsub_update = None
            self.async_schedule_update_ha_state(True)

        self._unsub_update = async_track_point_in_utc_time(
            self.hass, async_schedule_update, nxt_dttm
        )


class Sun2PhaseSensorBase(Sun2Sensor):
    """Sun2 Phase Sensor Base."""

    class Data:
        """Unique data to each subclass that is determined once at initialization."""

        __slots__ = ("rising_elevs", "rising_states", "falling_elevs", "falling_states")

    class Parameters:
        """
        Parameters common to all subclasses that describes current portion of
        elevation curve, determined at update time, after crossing solar noon
        or solar midnight.
        """

        __slots__ = (
            "tL_dttm",
            "tL_elev",
            "tR_dttm",
            "tR_elev",
            "mid_date",
            "nxt_noon",
            "rising",
        )

    @abstractmethod
    def __init__(self, hass, sensor_type, icon, info):
        """Initialize sensor."""
        super().__init__(hass, sensor_type, icon, info)
        self._attrs = {}
        self._d = __class__.Data()
        self._p = __class__.Parameters()
        self._updates = []

    def _device_state_attributes(self):
        return self._attrs

    def _setup_fixed_updating(self):
        pass

    def _state_at_elev(self, elev):
        if self._p.rising:
            return list(filter(lambda x: elev >= x[0], self._d.rising_states))[-1][1]
        else:
            return list(filter(lambda x: elev <= x[0], self._d.falling_states))[-1][1]

    @abstractmethod
    def _attrs_at_elev(self, elev):
        if self._p.rising:
            if elev < -18:
                icon = "mdi:weather-night"
            elif elev < -0.833:
                icon = "mdi:weather-sunset-up"
            else:
                icon = "mdi:weather-sunny"
        else:
            if elev > -0.833:
                icon = "mdi:weather-sunny"
            elif elev > -18:
                icon = "mdi:weather-sunset-down"
            else:
                icon = "mdi:weather-night"
        return {ATTR_ICON: icon}

    def _set_attrs(self, attrs):
        self._attrs = {ATTR_NEXT_CHANGE: dt_util.as_local(self._updates[0][1])}
        icon = attrs.pop(ATTR_ICON, None)
        if icon:
            self._icon = icon
        self._attrs.update(attrs)

    def _calc_elev_curve_params(self, cur_dttm, cur_elev):
        cur_date = cur_dttm.date()

        # Find the highest and lowest points on the elevation curve that encompass
        # current time, where it is ok for the current time to be the same as the
        # first of these two points.
        # Note that the astral solar_midnight event will always come before the astral
        # solar_noon event for any given date, even if it actually falls on the previous
        # day.
        hi_dttm = astral_event(self._info, "solar_noon", cur_date)
        lo_dttm = astral_event(self._info, "solar_midnight", cur_date)
        nxt_noon = astral_event(self._info, "solar_noon", cur_date + _ONE_DAY)
        if cur_dttm < lo_dttm:
            self._p.tL_dttm = astral_event(
                self._info, "solar_noon", cur_date - _ONE_DAY
            )
            self._p.tR_dttm = lo_dttm
        elif cur_dttm < hi_dttm:
            self._p.tL_dttm = lo_dttm
            self._p.tR_dttm = hi_dttm
        else:
            lo_dttm = astral_event(self._info, "solar_midnight", cur_date + _ONE_DAY)
            if cur_dttm < lo_dttm:
                self._p.tL_dttm = hi_dttm
                self._p.tR_dttm = lo_dttm
            else:
                self._p.tL_dttm = lo_dttm
                self._p.tR_dttm = nxt_noon
        self._p.tL_elev = astral_event(self._info, "solar_elevation", self._p.tL_dttm)
        self._p.tR_elev = astral_event(self._info, "solar_elevation", self._p.tR_dttm)
        self._p.mid_date = (self._p.tL_dttm + (self._p.tR_dttm - self._p.tL_dttm) / 2).date()
        self._p.nxt_noon = nxt_noon
        self._p.rising = self._p.tR_elev > self._p.tL_elev

        _LOGGER.debug(
            "%s: tL = %s/%0.3f, cur = %s/%0.3f, tR = %s/%0.3f, rising = %s",
            self.name,
            self._p.tL_dttm,
            self._p.tL_elev,
            cur_dttm,
            cur_elev,
            self._p.tR_dttm,
            self._p.tR_elev,
            self._p.rising,
        )

    @callback
    def _async_do_update(self, now):
        _, _, state, attrs = self._updates.pop(0)
        if self._updates:
            self._state = state
            self._set_attrs(attrs)
            self.async_write_ha_state()
        else:
            self.async_schedule_update_ha_state(True)

    def _setup_update_at_time(self, update_dttm, state=None, attrs=None):
        self._updates.append(
            (
                async_track_point_in_utc_time(
                    self.hass, self._async_do_update, update_dttm
                ),
                update_dttm,
                state,
                attrs,
            )
        )

    def _setup_update_at_elev(self, elev):
        # Try to find a close approximation for when the sun will reach the given
        # elevation. This should allow _get_dttm_at_elev to converge more quickly.
        try:
            def get_est_dttm(offset=None):
                return nearest_second(
                    astral_event(
                        self._info,
                        "time_at_elevation",
                        self._p.mid_date + offset if offset else self._p.mid_date,
                        elevation=elev,
                        direction=SUN_RISING if self._p.rising else SUN_SETTING,
                    )
                )

            est_dttm = get_est_dttm()
            if not self._p.tL_dttm <= est_dttm < self._p.tR_dttm:
                est_dttm = get_est_dttm(
                    _ONE_DAY if est_dttm < self._p.tL_dttm else -_ONE_DAY
                )
                if not self._p.tL_dttm <= est_dttm < self._p.tR_dttm:
                    raise ValueError
        except (TypeError, ValueError) as exc:
            if isinstance(exc, TypeError):
                # time_at_elevation doesn't always work around solar midnight & solar
                # noon.
                _LOGGER.debug(
                    "%s: time_at_elevation(%0.3f) returned none", self.name, elev
                )
            else:
                _LOGGER.debug(
                    "%s: time_at_elevation(%0.3f) outside [tL, tR): %s",
                    self.name,
                    elev,
                    est_dttm,
                )
            t0_dttm = self._p.tL_dttm
            t1_dttm = self._p.tR_dttm
        else:
            t0_dttm = max(est_dttm - _DELTA, self._p.tL_dttm)
            t1_dttm = min(est_dttm + _DELTA, self._p.tR_dttm)
        update_dttm = _get_dttm_at_elev(
            self._info,
            self.name,
            self._p.tL_dttm,
            self._p.tR_dttm,
            t0_dttm,
            t1_dttm,
            elev,
            0.005,
        )
        if update_dttm:
            self._setup_update_at_time(
                update_dttm, self._state_at_elev(elev), self._attrs_at_elev(elev)
            )
        else:
            _LOGGER.error("%s: Failed to find the time at elev: %0.3f", self.name, elev)

    def _setup_updates(self, cur_dttm, cur_elev):
        if self._p.rising:
            for elev in self._d.rising_elevs:
                if cur_elev < elev < self._p.tR_elev:
                    self._setup_update_at_elev(elev)
        else:
            for elev in self._d.falling_elevs:
                if cur_elev > elev > self._p.tR_elev:
                    self._setup_update_at_elev(elev)

    def _update(self, cur_dttm):
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
        cur_elev = astral_event(self._info, "solar_elevation", cur_dttm)

        self._calc_elev_curve_params(cur_dttm, cur_elev)

        self._state = None
        self._setup_updates(cur_dttm, cur_elev)
        # This last update will not directly update the state, but will rather
        # reschedule aysnc_update() with self._updates being empty so as to make this
        # method run again to create a new schedule of udpates. Therefore we do not
        # need to provide state and attribute values.
        self._setup_update_at_time(self._p.tR_dttm)

        # _setup_updates may have already determined the state.
        if not self._state:
            self._state = self._state_at_elev(cur_elev)
        self._set_attrs(self._attrs_at_elev(cur_elev))

        def cancel_updates():
            for update in self._updates:
                update[0]()
            self._updates = []

        self._unsub_update = cancel_updates

        _LOGGER.debug("%s: _update time: %s", self.name, dt_util.now() - start_update)


class Sun2PhaseSensor(Sun2PhaseSensorBase):
    """Sun2 Phase Sensor."""

    def __init__(self, hass, sensor_type, icon, info):
        """Initialize sensor."""
        super().__init__(hass, sensor_type, icon, info)
        phases = [
            (-90, "Night"),
            (-18, "Astronomical Twilight"),
            (-12, "Nautical Twilight"),
            (-6, "Civil Twilight"),
            (-0.833, "Day"),
            (90, None),
        ]
        elevs, states = zip(*phases)
        self._d.rising_elevs = sorted([*elevs[1:-1], -4, 6])
        self._d.rising_states = phases[:-1]
        self._d.falling_elevs = self._d.rising_elevs[::-1]
        self._d.falling_states = list(zip(elevs[1:], states[:-1]))[::-1]

    def _attrs_at_elev(self, elev):
        attrs = super()._attrs_at_elev(elev)
        if self._p.rising:
            blue_hour = -6 <= elev < -4
            golden_hour = -4 <= elev < 6
        else:
            blue_hour = -6 < elev <= -4
            golden_hour = -4 < elev <= 6
        attrs[ATTR_BLUE_HOUR] = blue_hour
        attrs[ATTR_GOLDEN_HOUR] = golden_hour
        attrs[ATTR_RISING] = self._p.rising
        return attrs


class Sun2DeconzDaylightSensor(Sun2PhaseSensorBase):
    """Sun2 deCONZ Phase Sensor."""

    def __init__(self, hass, sensor_type, icon, info):
        """Initialize sensor."""
        super().__init__(hass, sensor_type, icon, info)
        phases = [
            (-90, "nadir", None),
            (-18, "night_end", "night_start"),
            (-12, "nautical_dawn", "nautical_dusk"),
            (-6, "dawn", "dusk"),
            (-0.833, "sunrise_start", "sunset_end"),
            (-0.3, "sunrise_end", "sunset_start"),
            (6, "golden_hour_1", "golden_hour_2"),
            (90, None, "solar_noon"),
        ]
        elevs, rising_states, falling_states = zip(*phases)
        self._d.rising_elevs = list(elevs[1:-1])
        self._d.rising_states = list(zip(elevs[:-1], rising_states[:-1]))
        self._d.falling_elevs = self._d.rising_elevs[::-1]
        self._d.falling_states = list(zip(elevs[1:], falling_states[1:]))[::-1]

    def _attrs_at_elev(self, elev):
        attrs = super()._attrs_at_elev(elev)
        if self._p.rising:
            daylight = -0.833 <= elev
        else:
            daylight = -0.833 < elev
        attrs[ATTR_DAYLIGHT] = daylight
        return attrs

    def _setup_updates(self, cur_dttm, cur_elev):
        if self._p.rising:
            nadir_dttm = self._p.tR_dttm - _HALF_DAY
            if cur_dttm < nadir_dttm:
                self._state = self._d.falling_states[-1][1]
                nadir_elev = astral_event(self._info, "solar_elevation", nadir_dttm)
                self._setup_update_at_time(
                    nadir_dttm,
                    self._d.rising_states[0][1],
                    self._attrs_at_elev(nadir_elev),
                )
        else:
            nadir_dttm = self._p.nxt_noon - _HALF_DAY
            if cur_dttm >= nadir_dttm:
                self._state = self._d.rising_states[0][1]
        super()._setup_updates(cur_dttm, cur_elev)


_SENSOR_TYPES = {
    # Points in time
    "solar_midnight": (Sun2PointInTimeSensor, "mdi:weather-night"),
    "astronomical_dawn": (Sun2PointInTimeSensor, "mdi:weather-sunset-up"),
    "nautical_dawn": (Sun2PointInTimeSensor, "mdi:weather-sunset-up"),
    "dawn": (Sun2PointInTimeSensor, "mdi:weather-sunset-up"),
    "sunrise": (Sun2PointInTimeSensor, "mdi:weather-sunset-up"),
    "solar_noon": (Sun2PointInTimeSensor, "mdi:weather-sunny"),
    "sunset": (Sun2PointInTimeSensor, "mdi:weather-sunset-down"),
    "dusk": (Sun2PointInTimeSensor, "mdi:weather-sunset-down"),
    "nautical_dusk": (Sun2PointInTimeSensor, "mdi:weather-sunset-down"),
    "astronomical_dusk": (Sun2PointInTimeSensor, "mdi:weather-sunset-down"),
    # Time periods
    "daylight": (Sun2PeriodOfTimeSensor, "mdi:weather-sunny"),
    "civil_daylight": (Sun2PeriodOfTimeSensor, "mdi:weather-sunny"),
    "nautical_daylight": (Sun2PeriodOfTimeSensor, "mdi:weather-sunny"),
    "astronomical_daylight": (Sun2PeriodOfTimeSensor, "mdi:weather-sunny"),
    "night": (Sun2PeriodOfTimeSensor, "mdi:weather-night"),
    "civil_night": (Sun2PeriodOfTimeSensor, "mdi:weather-night"),
    "nautical_night": (Sun2PeriodOfTimeSensor, "mdi:weather-night"),
    "astronomical_night": (Sun2PeriodOfTimeSensor, "mdi:weather-night"),
    # Min/Max elevation
    "min_elevation": (Sun2MinElevationSensor, "mdi:weather-night"),
    "max_elevation": (Sun2MaxElevationSensor, "mdi:weather-sunny"),
    # Elevation
    "elevation": (Sun2ElevationSensor, "mdi:weather-sunny"),
    # Phase
    "sun_phase": (Sun2PhaseSensor, None),
    "deconz_daylight": (Sun2DeconzDaylightSensor, None),
}

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_MONITORED_CONDITIONS): vol.All(
            cv.ensure_list, [vol.In(_SENSOR_TYPES)]
        ),
        vol.Inclusive(CONF_LATITUDE, "location"): cv.latitude,
        vol.Inclusive(CONF_LONGITUDE, "location"): cv.longitude,
        vol.Inclusive(CONF_TIME_ZONE, "location"): cv.time_zone,
        vol.Inclusive(CONF_ELEVATION, "location"): vol.Coerce(float),
    }
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up sensors."""
    if CONF_LATITUDE in config:
        info = (
            config[CONF_LATITUDE],
            config[CONF_LONGITUDE],
            config[CONF_TIME_ZONE],
            config[CONF_ELEVATION],
        )
    else:
        info = None
    # Don't force update now. Wait for first update until async_added_to_hass is called
    # when final name is determined.
    async_add_entities(
        [
            _SENSOR_TYPES[event][0](hass, event, _SENSOR_TYPES[event][1], info)
            for event in config[CONF_MONITORED_CONDITIONS]
        ],
        False,
    )
