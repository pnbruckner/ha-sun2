"""Sun2 Sensor."""
from __future__ import annotations

from abc import abstractmethod
import asyncio
from collections.abc import Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass, make_dataclass
from datetime import date, datetime, time, timedelta
from itertools import chain
from math import fabs
from typing import Any, Generic, TypeVar, cast

from astral import SunDirection
from astral.sun import SUN_APPARENT_RADIUS
from propcache.api import cached_property

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_ICON,
    CONF_NAME,
    CONF_SENSORS,
    CONF_UNIQUE_ID,
    DEGREE,
    EVENT_HOMEASSISTANT_STARTED,
    EVENT_STATE_CHANGED,
    UnitOfTime,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    CoreState,
    Event,
    EventStateChangedData,
    callback,
)
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_BLUE_HOUR,
    ATTR_DAYLIGHT,
    ATTR_GOLDEN_HOUR,
    ATTR_RISING,
    ATTR_TODAY,
    ATTR_TODAY_HMS,
    ATTR_TOMORROW,
    ATTR_TOMORROW_HMS,
    ATTR_YESTERDAY,
    ATTR_YESTERDAY_HMS,
    CONF_DIRECTION,
    CONF_ELEVATION_AT_TIME,
    CONF_TIME_AT_ELEVATION,
    ELEV_STEP,
    ICON_AZIMUTH,
    ICON_DAY,
    ICON_NIGHT,
    ICON_RISING,
    ICON_SETTING,
    LOGGER,
    MAX_UPDATE_TIME,
    ONE_DAY,
    STATE_ASTRO_TW,
    STATE_CIVIL_TW,
    STATE_DAWN,
    STATE_DAY,
    STATE_DUSK,
    STATE_G_HR_1,
    STATE_G_HR_2,
    STATE_NADIR,
    STATE_NAUT_DAWN,
    STATE_NAUT_DUSK,
    STATE_NAUT_TW,
    STATE_NIGHT,
    STATE_NIGHT_END,
    STATE_NIGHT_START,
    STATE_RIS_END,
    STATE_RIS_START,
    STATE_SET_END,
    STATE_SET_START,
    STATE_SOL_NOON,
    SUNSET_ELEV,
)
from .helpers import (
    Num,
    Sun2Entity,
    Sun2EntityParams,
    Sun2EntityWithElvAdjs,
    Sun2EntrySetup,
    hours_to_hms,
    nearest_second,
)

# Cause Semaphore to be created to make async_update, and anything protected by
# async_request_call, atomic.
PARALLEL_UPDATES = 1

_ENABLED_SENSORS = [
    "solar_midnight",
    "dawn",
    "sunrise",
    "solar_noon",
    "sunset",
    "dusk",
    CONF_ELEVATION_AT_TIME,
    CONF_TIME_AT_ELEVATION,
]
_SOLAR_DEPRESSIONS = ("astronomical", "civil", "nautical")

_T = TypeVar("_T")


class Sun2AzimuthSensor(Sun2EntityWithElvAdjs, SensorEntity):
    """Sun2 Azimuth Sensor."""

    _supports_entity_update_action = True

    def __init__(
        self, sun2_entity_params: Sun2EntityParams, sensor_type: str, icon: str | None
    ) -> None:
        """Initialize sensor."""
        name = sensor_type.replace("_", " ").title()
        self.entity_description = SensorEntityDescription(
            key=sensor_type,
            entity_registry_enabled_default=sensor_type in _ENABLED_SENSORS,
            icon=icon,
            name=name,
            native_unit_of_measurement=DEGREE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=2,
        )
        super().__init__(sun2_entity_params)
        if self._auto_update:
            self._attr_extra_state_attributes = {}

    async def _update(self, cur_dttm: datetime, requested: bool) -> None:
        """Update state."""
        if requested:
            self._cancel_update()

        if cur_dttm >= self._nxt_dir_chg_dttm:
            self._change_sun_direction()

        # Astral package ignores microseconds when determining azimuth & solar
        # elevation, so round to nearest second.
        rnd_dttm = nearest_second(cur_dttm)
        self._attr_native_value = self._solar_azimuth(rnd_dttm)

        if not self._auto_update:
            return

        if self._rising:
            threshold = SUN_APPARENT_RADIUS - self._ris_elv_adj
        else:
            threshold = SUN_APPARENT_RADIUS - self._set_elv_adj
        if fabs(self._solar_elevation(rnd_dttm) - threshold) <= 6:
            delta = 2 * 60
        else:
            delta = 10 * 60
        self._schedule_update(cur_dttm + timedelta(seconds=delta))


@dataclass(frozen=True)
class PhaseAttrs:
    """Phase attributes."""


