"""Config flow for Sun2 integration."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import suppress
from typing import Any, cast

from astral import SunDirection
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlowWithConfigEntry,
    SOURCE_IMPORT,
)
from homeassistant.const import (
    CONF_BINARY_SENSORS,
    CONF_ELEVATION,
    CONF_ICON,
    CONF_LATITUDE,
    CONF_LOCATION,
    CONF_LONGITUDE,
    CONF_NAME,
    CONF_SENSORS,
    CONF_TIME_ZONE,
    CONF_UNIQUE_ID,
)
from homeassistant.core import callback, HomeAssistant
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    IconSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TimeSelector,
)
from homeassistant.util.uuid import random_uuid_hex

from .config import (
    val_bs_elevation,
    val_elevation,
    val_elevation_at_time,
    val_time_at_elevation,
)
from .const import (
    CONF_DIRECTION,
    CONF_ELEVATION_AT_TIME,
    CONF_TIME_AT_ELEVATION,
    DOMAIN,
)
from .helpers import init_translations

_LOCATION_OPTIONS = [CONF_ELEVATION, CONF_LATITUDE, CONF_LONGITUDE, CONF_TIME_ZONE]


class Sun2Flow(ABC):
    """Sun2 flow mixin."""

    _existing_entries: list[ConfigEntry] | None = None

    @property
    def _entries(self) -> list[ConfigEntry]:
        """Get existing config entries."""
        if self._existing_entries is None:
            self._existing_entries = self.hass.config_entries.async_entries(DOMAIN)
        return self._existing_entries

    def _any_using_ha_loc(self) -> bool:
        """Determine if a config is using Home Assistant location."""
        return any(CONF_LATITUDE not in entry.options for entry in self._entries)

    async def async_step_location(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle location options."""
        if user_input is not None:
            user_input[CONF_TIME_ZONE] = cv.time_zone(user_input[CONF_TIME_ZONE])
            self.options.update(user_input)
            return await self.async_step_entities_menu()

        schema = {
            vol.Required(
                CONF_LATITUDE, default=self.options.get(CONF_LATITUDE, vol.UNDEFINED)
            ): cv.latitude,
            vol.Required(
                CONF_LONGITUDE,
                default=self.options.get(CONF_LONGITUDE, vol.UNDEFINED),
            ): cv.longitude,
            vol.Required(
                CONF_ELEVATION,
                default=self.options.get(CONF_ELEVATION, vol.UNDEFINED),
            ): val_elevation,
            vol.Required(
                CONF_TIME_ZONE,
                default=self.options.get(CONF_TIME_ZONE, vol.UNDEFINED),
            ): cv.string,
        }
        return self.async_show_form(
            step_id="location", data_schema=vol.Schema(schema), last_step=False
        )

    async def async_step_entities_menu(
        self, _: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle entity options."""
        await init_translations(self.hass)
        menu_options = [
            "elevation_binary_sensor",
            "elevation_at_time_sensor_menu",
            "time_at_elevation_sensor",
            "done",
        ]
        return self.async_show_menu(step_id="entities_menu", menu_options=menu_options)

    async def async_step_elevation_binary_sensor(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle elevation binary sensor options."""
        if user_input is not None:
            if user_input["use_horizon"]:
                return await self.async_finish_sensor(
                    {CONF_ELEVATION: "horizon"}, val_bs_elevation, CONF_BINARY_SENSORS
                )
            return await self.async_step_elevation_binary_sensor_2()

        return self.async_show_form(
            step_id="elevation_binary_sensor",
            data_schema=vol.Schema({vol.Required("use_horizon", default=False): bool}),
            last_step=False,
        )

    async def async_step_elevation_binary_sensor_2(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle additional elevation binary sensor options."""
        if user_input is not None:
            return await self.async_finish_sensor(
                user_input, val_bs_elevation, CONF_BINARY_SENSORS
            )

        schema = {
            vol.Required(CONF_ELEVATION, default=0.0): NumberSelector(
                NumberSelectorConfig(
                    min=-90, max=90, step="any", mode=NumberSelectorMode.BOX
                )
            ),
            vol.Optional(CONF_NAME): TextSelector(),
        }
        return self.async_show_form(
            step_id="elevation_binary_sensor_2",
            data_schema=vol.Schema(schema),
            last_step=False,
        )

    async def async_step_elevation_at_time_sensor_menu(
        self, _: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask elevation_at_time type."""
        menu_options = [
            "elevation_at_time_sensor_entity",
            "elevation_at_time_sensor_time",
        ]
        return self.async_show_menu(
            step_id="elevation_at_time_sensor_menu", menu_options=menu_options
        )

    async def async_step_elevation_at_time_sensor_entity(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle elevation_at_time sensor options w/ input_datetime entity."""
        if user_input is not None:
            return await self.async_finish_sensor(
                user_input, val_elevation_at_time, CONF_SENSORS
            )

        schema = {
            vol.Required(CONF_ELEVATION_AT_TIME): EntitySelector(
                EntitySelectorConfig(domain="input_datetime")
            ),
            vol.Optional(CONF_NAME): TextSelector(),
        }
        return self.async_show_form(
            step_id="elevation_at_time_sensor_entity",
            data_schema=vol.Schema(schema),
            last_step=False,
        )

    async def async_step_elevation_at_time_sensor_time(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle elevation_at_time sensor options w/ time string."""
        if user_input is not None:
            return await self.async_finish_sensor(
                user_input, val_elevation_at_time, CONF_SENSORS
            )

        schema = {
            vol.Required(CONF_ELEVATION_AT_TIME): TimeSelector(),
            vol.Optional(CONF_NAME): TextSelector(),
        }
        return self.async_show_form(
            step_id="elevation_at_time_sensor_time",
            data_schema=vol.Schema(schema),
            last_step=False,
        )

    async def async_step_time_at_elevation_sensor(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle time_at_elevation sensor options."""
        if user_input is not None:
            user_input[CONF_DIRECTION] = vol.All(vol.Upper, cv.enum(SunDirection))(
                user_input[CONF_DIRECTION]
            )
            return await self.async_finish_sensor(
                user_input, val_time_at_elevation, CONF_SENSORS
            )

        schema = {
            vol.Required(CONF_TIME_AT_ELEVATION, default=0.0): NumberSelector(
                NumberSelectorConfig(
                    min=-90, max=90, step="any", mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(CONF_DIRECTION): SelectSelector(
                SelectSelectorConfig(
                    options=["rising", "setting"], translation_key="direction"
                )
            ),
            vol.Optional(CONF_ICON): IconSelector(),
            vol.Optional(CONF_NAME): TextSelector(),
        }
        return self.async_show_form(
            step_id="time_at_elevation_sensor",
            data_schema=vol.Schema(schema),
            last_step=False,
        )

    async def async_finish_sensor(
        self,
        config: dict[str, Any],
        validator: Callable[[HomeAssistant], Callable[[dict], dict]],
        sensor_type: str,
    ) -> FlowResult:
        """Finish elevation binary sensor."""
        sensor_option = validator(self.hass)(config)
        sensor_option[CONF_UNIQUE_ID] = random_uuid_hex()
        self.options.setdefault(sensor_type, []).append(sensor_option)
        return await self.async_step_entities_menu()

    @abstractmethod
    async def async_step_done(self, _: dict[str, Any] | None = None) -> FlowResult:
        """Finish the flow."""


class Sun2ConfigFlow(ConfigFlow, Sun2Flow, domain=DOMAIN):
    """Sun2 config flow."""

    VERSION = 1

    _location_name: str | vol.UNDEFINED = vol.UNDEFINED

    def __init__(self) -> None:
        """Initialize config flow."""
        self.options = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> Sun2OptionsFlow:
        """Get the options flow for this handler."""
        flow = Sun2OptionsFlow(config_entry)
        flow.init_step = (
            "location" if CONF_LATITUDE in config_entry.options else "entities_menu"
        )
        return flow

    @classmethod
    @callback
    def async_supports_options_flow(cls, config_entry: ConfigEntry) -> bool:
        """Return options flow support for this handler."""
        if config_entry.source == SOURCE_IMPORT:
            return False
        return True

    async def async_step_import(self, data: dict[str, Any]) -> FlowResult:
        """Import config entry from configuration."""
        self._location_name = cast(
            str, data.pop(CONF_LOCATION, self.hass.config.location_name)
        )
        if existing_entry := await self.async_set_unique_id(data.pop(CONF_UNIQUE_ID)):
            if not self.hass.config_entries.async_update_entry(
                existing_entry, title=self._location_name, options=data
            ):
                self.hass.async_create_task(
                    self.hass.config_entries.async_reload(existing_entry.entry_id)
                )
            return self.async_abort(reason="already_configured")

        self.options.clear()
        self.options.update(data)
        return await self.async_step_done()

    async def async_step_user(self, _: dict[str, Any] | None = None) -> FlowResult:
        """Start user config flow."""
        if not self._any_using_ha_loc():
            return await self.async_step_use_home()
        return await self.async_step_location_name()

    async def async_step_use_home(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask user if entry should use Home Assistant's name & location."""
        if user_input is not None:
            if user_input["use_home"]:
                self._location_name = self.hass.config.location_name
                for option in _LOCATION_OPTIONS:
                    with suppress(KeyError):
                        del self.options[option]
                return await self.async_step_entities_menu()
            return await self.async_step_location_name()

        schema = {vol.Required("use_home", default=True): bool}
        return self.async_show_form(
            step_id="use_home", data_schema=vol.Schema(schema), last_step=False
        )

    async def async_step_location_name(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Get location name."""
        errors = {}

        if user_input is not None:
            self._location_name = user_input[CONF_NAME]
            if not any(entry.title == self._location_name for entry in self._entries):
                return await self.async_step_location()
            errors[CONF_NAME] = "name_used"

        schema = {vol.Required(CONF_NAME, default=self._location_name): TextSelector()}
        return self.async_show_form(
            step_id="location_name",
            data_schema=vol.Schema(schema),
            errors=errors,
            last_step=False,
        )

    async def async_step_done(self, _: dict[str, Any] | None = None) -> FlowResult:
        """Finish the flow."""
        return self.async_create_entry(
            title=self._location_name, data={}, options=self.options
        )


class Sun2OptionsFlow(OptionsFlowWithConfigEntry, Sun2Flow):
    """Sun2 integration options flow."""

    async def async_step_done(self, _: dict[str, Any] | None = None) -> FlowResult:
        """Finish the flow."""
        return self.async_create_entry(title="", data=self.options or {})
