"""Config flow for Sun2 integration."""
from __future__ import annotations

from abc import abstractmethod
from collections.abc import Mapping
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
    DEGREE,
    UnitOfLength,
)
from homeassistant.core import HomeAssistant, callback
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
    CONF_ABOVE_GROUND,
    CONF_DIRECTION,
    CONF_ELEVATION_AT_TIME,
    CONF_OBS_ELV,
    CONF_SUNRISE_OBSTRUCTION,
    CONF_SUNSET_OBSTRUCTION,
    CONF_TIME_AT_ELEVATION,
    DOMAIN,
)
from .helpers import Num, init_translations

_LOCATION_OPTIONS = [CONF_LATITUDE, CONF_LONGITUDE, CONF_TIME_ZONE]

_DEGREES_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=-90,
        max=90,
        step="any",
        unit_of_measurement=DEGREE,
        mode=NumberSelectorMode.BOX,
    )
)
_INPUT_DATETIME_SELECTOR = EntitySelector(EntitySelectorConfig(domain="input_datetime"))
_METERS_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        step="any",
        unit_of_measurement=UnitOfLength.METERS,
        mode=NumberSelectorMode.BOX,
    )
)
_POSITIVE_METERS_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=0,
        step="any",
        unit_of_measurement=UnitOfLength.METERS,
        mode=NumberSelectorMode.BOX,
    )
)
_SUN_DIRECTION_SELECTOR = SelectSelector(
    SelectSelectorConfig(options=SUN_DIRECTIONS, translation_key="direction")
)


def loc_from_options(
    hass: HomeAssistant, options: Mapping[str, Any]
) -> tuple[float, float, str]:
    """Return latitude, longitude & time_zone from options."""
    if CONF_LATITUDE in options:
        return options[CONF_LATITUDE], options[CONF_LONGITUDE], options[CONF_TIME_ZONE]
    return hass.config.latitude, hass.config.longitude, hass.config.time_zone