@dataclass(frozen=True)
class PhaseParams:
    """Phase parameters."""

    elv: Num  # elevation at which phase begins
    state: str
    _attrs: PhaseAttrs

    @property
    def attrs(self) -> dict[str, Any]:
        """Return attributes as a dict."""
        return asdict(self._attrs)


class PhaseSensor(Sun2EntityWithElvAdjs, SensorEntity):
    """Phase sensor base."""

    # Rising & setting phase parameters defined by subclass
    _ris_ph_params: Sequence[PhaseParams]
    _set_ph_params: Sequence[PhaseParams]

    _nxt_ph_idx: int | None

    def __init__(
        self, sun2_entity_params: Sun2EntityParams, sensor_type: str, icon: str | None
    ) -> None:
        """Initialize sensor."""
        self.entity_description = SensorEntityDescription(
            key=sensor_type,
            device_class=SensorDeviceClass.ENUM,
            entity_registry_enabled_default=sensor_type in _ENABLED_SENSORS,
            icon=icon,
            options=self._phases,
        )
        super().__init__(sun2_entity_params)

    @cached_property
    def _phases(self) -> list[str]:
        """Return list of phase state values."""
        return sorted(
            {pp.state for pp in self._ris_ph_params}
            | {pp.state for pp in self._set_ph_params}
            | self._extra_states
        )

    @property
    def _extra_states(self) -> set[str]:
        """Return states that are not in phase parameter lists."""
        return set()

    @cached_property
    def _ph_params(self) -> Sequence[PhaseParams]:
        """Return phase parameters list based on rising state."""
        if self._rising:
            return self._ris_ph_params
        return self._set_ph_params

    def _rising_changed(self) -> None:
        """Rising attribute changed."""
        super()._rising_changed()
        with suppress(AttributeError):
            del self._ph_params

    async def _update(self, cur_dttm: datetime, requested: bool) -> None:
        """Update state."""
        if self._first_update:
            # Determine what phase the sensor would have been at the last time the sun
            # direction changed before current time. Then determine what phase the
            # sensor should be now.
            prv_chg_elv = self._solar_elevation(self._prv_dir_chg_dttm)
            prv_chg_idx = self._find_ph_idx(prv_chg_elv)
            cur_elv = self._solar_elevation(cur_dttm)
            self._nxt_ph_idx = self._find_ph_idx(cur_elv)
            # For this first update, indicate that the sun direction just changed only
            # if the two phases determined above are the same.
            chg_dir = self._nxt_ph_idx == prv_chg_idx
        elif self._nxt_ph_idx is None:
            # The sun direction just changed.
            # Determine what phase the sensor should be now.
            cur_elv = self._solar_elevation(cur_dttm)
            self._nxt_ph_idx = self._find_ph_idx(cur_elv)
            chg_dir = True
        else:
            # The sun direction did not just change.
            chg_dir = False

        self._set_state(chg_dir)
        self._attr_icon = self._icon()

        nxt_chg = self._find_next_change()
        # LOGGER.debug("*4*: dt: %s, ris: %s, nxt idx: %s", self._dt, self._rising, self._nxt_ph_idx)
        self._schedule_update(nxt_chg)

    def _find_ph_idx(self, elv: float) -> int | None:
        """Find phase index for elevation."""
        if self._rising:

            def elv_is_before(ph_idx: int) -> bool:
                """Return if elevation is before given phase."""
                return elv < self._ph_params[ph_idx].elv - self._ris_elv_adj

        else:

            def elv_is_before(ph_idx: int) -> bool:
                """Return if elevation is before given phase."""
                return elv > self._ph_params[ph_idx].elv - self._set_elv_adj

        if elv_is_before(0):
            # Phase for elevation is not in list.
            return None
        for ph_idx in range(len(self._ph_params) - 1):
            if elv_is_before(ph_idx + 1):
                return ph_idx
        # Phase for elevation is last entry in list.
        return len(self._ph_params) - 1

    def _find_next_change(self) -> datetime:
        """Find next change.

        Determine which phase comes next and when it happens. Update self._dt,
        self._rising, self._nxt_ph_idx to indicate what the next state should be, and
        return when it will occur.
        """
        nxt_chg: datetime | None = None
        if self._nxt_ph_idx is None:
            # Was not in one of the listed phases (i.e., was "before" first listed phase
            # boundary), so check first listed phase.
            self._nxt_ph_idx = 0
        elif self._nxt_ph_idx < len(self._ph_params) - 1:
            # Was in one of the listed phases except the last one, so check next one.
            self._nxt_ph_idx += 1
        else:
            # Was in the last listed phase, so use solar noon or solar midnight below.
            self._nxt_ph_idx = None
        if self._nxt_ph_idx is not None and not (
            nxt_chg := self._time_at_elevation(self._ph_params[self._nxt_ph_idx].elv)
        ):
            # Next listed phase does not occur today, so use solar noon or solar
            # midnight below.
            self._nxt_ph_idx = None

        # LOGGER.debug("*3*: dt: %s, ris: %s, nxt idx: %s", self._dt, self._rising, self._nxt_ph_idx)

        if self._nxt_ph_idx is None:
            # Couldn't find a phase boundary that happens today, so use solar noon or
            # solar midnight, whichever comes next.
            nxt_chg = self._nxt_dir_chg_dttm
            self._change_sun_direction()

        assert nxt_chg
        return nxt_chg

    @abstractmethod
    def _set_state(self, chg_dir: bool) -> None:
        """Set state based on updated parameters."""

    @abstractmethod
    def _icon(self) -> str:
        """Determine icon based on state."""


