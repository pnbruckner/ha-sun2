"""Sun2 Helpers."""
from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable, Coroutine, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from functools import lru_cache
import logging
from math import copysign, fabs
from typing import Any, Self, cast, overload

from astral import LocationInfo
from astral.location import Location

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import (
    CONF_ELEVATION,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_TIME_ZONE,
)
from homeassistant.core import CALLBACK_TYPE, Config, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType

# Device Info moved to device_registry in 2023.9
try:
    from homeassistant.helpers.device_registry import DeviceInfo
except ImportError:
    from homeassistant.helpers.entity import DeviceInfo  # type: ignore[attr-defined]

from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.translation import async_get_translations
from homeassistant.helpers.typing import ConfigType
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
    SIG_ASTRAL_DATA_UPDATED,
    SIG_HA_LOC_UPDATED,
)

_LOGGER = logging.getLogger(__name__)

Num = float | int


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
            _LOGGER.warning("Did not find time zone: %s", lp.time_zone)
        return cls(Location(LocationInfo("", "", tz, lp.latitude, lp.longitude)), tzi)


@lru_cache
def _get_loc_data(lp: LocParams | None) -> LocData | None:
    """Get LocData from LocParams & cache results.

    lp = None -> using HA's location configuration; return None
    """
    if lp is None:
        return None
    return LocData.from_loc_params(lp)


@overload
def get_loc_data(arg: Config) -> LocData:
    ...


@overload
def get_loc_data(arg: Mapping[str, Any]) -> LocData | None:
    ...


def get_loc_data(arg: Config | Mapping[str, Any]) -> LocData | None:
    """Get LocData from HA config or config entry options.

    If config entry provided, and it does not contain location options,
    then return None, meaning HA's location configuration should be used.
    """
    if isinstance(arg, Config):
        return _get_loc_data(LocParams.from_hass_config(arg))
    return _get_loc_data(LocParams.from_entry_options(arg))


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
        if isinstance(obs_elv, Num):  # type: ignore[misc, arg-type]
            return float(cast(Num, obs_elv))
        height, distance = cast(list[Num], obs_elv)
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
    binary_sensors: list[dict[str, Any]]
    sensors: list[dict[str, Any]]
    loc_data: LocData | None
    obs_elvs: ObsElvs


@dataclass
class Sun2Data:
    """Sun2 shared data."""

    ha_loc_data: LocData
    translations: dict[str, str] = field(default_factory=dict)
    language: str | None = None
    config_data: dict[str, ConfigData] = field(default_factory=dict)


def sun2_data(hass: HomeAssistant) -> Sun2Data:
    """Return Sun2 integration data."""
    try:
        return cast(Sun2Data, hass.data[DOMAIN])
    except KeyError:
        hass.data[DOMAIN] = s2data = Sun2Data(get_loc_data(hass.config))
        return s2data


def hours_to_hms(hours: Num | None) -> str | None:
    """Convert hours to HH:MM:SS string."""
    try:
        return str(timedelta(seconds=int(cast(Num, hours) * 3600)))
    except TypeError:
        return None


_TRANS_PREFIX = f"component.{DOMAIN}.selector.misc.options"


async def init_translations(hass: HomeAssistant) -> None:
    """Initialize translations."""
    s2data = sun2_data(hass)
    if s2data.language != hass.config.language:
        sel_trans = await async_get_translations(
            hass, hass.config.language, "selector", [DOMAIN], False
        )
        s2data.translations = {}
        for sel_key, val in sel_trans.items():
            prefix, key = sel_key.rsplit(".", 1)
            if prefix == _TRANS_PREFIX:
                s2data.translations[key] = val


def translate(
    hass: HomeAssistant, key: str, placeholders: dict[str, Any] | None = None
) -> str:
    """Sun2 translations."""
    trans = sun2_data(hass).translations[key]
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
class AstralData:
    """astral data."""

    loc_data: LocData
    obs_elvs: ObsElvs