class Sun2Flow(FlowHandler):
    """Sun2 flow mixin."""

    _existing_entries: list[ConfigEntry] | None = None
    _existing_entities: dict[str, str] | None = None

    # Temporary variables between steps.
    _use_map: bool
    _sunrise_obstruction: bool
    _sunset_obstruction: bool

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

    async def async_step_location_menu(
        self, _: dict[str, Any] | None = None
    ) -> FlowResult:
        """Provide options for how to enter location."""
        menu_options = ["location_map", "location_manual"]
        kwargs = {}
        if CONF_LATITUDE in self.options:
            menu_options.append("observer_elevation")
            location = f"{self.options[CONF_LATITUDE]}, {self.options[CONF_LONGITUDE]}"
            kwargs["description_placeholders"] = {
                "location": location,
                "time_zone": self.options[CONF_TIME_ZONE],
            }
        return self.async_show_menu(
            step_id="location_menu", menu_options=menu_options, **kwargs
        )

    async def async_step_location_map(
        self, _: dict[str, Any] | None = None
    ) -> FlowResult:
        """Enter location via a map."""
        self._use_map = True
        return await self.async_step_location()

    async def async_step_location_manual(
        self, _: dict[str, Any] | None = None
    ) -> FlowResult:
        """Enter location manually."""
        self._use_map = False
        return await self.async_step_location()

    async def async_step_location(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle location options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input[CONF_TIME_ZONE] = cv.time_zone(user_input[CONF_TIME_ZONE])
            location: dict[str, Any] | str = user_input.pop(CONF_LOCATION)
            if isinstance(location, dict):
                user_input[CONF_LATITUDE] = location[CONF_LATITUDE]
                user_input[CONF_LONGITUDE] = location[CONF_LONGITUDE]
            else:
                try:
                    lat = lon = ""
                    with suppress(ValueError):
                        lat, lon = location.split(",")
                        lat = lat.strip()
                        lon = lon.strip()
                    if not lat or not lon:
                        lat, lon = location.split()
                        lat = lat.strip()
                        lon = lon.strip()
                    user_input[CONF_LATITUDE] = float(lat)
                    user_input[CONF_LONGITUDE] = float(lon)
                except ValueError:
                    errors[CONF_LOCATION] = "invalid_location"
            if not errors:
                self.options.update(user_input)
                return await self.async_step_observer_elevation()

        location_selector = LocationSelector if self._use_map else TextSelector
        data_schema = vol.Schema(
            {
                vol.Required(CONF_LOCATION): location_selector(),
                vol.Required(CONF_TIME_ZONE): TextSelector(),
            }
        )

        latitude, longitude, time_zone = loc_from_options(self.hass, self.options)
        suggested_values: dict[str, Any] = {CONF_TIME_ZONE: time_zone}
        if self._use_map:
            suggested_values[CONF_LOCATION] = {
                CONF_LATITUDE: latitude,
                CONF_LONGITUDE: longitude,
            }
        else:
            suggested_values[CONF_LOCATION] = f"{latitude}, {longitude}"
        data_schema = self.add_suggested_values_to_schema(data_schema, suggested_values)

        return self.async_show_form(
            step_id="location", data_schema=data_schema, errors=errors, last_step=False
        )

    async def async_step_observer_elevation(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle observer elevation options."""
        if user_input is not None:
            self._sunrise_obstruction = user_input[CONF_SUNRISE_OBSTRUCTION]
            self._sunset_obstruction = user_input[CONF_SUNSET_OBSTRUCTION]
            return await self.async_step_obs_elv_values()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_SUNRISE_OBSTRUCTION): BooleanSelector(),
                vol.Required(CONF_SUNSET_OBSTRUCTION): BooleanSelector(),
            }
        )

        if obs_elv := self.options.get(CONF_OBS_ELV):
            suggested_values = {
                CONF_SUNRISE_OBSTRUCTION: not isinstance(obs_elv[0], Num),  # type: ignore[misc, arg-type]
                CONF_SUNSET_OBSTRUCTION: not isinstance(obs_elv[1], Num),  # type: ignore[misc, arg-type]
            }
        else:
            suggested_values = {
                CONF_SUNRISE_OBSTRUCTION: False,
                CONF_SUNSET_OBSTRUCTION: False,
            }
        data_schema = self.add_suggested_values_to_schema(data_schema, suggested_values)

        return self.async_show_form(
            step_id="observer_elevation", data_schema=data_schema, last_step=False
        )

    async def async_step_obs_elv_values(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle observer elevation option values."""
        get_above_ground = not self._sunrise_obstruction or not self._sunset_obstruction

        if user_input is not None:
            above_ground = user_input.get(CONF_ABOVE_GROUND, 0)
            if self._sunrise_obstruction:
                sunrise_obs_elv = [
                    user_input["sunrise_relative_height"],
                    user_input["sunrise_distance"],
                ]
            else:
                sunrise_obs_elv = above_ground
            if self._sunset_obstruction:
                sunset_obs_elv = [
                    user_input["sunset_relative_height"],
                    user_input["sunset_distance"],
                ]
            else:
                sunset_obs_elv = above_ground
            self.options[CONF_OBS_ELV] = [sunrise_obs_elv, sunset_obs_elv]
            # For backwards compatibility, add elevation to options if necessary.
            if CONF_ELEVATION not in self.options:
                self.options[CONF_ELEVATION] = above_ground
            return await self.async_step_entities_menu()

        schema: dict[str, Any] = {}
        if get_above_ground:
            schema[vol.Required(CONF_ABOVE_GROUND)] = _POSITIVE_METERS_SELECTOR
        if self._sunrise_obstruction:
            schema[vol.Required("sunrise_distance")] = _POSITIVE_METERS_SELECTOR
            schema[vol.Required("sunrise_relative_height")] = _METERS_SELECTOR
        if self._sunset_obstruction:
            schema[vol.Required("sunset_distance")] = _POSITIVE_METERS_SELECTOR
            schema[vol.Required("sunset_relative_height")] = _METERS_SELECTOR
        data_schema = vol.Schema(schema)

        above_ground = 0
        sunrise_distance = sunset_distance = 1000
        sunrise_relative_height = sunset_relative_height = 1000
        if obs_elv := self.options.get(CONF_OBS_ELV):
            if isinstance(obs_elv[0], Num):  # type: ignore[misc, arg-type]
                above_ground = obs_elv[0]
            else:
                sunrise_relative_height, sunrise_distance = obs_elv[0]
            if isinstance(obs_elv[1], Num):  # type: ignore[misc, arg-type]
                # If both directions use above_ground, they should be the same.
                # Assume this is true and don't bother checking here.
                above_ground = obs_elv[1]
            else:
                sunset_relative_height, sunset_distance = obs_elv[1]
        suggested_values: dict[str, Any] = {}
        if get_above_ground:
            suggested_values[CONF_ABOVE_GROUND] = above_ground
        if self._sunrise_obstruction:
            suggested_values["sunrise_distance"] = sunrise_distance
            suggested_values["sunrise_relative_height"] = sunrise_relative_height
        if self._sunset_obstruction:
            suggested_values["sunset_distance"] = sunset_distance
            suggested_values["sunset_relative_height"] = sunset_relative_height
        data_schema = self.add_suggested_values_to_schema(data_schema, suggested_values)

        return self.async_show_form(
            step_id="obs_elv_values", data_schema=data_schema, last_step=False
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
                vol.Required(CONF_ELEVATION): _DEGREES_SELECTOR,
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
                vol.Required(CONF_ELEVATION_AT_TIME): _INPUT_DATETIME_SELECTOR,
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
                vol.Required(CONF_TIME_AT_ELEVATION): _DEGREES_SELECTOR,
                vol.Required(CONF_DIRECTION): _SUN_DIRECTION_SELECTOR,
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
            raise RuntimeError(f"Unexpected unique ID ({unique_id}) to remove")

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
            "location_menu"
            if CONF_LATITUDE in config_entry.options
            else "entities_menu"
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

        async def reload(entry: ConfigEntry) -> None:
            """Reload config entry."""
            if not entry.state.recoverable:
                return
            await self.hass.config_entries.async_reload(entry.entry_id)

        title = cast(str, data.pop(CONF_LOCATION, self.hass.config.location_name))
        if existing_entry := await self.async_set_unique_id(data.pop(CONF_UNIQUE_ID)):
            if not self.hass.config_entries.async_update_entry(
                existing_entry, title=title, options=data
            ):
                self.hass.async_create_task(reload(existing_entry))
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
                return await self.async_step_location_menu()
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
