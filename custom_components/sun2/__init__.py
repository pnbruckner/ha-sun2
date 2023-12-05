"""Sun2 integration."""
from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, cast

from astral import SunDirection

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import (
    CONF_LATITUDE,
    CONF_SENSORS,
    CONF_UNIQUE_ID,
    EVENT_CORE_CONFIG_UPDATE,
    SERVICE_RELOAD,
    Platform,
)
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.helpers.dispatcher import dispatcher_send
from homeassistant.helpers.reload import async_integration_yaml_config
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType

from .const import CONF_DIRECTION, CONF_TIME_AT_ELEVATION, DOMAIN, SIG_HA_LOC_UPDATED
from .helpers import LocData, LocParams, Sun2Data

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]


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
            if reload:
                await hass.config_entries.async_reload(entry.entry_id)

    update_local_loc_data()
    await process_config(config, run_immediately=False)
    async_register_admin_service(hass, DOMAIN, SERVICE_RELOAD, reload_config)
    hass.bus.async_listen(EVENT_CORE_CONFIG_UPDATE, handle_core_config_update)

    return True


async def entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up config entry."""
    # From 3.0.0b8 or older: Convert config direction from -1, 1 -> "setting", "rising"
    options = dict(entry.options)
    for sensor in options.get(CONF_SENSORS, []):
        if CONF_TIME_AT_ELEVATION not in sensor:
            continue
        if isinstance(direction := sensor[CONF_DIRECTION], str):
            continue
        sensor[CONF_DIRECTION] = SunDirection(direction).name.lower()
    if options != entry.options:
        hass.config_entries.async_update_entry(entry, options=options)

    entry.async_on_unload(entry.add_update_listener(entry_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