Sun2PA_fields = ((ATTR_BLUE_HOUR, bool), (ATTR_GOLDEN_HOUR, bool), (ATTR_RISING, bool))
Sun2PA = make_dataclass("Sun2PA", Sun2PA_fields, bases=(PhaseAttrs,), frozen=True)


class Sun2PhaseSensor(PhaseSensor):
    """Sun2 Phase Sensor."""

    _ris_ph_params = (
        PhaseParams(-18, STATE_ASTRO_TW, Sun2PA(False, False, True)),
        PhaseParams(-12, STATE_NAUT_TW, Sun2PA(False, False, True)),
        PhaseParams(-6, STATE_CIVIL_TW, Sun2PA(True, False, True)),
        PhaseParams(-4, STATE_CIVIL_TW, Sun2PA(False, True, True)),
        PhaseParams(-SUN_APPARENT_RADIUS, STATE_DAY, Sun2PA(False, True, True)),
        PhaseParams(6, STATE_DAY, Sun2PA(False, False, True)),
    )
    _set_ph_params = (
        PhaseParams(6, STATE_DAY, Sun2PA(False, True, False)),
        PhaseParams(-SUN_APPARENT_RADIUS, STATE_CIVIL_TW, Sun2PA(False, True, False)),
        PhaseParams(-4, STATE_CIVIL_TW, Sun2PA(True, False, False)),
        PhaseParams(-6, STATE_NAUT_TW, Sun2PA(False, False, False)),
        PhaseParams(-12, STATE_ASTRO_TW, Sun2PA(False, False, False)),
        PhaseParams(-18, STATE_NIGHT, Sun2PA(False, False, False)),
    )

    def _set_state(self, chg_dir: bool) -> None:
        """Set state based on updated parameters."""
        if self._nxt_ph_idx is None:
            self._attr_native_value = STATE_NIGHT if self._rising else STATE_DAY
            self._attr_extra_state_attributes = asdict(
                Sun2PA(False, False, self._rising)
            )
        else:
            # Just entered one of the listed phases.
            pp = self._ph_params[self._nxt_ph_idx]
            self._attr_native_value = pp.state
            self._attr_extra_state_attributes = pp.attrs

    def _icon(self) -> str:
        """Determine icon based on state."""
        if self._attr_native_value == STATE_NIGHT:
            return ICON_NIGHT
        if self._attr_native_value == STATE_DAY:
            return ICON_DAY
        if cast(bool, self._attr_extra_state_attributes[ATTR_RISING]):
            return ICON_RISING
        return ICON_SETTING


Sun2DA_fields = ((ATTR_DAYLIGHT, bool),)
Sun2DA = make_dataclass("Sun2DA", Sun2DA_fields, bases=(PhaseAttrs,), frozen=True)


