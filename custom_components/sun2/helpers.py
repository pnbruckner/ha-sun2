"""Sun2 Helpers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from functools import lru_cache, partial
from math import copysign, fabs
from typing import Any, Self, cast

from astral import LocationInfo, SunDirection
from astral.location import Location
from astral.sun import adjust_to_horizon, adjust_to_obscuring_feature
from propcache.api import cached_property

from homeassistant.components.binary_sensor import (
    DOMAIN as BS_DOMAIN,
    BinarySensorEntity,
)
from homeassistant.components.sensor import DOMAIN as S_DOMAIN
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import (
    CONF_ELEVATION,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_TIME_ZONE,
)
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.core_config import Config
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_device_registry_updated_event,
    async_track_entity_registry_updated_event,
    async_track_point_in_utc_time,
)
from homeassistant.util import dt as dt_util
from homeassistant.util.hass_dict import HassKey

from .const import (
    ATTR_NEXT_CHANGE,
    ATTR_TODAY_HMS,
    ATTR_TOMORROW,
    ATTR_TOMORROW_HMS,
    ATTR_YESTERDAY,
    ATTR_YESTERDAY_HMS,
    CONF_OBS_ELV,
    DOMAIN,
    LOGGER,
    ONE_DAY,
    SIG_ASTRAL_DATA_UPDATED,
    SIG_HA_LOC_UPDATED,
)

Num = float | int
SUN2_DATA: HassKey[Sun2Data] = HassKey(DOMAIN)


@dataclass(frozen=True)
class LocParams:
    """Location parameters."""

    latitude: float
    longitude: float
    time_zone: str

    @classmethod
    def from_hass_config(cls, config: Config) -> Self:
        """Initialize from HA configuration."""
        return cls(
            config.latitude,
            config.longitude,
            config.time_zone,
        )

    @classmethod
    def from_entry_options(cls, options: Mapping[str, Any]) -> Self | None:
        """Initialize from configuration entry options.

        Retrun None if no location options, meaning use HA's configured location.
        """
        try:
            return cls(
                options[CONF_LATITUDE],
                options[CONF_LONGITUDE],
                options[CONF_TIME_ZONE],
            )
        except KeyError:
            return None


@dataclass(frozen=True)
class LocData:
    """Location data."""

    loc: Location
    tzi: tzinfo | None

    @classmethod
    def from_loc_params(cls, lp: LocParams) -> Self:
        """Initialize from LocParams."""
        tzi = dt_util.get_time_zone(tz := lp.time_zone)
        if not tzi:
            LOGGER.warning("Did not find time zone: %s", lp.time_zone)
        loc = Location(LocationInfo("", "", tz, lp.latitude, lp.longitude))
        # Cache results of methods used by many entity types.
        loc.midnight = lru_cache(10)(loc.midnight)
        loc.noon = lru_cache(10)(loc.noon)
        return cls(loc, tzi)


@lru_cache
def _get_loc_data(lp: LocParams | None) -> LocData | None:
    """Get LocData from LocParams & cache results.

    lp = None -> using HA's location configuration; return None
    """
    if lp is None:
        return None
    return LocData.from_loc_params(lp)


async def async_get_loc_data(
    hass: HomeAssistant, arg: Config | Mapping[str, Any]
) -> LocData | None:
    """Get LocData from HA config or config entry options.

    If config entry provided, and it does not contain location options,
    then return None, meaning HA's location configuration should be used.
    """

    def get_loc_data() -> LocData | None:
        """Get LocData.

        Must be run in an executor because dt_util.get_time_zone can do file I/O.
        Also, astral's Location methods use pytz when local=True and pytz, when first
        called with a given time zone, will do file I/O. After that the data will be
        cached and it won't do file I/O again for the same time zone.
        """
        if isinstance(arg, Config):
            loc_data = _get_loc_data(LocParams.from_hass_config(arg))
        else:
            loc_data = _get_loc_data(LocParams.from_entry_options(arg))
        if loc_data is None:
            return None

        # Force pytz to do its file I/O now by using the Location object's tzinfo
        # property.
        loc_data.loc.tzinfo  # noqa: B018

        return loc_data

    return await hass.async_add_executor_job(get_loc_data)


ObsElv = float | tuple[float, float]


@dataclass
class ObsElvs:
    """Oberserver elevations."""

    east: ObsElv
    west: ObsElv

    @staticmethod
    def _obs_elv_2_astral(
        obs_elv: Num | list[Num],
    ) -> float | tuple[float, float]:
        """Convert value stored in config entry to astral observer_elevation param.

        When sun event is affected by an obstruction, the astral package says to pass
        a tuple of floats in the observer_elevaton parameter, where the first element is
        the relative height from the observer to the obstruction (which may be negative)
        and the second element is the horizontal distance to the obstruction.

        However, due to a bug (see issue 89), it reverses the values and results in a
        sign error. The code below works around that bug.

        Also, astral only accepts a tuple, not a list, which is what stored in the
        config entry (since it's from a JSON file), so convert to a tuple.
        """
        if isinstance(obs_elv, Num):
            return float(obs_elv)
        height, distance = obs_elv
        return -copysign(1, float(height)) * float(distance), fabs(float(height))

    @classmethod
    def from_entry_options(cls, options: Mapping[str, Any]) -> Self:
        """Initialize from configuration entry options."""
        if obs_elv := options.get(CONF_OBS_ELV):
            east_obs_elv, west_obs_elv = obs_elv
            return cls(
                cls._obs_elv_2_astral(east_obs_elv),
                cls._obs_elv_2_astral(west_obs_elv),
            )
        above_ground = float(options.get(CONF_ELEVATION, 0))
        return cls(above_ground, above_ground)


@dataclass
class ConfigData:
    """Sun2 config entry data."""

    title: str
    pref_disable_polling: bool
    binary_sensors: list[dict[str, Any]]
    sensors: list[dict[str, Any]]
    loc_data: LocData | None
    obs_elvs: ObsElvs


@dataclass
class Sun2Data:
    """Sun2 shared data."""

    ha_loc_data: LocData
    config_data: dict[str, ConfigData] = field(default_factory=dict)


async def init_sun2_data(hass: HomeAssistant) -> Sun2Data:
    """Initialize Sun2 integration data."""
    if SUN2_DATA not in hass.data:
        loc_data = cast(LocData, await async_get_loc_data(hass, hass.config))
        hass.data[SUN2_DATA] = Sun2Data(loc_data)
    return hass.data[SUN2_DATA]


def sun2_data(hass: HomeAssistant) -> Sun2Data:
    """Return Sun2 integration data."""
    return hass.data[SUN2_DATA]


def hours_to_hms(hours: Num | None) -> str | None:
    """Convert hours to HH:MM:SS string."""
    try:
        return str(timedelta(seconds=int(cast(Num, hours) * 3600)))
    except TypeError:
        return None


def sun2_dev_info(hass: HomeAssistant, entry: ConfigEntry) -> dr.DeviceInfo:
    """Sun2 device (service) info."""
    return dr.DeviceInfo(
        entry_type=dr.DeviceEntryType.SERVICE,
        identifiers={(DOMAIN, entry.entry_id)},
        translation_key="service",
        translation_placeholders={"location": entry.title},
    )


def nearest_second(dttm: datetime) -> datetime:
    """Round dttm to nearest second."""
    return dttm.replace(microsecond=0) + timedelta(
        seconds=0 if dttm.microsecond < 500000 else 1
    )


def next_midnight(dttm: datetime) -> datetime:
    """Return next midnight in same time zone."""
    return datetime.combine(dttm.date() + ONE_DAY, time(), dttm.tzinfo)


@dataclass
class AstralData:
    """astral data."""

    loc_data: LocData
    obs_elvs: ObsElvs


@dataclass
class Sun2EntityParams:
    """Sun2Entity parameters."""

    pref_disable_polling: bool
    device_info: dr.DeviceInfo
    astral_data: AstralData
    unique_id: str = ""


class Sun2Entity(Entity, ABC):
    """Sun2 Entity.

    Assumes async_update & anything called via async_request_call are protected by a
    semaphore. To make sure the semaphore is created and used, platform modules MUST
    declare PARALLEL_UPDATES = 1!
    """

    # Override in subclass as needed
    _supports_entity_update_action = False
    _reschedule_at_midnight = False

    _unrecorded_attributes = frozenset(
        {
            ATTR_NEXT_CHANGE,
            ATTR_TODAY_HMS,
            ATTR_TOMORROW,
            ATTR_TOMORROW_HMS,
            ATTR_YESTERDAY,
            ATTR_YESTERDAY_HMS,
        }
    )
    _attr_should_poll = False

    _unsub_update: CALLBACK_TYPE | None = None
    _first_update = True

    @abstractmethod
    def __init__(self, sun2_entity_params: Sun2EntityParams) -> None:
        """Initialize base class."""
        self._attr_has_entity_name = True
        self._attr_translation_key = self.entity_description.key
        self._attr_unique_id = sun2_entity_params.unique_id
        self._attr_device_info = sun2_entity_params.device_info
        # Automatically update sensor if entity does not support user requested updates
        # or, if it does, only if user has not disabled "polling."
        self._auto_update = (
            not self._supports_entity_update_action
            or not sun2_entity_params.pref_disable_polling
        )
        self._astral_data = sun2_entity_params.astral_data
        self.async_on_remove(self._cancel_update)

    @cached_property
    def _log_name(self) -> str:
        """Return entity name for logging."""
        uid = cast(str, self.unique_id)
        ent_reg = er.async_get(self.hass)
        ent_domain = BS_DOMAIN if isinstance(self, BinarySensorEntity) else S_DOMAIN
        ent_name = (
            (eid := ent_reg.async_get_entity_id(ent_domain, DOMAIN, uid))
            and (ent_entry := ent_reg.async_get(eid))
            and (ent_entry.name or ent_entry.original_name)
        ) or str(self.name)
        dev_reg = dr.async_get(self.hass)
        assert self.platform.config_entry
        cfg_entry_id = self.platform.config_entry.entry_id
        dev_entry = dev_reg.async_get_device(identifiers={(DOMAIN, cfg_entry_id)})
        if dev_entry and (dev_name := dev_entry.name_by_user or dev_entry.name):
            return f"{dev_name} {ent_name}"
        return ent_name

    @cached_property
    def _loc(self) -> Location:
        """Return astral location."""
        return self._astral_data.loc_data.loc

    @cached_property
    def _tzi(self) -> tzinfo | None:
        """Return time zone info."""
        return self._astral_data.loc_data.tzi

    @cached_property
    def _east_obs_elv(self) -> ObsElv:
        """Return easterly observer elevation."""
        return self._astral_data.obs_elvs.east

    @cached_property
    def _west_obs_elv(self) -> ObsElv:
        """Return westerly observer elevation."""
        return self._astral_data.obs_elvs.west

    def _as_tz(self, dttm: datetime) -> datetime:
        """Return datetime in location's time zone."""
        return dttm.astimezone(self._tzi)

    def _dttm_2_str(self, dttm: datetime) -> str:
        """Return string representation of datetime in configured time zone."""
        return self._as_tz(dttm).isoformat(timespec="microseconds")

    async def async_update(self) -> None:
        """Update state."""
        # User can request an update using the homeassistant.update_entity action,
        # although this cannot happen before the entity has had a chance to complete its
        # first update. Since there is no indication from HA as to whether this update
        # is being called due to a user request or from an update the entity itself has
        # scheduled, this must be determined by considering the auto update "feature" of
        # this base class. If the entity is not updating itself, then the request must
        # have come from the user. Or, if the entity is updating itself, then the
        # request must have come from the user if there is a pending update, since the
        # pending update gets cleared before this method is called.
        requested = not self._first_update and (
            not self._auto_update or self._unsub_update is not None
        )

        if requested and not self._supports_entity_update_action:
            LOGGER.warning(
                "%s: Does not support homeassistant.update_entity action",
                self._log_name,
            )
            return

        cur_dttm = dt_util.utcnow()
        LOGGER.debug(
            "%s: +++++++++++++++++++++ first update: %s, update at: %s%s",
            self._log_name,
            self._first_update,
            self._dttm_2_str(cur_dttm),
            " (requested)" if requested else "",
        )
        if self._first_update:
            self._update_setup(cur_dttm)
        await self._update(cur_dttm, requested)
        LOGGER.debug(
            "%s: --------------------- first update: %s, update took: %0.6f",
            self._log_name,
            self._first_update,
            (dt_util.utcnow() - cur_dttm).total_seconds(),
        )

        if self._reschedule_at_midnight:
            self._schedule_update(
                next_midnight(self._as_tz(cur_dttm)), update_attr=False
            )

        self._first_update = False

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""

        def reset_log_name(
            event: Event[dr.EventDeviceRegistryUpdatedData]
            | Event[er.EventEntityRegistryUpdatedData]
            | None = None,
        ) -> None:
            """Clear _log_name cache."""
            with suppress(AttributeError):
                del self._log_name

        reset_log_name()
        assert self.device_entry
        assert self.entity_id
        self.async_on_remove(
            async_track_device_registry_updated_event(
                self.hass, self.device_entry.id, reset_log_name
            )
        )
        self.async_on_remove(
            async_track_entity_registry_updated_event(
                self.hass, self.entity_id, reset_log_name
            )
        )

    def _schedule_update(
        self, nxt_chg: datetime | None, update_attr: bool = True
    ) -> None:
        """Schedule an update."""
        assert not self._unsub_update

        @callback
        def async_schedule_update(now: datetime) -> None:
            """Schedule entity update."""
            self._unsub_update = None
            self.async_schedule_update_ha_state(True)

        if nxt_chg:
            self._unsub_update = async_track_point_in_utc_time(
                self.hass, async_schedule_update, nxt_chg
            )
            fmt_nxt_chg = self._dttm_2_str(nxt_chg)
        else:
            fmt_nxt_chg = str(None)

        LOGGER.debug("%s: nxt chg: %s", self._log_name, fmt_nxt_chg)
        if update_attr:
            self._attr_extra_state_attributes[ATTR_NEXT_CHANGE] = (
                self._as_tz(nxt_chg) if nxt_chg else None
            )

    def _cancel_update(self) -> None:
        """Cancel update."""
        if self._unsub_update:
            self._unsub_update()
            self._unsub_update = None

    def _update_setup(self, cur_dttm: datetime) -> None:
        """Set up before first update.

        None by default. Override in subclass if needed.
        """

    @abstractmethod
    async def _update(self, cur_dttm: datetime, requested: bool) -> None:
        """Update state."""

    async def update_astral_data(self, astral_data: AstralData) -> None:
        """Update astral data.

        Should be called via Entity.async_request_call.
        """
        self._update_astral_data(astral_data)

    def _update_astral_data(self, astral_data: AstralData) -> None:
        """Update astral data."""
        self._cancel_update()
        self._astral_data = astral_data
        with suppress(AttributeError):
            del self._loc
        with suppress(AttributeError):
            del self._tzi
        with suppress(AttributeError):
            del self._east_obs_elv
        with suppress(AttributeError):
            del self._west_obs_elv
        self._first_update = True

    def _dawn(
        self, dt: date, solar_depression: Num | str, *, rnd: bool = False
    ) -> datetime | None:
        """Return dawn."""
        self._loc.solar_depression = solar_depression
        return self._astral_dt_2_dttm_none(
            "DWN",
            dt,
            rnd,
            partial(self._loc.dawn, observer_elevation=self._east_obs_elv),
        )

    def _dusk(
        self, dt: date, solar_depression: Num | str, *, rnd: bool = False
    ) -> datetime | None:
        """Return dusk."""
        self._loc.solar_depression = solar_depression
        return self._astral_dt_2_dttm_none(
            "DSK",
            dt,
            rnd,
            partial(self._loc.dusk, observer_elevation=self._west_obs_elv),
        )

    def _solar_azimuth(self, dttm: datetime) -> float:
        """Return solar azimuth."""
        return self._astral_dttm_2_float("AZ", dttm, self._loc.solar_azimuth)

    def _solar_elevation(self, dttm: datetime) -> float:
        """Return solar elevation."""
        return self._astral_dttm_2_float("EL", dttm, self._loc.solar_elevation)

    def _solar_midnight(self, dt: date, *, rnd: bool = False) -> datetime:
        """Return solar midnight."""
        return cast(
            datetime, self._astral_dt_2_dttm_none("SM", dt, rnd, self._loc.midnight)
        )

    def _solar_noon(self, dt: date, *, rnd: bool = False) -> datetime:
        """Return solar noon."""
        return cast(
            datetime,
            self._astral_dt_2_dttm_none("SN", dt, rnd, self._loc.noon),
        )

    def _sunrise(
        self, dt: date, observer_elevation: ObsElv | None = None, *, rnd: bool = False
    ) -> datetime | None:
        """Return sunrise."""
        if observer_elevation is None:
            observer_elevation = self._east_obs_elv
        return self._astral_dt_2_dttm_none(
            "SR",
            dt,
            rnd,
            partial(self._loc.sunrise, observer_elevation=observer_elevation),
        )

    def _sunset(
        self, dt: date, observer_elevation: ObsElv | None = None, *, rnd: bool = False
    ) -> datetime | None:
        """Return sunset."""
        if observer_elevation is None:
            observer_elevation = self._west_obs_elv
        return self._astral_dt_2_dttm_none(
            "SS",
            dt,
            rnd,
            partial(self._loc.sunset, observer_elevation=observer_elevation),
        )

    def _time_at_elevation(
        self,
        elevation: float,
        *,
        dt: date | None = None,
        direction: SunDirection = SunDirection.RISING,
        rnd: bool = False,
    ) -> datetime | None:
        """Return time at solar elevation."""
        result: datetime | None
        try:
            result = self._loc.time_at_elevation(elevation, dt, direction, False)
        except (TypeError, ValueError):
            result = None
            fmt_result = str(None)
        else:
            fmt_result = self._dttm_2_str(result)
            if rnd:
                result = nearest_second(result)
        LOGGER.debug(
            "%s:   TAE(%s, %10.6f, %-20s) -> %s",
            self._log_name,
            dt,
            elevation,
            direction,
            fmt_result,
        )
        return result

    def _astral_dt_2_dttm_none(
        self, label: str, dt: date, rnd: bool, func: Callable[[date, bool], datetime]
    ) -> datetime | None:
        """Call an astral function.

        Astral function takes a date and returns a datetime or throws an exception, in
        which case, return None.
        """
        result: datetime | None
        try:
            result = func(dt, False)
        except (TypeError, ValueError):
            result = None
            fmt_result = str(None)
        else:
            fmt_result = self._dttm_2_str(result)
            if rnd:
                result = nearest_second(result)
            if hasattr(func, "cache_info"):
                fmt_result += f" cache_info: {func.cache_info()}"
        LOGGER.debug(
            "%s:   %-3s(%s)%35s-> %s",
            self._log_name,
            label,
            dt,
            "",
            fmt_result,
        )
        return result

    def _astral_dttm_2_float(
        self, label: str, dttm: datetime, func: Callable[[datetime], float]
    ) -> float:
        """Call an astral function.

        Astral function takes a datetime and returns a float.
        """
        result = func(dttm)
        LOGGER.debug(
            "%s:   %-3s(%s)%13s-> %s",
            self._log_name,
            label,
            self._dttm_2_str(dttm),
            "",
            result,
        )
        return result


class Sun2EntityWithElvAdjs(Sun2Entity):
    """Sun2 Entity with elevation adjustments."""

    # Override in subclass if _nxt_dir_chg_dttm not used.
    _use_nxt_dir_chg: bool = True

    _prv_dir_chg_dttm: datetime  # Only used for first update
    _nxt_dir_chg_dttm: datetime

    # Elevation curve parameters
    _dt: date
    __rising: bool

    @property
    def _rising(self) -> bool:
        """Return if sun is rising."""
        return self.__rising

    @_rising.setter
    def _rising(self, rising: bool) -> None:
        """Set if sun is rising."""
        # NOTE: Instance variables starting with double underscores get mangled with
        # class name.
        changed = (
            not hasattr(self, f"_{self.__class__.__name__}__rising")
            or rising != self.__rising
        )
        self.__rising = rising
        if changed:
            self._rising_changed()

    @cached_property
    def _sun_direction(self) -> SunDirection:
        """Return sun direction."""
        if self._rising:
            return SunDirection.RISING
        return SunDirection.SETTING

    @cached_property
    def _ris_elv_adj(self) -> float:
        """Return rising elevation adjustment."""
        if isinstance(self._east_obs_elv, Num):
            ris_elv_adj: float = adjust_to_horizon(self._east_obs_elv)
        else:
            ris_elv_adj = adjust_to_obscuring_feature(self._east_obs_elv)
        LOGGER.debug("%s: ris_elv_adj: %10.6f", self._log_name, ris_elv_adj)
        return ris_elv_adj

    @cached_property
    def _set_elv_adj(self) -> float:
        """Return setting elevation adjustment."""
        if isinstance(self._west_obs_elv, Num):
            set_elv_adj: float = adjust_to_horizon(self._west_obs_elv)
        else:
            set_elv_adj = adjust_to_obscuring_feature(self._west_obs_elv)
        LOGGER.debug("%s: set_elv_adj: %10.6f", self._log_name, set_elv_adj)
        return set_elv_adj

    def _rising_changed(self) -> None:
        """Rising attribute changed."""
        with suppress(AttributeError):
            del self._sun_direction

    def _change_sun_direction(self) -> None:
        """Change sun direction."""
        self._rising = not self._rising
        if self._rising:
            self._dt += ONE_DAY
        if not self._use_nxt_dir_chg:
            return
        if self._rising:
            self._nxt_dir_chg_dttm = self._solar_noon(self._dt)
        else:
            self._nxt_dir_chg_dttm = self._solar_midnight(self._dt + ONE_DAY)

    def _update_astral_data(self, astral_data: AstralData) -> None:
        """Update astral data."""
        super()._update_astral_data(astral_data)
        with suppress(AttributeError):
            del self._ris_elv_adj
        with suppress(AttributeError):
            del self._set_elv_adj

    def _update_setup(self, cur_dttm: datetime) -> None:
        """Set up before first update.

        Find the last time that the sun changed direction (i.e., the last solar noon or
        solar midnight before current time.)

        Also initialize self._dt & self._rising based on that determination.
        """
        super()._update_setup(cur_dttm)

        # Note that solar midnight for a given date can happen early on that same
        # day (where the date is the same), or it can happen late on the previous
        # day (where the date is one less.) Therefore, it's possible for zero, one
        # or two solar midnight events to happen in the current day.
        # So, start by checking the current time against today's solar midnight, then
        # today's solar noon, and lastly, tomorrow's solar midnight.
        self._dt = self._as_tz(cur_dttm).date()
        if cur_dttm < (sol_midn := self._solar_midnight(self._dt)):
            # Last event was solar noon yesterday.
            self._rising = False
            self._dt -= ONE_DAY
            self._prv_dir_chg_dttm = self._solar_noon(self._dt)
            if self._use_nxt_dir_chg:
                self._nxt_dir_chg_dttm = sol_midn
        elif cur_dttm < (sol_noon := self._solar_noon(self._dt)):
            # Last event was solar midnight today.
            self._rising = True
            self._prv_dir_chg_dttm = sol_midn
            if self._use_nxt_dir_chg:
                self._nxt_dir_chg_dttm = sol_noon
        elif cur_dttm < (sol_midn := self._solar_midnight(self._dt + ONE_DAY)):
            # Last event was solar solar noon today.
            self._rising = False
            self._prv_dir_chg_dttm = sol_noon
            if self._use_nxt_dir_chg:
                self._nxt_dir_chg_dttm = sol_midn
        else:
            # Last event was solar midnight tomorrow.
            self._rising = True
            self._dt += ONE_DAY
            self._prv_dir_chg_dttm = sol_midn
            if self._use_nxt_dir_chg:
                self._nxt_dir_chg_dttm = self._solar_noon(self._dt)

    def _time_at_elevation(
        self,
        elevation: float,
        *,
        adj_elv: bool = True,
        rnd: bool = False,
        **kwargs: Any,
    ) -> datetime | None:
        """Return time at solar elevation."""
        return super()._time_at_elevation(
            elevation
            - adj_elv * (self._ris_elv_adj if self._rising else self._set_elv_adj),
            dt=self._dt,
            direction=self._sun_direction,
            rnd=rnd,
        )


class Sun2EntrySetup(ABC):
    """Platform config entry setup."""

    _remove_ha_loc_listener: Callable[[], None] | None = None

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        """Initialize."""
        self._hass = hass
        self._entry = entry

        entry.async_on_unload(self._unsub_ha_loc_updated)

        config_data = self._s2data.config_data[entry.entry_id]
        loc_data = config_data.loc_data
        obs_elvs = config_data.obs_elvs

        # These are available to _get_entities method defined in subclass.
        self._imported = entry.source == SOURCE_IMPORT
        self._uid_prefix = f"{entry.entry_id}-"
        self._sun2_entity_params = Sun2EntityParams(
            entry.pref_disable_polling,
            sun2_dev_info(hass, entry),
            AstralData(self._new_loc_data(loc_data), obs_elvs),
        )

        self._entities = list(self._get_entities())
        async_add_entities(self._entities, True)
        self._obs_elvs = obs_elvs

        self._entry.async_on_unload(
            async_dispatcher_connect(
                self._hass,
                SIG_ASTRAL_DATA_UPDATED.format(self._entry.entry_id),
                self._astral_data_updated,
            )
        )

    @cached_property
    def _s2data(self) -> Sun2Data:
        """Return Sun2Data."""
        return sun2_data(self._hass)

    def _unsub_ha_loc_updated(self) -> None:
        """Unsubscribe to HA location updated signal."""
        if self._remove_ha_loc_listener:
            self._remove_ha_loc_listener()
            self._remove_ha_loc_listener = None

    def _sub_ha_loc_updated(self) -> None:
        """Subscribe to HA location updated signal."""
        if not self._remove_ha_loc_listener:
            self._remove_ha_loc_listener = async_dispatcher_connect(
                self._hass, SIG_HA_LOC_UPDATED, self._ha_loc_updated
            )

    def _new_loc_data(self, loc_data: LocData | None) -> LocData:
        """Check new location data.

        None -> use HA's configured location.
        """
        if loc_data:
            self._unsub_ha_loc_updated()
            return loc_data
        self._sub_ha_loc_updated()
        return self._s2data.ha_loc_data

    @abstractmethod
    def _get_entities(self) -> Iterable[Sun2Entity]:
        """Return entities to add."""

    @callback
    def _astral_data_updated(self, loc_data: LocData | None, obs_elvs: ObsElvs) -> None:
        """Handle new astral data."""
        self._update_entities(self._new_loc_data(loc_data), obs_elvs)

    @callback
    def _ha_loc_updated(self) -> None:
        """Handle new HA location configuration."""
        self._update_entities(self._s2data.ha_loc_data)

    def _update_entities(
        self, loc_data: LocData, obs_elvs: ObsElvs | None = None
    ) -> None:
        """Update entities with new astral data."""
        if obs_elvs is None:
            obs_elvs = self._obs_elvs
        else:
            self._obs_elvs = obs_elvs
        astral_data = AstralData(loc_data, obs_elvs)
        for entity in self._entities:
            if entity.enabled:
                self._update_entity(entity, astral_data)

    def _update_entity(self, entity: Sun2Entity, astral_data: AstralData) -> None:
        """Update entity with new astral data."""

        async def update_entity(entity: Sun2Entity, astral_data: AstralData) -> None:
            """Update entity."""
            await entity.async_request_call(entity.update_astral_data(astral_data))
            await entity.async_update_ha_state(True)

        self._entry.async_create_task(
            self._hass,
            update_entity(entity, astral_data),
            f"Update astral data: {entity.name}",
        )

    @classmethod
    async def async_setup_entry(
        cls,
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        """Platform async_setup_entry function.

        class Sun2PlatformEntrySetup(Sun2EntrySetup):
            def _get_entities(self) -> list[Sun2Entity]:
            ...

        async_setup_entry = Sun2PlatformEntrySetup.async_setup_entry
        """
        cls(hass, entry, async_add_entities)
