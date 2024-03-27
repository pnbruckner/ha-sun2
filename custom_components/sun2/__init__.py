"""Sun2 integration."""
from __future__ import annotations

import asyncio
from collections.abc import Coroutine
import re
from typing import Any, cast

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import (
    CONF_BINARY_SENSORS,
    CONF_LATITUDE,
    CONF_SENSORS,
    CONF_UNIQUE_ID,
    EVENT_CORE_CONFIG_UPDATE,
    SERVICE_RELOAD,
    Platform,
)
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import dispatcher_send
from homeassistant.helpers.reload import async_integration_yaml_config
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, SIG_HA_LOC_UPDATED
from .helpers import LocData, LocParams, Sun2Data

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]
_OLD_UNIQUE_ID = re.compile(r"[0-9a-f]{32}-([0-9a-f]{32})")
_UUID_UNIQUE_ID = re.compile(r"[0-9a-f]{32}")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up composite integration."""

    def update_local_loc_data() -> LocData:
        """Update local location data from HA's config."""
        cast(Sun2Data, hass.data[DOMAIN]).locations[None] = loc_data = LocData(
            LocParams(
                hass.config.elevation,
                hass.config.latitude,
                hass.config.longitude,
                str(hass.config.time_zone),
            )
        )
        return loc_data

    async def process_config(
        config: ConfigType | None, run_immediately: bool = True
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
            tasks.append(
                hass.config_entries.flow.async_init(
                    DOMAIN, context={"source": SOURCE_IMPORT}, data=conf.copy()
                )
            )

        if not tasks:
            return

        if run_immediately:
            await asyncio.gather(*tasks)
        else:
            for task in tasks:
                hass.async_create_task(task)

    async def reload_config(call: ServiceCall | None = None) -> None:
        """Reload configuration."""
        await process_config(await async_integration_yaml_config(hass, DOMAIN))

    async def handle_core_config_update(event: Event) -> None:
        """Handle core config update."""
        if not event.data:
            return

        loc_data = update_local_loc_data()

        if not any(key in event.data for key in ("location_name", "language")):
            # Signal all instances that location data has changed.
            dispatcher_send(hass, SIG_HA_LOC_UPDATED, loc_data)
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

    update_local_loc_data()
    await process_config(config, run_immediately=False)
    async_register_admin_service(hass, DOMAIN, SERVICE_RELOAD, reload_config)
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
    if entry.state.recoverable:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up config entry."""
    entry.async_on_unload(entry.add_update_listener(entry_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