class Sun2DeconzDaylightSensor(PhaseSensor):
    """Sun2 deCONZ Phase Sensor."""

    _ris_ph_params = (
        PhaseParams(-18, STATE_NIGHT_END, Sun2DA(False)),
        PhaseParams(-12, STATE_NAUT_DAWN, Sun2DA(False)),
        PhaseParams(-6, STATE_DAWN, Sun2DA(False)),
        PhaseParams(-SUN_APPARENT_RADIUS, STATE_RIS_START, Sun2DA(True)),
        PhaseParams(SUN_APPARENT_RADIUS, STATE_RIS_END, Sun2DA(True)),
        PhaseParams(6, STATE_G_HR_1, Sun2DA(True)),
    )
    _set_ph_params = (
        PhaseParams(6, STATE_G_HR_2, Sun2DA(True)),
        PhaseParams(SUN_APPARENT_RADIUS, STATE_SET_START, Sun2DA(True)),
        PhaseParams(-SUN_APPARENT_RADIUS, STATE_SET_END, Sun2DA(False)),
        PhaseParams(-6, STATE_DUSK, Sun2DA(False)),
        PhaseParams(-12, STATE_NAUT_DUSK, Sun2DA(False)),
        PhaseParams(-18, STATE_NIGHT_START, Sun2DA(False)),
    )

    @property
    def _extra_states(self) -> set[str]:
        """Return states that are not in phase parameter lists."""
        return super()._extra_states | {STATE_NADIR, STATE_SOL_NOON}

    def _set_state(self, chg_dir: bool) -> None:
        """Set state based on updated parameters."""
        if chg_dir:
            self._attr_native_value = STATE_NADIR if self._rising else STATE_SOL_NOON
        else:
            assert self._nxt_ph_idx is not None
        if self._nxt_ph_idx is None:
            self._attr_extra_state_attributes = asdict(Sun2DA(not self._rising))
        else:
            # Just entered one of the listed phases.
            pp = self._ph_params[self._nxt_ph_idx]
            if not chg_dir:
                self._attr_native_value = pp.state
            self._attr_extra_state_attributes = pp.attrs

    def _icon(self) -> str:
        """Determine icon based on state."""
        if self._attr_native_value in (STATE_NADIR, STATE_NIGHT_START):
            return ICON_NIGHT
        if cast(bool, self._attr_extra_state_attributes[ATTR_DAYLIGHT]):
            return ICON_DAY
        if self._attr_native_value in (STATE_NIGHT_END, STATE_NAUT_DAWN, STATE_DAWN):
            return ICON_RISING
        return ICON_SETTING


class Sun2SensorEntityWithYTT(Sun2Entity, SensorEntity, Generic[_T]):
    """Sun2 Sensor Entity with yesterday, today & tomorrow attributes."""

    _reschedule_at_midnight = True

    _attr_native_value: _T | None  # type: ignore[assignment]
    _yesterday: _T | None = None
    _today: _T | None = None
    _tomorrow: _T | None = None

    @abstractmethod
    def __init__(
        self,
        sun2_entity_params: Sun2EntityParams,
        entity_description: SensorEntityDescription,
        name: str | None = None,
    ) -> None:
        """Initialize sensor."""
        if name:
            self._attr_name = name
        self._attr_entity_registry_enabled_default = (
            entity_description.key in _ENABLED_SENSORS
        )
        self.entity_description = entity_description
        super().__init__(sun2_entity_params)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return entity specific state attributes."""
        return {
            ATTR_YESTERDAY: self._yesterday,
            ATTR_TODAY: self._today,
            ATTR_TOMORROW: self._tomorrow,
        }


class Sun2ElevationAtTimeSensor(Sun2SensorEntityWithYTT[float]):
    """Sun2 Elevation at Time Sensor."""

    _at_time: time | datetime | None = None
    _input_datetime: str | None = None
    _unsub_track: CALLBACK_TYPE | None = None
    _unsub_listen: CALLBACK_TYPE | None = None

    def __init__(
        self,
        sun2_entity_params: Sun2EntityParams,
        name: str | None,
        at_time: str | time,
    ) -> None:
        """Initialize sensor."""
        if isinstance(at_time, str):
            self._input_datetime = at_time
        else:
            self._at_time = at_time
        entity_description = SensorEntityDescription(
            key=CONF_ELEVATION_AT_TIME,
            icon=ICON_DAY,
            native_unit_of_measurement=DEGREE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=2,
        )
        super().__init__(sun2_entity_params, entity_description, name=name)

        if not name:
            self._attr_translation_key = CONF_ELEVATION_AT_TIME + "_name"
            self._attr_translation_placeholders = {"elev_time": str(at_time)}

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return entity specific state attributes."""
        if isinstance(self._at_time, datetime):
            return None
        return super().extra_state_attributes

    def _cancel_update(self) -> None:
        """Cancel update."""
        super()._cancel_update()
        if self._unsub_track:
            self._unsub_track()
            self._unsub_track = None
        if self._unsub_listen:
            self._unsub_listen()
            self._unsub_listen = None

    def _update_setup(self, cur_dttm: datetime) -> None:
        """Set up before first update.

        Update _at_time parameter per input_datetime (if configured).
        """
        super()._update_setup(cur_dttm)
        if not self._input_datetime:
            assert isinstance(self._at_time, time)
            return

        @callback
        def update_at_time_param(
            event: Event | Event[EventStateChangedData] | None = None,
        ) -> None:
            """Update time from input_datetime entity."""
            at_time_was = self._at_time

            self._at_time = None
            if event and event.event_type == EVENT_STATE_CHANGED:
                state = event.data["new_state"]
            else:
                assert self._input_datetime
                state = self.hass.states.get(self._input_datetime)
            if not state:
                if event and event.event_type == EVENT_STATE_CHANGED:
                    LOGGER.error("%s: %s deleted", self._log_name, self._input_datetime)
                elif self.hass.state == CoreState.running:
                    LOGGER.error(
                        "%s: %s not found", self._log_name, self._input_datetime
                    )
                else:
                    self._unsub_listen = self.hass.bus.async_listen(
                        EVENT_HOMEASSISTANT_STARTED, update_at_time_param
                    )
            elif not state.attributes["has_time"]:
                LOGGER.error(
                    "%s: %s missing time attributes",
                    self._log_name,
                    self._input_datetime,
                )
            elif state.attributes["has_date"]:
                self._at_time = datetime(
                    state.attributes["year"],
                    state.attributes["month"],
                    state.attributes["day"],
                    state.attributes["hour"],
                    state.attributes["minute"],
                    state.attributes["second"],
                )
            else:
                self._at_time = time(
                    state.attributes["hour"],
                    state.attributes["minute"],
                    state.attributes["second"],
                )

            if event and self._at_time != at_time_was:
                self.async_schedule_update_ha_state(True)

        self._unsub_track = async_track_state_change_event(
            self.hass,
            self._input_datetime,
            update_at_time_param,
        )
        update_at_time_param()

    async def _update(self, cur_dttm: datetime, requested: bool) -> None:
        """Update state."""
        if not self._at_time:
            self._yesterday = None
            self._attr_native_value = self._today = None
            self._tomorrow = None
            return
        if isinstance(self._at_time, datetime):
            dttm = self._at_time
        else:
            dttm = datetime.combine(cur_dttm.date(), self._at_time)
        self._attr_native_value = self._solar_elevation(dttm)
        if isinstance(self._at_time, datetime):
            return
        self._yesterday = self._solar_elevation(dttm - ONE_DAY)
        self._today = self._attr_native_value
        self._tomorrow = self._solar_elevation(dttm + ONE_DAY)


