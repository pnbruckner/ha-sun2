"""Sun2 Helpers."""
from __future__ import annotations

from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any, TypeVar, Union, cast

from astral import LocationInfo
from astral.location import Location
import voluptuous as vol

from homeassistant.const import (
    CONF_ELEVATION,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_TIME_ZONE,
    EVENT_CORE_CONFIG_UPDATE,
)
from homeassistant.core import CALLBACK_TYPE, Event
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    dispatcher_send,
)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util, slugify

from .const import DOMAIN, LOGGER, ONE_DAY, SIG_HA_LOC_UPDATED


Num = Union[float, int]
LOC_PARAMS = {
    vol.Inclusive(CONF_ELEVATION, "location"): vol.Coerce(float),
    vol.Inclusive(CONF_LATITUDE, "location"): cv.latitude,
    vol.Inclusive(CONF_LONGITUDE, "location"): cv.longitude,
    vol.Inclusive(CONF_TIME_ZONE, "location"): cv.time_zone,
}


@dataclass(frozen=True)
class LocParams:
    """Location parameters."""

    elevation: Num
    latitude: float
    longitude: float
    time_zone: str


@dataclass(frozen=True)
class LocData:
    """Location data."""

    loc: Location
    elv: Num
    tzi: tzinfo

    def __init__(self, lp: LocParams) -> None:
        """Initialize location data from location parameters."""
        loc = Location(LocationInfo("", "", lp.time_zone, lp.latitude, lp.longitude))
        object.__setattr__(self, "loc", loc)
        object.__setattr__(self, "elv", lp.elevation)
        object.__setattr__(self, "tzi", dt_util.get_time_zone(lp.time_zone))


def get_loc_params(config: ConfigType) -> LocParams | None:
    """Get location parameters from configuration."""
    try:
        return LocParams(
            config[CONF_ELEVATION],
            config[CONF_LATITUDE],
            config[CONF_LONGITUDE],
            config[CONF_TIME_ZONE],
        )
    except KeyError:
        return None


def hours_to_hms(hours: Num | None) -> str | None:
    """Convert hours to HH:MM:SS string."""
    try:
        return str(timedelta(hours=cast(Num, hours))).split(".")[0]
    except TypeError:
        return None


_Num = TypeVar("_Num", bound=Num)


def nearest_second(dttm: datetime) -> datetime:
    """Round dttm to nearest second."""
    return dttm.replace(microsecond=0) + timedelta(
        seconds=0 if dttm.microsecond < 500000 else 1
    )


def next_midnight(dttm: datetime) -> datetime:
    """Return next midnight in same time zone."""
    return datetime.combine(dttm.date() + ONE_DAY, time(), dttm.tzinfo)


class Sun2Entity(Entity):
    """Sun2 Entity."""

    _attr_should_poll = False
    _loc_data: LocData = None  # type: ignore[assignment]
    _unsub_update: CALLBACK_TYPE | None = None
    _event: str
    _solar_depression: Num | str

    @abstractmethod
    def __init__(
        self, loc_params: LocParams | None, domain: str, object_id: str
    ) -> None:
        """Initialize base class.

        self.name must be set up to return name before calling this.
        E.g., set up self.entity_description.name first.
        """
        # Note that entity_platform will add namespace prefix to object ID.
        self.entity_id = f"{domain}.{slugify(object_id)}"
        self._attr_unique_id = self.name
        self._loc_params = loc_params

    async def async_update(self) -> None:
        """Update state."""
        if not self._loc_data:
            self._loc_data = self._get_loc_data()
        self._update(dt_util.now(self._loc_data.tzi))

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        self._setup_fixed_updating()

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        if self._unsub_update:
            self._unsub_update()
            self._unsub_update = None

    def _get_loc_data(self) -> LocData:
        """Get location data from location parameters.

        loc_params = None -> Use location parameters from HA's config.
        """
        if DOMAIN not in self.hass.data:
            self.hass.data[DOMAIN] = {}

            def update_local_loc_data(event: Event | None = None) -> None:
                """Update local location data from HA's config."""
                self.hass.data[DOMAIN][None] = loc_data = LocData(
                    LocParams(
                        self.hass.config.elevation,
                        self.hass.config.latitude,
                        self.hass.config.longitude,
                        str(self.hass.config.time_zone),
                    )
                )
                if event:
                    # Signal all instances that location data has changed.
                    dispatcher_send(self.hass, SIG_HA_LOC_UPDATED, loc_data)

            update_local_loc_data()
            self.hass.bus.async_listen(EVENT_CORE_CONFIG_UPDATE, update_local_loc_data)

        try:
            loc_data = cast(LocData, self.hass.data[DOMAIN][self._loc_params])
        except KeyError:
            loc_data = self.hass.data[DOMAIN][self._loc_params] = LocData(
                cast(LocParams, self._loc_params)
            )

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
        if self._unsub_update:
            self._unsub_update()
            self._unsub_update = None
        self._loc_data = loc_data
        self._setup_fixed_updating()
        self.async_schedule_update_ha_state(True)

    @abstractmethod
    def _update(self, cur_dttm: datetime) -> None:
        """Update state."""
        pass

    def _setup_fixed_updating(self) -> None:
        """Set up fixed updating."""
        pass

    def _astral_event(
        self,
        date_or_dttm: date | datetime,
        event: str | None = None,
        /,
        **kwargs: Mapping[str, Any],
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
            elif event == "time_at_elevation":
                return loc.time_at_elevation(
                    kwargs["elevation"], date_or_dttm, kwargs["direction"]
                )
            else:
                return getattr(loc, event)(
                    date_or_dttm, observer_elevation=self._loc_data.elv
                )
        except (TypeError, ValueError):
            return None