@dataclass
class Sun2EntityParams:
    """Sun2Entity parameters."""

    device_info: DeviceInfo
    astral_data: AstralData
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
    _unsub_update: CALLBACK_TYPE | None = None
    _event: str
    _solar_depression: Num | str

    @abstractmethod
    def __init__(self, sun2_entity_params: Sun2EntityParams) -> None:
        """Initialize base class."""
        self._attr_has_entity_name = True
        self._attr_translation_key = self.entity_description.key
        self._attr_unique_id = sun2_entity_params.unique_id
        self._attr_device_info = sun2_entity_params.device_info
        self._astral_data = sun2_entity_params.astral_data
        self.async_on_remove(self._cancel_update)

    async def async_update(self) -> None:
        """Update state."""
        self._update(dt_util.now(self._astral_data.loc_data.tzi))

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        self._setup_fixed_updating()

    def request_astral_data_update(self, astral_data: AstralData) -> None:
        """Request update of astral data."""
        cast(ConfigEntry, self.platform.config_entry).async_create_task(
            self.hass,
            self._update_astral_data_atomic(astral_data),
            f"{self.name}: update astral data",
        )

    def _cancel_update(self) -> None:
        """Cancel update."""
        if self._unsub_update:
            self._unsub_update()
            self._unsub_update = None

    @abstractmethod
    def _update(self, cur_dttm: datetime) -> None:
        """Update state."""

    def _setup_fixed_updating(self) -> None:
        """Set up fixed updating."""

    async def _update_astral_data_atomic(self, astral_data: AstralData) -> None:
        """Update astral data atomically."""

        async def do_update_astral_data() -> None:
            """Update astral data."""
            self._update_astral_data(astral_data)

        await self.async_request_call(do_update_astral_data())
        self.async_schedule_update_ha_state(True)

    def _update_astral_data(self, astral_data: AstralData) -> None:
        """Update astral data."""
        self._cancel_update()
        self._astral_data = astral_data
        self._setup_fixed_updating()

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
        loc = self._astral_data.loc_data.loc
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
                kwargs = {"observer_elevation": self._astral_data.obs_elvs.east}
            elif event in ("sunset", "dusk"):
                kwargs = {"observer_elevation": self._astral_data.obs_elvs.west}
            else:
                kwargs = {}
            return getattr(loc, event)(date_or_dttm, **kwargs)

        except (TypeError, ValueError):
            return None


def make_async_setup_entry(
    sensors: Callable[
        [HomeAssistant, bool, str, Sun2EntityParams, Iterable[ConfigType | str]],
        list[Sun2Entity],
    ],
    sensor_configs: Callable[[ConfigEntry], Iterable[ConfigType | str]],
) -> Callable[
    [HomeAssistant, ConfigEntry, AddEntitiesCallback], Coroutine[Any, Any, None]
]:
    """Make async_setup_entry function."""

    async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        """Set up the sensor platform."""
        s2data = sun2_data(hass)
        imported = entry.source == SOURCE_IMPORT
        uid_prefix = f"{entry.entry_id}-"
        device_info = sun2_dev_info(hass, entry)
        config_data = s2data.config_data[entry.entry_id]
        if (loc_data := config_data.loc_data) is None:
            loc_data = s2data.ha_loc_data
        obs_elvs = config_data.obs_elvs
        sun2_entity_params = Sun2EntityParams(
            device_info, AstralData(loc_data, obs_elvs)
        )

        entities = sensors(
            hass, imported, uid_prefix, sun2_entity_params, sensor_configs(entry)
        )
        async_add_entities(entities, True)

        def update_entities(
            loc_data_: LocData, obs_elvs_: ObsElvs | None = None
        ) -> None:
            """Update entities with new astral data."""
            nonlocal obs_elvs

            if obs_elvs_ is None:
                obs_elvs_ = obs_elvs
            else:
                obs_elvs = obs_elvs_
            astral_data = AstralData(loc_data_, obs_elvs_)
            for entity in entities:
                entity.request_astral_data_update(astral_data)

        @callback
        def ha_loc_updated() -> None:
            """Handle new HA location configuration."""
            update_entities(s2data.ha_loc_data)

        remove_ha_loc_listener: Callable[[], None] | None = None

        def sub_ha_loc_updated() -> None:
            """Subscribe to HA location updated signal."""
            nonlocal remove_ha_loc_listener

            if not remove_ha_loc_listener:
                remove_ha_loc_listener = async_dispatcher_connect(
                    hass, SIG_HA_LOC_UPDATED, ha_loc_updated
                )

        def unsub_ha_loc_updated() -> None:
            """Unsubscribe to HA location updated signal."""
            nonlocal remove_ha_loc_listener

            if remove_ha_loc_listener:
                remove_ha_loc_listener()
                remove_ha_loc_listener = None

        @callback
        def astral_data_updated(loc_data: LocData | None, obs_elvs: ObsElvs) -> None:
            """Handle new astral data."""
            if loc_data is None:
                sub_ha_loc_updated()
                loc_data = s2data.ha_loc_data
            else:
                unsub_ha_loc_updated()
            update_entities(loc_data, obs_elvs)

        entry.async_on_unload(unsub_ha_loc_updated)
        entry.async_on_unload(
            async_dispatcher_connect(
                hass,
                SIG_ASTRAL_DATA_UPDATED.format(entry.entry_id),
                astral_data_updated,
            )
        )

    return async_setup_entry