class Sun2SensorEntityWithUpdate(Sun2SensorEntityWithYTT[_T]):
    """Sun2 Sensor Entity with update methods."""

    async def _update(self, cur_dttm: datetime, requested: bool) -> None:
        """Update state."""
        cur_date = self._as_tz(cur_dttm).date()
        if self._first_update:
            self._yesterday = self._astral_event(cur_date - ONE_DAY)
            self._today = self._astral_event(cur_date)
        else:
            self._yesterday = self._today
            self._today = self._tomorrow
        self._tomorrow = self._astral_event(cur_date + ONE_DAY)
        self._attr_native_value = self._today

    @abstractmethod
    def _astral_event(self, dt: date) -> _T | None:
        """Return astral event result."""


class Sun2SensorEntityWithEvent(Sun2SensorEntityWithUpdate[_T]):
    """Sun2 Sensor Entity with update methods, event & solar depression."""

    _event: str
    _solar_depression: Num | str

    def __init__(
        self,
        sun2_entity_params: Sun2EntityParams,
        entity_description: SensorEntityDescription,
        default_solar_depression: Num | str = "civil",
        name: str | None = None,
    ) -> None:
        """Initialize sensor."""
        super().__init__(sun2_entity_params, entity_description, name)
        key = entity_description.key
        if any(key.startswith(sol_dep + "_") for sol_dep in _SOLAR_DEPRESSIONS):
            self._solar_depression, self._event = key.rsplit("_", 1)
        else:
            self._solar_depression = default_solar_depression
            self._event = key


