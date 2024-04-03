"""Sun2 integration."""
from __future__ import annotations

import asyncio
from collections.abc import Coroutine
import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_USER, ConfigEntry
from homeassistant.const import (
    CONF_BINARY_SENSORS,
    CONF_LATITUDE,
    CONF_LOCATION,
    CONF_LONGITUDE,
    CONF_SENSORS,
    CONF_TIME_ZONE,
    CONF_UNIQUE_ID,
    EVENT_CORE_CONFIG_UPDATE,
    SERVICE_RELOAD,
    Platform,
)
from homeassistant.core import (
    Event,
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.reload import async_integration_yaml_config
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType

from .config import (
    SUN2_LOCATION_BASE_SCHEMA,
    obs_elv_from_options,
    options_from_obs_elv,
)
from .config_flow import loc_from_options
from .const import CONF_OBS_ELV, DOMAIN, SIG_ASTRAL_DATA_UPDATED, SIG_HA_LOC_UPDATED
from .helpers import ConfigData, ObsElvs, get_loc_data, sun2_data

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]

_UUID_UNIQUE_ID = re.compile(r"[0-9a-f]{32}")
_LOCATION = {vol.Required(CONF_LOCATION): cv.string}
_GET_LOCATION_SERVICE_SCHEMA = vol.Schema(_LOCATION)
_UPDATE_LOCATION_SERVICE_SCHEMA = SUN2_LOCATION_BASE_SCHEMA.extend(_LOCATION)


async def _process_config(
    hass: HomeAssistant, config: ConfigType | None, run_immediately: bool = True
) -> None:
    """Process sun2 config."""
    if not config or not (configs := config.get(DOMAIN)):
        configs = []
    unique_ids = [config[CONF_UNIQUE_ID] for config in configs]
    tasks: list[Coroutine[Any, Any, Any]] = []

    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.source != SOURCE_IMPORT:
            continue
        if entry.unique_id not in unique_ids:
            tasks.append(hass.config_entries.async_remove(entry.entry_id))

    for conf in configs:
        tasks.append(  # noqa: PERF401
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}, data=dict(conf)
            )
        )

    if not tasks:
        return

    if run_immediately:
        await asyncio.gather(*tasks)
    else:
        for task in tasks:
            hass.async_create_task(task)


def _entry_by_title(
    hass: HomeAssistant, title: str
) -> tuple[ConfigEntry, dict[str, Any]]:
    """Get config entry by title and a mutable copy of its options.

    Raise ValueError if title does not exist.
    """
    for entry in hass.config_entries.async_entries(
        DOMAIN, include_ignore=False, include_disabled=False
    ):
        if entry.title == title:
            return entry, dict(entry.options)
    raise ValueError(f"Integration entry does not exist or is not loaded: {title}")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up composite integration."""

    async def reload_config(call: ServiceCall | None = None) -> None:
        """Reload configuration."""
        await _process_config(hass, await async_integration_yaml_config(hass, DOMAIN))

    @callback
    def get_location(call: ServiceCall) -> ServiceResponse:
        """Get location parameters."""
        _, options = _entry_by_title(hass, location := call.data[CONF_LOCATION])
        latitude, longitude, time_zone = loc_from_options(hass, options)
        return {
            CONF_LOCATION: location,
            CONF_LATITUDE: latitude,
            CONF_LONGITUDE: longitude,
            CONF_TIME_ZONE: time_zone,
            CONF_OBS_ELV: obs_elv_from_options(hass, options),
        }

    @callback
    def update_location(call: ServiceCall) -> None:
        """Update location parameters."""
        loc_config = dict(call.data)
        location = loc_config.pop(CONF_LOCATION)
        entry, options = _entry_by_title(hass, location)
        if entry.source != SOURCE_USER:
            raise ValueError(f"Imported integration entries not supported: {location}")
        if CONF_LATITUDE in loc_config and CONF_LATITUDE not in options:
            raise ValueError("Changing location of Home configuration not supported")
        if CONF_OBS_ELV in loc_config:
            options_from_obs_elv(hass, loc_config)
        options.update(loc_config)
        hass.config_entries.async_update_entry(entry, options=options)

    s2data = sun2_data(hass)

    async def handle_core_config_update(event: Event) -> None:
        """Handle core config update."""
        if not event.data:
            return

        new_ha_loc_data = get_loc_data(hass.config)
        if ha_loc_data_changed := new_ha_loc_data != s2data.ha_loc_data:
            s2data.ha_loc_data = new_ha_loc_data

        if not any(key in event.data for key in ("location_name", "language")):
            if ha_loc_data_changed:
                async_dispatcher_send(hass, SIG_HA_LOC_UPDATED)
            return

        await reload_config()
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.source == SOURCE_IMPORT:
                continue
            if CONF_LATITUDE not in entry.options:
                reload = not hass.config_entries.async_update_entry(
                    entry, title=hass.config.location_name
                )
            else:
                reload = True
            if reload and entry.state.recoverable:
                await hass.config_entries.async_reload(entry.entry_id)

    await _process_config(hass, config, run_immediately=False)

    async_register_admin_service(hass, DOMAIN, SERVICE_RELOAD, reload_config)
    hass.services.async_register(
        DOMAIN,
        "get_location",
        get_location,
        _GET_LOCATION_SERVICE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "update_location",
        update_location,
        _UPDATE_LOCATION_SERVICE_SCHEMA,
        supports_response=SupportsResponse.NONE,
    )
    hass.bus.async_listen(EVENT_CORE_CONFIG_UPDATE, handle_core_config_update)

    return True


async def entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry update."""
    # Remove entity registry entries for additional sensors that were deleted.
    unqiue_ids = [
        sensor[CONF_UNIQUE_ID]
        for sensor_type in (CONF_BINARY_SENSORS, CONF_SENSORS)
        for sensor in entry.options.get(sensor_type, [])
    ]
    ent_reg = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        unique_id = entity.unique_id
        # Only sensors that were added via the UI have UUID type unique IDs.
        if _UUID_UNIQUE_ID.fullmatch(unique_id) and unique_id not in unqiue_ids:
            ent_reg.async_remove(entity.entity_id)

    config_data = sun2_data(hass).config_data[entry.entry_id]
    if (
        entry.title == config_data.title
        and entry.options.get(CONF_BINARY_SENSORS, []) == config_data.binary_sensors
        and entry.options.get(CONF_SENSORS, []) == config_data.sensors
    ):
        loc_data = get_loc_data(entry.options)
        obs_elvs = ObsElvs.from_entry_options(entry.options)
        if loc_data != config_data.loc_data or obs_elvs != config_data.obs_elvs:
            config_data.loc_data = loc_data
            config_data.obs_elvs = obs_elvs
            async_dispatcher_send(
                hass, SIG_ASTRAL_DATA_UPDATED.format(entry.entry_id), loc_data, obs_elvs
            )
        return

    if entry.state.recoverable:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up config entry."""
    sun2_data(hass).config_data[entry.entry_id] = ConfigData(
        entry.title,
        entry.options.get(CONF_BINARY_SENSORS, [])[:],
        entry.options.get(CONF_SENSORS, [])[:],
        get_loc_data(entry.options),
        ObsElvs.from_entry_options(entry.options),
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(entry_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    result = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    del sun2_data(hass).config_data[entry.entry_id]
    return result
