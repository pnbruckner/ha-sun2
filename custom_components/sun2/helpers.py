"""Sun2 Helpers."""
from __future__ import annotations

from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from math import copysign, fabs
from typing import Any, Self, Union, cast

from astral import LocationInfo
from astral.location import Location

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_ELEVATION,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_TIME_ZONE,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType

# Device Info moved to device_registry in 2023.9
try:
    from homeassistant.helpers.device_registry import DeviceInfo
except ImportError:
    from homeassistant.helpers.entity import DeviceInfo  # type: ignore[attr-defined]

from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_NEXT_CHANGE,
    ATTR_TODAY_HMS,
    ATTR_TOMORROW,
    ATTR_TOMORROW_HMS,
    ATTR_YESTERDAY,
    ATTR_YESTERDAY_HMS,
    CONF_OBS_ELV,
    DOMAIN,
    ONE_DAY,
    SIG_HA_LOC_UPDATED,
)

Num = Union[float, int]


@dataclass(frozen=True)
class LocParams:
    """Location parameters."""

    latitude: float
    longitude: float
    time_zone: str

    @classmethod
    def from_entry_options(cls, options: Mapping[str, Any]) -> Self | None:
        """Initialize from configuration entry options."""
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
    tzi: tzinfo

    @classmethod
    def from_loc_params(cls, lp: LocParams) -> Self:
        """Initialize from LocParams."""
        tzi = dt_util.get_time_zone(tz := lp.time_zone)
        assert tzi
        return cls(Location(LocationInfo("", "", tz, lp.latitude, lp.longitude)), tzi)

    @classmethod
    def from_hass_config(cls, hass: HomeAssistant) -> Self:
        """Initialize from HA configuration."""
        hc = hass.config
        tzi = dt_util.get_time_zone(tz := hc.time_zone)
        assert tzi
        return cls(Location(LocationInfo("", "", tz, hc.latitude, hc.longitude)), tzi)


@dataclass
class Sun2Data:
    """Sun2 shared data."""

    locations: dict[LocParams | None, LocData] = field(default_factory=dict)
    translations: dict[str, str] = field(default_factory=dict)
    language: str | None = None


def hours_to_hms(hours: Num | None) -> str | None:
    """Convert hours to HH:MM:SS string."""
    try:
        return str(timedelta(seconds=int(cast(Num, hours) * 3600)))
    except TypeError:
        return None


_TRANS_PREFIX = f"component.{DOMAIN}.selector.misc.options"


async def init_translations(hass: HomeAssistant) -> None:
    """Initialize translations."""
    data = cast(Sun2Data, hass.data.setdefault(DOMAIN, Sun2Data()))
    if data.language != hass.config.language:
        sel_trans = await async_get_translations(
            hass, hass.config.language, "selector", [DOMAIN], False
        )
        data.translations = {}
        for sel_key, val in sel_trans.items():
            prefix, key = sel_key.rsplit(".", 1)
            if prefix == _TRANS_PREFIX:
                data.translations[key] = val


def translate(
    hass: HomeAssistant, key: str, placeholders: dict[str, Any] | None = None
) -> str:
    """Sun2 translations."""
    trans = cast(Sun2Data, hass.data[DOMAIN]).translations[key]
    if not placeholders:
        return trans
    for ph_key, val in placeholders.items():
        trans = trans.replace(f"{{{ph_key}}}", str(val))
    return trans