class Sun2PointInTimeSensor(Sun2SensorEntityWithEvent[datetime]):
    """Sun2 Point in Time Sensor."""

    _future_date: date | None = None
    _future_value: datetime | None = None

    def __init__(
        self,
        sun2_entity_params: Sun2EntityParams,
        sensor_type: str,
        icon: str | None,
        name: str | None = None,
    ) -> None:
        """Initialize sensor."""
        entity_description = SensorEntityDescription(
            key=sensor_type,
            device_class=SensorDeviceClass.TIMESTAMP,
            icon=icon,
        )
        super().__init__(sun2_entity_params, entity_description, name=name)

    async def _update(self, cur_dttm: datetime, requested: bool) -> None:
        """Update state."""
        cur_date = self._as_tz(cur_dttm).date()

        # Did last update result in checking for a future event?
        if self._future_date:
            # Yes. That means self._today & self._tomorrow were both None.

            # TODO: Remove these assert's.
            assert not self._today and not self._tomorrow

            # No need to use parent's _update method. However, still need to set
            # yesterday to "yesterday's today", which in this case is None.
            self._yesterday = None

            # Did last check find a future event?
            if self._future_value:
                # Yes. That means the sensor's state was set to that future value. I.e.,
                # it was determined the next event happens sometime in the future, but
                # somewhere beyond yesterday's tomorrow (i.e., today.)

                # TODO: Remove these assert's.
                assert self._attr_native_value == self._future_value

                # Has tomorrow made it to that future date?
                if cur_date + ONE_DAY == self._future_date:
                    self._tomorrow = self._future_value
                    self._future_date = None
                    self._future_value = None
            else:
                # No. The sensor's state is None (aka, unknown.) Also, warning has
                # already been issued that event does not occur within the next year.

                # TODO: Remove these assert's.
                assert not self._attr_native_value

                # Check one more day.
                self._check_for_future_event(self._future_date + ONE_DAY)
            return

        # No. Continue normally.
        await super()._update(cur_dttm, requested)
        if self._today:
            return

        # Event does not happen today. Does it happen tomorrow?
        if self._tomorrow:
            self._attr_native_value = self._tomorrow
            return

        # Event does not occur today or tomorrow.
        # Look for next time the event occurs in the future up to one year beyond today,
        # starting with the day after tomorrow.
        self._future_date = cur_date + ONE_DAY
        try_until = dt_util.utcnow() + MAX_UPDATE_TIME
        for _ in range(365):
            self._check_for_future_event(self._future_date + ONE_DAY)
            if self._future_value:
                self._attr_native_value = self._future_value
                return

            if dt_util.utcnow() >= try_until:
                # Give someone else a turn!
                await asyncio.sleep(0)
                try_until = dt_util.utcnow() + MAX_UPDATE_TIME

        LOGGER.warning("%s does not occur within the next year", self._log_name)

    def _check_for_future_event(self, chk_date: date) -> None:
        """Check if event happens on future date."""
        self._future_date = chk_date
        self._future_value = self._astral_event(chk_date)
        if self._future_value:
            LOGGER.debug(
                "%s: Does not occur again until %s",
                self._log_name,
                self._dttm_2_str(self._future_value),
            )

    def _astral_event(self, dt: date) -> datetime | None:
        """Return astral event result."""
        match self._event:
            case "dawn":
                result = self._dawn(dt, self._solar_depression, rnd=True)
            case "dusk":
                result = self._dusk(dt, self._solar_depression, rnd=True)
            case "solar_midnight":
                result = self._solar_midnight(dt, rnd=True)
            case "solar_noon":
                result = self._solar_noon(dt, rnd=True)
            case "sunrise":
                result = self._sunrise(dt, rnd=True)
            case "sunset":
                result = self._sunset(dt, rnd=True)
            case _:
                raise RuntimeError("Unexpected event type")
        if result is None:
            return None
        return self._as_tz(result)


class Sun2TimeAtElevationSensor(Sun2PointInTimeSensor):
    """Sun2 Time at Elevation Sensor."""

    def __init__(
        self,
        sun2_entity_params: Sun2EntityParams,
        name: str | None,
        icon: str | None,
        direction: SunDirection,
        elevation: float,
    ) -> None:
        """Initialize sensor."""
        if not icon:
            icon = {
                SunDirection.RISING: ICON_RISING,
                SunDirection.SETTING: ICON_SETTING,
            }[direction]
        self._direction = direction
        self._elevation = elevation
        super().__init__(sun2_entity_params, CONF_TIME_AT_ELEVATION, icon, name)

        if not name:
            suffix = f"{direction.name.lower()}_{'neg' if elevation < 0 else 'pos'}"
            self._attr_translation_key = f"{CONF_TIME_AT_ELEVATION}_{suffix}"
            self._attr_translation_placeholders = {"elevation": str(abs(elevation))}

    def _astral_event(self, dt: date) -> datetime | None:
        if (
            result := self._time_at_elevation(
                self._elevation, dt=dt, direction=self._direction, rnd=True
            )
        ) is None:
            return None
        return self._as_tz(result)


class Sun2PeriodOfTimeSensor(Sun2SensorEntityWithEvent[float]):
    """Sun2 Period of Time Sensor."""

    def __init__(
        self, sun2_entity_params: Sun2EntityParams, sensor_type: str, icon: str | None
    ) -> None:
        """Initialize sensor."""
        entity_description = SensorEntityDescription(
            key=sensor_type,
            device_class=SensorDeviceClass.DURATION,
            icon=icon,
            native_unit_of_measurement=UnitOfTime.HOURS,
            state_class=SensorStateClass.MEASUREMENT,
        )
        super().__init__(sun2_entity_params, entity_description, SUN_APPARENT_RADIUS)

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

    def _astral_event(self, dt: date) -> float | None:
        """Return astral event result."""
        if self._event == "daylight":
            start = self._dawn(dt, self._solar_depression)
            end = self._dusk(dt, self._solar_depression)
        else:
            start = self._dusk(dt, self._solar_depression)
            end = self._dawn(dt + ONE_DAY, self._solar_depression)
        if not start or not end:
            return None
        return (end - start).total_seconds() / 3600


