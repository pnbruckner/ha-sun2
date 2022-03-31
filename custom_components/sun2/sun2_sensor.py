from abc import ABC, abstractmethod

from homeassistant.const import (
    MAJOR_VERSION,
    MINOR_VERSION,
)
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util, slugify

from .helpers import (
    async_init_astral_loc,
    get_local_info,
    SIG_LOC_UPDATED,
)


class Sun2SensorBase(ABC):
    """Sun2 Abstract Base Class."""

    @abstractmethod
    def __init__(self, hass, name, info):
        """Initialize base class."""
        self.hass = hass
        self._name = self._orig_name = name
        self._state = None

        self._use_local_info = info is None
        if self._use_local_info:
            self._info = get_local_info(hass)
        else:
            self._info = info

        self._unsub_loc_updated = None
        self._unsub_update = None

    @property
    def _info(self):
        return self.__info

    @_info.setter
    def _info(self, info):
        self.__info = info
        self._tzinfo = dt_util.get_time_zone(info[2])
        async_init_astral_loc(self.hass, info)

    @property
    def should_poll(self):
        """Do not poll."""
        return False

    @property
    def name(self):
        """Return the name of the entity."""
        return self._name

    @abstractmethod
    def _device_state_attributes(self):
        pass

    if MAJOR_VERSION < 2021 or MAJOR_VERSION == 2021 and MINOR_VERSION < 4:

        @property
        def device_state_attributes(self):
            """Return device specific state attributes."""
            return self._device_state_attributes()

    else:

        @property
        def extra_state_attributes(self):
            """Return device specific state attributes."""
            return self._device_state_attributes()

    def _setup_fixed_updating(self):
        pass

    def _loc_updated(self):
        if self._unsub_update:
            self._unsub_update()
            self._unsub_update = None
        self._info = get_local_info(self.hass)
        self._setup_fixed_updating()
        self.async_schedule_update_ha_state(True)

    async def async_loc_updated(self):
        """Location updated."""
        self._loc_updated()

    async def async_added_to_hass(self):
        """Run when entity about to be added to hass."""
        # Determine final name, which will include entity_namespace if it's used.
        slug = slugify(self._orig_name)
        object_id = self.entity_id.split(".")[1]
        if slug != object_id and object_id.endswith(slug):
            prefix = object_id[: -len(slug)].replace("_", " ").strip().title()
            self._name = f"{prefix} {self._orig_name}"

        # Now that we have final name, let's do the update that was delayed from
        # async_add_entities call.
        await self.async_update()

        # Subscribe to update signal.
        if self._use_local_info:
            self._unsub_loc_updated = async_dispatcher_connect(
                self.hass, SIG_LOC_UPDATED, self.async_loc_updated
            )

        self._setup_fixed_updating()

    async def async_will_remove_from_hass(self):
        """Run when entity will be removed from hass."""
        # Disconnect from update signal and cancel any pending updates.
        if self._unsub_loc_updated:
            self._unsub_loc_updated()
        if self._unsub_update:
            self._unsub_update()
        # Return name to what it was originally so platform doesn't get confused.
        self._name = self._orig_name
