"""Sun2 integration."""
from __future__ import annotations

from typing import cast

from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.const import EVENT_CORE_CONFIG_UPDATE, Platform, SERVICE_RELOAD
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.helpers.dispatcher import dispatcher_send
from homeassistant.helpers.reload import async_integration_yaml_config
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, SIG_HA_LOC_UPDATED
from .helpers import LocData, LocParams, Sun2Data


PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Setup composite integration."""

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

    update_local_loc_data()

    def process_config(config: ConfigType) -> None:
        """Process sun2 config."""
        for conf in config.get(DOMAIN, []):
            hass.async_create_task(
                hass.config_entries.flow.async_init(
                    DOMAIN, context={"source": SOURCE_IMPORT}, data=conf.copy()
                )
            )

    process_config(config)

    async def reload_config(call: ServiceCall | None = None) -> None:
        """Reload configuration."""
        process_config(await async_integration_yaml_config(hass, DOMAIN))

    async def handle_core_config_update(event: Event) -> None:
        """Handle core config update."""
        if not event.data:
            return

        loc_data = update_local_loc_data()
        if not any(key in event.data for key in ["location_name", "language"]):
            # Signal all instances that location data has changed.
            dispatcher_send(hass, SIG_HA_LOC_UPDATED, loc_data)
            return

        await reload_config()

    async_register_admin_service(hass, DOMAIN, SERVICE_RELOAD, reload_config)
    hass.bus.async_listen(EVENT_CORE_CONFIG_UPDATE, handle_core_config_update)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