def sun2_dev_info(hass: HomeAssistant, entry: ConfigEntry) -> DeviceInfo:
    """Sun2 device (service) info."""
    return DeviceInfo(
        entry_type=DeviceEntryType.SERVICE,
        identifiers={(DOMAIN, entry.entry_id)},
        name=translate(hass, "service_name", {"location": entry.title}),
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
class Sun2EntityParams:
    """Sun2Entity parameters."""

    entry: ConfigEntry
    device_info: DeviceInfo
    unique_id: str = ""


class Sun2Entity(Entity):
    """Sun2 Entity."""

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
    _loc_data: LocData = None  # type: ignore[assignment]
    _unsub_update: CALLBACK_TYPE | None = None
    _event: str
    _solar_depression: Num | str

    @abstractmethod
    def __init__(
        self,
        loc_params: LocParams | None,
        sun2_entity_params: Sun2EntityParams,
    ) -> None:
        """Initialize base class."""
        self._attr_has_entity_name = True
        self._attr_translation_key = self.entity_description.key
        self._attr_unique_id = sun2_entity_params.unique_id
        self._attr_device_info = sun2_entity_params.device_info
        self._loc_params = loc_params
        options = sun2_entity_params.entry.options
        if obs_elv := options.get(CONF_OBS_ELV):
            east_obs_elv, west_obs_elv = obs_elv
            self._east_obs_elv = self._obs_elv_cfg_2_astral(east_obs_elv)
            self._west_obs_elv = self._obs_elv_cfg_2_astral(west_obs_elv)
        else:
            self._east_obs_elv = self._west_obs_elv = options.get(CONF_ELEVATION, 0)
        self.async_on_remove(self._cancel_update)

    @staticmethod
    def _obs_elv_cfg_2_astral(
        obs_elv: float | list[float],
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
        if isinstance(obs_elv, list):
            height, distance = obs_elv
            return -copysign(1, height) * distance, fabs(height)
        return obs_elv

    @property
    def _sun2_data(self) -> Sun2Data:
        return cast(Sun2Data, self.hass.data[DOMAIN])

    async def async_update(self) -> None:
        """Update state."""
        if not self._loc_data:
            self._loc_data = self._get_loc_data()
        self._update(dt_util.now(self._loc_data.tzi))

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        self._setup_fixed_updating()

    def _cancel_update(self) -> None:
        """Cancel update."""
        if self._unsub_update:
            self._unsub_update()
            self._unsub_update = None

    def _get_loc_data(self) -> LocData:
        """Get location data from location parameters.

        loc_params = None -> Use location parameters from HA's config.
        """
        try:
            loc_data = self._sun2_data.locations[self._loc_params]
        except KeyError:
            # LocData from HA's config will always be in cache, so will not get here if
            # self._loc_params is None.
            assert self._loc_params
            loc_data = self._sun2_data.locations[
                self._loc_params
            ] = LocData.from_loc_params(self._loc_params)

        if not self._loc_params:

            async def loc_updated(loc_data: LocData) -> None:
                """Location updated."""
                await self.async_request_call(self._async_loc_updated(loc_data))

            self.async_on_remove(
                async_dispatcher_connect(self.hass, SIG_HA_LOC_UPDATED, loc_updated)
            )

        return loc_data

    async def _async_loc_updated(self, loc_data: LocData) -> None:
        """Location updated."""
        self._cancel_update()
        self._loc_data = loc_data
        self._setup_fixed_updating()
        self.async_schedule_update_ha_state(True)

    @abstractmethod
    def _update(self, cur_dttm: datetime) -> None:
        """Update state."""

    def _setup_fixed_updating(self) -> None:
        """Set up fixed updating."""

    def _astral_event(
        self,
        date_or_dttm: date | datetime,
        event: str | None = None,
        /,
        **kwargs: Any,
    ) -> Any:
        """Return astral event result."""
        if not event:
            event = self._event
        loc = self._loc_data.loc
        if hasattr(self, "_solar_depression"):
            loc.solar_depression = self._solar_depression

        try:
            if event in ("solar_midnight", "solar_noon"):
                return getattr(loc, event.split("_")[1])(date_or_dttm)

            if event == "time_at_elevation":
                return loc.time_at_elevation(
                    kwargs["elevation"], date_or_dttm, kwargs["direction"]
                )

            if event in ("sunrise", "dawn"):
                kwargs = {"observer_elevation": self._east_obs_elv}
            elif event in ("sunset", "dusk"):
                kwargs = {"observer_elevation": self._west_obs_elv}
            else:
                kwargs = {}
            return getattr(loc, event)(date_or_dttm, **kwargs)

        except (TypeError, ValueError):
            return None
