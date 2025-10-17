"""Sun2 Sensor."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from itertools import chain
from math import ceil, floor
from typing import Any, Generic, TypeVar, cast

from astral import SunDirection
from astral.sun import SUN_APPARENT_RADIUS

from homeassistant.components.sensor import (
    DOMAIN as SENSOR_DOMAIN,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    ATTR_ICON,
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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_NEXT_CHANGE,
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
    LOGGER,
    MAX_ERR_ELEV,
    ONE_DAY,
    SUNSET_ELEV,
)
from .helpers import (
    AstralData,
    Num,
    Sun2Entity,
    Sun2EntityParams,
    Sun2EntrySetup,
    hours_to_hms,
    nearest_second,
    next_midnight,
    translate,
)

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
_DELTA = timedelta(minutes=5)


_T = TypeVar("_T")


class Sun2AzimuthSensor(Sun2Entity, SensorEntity):
    """Sun2 Azimuth Sensor."""

    _attr_native_value: float

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
        self._event = "solar_azimuth"

    def _setup_fixed_updating(self) -> None:
        """Set up fixed updating."""

    def _update(self, cur_dttm: datetime) -> None:
        """Update state."""
        # Astral package ignores microseconds, so round to nearest second
        # before continuing.
        cur_dttm = nearest_second(cur_dttm)
        self._attr_native_value = self._astral_event(cur_dttm)

        elevation = self._astral_event(cur_dttm, "solar_elevation")
        if elevation >= 10:
            delta = 4 * 60
        elif elevation >= 0:
            delta = 2 * 60
        elif elevation >= -6:
            delta = 4 * 60
        elif elevation >= -18:
            delta = 8 * 60
        else:
            delta = 20 * 60
        self._schedule_update(delta)


@dataclass(frozen=True)
class PhaseAttrs:
    """Phase attributes."""


@dataclass(frozen=True)
class PhaseParams:
    """Phase parameters."""

    event: str
    solar_depression: Num | None
    phase: str
    attrs: PhaseAttrs

    @property
    def attributes(self) -> dict[str, Any]:
        """Return attributes as a dictionary."""
        return asdict(self.attrs)


class PhaseSensor(Sun2Entity, SensorEntity, ABC):
    """Phase sensor base."""

    _attr_native_value: str
    _phase_params: tuple[PhaseParams, ...]
    _phase_idx: int | None = None

    def __init__(
        self, sun2_entity_params: Sun2EntityParams, sensor_type: str, icon: str | None
    ) -> None:
        """Initialize sensor."""
        self.entity_description = SensorEntityDescription(
            key=sensor_type,
            device_class=SensorDeviceClass.ENUM,
            entity_registry_enabled_default=sensor_type in _ENABLED_SENSORS,
            icon=icon,
            options=self.phases,
        )
        super().__init__(sun2_entity_params)

    @property
    def phases(self) -> list[str]:
        """Return list of phase state values."""
        return sorted({params.phase for params in self._phase_params})

    def _update(self, cur_dttm: datetime) -> None:
        """Update state."""
        cur_date = self._as_tz(cur_dttm).date()

        if self._phase_idx is None:
            # Find phase that started before current time.
            for phase_idx, phase_params in enumerate(self._phase_params):
                if (solar_depression := phase_params.solar_depression) is not None:
                    self._solar_depression = solar_depression
                nxt_chg = cast(
                    datetime, self._astral_event(cur_date, phase_params.event, False)
                )
                if nxt_chg > cur_dttm:
                    if phase_idx == 0:
                        # None of the phases started before current time.
                        # Phase is last one of previous day.
                        self._phase_idx = len(self._phase_params) - 1
                        cur_date -= ONE_DAY
                    else:
                        # Previous phase started before current time.
                        self._phase_idx = phase_idx - 1
                    break
            else:
                # All of the phases started before current time.
                # Current phase is the last one of today.
                self._phase_idx = len(self._phase_params) - 1

        cur_phase_params = self._phase_params[self._phase_idx]
        self._phase_idx = (self._phase_idx + 1) % len(self._phase_params)
        nxt_phase_params = self._phase_params[self._phase_idx]

        if self._phase_idx == 0:
            cur_date += ONE_DAY
        if (solar_depression := nxt_phase_params.solar_depression) is not None:
            self._solar_depression = solar_depression
        nxt_chg = cast(
            datetime, self._astral_event(cur_date, nxt_phase_params.event, False)
        )

        self._attr_native_value = cur_phase_params.phase
        self._attr_icon = self._icon(cur_phase_params)
        self._attr_extra_state_attributes = {
            ATTR_NEXT_CHANGE: self._as_tz(nxt_chg),
        } | cur_phase_params.attributes

        self._schedule_update(nxt_chg)

    def _update_astral_data(self, astral_data: AstralData) -> None:
        """Update astral data."""
        self._phase_idx = None
        super()._update_astral_data(astral_data)

    @abstractmethod
    def _icon(self, phase_params: PhaseParams) -> str:
        """Determine icon based on state."""


@dataclass(frozen=True)
class Sun2PA(PhaseAttrs):
    """Sun2 Phase Sensor attributes."""

    blue_hour: bool
    golden_hour: bool
    rising: bool


class Sun2PhaseSensor(PhaseSensor):
    """Sun2 Phase Sensor."""

    _phase_params: tuple[PhaseParams, ...] = (
        PhaseParams("solar_midnight", None, "night", Sun2PA(False, False, True)),
        PhaseParams("dawn", 18, "astronomical_twilight", Sun2PA(False, False, True)),
        PhaseParams("dawn", 12, "nautical_twilight", Sun2PA(False, False, True)),
        PhaseParams("dawn", 6, "civil_twilight", Sun2PA(True, False, True)),
        PhaseParams("dawn", 4, "civil_twilight", Sun2PA(False, True, True)),
        PhaseParams("sunrise", None, "day", Sun2PA(False, True, True)),
        PhaseParams("dawn", -6, "day", Sun2PA(False, False, True)),
        PhaseParams("solar_noon", None, "day", Sun2PA(False, False, False)),
        PhaseParams("dusk", -6, "day", Sun2PA(False, True, False)),
        PhaseParams("sunset", None, "civil_twilight", Sun2PA(False, True, False)),
        PhaseParams("dusk", 4, "civil_twilight", Sun2PA(True, False, False)),
        PhaseParams("dusk", 6, "nautical_twilight", Sun2PA(False, False, False)),
        PhaseParams("dusk", 12, "astronomical_twilight", Sun2PA(False, False, False)),
        PhaseParams("dusk", 18, "night", Sun2PA(False, False, False)),
    )

    def _icon(self, phase_params: PhaseParams) -> str:
        """Determine icon based on state."""
        if phase_params.phase == "night":
            return "mdi:weather-night"
        if phase_params.phase == "day":
            return "mdi:weather-sunny"
        if cast(Sun2PA, phase_params.attrs).rising:
            return "mdi:weather-sunset-up"
        return "mdi:weather-sunset-down"


@dataclass(frozen=True)
class Sun2DA(PhaseAttrs):
    """Sun2 deCONZ Phase Sensor attributes."""

    daylight: bool


class Sun2DeconzDaylightSensor(PhaseSensor):
    """Sun2 deCONZ Phase Sensor."""

    _phase_params: tuple[PhaseParams, ...] = (
        PhaseParams("solar_midnight", None, "nadir", Sun2DA(False)),
        PhaseParams("dawn", 18, "night_end", Sun2DA(False)),
        PhaseParams("dawn", 12, "nautical_dawn", Sun2DA(False)),
        PhaseParams("dawn", 6, "dawn", Sun2DA(False)),
        PhaseParams("sunrise", None, "sunrise_start", Sun2DA(True)),
        PhaseParams("dawn", 0.3, "sunrise_end", Sun2DA(True)),
        PhaseParams("dawn", -6, "golden_hour_1", Sun2DA(True)),
        PhaseParams("solar_noon", None, "solar_noon", Sun2DA(True)),
        PhaseParams("dusk", -6, "golden_hour_2", Sun2DA(True)),
        PhaseParams("dusk", 0.3, "sunset_start", Sun2DA(True)),
        PhaseParams("sunset", None, "sunset_end", Sun2DA(False)),
        PhaseParams("dusk", 6, "dusk", Sun2DA(False)),
        PhaseParams("dusk", 12, "nautical_dusk", Sun2DA(False)),
        PhaseParams("dusk", 18, "night_start", Sun2DA(False)),
    )

    def _icon(self, phase_params: PhaseParams) -> str:
        """Determine icon based on state."""
        if phase_params.phase in ("nadir", "night_start"):
            return "mdi:weather-night"
        if cast(Sun2DA, phase_params.attrs).daylight:
            return "mdi:weather-sunny"
        if phase_params.phase in ("night_end", "nautical_dawn", "dawn"):
            return "mdi:weather-sunset-up"
        return "mdi:weather-sunset-down"


class Sun2SensorEntity(Sun2Entity, SensorEntity, Generic[_T]):
    """Sun2 Sensor Entity."""

    _attr_native_value: _T | None  # type: ignore[assignment]
    _yesterday: _T | None = None
    _today: _T | None = None
    _tomorrow: _T | None = None

    @abstractmethod
    def __init__(
        self,
        sun2_entity_params: Sun2EntityParams,
        entity_description: SensorEntityDescription,
        default_solar_depression: Num | str = 0,
        name: str | None = None,
    ) -> None:
        """Initialize sensor."""
        key = entity_description.key
        if name:
            self._attr_name = name
        self._attr_entity_registry_enabled_default = key in _ENABLED_SENSORS
        self.entity_description = entity_description
        super().__init__(sun2_entity_params)

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
            next_midn = next_midnight(self._as_tz(now))
            self._unsub_update = async_track_point_in_utc_time(
                self.hass, async_schedule_update_at_midnight, next_midn
            )
            self.async_schedule_update_ha_state(True)

        next_midn = next_midnight(self._as_tz(dt_util.utcnow()))
        self._unsub_update = async_track_point_in_utc_time(
            self.hass, async_schedule_update_at_midnight, next_midn
        )

    def _update(self, cur_dttm: datetime) -> None:
        """Update state."""
        cur_date = self._as_tz(cur_dttm).date()
        self._yesterday = cast(_T | None, self._astral_event(cur_date - ONE_DAY))
        self._attr_native_value = self._today = cast(
            _T | None, self._astral_event(cur_date)
        )
        self._tomorrow = cast(_T | None, self._astral_event(cur_date + ONE_DAY))


class Sun2ElevationAtTimeSensor(Sun2SensorEntity[float]):
    """Sun2 Elevation at Time Sensor."""

    _at_time: time | datetime | None = None
    _input_datetime: str | None = None
    _unsub_track: CALLBACK_TYPE | None = None
    _unsub_listen: CALLBACK_TYPE | None = None

    def __init__(
        self, sun2_entity_params: Sun2EntityParams, name: str, at_time: str | time
    ) -> None:
        """Initialize sensor."""
        if isinstance(at_time, str):
            self._input_datetime = at_time
        else:
            self._at_time = at_time
        entity_description = SensorEntityDescription(
            key=CONF_ELEVATION_AT_TIME,
            icon="mdi:weather-sunny",
            native_unit_of_measurement=DEGREE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=2,
        )
        super().__init__(sun2_entity_params, entity_description, name=name)
        self._event = "solar_elevation"

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return entity specific state attributes."""
        if isinstance(self._at_time, datetime):
            return None
        return super().extra_state_attributes

    def _setup_fixed_updating(self) -> None:
        """Set up fixed updating."""
        super()._setup_fixed_updating()
        if not self._input_datetime:
            return

        @callback
        def update_at_time(
            event: Event | Event[EventStateChangedData] | None = None,
        ) -> None:
            """Update time from input_datetime entity."""
            self._at_time = None
            if event and event.event_type == EVENT_STATE_CHANGED:
                state = event.data["new_state"]
            else:
                assert self._input_datetime
                state = self.hass.states.get(self._input_datetime)
            if not state:
                if event and event.event_type == EVENT_STATE_CHANGED:
                    LOGGER.error("%s: %s deleted", self.name, self._input_datetime)
                elif self.hass.state == CoreState.running:
                    LOGGER.error("%s: %s not found", self.name, self._input_datetime)
                else:
                    self._unsub_listen = self.hass.bus.async_listen(
                        EVENT_HOMEASSISTANT_STARTED, update_at_time
                    )
            elif not state.attributes["has_time"]:
                LOGGER.error(
                    "%s: %s missing time attributes",
                    self.name,
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

            self.async_schedule_update_ha_state(True)

        self._unsub_track = async_track_state_change_event(
            self.hass,
            self._input_datetime,
            update_at_time,
        )
        update_at_time()

    def _cancel_update(self) -> None:
        """Cancel update."""
        super()._cancel_update()
        if self._unsub_track:
            self._unsub_track()
            self._unsub_track = None
        if self._unsub_listen:
            self._unsub_listen()
            self._unsub_listen = None

    def _update(self, cur_dttm: datetime) -> None:
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
        self._attr_native_value = cast(float | None, self._astral_event(dttm))
        if isinstance(self._at_time, datetime):
            return
        self._yesterday = cast(float | None, self._astral_event(dttm - ONE_DAY))
        self._today = self._attr_native_value
        self._tomorrow = cast(float | None, self._astral_event(dttm + ONE_DAY))


class Sun2PointInTimeSensor(Sun2SensorEntity[datetime | str]):
    """Sun2 Point in Time Sensor."""

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
        super().__init__(sun2_entity_params, entity_description, "civil", name)


class Sun2TimeAtElevationSensor(Sun2PointInTimeSensor):
    """Sun2 Time at Elevation Sensor."""

    def __init__(
        self,
        sun2_entity_params: Sun2EntityParams,
        name: str,
        icon: str | None,
        direction: SunDirection,
        elevation: float,
    ) -> None:
        """Initialize sensor."""
        if not icon:
            icon = {
                SunDirection.RISING: "mdi:weather-sunset-up",
                SunDirection.SETTING: "mdi:weather-sunset-down",
            }[direction]
        self._direction = direction
        self._elevation = elevation
        super().__init__(sun2_entity_params, CONF_TIME_AT_ELEVATION, icon, name)

    def _astral_event(
        self,
        date_or_dttm: date | datetime,
        event: str | None = None,
        local: bool = True,
        /,
        **kwargs: Any,
    ) -> Any:
        return super()._astral_event(
            date_or_dttm, direction=self._direction, elevation=self._elevation
        )


class Sun2PeriodOfTimeSensor(Sun2SensorEntity[float]):
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

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()

        # In 3.1.0 and earlier, entity_description.suggested_display_precision was set
        # to 3. Starting with HA 2024.2, that causes the state to be displayed as a
        # float instead of HH:MM:SS. To fix that
        # entity_description.suggested_display_precision is no longer being set.
        # However, due to a bug in the sensor component, that value is not getting
        # properly removed from the entity registry, causing the state to still be
        # displayed as a float. To work around that bug, we'll forcibly remove it from
        # the registry here if necessary.
        ent_reg = er.async_get(self.hass)
        sensor_options: Mapping[str, Any] = ent_reg.entities[
            self.entity_id
        ].options.get(SENSOR_DOMAIN, {})
        if sensor_options.get("suggested_display_precision") is None:
            return
        sensor_options = dict(sensor_options)
        del sensor_options["suggested_display_precision"]
        ent_reg.async_update_entity_options(
            self.entity_id, SENSOR_DOMAIN, sensor_options or None
        )

    def _astral_event(
        self,
        date_or_dttm: date | datetime,
        event: str | None = None,
        local: bool = True,
        /,
        **kwargs: Any,
    ) -> float | None:
        """Return astral event result."""
        start: datetime | None
        end: datetime | None
        if self._event == "daylight":
            start = super()._astral_event(date_or_dttm, "dawn", False)
            end = super()._astral_event(date_or_dttm, "dusk", False)
        else:
            start = super()._astral_event(date_or_dttm, "dusk", False)
            end = super()._astral_event(date_or_dttm + ONE_DAY, "dawn", False)
        if not start or not end:
            return None
        return (end - start).total_seconds() / 3600


class Sun2MinMaxElevationSensor(Sun2SensorEntity[float]):
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
        self._event = {
            "min_elevation": "solar_midnight",
            "max_elevation": "solar_noon",
        }[sensor_type]

    def _astral_event(
        self,
        date_or_dttm: date | datetime,
        event: str | None = None,
        local: bool = True,
        /,
        **kwargs: Any,
    ) -> float | None:
        """Return astral event result."""
        return cast(
            float | None,
            super()._astral_event(
                cast(datetime, super()._astral_event(date_or_dttm)), "solar_elevation"
            ),
        )


class Sun2SunriseSunsetAzimuthSensor(Sun2SensorEntity[float]):
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
        self._event = "solar_azimuth"
        self._method = sensor_type.split("_")[0]

    def _astral_event(
        self,
        date_or_dttm: date | datetime,
        event: str | None = None,
        local: bool = True,
        /,
        **kwargs: Any,
    ) -> float | None:
        """Return astral event result."""
        # Get sunrise or sunset time.
        # Don't use parent method because observer elevation should not be used
        # because there is no way to know if currently configured observer elevation
        # was valid yesterday or will be valid tomorrow since it is very possible the
        # state of this sensor will be used to automatically change the observer
        # configuration throughout the year. This also avoids a potentially infinite
        # feedback loop.
        try:
            dttm = getattr(self._astral_data.loc_data.loc, self._method)(date_or_dttm)
        except (TypeError, ValueError):
            return None
        return cast(float | None, super()._astral_event(dttm))


@dataclass
class CurveParameters:
    """Parameters that describe current portion of elevation curve.

    The ends of the current portion of the curve are bounded by a pair of solar
    midnight and solar noon, such that tl_dttm <= cur_dttm < tr_dttm. rising is True if
    tr_elev > tl_elev (i.e., tL represents a solar midnight and tR represents a solar
    noon.) mid_date is the date of the midpoint between tL & tR. nxt_noon is the solar
    noon for tomorrow (i.e., cur_date + 1.)
    """

    tl_dttm: datetime
    tl_elev: Num
    tr_dttm: datetime
    tr_elev: Num
    mid_date: date
    nxt_noon: datetime
    rising: bool


class Sun2CPSensorEntity(Sun2SensorEntity[_T]):
    """Sun2 Sensor Entity with elevation curve methods."""

    _cp: CurveParameters | None = None

    @abstractmethod
    def __init__(
        self,
        sun2_entity_params: Sun2EntityParams,
        entity_description: SensorEntityDescription,
        default_solar_depression: Num | str = 0,
    ) -> None:
        """Initialize sensor."""
        super().__init__(
            sun2_entity_params, entity_description, default_solar_depression
        )
        self._event = "solar_elevation"

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return entity specific state attributes."""
        if hasattr(self, "_attr_extra_state_attributes"):
            return self._attr_extra_state_attributes
        return None

    def _update_astral_data(self, astral_data: AstralData) -> None:
        """Update astral data."""
        self._cp = None
        super()._update_astral_data(astral_data)

    def _setup_fixed_updating(self) -> None:
        """Set up fixed updating."""

    def _attrs_at_elev(self, elev: Num) -> dict[str, Any]:
        """Return attributes at elevation."""
        assert self._cp

        if self._cp.rising:
            if elev < -18:
                icon = "mdi:weather-night"
            elif elev < SUNSET_ELEV:
                icon = "mdi:weather-sunset-up"
            else:
                icon = "mdi:weather-sunny"
        else:  # noqa: PLR5501
            if elev > SUNSET_ELEV:
                icon = "mdi:weather-sunny"
            elif elev > -18:
                icon = "mdi:weather-sunset-down"
            else:
                icon = "mdi:weather-night"
        return {ATTR_ICON: icon}

    def _set_attrs(self, attrs: dict[str, Any], nxt_chg: datetime) -> None:
        """Set attributes."""
        self._attr_icon = cast(str | None, attrs.pop(ATTR_ICON, "mdi:weather-sunny"))
        attrs[ATTR_NEXT_CHANGE] = self._as_tz(nxt_chg)
        self._attr_extra_state_attributes = attrs

    def _get_curve_params(self, cur_dttm: datetime, cur_elev: Num) -> CurveParameters:
        """Calculate elevation curve parameters."""
        cur_date = self._as_tz(cur_dttm).date()

        # Find the highest and lowest points on the elevation curve that encompass
        # current time, where it is ok for the current time to be the same as the
        # first of these two points.
        # Note that the astral solar_midnight event will always come before the astral
        # solar_noon event for any given date, even if it actually falls on the previous
        # day.
        hi_dttm = cast(datetime, self._astral_event(cur_date, "solar_noon", False))
        lo_dttm = cast(datetime, self._astral_event(cur_date, "solar_midnight", False))
        nxt_noon = cast(
            datetime, self._astral_event(cur_date + ONE_DAY, "solar_noon", False)
        )
        if cur_dttm < lo_dttm:
            tl_dttm = cast(
                datetime, self._astral_event(cur_date - ONE_DAY, "solar_noon", False)
            )
            tr_dttm = lo_dttm
        elif cur_dttm < hi_dttm:
            tl_dttm = lo_dttm
            tr_dttm = hi_dttm
        else:
            lo_dttm = cast(
                datetime,
                self._astral_event(cur_date + ONE_DAY, "solar_midnight", False),
            )
            if cur_dttm < lo_dttm:
                tl_dttm = hi_dttm
                tr_dttm = lo_dttm
            else:
                tl_dttm = lo_dttm
                tr_dttm = nxt_noon
        tl_elev = cast(float, self._astral_event(tl_dttm))
        tr_elev = cast(float, self._astral_event(tr_dttm))
        rising = tr_elev > tl_elev

        LOGGER.debug(
            "%s: tL = %s/%0.3f, cur = %s/%0.3f, tR = %s/%0.3f, rising = %s",
            self.name,
            self._as_tz(tl_dttm),
            tl_elev,
            self._as_tz(cur_dttm),
            cur_elev,
            self._as_tz(tr_dttm),
            tr_elev,
            rising,
        )

        mid_date = self._as_tz(tl_dttm + (tr_dttm - tl_dttm) / 2).date()
        return CurveParameters(
            tl_dttm, tl_elev, tr_dttm, tr_elev, mid_date, nxt_noon, rising
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
                + f"t0 = {self._as_tz(t0_dttm)}/{t0_elev:+7.3f}, t1 = {self._as_tz(t1_dttm)}/{t1_elev:+7.3f} ->"
            )
            try:
                est_dttm = nearest_second(
                    t0_dttm
                    + (t1_dttm - t0_dttm) * ((elev - t0_elev) / (t1_elev - t0_elev))
                )
            except ZeroDivisionError:
                LOGGER.debug("%s ZeroDivisionError", msg)
                return None
            if est_dttm < self._cp.tl_dttm or est_dttm > self._cp.tr_dttm:
                LOGGER.debug("%s outside range", msg)
                return None
            est_elev = cast(float, self._astral_event(est_dttm))
            LOGGER.debug(
                "%s est = %s/%+7.3f[%+7.3f/%2i]",
                msg,
                self._as_tz(est_dttm),
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
        self, sun2_entity_params: Sun2EntityParams, sensor_type: str, icon: str | None
    ) -> None:
        """Initialize sensor."""
        entity_description = SensorEntityDescription(
            key=sensor_type,
            icon=icon,
            native_unit_of_measurement=DEGREE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        )
        super().__init__(sun2_entity_params, entity_description)

    def _update(self, cur_dttm: datetime) -> None:
        """Update state."""
        # Astral package ignores microseconds, so round to nearest second
        # before continuing.
        cur_dttm = nearest_second(cur_dttm)
        cur_elev = cast(float, self._astral_event(cur_dttm))
        self._attr_native_value = rnd_elev = round(cur_elev, 1)
        LOGGER.debug("%s: Raw elevation = %f -> %s", self.name, cur_elev, rnd_elev)

        if not self._cp or cur_dttm >= self._cp.tr_dttm:
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
            if self._cp.tr_dttm - _DELTA <= cur_dttm < self._cp.tr_dttm:
                nxt_dttm = self._cp.tr_dttm
            else:
                nxt_dttm = cur_dttm + _DELTA

        self._set_attrs(self._attrs_at_elev(cur_elev), nxt_dttm)

        self._prv_dttm = cur_dttm

        self._schedule_update(nxt_dttm)


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
    # Azimuth & Elevation
    "azimuth": SensorParams(Sun2AzimuthSensor, "mdi:sun-angle"),
    "sunrise_azimuth": SensorParams(Sun2SunriseSunsetAzimuthSensor, "mdi:sun-angle"),
    "sunset_azimuth": SensorParams(Sun2SunriseSunsetAzimuthSensor, "mdi:sun-angle"),
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
                yield Sun2ElevationAtTimeSensor(
                    self._sun2_entity_params,
                    self._elevation_at_time_name(name, at_time),
                    at_time,
                )
                continue

            if (elevation := config.get(CONF_TIME_AT_ELEVATION)) is not None:
                direction = SunDirection.__getitem__(
                    cast(str, config[CONF_DIRECTION]).upper()
                )
                yield Sun2TimeAtElevationSensor(
                    self._sun2_entity_params,
                    self._time_at_elevation_name(name, direction, elevation),
                    config.get(CONF_ICON),
                    direction,
                    elevation,
                )
                continue

            raise ValueError(f"Unexpected sensor config: {config}")

    def _elevation_at_time_name(self, name: str | None, at_time: str | time) -> str:
        """Return elevation_at_time sensor name."""
        if name:
            return name
        return translate(self._hass, "elevation_at", {"elev_time": str(at_time)})

    def _time_at_elevation_name(
        self, name: str | None, direction: SunDirection, elevation: float
    ) -> str:
        """Return time_at_elevation sensor name."""
        if name:
            return name
        return translate(
            self._hass,
            f"{direction.name.lower()}_{'neg' if elevation < 0 else 'pos'}_elev",
            {"elevation": str(abs(elevation))},
        )


async_setup_entry = Sun2SensorEntrySetup.async_setup_entry
