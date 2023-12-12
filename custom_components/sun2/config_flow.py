"""Config flow for Sun2 integration."""
from __future__ import annotations

from abc import abstractmethod
from contextlib import suppress
from typing import Any, cast

import voluptuous as vol

from homeassistant.components.binary_sensor import DOMAIN as BS_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.config_entries import (
    SOURCE_IMPORT,
    ConfigEntry,
    ConfigFlow,
    OptionsFlowWithConfigEntry,
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
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowHandler, FlowResult
from homeassistant.helpers import entity_registry as er
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    IconSelector,
    LocationSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TimeSelector,
)
from homeassistant.util.uuid import random_uuid_hex

from .config import SUN_DIRECTIONS
from .const import (
    CONF_DIRECTION,
    CONF_ELEVATION_AT_TIME,
    CONF_TIME_AT_ELEVATION,
    DOMAIN,
)
from .helpers import init_translations

_LOCATION_OPTIONS = [CONF_ELEVATION, CONF_LATITUDE, CONF_LONGITUDE, CONF_TIME_ZONE]


class Sun2Flow(FlowHandler):
    """Sun2 flow mixin."""

    _existing_entries: list[ConfigEntry] | None = None
    _existing_entities: dict[str, str] | None = None

    @property
    def _entries(self) -> list[ConfigEntry]:
        """Get existing config entries."""
        if self._existing_entries is None:
            self._existing_entries = self.hass.config_entries.async_entries(DOMAIN)
        return self._existing_entries

    @property
    def _entities(self) -> dict[str, str]:
        """Get existing configured entities."""
        if self._existing_entities is not None:
            return self._existing_entities

        ent_reg = er.async_get(self.hass)
        existing_entities: dict[str, str] = {}
        for key, domain in {
            CONF_BINARY_SENSORS: BS_DOMAIN,
            CONF_SENSORS: SENSOR_DOMAIN,
        }.items():
            for sensor in self.options.get(key, []):
                unique_id = cast(str, sensor[CONF_UNIQUE_ID])
                entity_id = cast(
                    str, ent_reg.async_get_entity_id(domain, DOMAIN, unique_id)
                )
                existing_entities[entity_id] = unique_id
        self._existing_entities = existing_entities
        return existing_entities

    @property
    @abstractmethod
    def options(self) -> dict[str, Any]:
        """Return mutable copy of options."""

    def _any_using_ha_loc(self) -> bool:
        """Determine if a config is using Home Assistant location."""
        return any(CONF_LATITUDE not in entry.options for entry in self._entries)

    async def async_step_location(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle location options."""
        if user_input is not None:
            user_input[CONF_TIME_ZONE] = cv.time_zone(user_input[CONF_TIME_ZONE])
            location: dict[str, Any] = user_input.pop(CONF_LOCATION)
            user_input[CONF_LATITUDE] = location[CONF_LATITUDE]
            user_input[CONF_LONGITUDE] = location[CONF_LONGITUDE]
            self.options.update(user_input)
            return await self.async_step_entities_menu()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_LOCATION): LocationSelector(),
                vol.Required(CONF_ELEVATION): NumberSelector(
                    NumberSelectorConfig(step="any", mode=NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_TIME_ZONE): TextSelector(),
            }
        )
        if CONF_LATITUDE in self.options:
            suggested_values = {
                CONF_LOCATION: {
                    CONF_LATITUDE: self.options[CONF_LATITUDE],
                    CONF_LONGITUDE: self.options[CONF_LONGITUDE],
                },
                CONF_ELEVATION: self.options[CONF_ELEVATION],
                CONF_TIME_ZONE: self.options[CONF_TIME_ZONE],
            }
        else:
            suggested_values = {
                CONF_LOCATION: {
                    CONF_LATITUDE: self.hass.config.latitude,
                    CONF_LONGITUDE: self.hass.config.longitude,
                },
                CONF_ELEVATION: self.hass.config.elevation,
                CONF_TIME_ZONE: self.hass.config.time_zone,
            }
        data_schema = self.add_suggested_values_to_schema(data_schema, suggested_values)
        return self.async_show_form(
            step_id="location", data_schema=data_schema, last_step=False
        )

    async def async_step_entities_menu(
        self, _: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle entity options."""
        await init_translations(self.hass)
        menu_options = ["add_entities_menu"]
        if self.options.get(CONF_BINARY_SENSORS) or self.options.get(CONF_SENSORS):
            menu_options.append("remove_entities")
        menu_options.append("done")
        return self.async_show_menu(step_id="entities_menu", menu_options=menu_options)

    async def async_step_add_entities_menu(
        self, _: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add entities."""
        menu_options = [
            "elevation_binary_sensor",
            "elevation_at_time_sensor_menu",
            "time_at_elevation_sensor",
            "done",
        ]
        return self.async_show_menu(
            step_id="add_entities_menu", menu_options=menu_options
        )

    async def async_step_elevation_binary_sensor(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle elevation binary sensor options."""
        if user_input is not None:
            if user_input["use_horizon"]:
                return await self.async_finish_sensor(
                    {CONF_ELEVATION: "horizon"}, CONF_BINARY_SENSORS
                )
            return await self.async_step_elevation_binary_sensor_2()

        return self.async_show_form(
            step_id="elevation_binary_sensor",
            data_schema=vol.Schema({vol.Required("use_horizon"): BooleanSelector()}),
            last_step=False,
        )

    async def async_step_elevation_binary_sensor_2(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle additional elevation binary sensor options."""
        if user_input is not None:
            return await self.async_finish_sensor(user_input, CONF_BINARY_SENSORS)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ELEVATION): NumberSelector(
                    NumberSelectorConfig(
                        min=-90, max=90, step="any", mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(CONF_NAME): TextSelector(),
            }
        )
        data_schema = self.add_suggested_values_to_schema(
            data_schema, {CONF_ELEVATION: 0.0}
        )
        return self.async_show_form(
            step_id="elevation_binary_sensor_2",
            data_schema=data_schema,
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
            return await self.async_finish_sensor(user_input, CONF_SENSORS)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ELEVATION_AT_TIME): EntitySelector(
                    EntitySelectorConfig(domain="input_datetime")
                ),
                vol.Optional(CONF_NAME): TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="elevation_at_time_sensor_entity",
            data_schema=data_schema,
            last_step=False,
        )

    async def async_step_elevation_at_time_sensor_time(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle elevation_at_time sensor options w/ time string."""
        if user_input is not None:
            return await self.async_finish_sensor(user_input, CONF_SENSORS)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ELEVATION_AT_TIME): TimeSelector(),
                vol.Optional(CONF_NAME): TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="elevation_at_time_sensor_time",
            data_schema=data_schema,
            last_step=False,
        )

    async def async_step_time_at_elevation_sensor(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle time_at_elevation sensor options."""
        if user_input is not None:
            return await self.async_finish_sensor(user_input, CONF_SENSORS)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_TIME_AT_ELEVATION): NumberSelector(
                    NumberSelectorConfig(
                        min=-90, max=90, step="any", mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(CONF_DIRECTION): SelectSelector(
                    SelectSelectorConfig(
                        options=SUN_DIRECTIONS, translation_key="direction"
                    )
                ),
                vol.Optional(CONF_ICON): IconSelector(),
                vol.Optional(CONF_NAME): TextSelector(),
            }
        )
        data_schema = self.add_suggested_values_to_schema(
            data_schema, {CONF_TIME_AT_ELEVATION: 0.0}
        )
        return self.async_show_form(
            step_id="time_at_elevation_sensor",
            data_schema=data_schema,
            last_step=False,
        )

    async def async_finish_sensor(
        self,
        config: dict[str, Any],
        sensor_type: str,
    ) -> FlowResult:
        """Finish elevation binary sensor."""
        config[CONF_UNIQUE_ID] = random_uuid_hex()
        self.options.setdefault(sensor_type, []).append(config)
        return await self.async_step_add_entities_menu()

    async def async_step_remove_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Remove entities added previously."""

        def delete_entity(unique_id: str) -> None:
            """Remove entity with given unique ID."""
            for sensor_type in (CONF_BINARY_SENSORS, CONF_SENSORS):
                for idx, sensor in enumerate(self.options.get(sensor_type, [])):
                    if sensor[CONF_UNIQUE_ID] == unique_id:
                        del self.options[sensor_type][idx]
                        if not self.options[sensor_type]:
                            del self.options[sensor_type]
                        return
            assert False

        if user_input is not None:
            for entity_id in user_input["choices"]:
                delete_entity(self._entities[entity_id])
            return await self.async_step_done()

        entity_ids = list(self._entities)
        data_schema = vol.Schema(
            {
                vol.Required("choices"): EntitySelector(
                    EntitySelectorConfig(include_entities=entity_ids, multiple=True)
                )
            }
        )
        return self.async_show_form(
            step_id="remove_entities",
            data_schema=data_schema,
            last_step=False,
        )

    @abstractmethod
    async def async_step_done(self, _: dict[str, Any] | None = None) -> FlowResult:
        """Finish the flow."""


class Sun2ConfigFlow(ConfigFlow, Sun2Flow, domain=DOMAIN):
    """Sun2 config flow."""

    VERSION = 1

    _location_name: str | None = None

    def __init__(self) -> None:
        """Initialize config flow."""
        self._options: dict[str, Any] = {}

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

    @property
    def options(self) -> dict[str, Any]:
        """Return mutable copy of options."""
        return self._options

    async def async_step_import(self, data: dict[str, Any]) -> FlowResult:
        """Import config entry from configuration."""
        title = cast(str, data.pop(CONF_LOCATION, self.hass.config.location_name))
        if existing_entry := await self.async_set_unique_id(data.pop(CONF_UNIQUE_ID)):
            if not self.hass.config_entries.async_update_entry(
                existing_entry, title=title, options=data
            ):
                self.hass.async_create_task(
                    self.hass.config_entries.async_reload(existing_entry.entry_id)
                )
            return self.async_abort(reason="already_configured")

        return self.async_create_entry(title=title, data={}, options=data)

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

        return self.async_show_form(
            step_id="use_home",
            data_schema=vol.Schema({vol.Required("use_home"): BooleanSelector()}),
            last_step=False,
        )

    async def async_step_location_name(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Get location name."""
        errors = {}

        if user_input is not None:
            self._location_name = cast(str, user_input[CONF_NAME])
            if not any(entry.title == self._location_name for entry in self._entries):
                return await self.async_step_location()
            errors[CONF_NAME] = "name_used"

        data_schema = vol.Schema({vol.Required(CONF_NAME): TextSelector()})
        if self._location_name is not None:
            data_schema = self.add_suggested_values_to_schema(
                data_schema, {CONF_NAME: self._location_name}
            )
        return self.async_show_form(
            step_id="location_name",
            data_schema=data_schema,
            errors=errors,
            last_step=False,
        )

    async def async_step_done(self, _: dict[str, Any] | None = None) -> FlowResult:
        """Finish the flow."""
        return self.async_create_entry(
            title=cast(str, self._location_name), data={}, options=self.options
        )


class Sun2OptionsFlow(OptionsFlowWithConfigEntry, Sun2Flow):
    """Sun2 integration options flow."""

    async def async_step_done(self, _: dict[str, Any] | None = None) -> FlowResult:
        """Finish the flow."""
        return self.async_create_entry(title="", data=self.options or {})