class Sun2MinMaxElevationSensor(Sun2SensorEntityWithUpdate[float]):
    """Sun2 Min/Max Elevation Sensor."""

    def __init__(
        self, sun2_entity_params: Sun2EntityParams, sensor_type: str, icon: str | None
    ) -> None:
        """Initialize sensor."""
        entity_description = SensorEntityDescription(
            key=sensor_type,
            icon=icon,
            native_unit_of_measurement=DEGREE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=3,
        )
        super().__init__(sun2_entity_params, entity_description)
        if sensor_type == "min_elevation":
            self._method = self._solar_midnight
        else:
            self._method = self._solar_noon

    def _astral_event(self, dt: date) -> float:
        """Return astral event result."""
        return self._solar_elevation(self._method(dt))


class Sun2SunriseSunsetAzimuthSensor(Sun2SensorEntityWithUpdate[float]):
    """Sun2 Azimuth at Sunrise or Sunset Sensor."""

    def __init__(
        self, sun2_entity_params: Sun2EntityParams, sensor_type: str, icon: str | None
    ) -> None:
        """Initialize sensor."""
        entity_description = SensorEntityDescription(
            key=sensor_type,
            icon=icon,
            native_unit_of_measurement=DEGREE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=2,
        )
        super().__init__(sun2_entity_params, entity_description)
        if sensor_type == "sunrise_azimuth":
            self._method = self._sunrise
        else:
            self._method = self._sunset

    def _astral_event(self, dt: date) -> float | None:
        """Return astral event result."""
        # Get sunrise or sunset time.
        # Configured observer elevation should not be used because there is no way to
        # know if it was valid yesterday or will be valid tomorrow since it is very
        # possible the state of this sensor will be used to automatically change it
        # throughout the year. This also avoids a potentially infinite feedback loop.
        if not (dttm := self._method(dt, observer_elevation=0.0)):
            return None
        return self._solar_azimuth(dttm)


class Sun2ElevationSensor(Sun2EntityWithElvAdjs, SensorEntity):
    """Sun2 Elevation Sensor."""

    _supports_entity_update_action = True

    # Only used when "polling" is not disabled by user.
    _nxt_elv: float

    def __init__(
        self, sun2_entity_params: Sun2EntityParams, sensor_type: str, icon: str | None
    ) -> None:
        """Initialize sensor."""
        self.entity_description = SensorEntityDescription(
            key=sensor_type,
            entity_registry_enabled_default=False,
            icon=icon,
            native_unit_of_measurement=DEGREE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        )
        super().__init__(sun2_entity_params)
        if self._auto_update:
            self._attr_extra_state_attributes = {}

    async def _update(self, cur_dttm: datetime, requested: bool) -> None:
        """Update state."""
        # Astral package ignores microseconds when determining solar elevation, so round
        # to nearest second.
        self._attr_native_value = raw_elv = self._solar_elevation(cur_dttm)

        if requested or not self._auto_update:
            self._attr_icon = self._icon(raw_elv)
            return

        # NOTE: Requested updates cannot happen before entity has had a chance to
        #       complete its first update.
        if self._first_update:
            self._nxt_elv = round(raw_elv, 1)
        else:
            LOGGER.debug("%s: target was: %0.1f", self._log_name, self._nxt_elv)

        # Base icon on targeted value, since raw value may be "before" target due to
        # inaccuracies in time_at_elevation.
        self._attr_icon = self._icon(self._nxt_elv)

        # Move elevation by desired step. If that elevation does not occur today, then
        # move to next solar noon or solar midnight event.
        if self._rising:
            self._nxt_elv = round(self._nxt_elv / ELEV_STEP) * ELEV_STEP + ELEV_STEP
        else:
            self._nxt_elv = round(self._nxt_elv / ELEV_STEP) * ELEV_STEP - ELEV_STEP
        if not (nxt_chg := self._time_at_elevation(self._nxt_elv, adj_elv=False)):
            nxt_chg = self._nxt_dir_chg_dttm
            self._change_sun_direction()
            self._nxt_elv = round(self._solar_elevation(nearest_second(nxt_chg)), 1)

        assert nxt_chg > cur_dttm

        self._schedule_update(nxt_chg)

    def _icon(self, elev: Num) -> str:
        """Return icon for elevation."""
        if self._rising:
            if elev < -18:
                return ICON_NIGHT
            if elev < SUNSET_ELEV:
                return ICON_RISING
            return ICON_DAY
        if elev > SUNSET_ELEV:
            return ICON_DAY
        if elev > -18:
            return ICON_SETTING
        return ICON_NIGHT


@dataclass
class SensorParams:
    """Parameters for sensor types."""

    cls: type
    icon: str | None


_SENSOR_TYPES = {
    # Points in time
    "solar_midnight": SensorParams(Sun2PointInTimeSensor, ICON_NIGHT),
    "astronomical_dawn": SensorParams(Sun2PointInTimeSensor, ICON_RISING),
    "nautical_dawn": SensorParams(Sun2PointInTimeSensor, ICON_RISING),
    "dawn": SensorParams(Sun2PointInTimeSensor, ICON_RISING),
    "sunrise": SensorParams(Sun2PointInTimeSensor, ICON_RISING),
    "solar_noon": SensorParams(Sun2PointInTimeSensor, ICON_DAY),
    "sunset": SensorParams(Sun2PointInTimeSensor, ICON_SETTING),
    "dusk": SensorParams(Sun2PointInTimeSensor, ICON_SETTING),
    "nautical_dusk": SensorParams(Sun2PointInTimeSensor, ICON_SETTING),
    "astronomical_dusk": SensorParams(Sun2PointInTimeSensor, ICON_SETTING),
    # Time periods
    "daylight": SensorParams(Sun2PeriodOfTimeSensor, ICON_DAY),
    "civil_daylight": SensorParams(Sun2PeriodOfTimeSensor, ICON_DAY),
    "nautical_daylight": SensorParams(Sun2PeriodOfTimeSensor, ICON_DAY),
    "astronomical_daylight": SensorParams(Sun2PeriodOfTimeSensor, ICON_DAY),
    "night": SensorParams(Sun2PeriodOfTimeSensor, ICON_NIGHT),
    "civil_night": SensorParams(Sun2PeriodOfTimeSensor, ICON_NIGHT),
    "nautical_night": SensorParams(Sun2PeriodOfTimeSensor, ICON_NIGHT),
    "astronomical_night": SensorParams(Sun2PeriodOfTimeSensor, ICON_NIGHT),
    # Min/Max elevation
    "min_elevation": SensorParams(Sun2MinMaxElevationSensor, ICON_NIGHT),
    "max_elevation": SensorParams(Sun2MinMaxElevationSensor, ICON_DAY),
    # Azimuth & Elevation
    "azimuth": SensorParams(Sun2AzimuthSensor, ICON_AZIMUTH),
    "sunrise_azimuth": SensorParams(Sun2SunriseSunsetAzimuthSensor, ICON_AZIMUTH),
    "sunset_azimuth": SensorParams(Sun2SunriseSunsetAzimuthSensor, ICON_AZIMUTH),
    "elevation": SensorParams(Sun2ElevationSensor, None),
    # Phase
    "sun_phase": SensorParams(Sun2PhaseSensor, None),
    "deconz_daylight": SensorParams(Sun2DeconzDaylightSensor, None),
}


class Sun2SensorEntrySetup(Sun2EntrySetup):
    """Binary sensor config entry setup."""

    def _get_entities(self) -> Iterable[Sun2Entity]:
        """Return entities to add."""
        return chain(self._basic_sensors(), self._config_sensors())

    def _basic_sensors(self) -> Iterable[Sun2Entity]:
        """Return basic entities to add."""
        for sensor_type, sensor_params in _SENSOR_TYPES.items():
            self._sun2_entity_params.unique_id = self._uid_prefix + sensor_type
            yield sensor_params.cls(
                self._sun2_entity_params, sensor_type, sensor_params.icon
            )

    def _config_sensors(self) -> Iterable[Sun2Entity]:
        """Return configured entities to add."""
        for config in self._entry.options.get(CONF_SENSORS, []):
            unique_id = config[CONF_UNIQUE_ID]
            if self._imported:
                unique_id = self._uid_prefix + unique_id
            self._sun2_entity_params.unique_id = unique_id
            name = config.get(CONF_NAME)

            if (at_time := config.get(CONF_ELEVATION_AT_TIME)) is not None:
                # For config entries, JSON serialization turns a time into a string.
                # Convert back to time in that case.
                if isinstance(at_time, str):
                    with suppress(ValueError):
                        at_time = time.fromisoformat(at_time)
                yield Sun2ElevationAtTimeSensor(self._sun2_entity_params, name, at_time)
                continue

            if (elevation := config.get(CONF_TIME_AT_ELEVATION)) is not None:
                direction = SunDirection.__getitem__(
                    cast(str, config[CONF_DIRECTION]).upper()
                )
                yield Sun2TimeAtElevationSensor(
                    self._sun2_entity_params,
                    name,
                    config.get(CONF_ICON),
                    direction,
                    elevation,
                )
                continue

            raise ValueError(f"Unexpected sensor config: {config}")


async_setup_entry = Sun2SensorEntrySetup.async_setup_entry
