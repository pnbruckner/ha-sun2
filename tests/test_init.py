"""Test init module."""
from __future__ import annotations

from unittest.mock import patch
from pytest_homeassistant_custom_component.common import assert_setup_component

from homeassistant.const import EVENT_CORE_CONFIG_UPDATE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import EntityRegistry
from homeassistant.setup import async_setup_component
from homeassistant.util import slugify

from custom_components.sun2.const import DOMAIN

from .const import HOME_CONFIG, HW_CONFIG, HW_LOC, NY_CONFIG, NY_LOC, TWINE_CONFIG, TWINE_LOC


async def test_basic_yaml_config(
    hass: HomeAssistant, entity_registry: EntityRegistry
) -> None:
    """Test basic YAML configuration."""
    with assert_setup_component(1, DOMAIN):
        await async_setup_component(hass, DOMAIN, {DOMAIN: [HOME_CONFIG]})
    await hass.async_block_till_done()

    expected_entities = (
        (True, ("dawn", "dusk", "rising", "setting", "solar_midnight", "solar_noon")),
        (
            False,
            (
                "astronomical_dawn",
                "astronomical_daylight",
                "astronomical_dusk",
                "astronomical_night",
                "azimuth",
                "civil_daylight",
                "civil_night",
                "daylight",
                "deconz_daylight",
                "elevation",
                "maximum_elevation",
                "minimum_elevation",
                "nautical_dawn",
                "nautical_daylight",
                "nautical_dusk",
                "nautical_night",
                "night",
                "phase",
            ),
        ),
    )

    # Check that the expected number of entities were created.
    n_expected_entities = sum(len(x[1]) for x in expected_entities)
    n_actual_entities = len(
        [
            entry
            for entry in entity_registry.entities.values()
            if entry.platform == DOMAIN
        ]
    )
    assert n_actual_entities == n_expected_entities

    # Check that the created entities have the correct IDs and enabled status.
    location_name = hass.config.location_name
    for enabled, suffixes in expected_entities:
        for suffix in suffixes:
            entry = entity_registry.async_get(
                f"sensor.{slugify(location_name)}_sun_{suffix}"
            )
            assert entry
            assert entry.disabled != enabled


async def test_reload_service(hass: HomeAssistant) -> None:
    """Test basic YAML configuration."""
    init_config = [HOME_CONFIG, NY_CONFIG]
    with assert_setup_component(len(init_config), DOMAIN):
        await async_setup_component(hass, DOMAIN, {DOMAIN: init_config})
    await hass.async_block_till_done()

    # Check config entries match config.
    config_entries = hass.config_entries.async_entries(DOMAIN)
    assert len(config_entries) == 2
    config_entry_1 = config_entries[0]
    assert config_entry_1.unique_id == HOME_CONFIG["unique_id"]
    assert config_entry_1.title == hass.config.location_name
    assert config_entry_1.options == {}
    config_entry_2 = config_entries[1]
    assert config_entry_2.unique_id == NY_CONFIG["unique_id"]
    assert config_entry_2.title == NY_CONFIG["location"]
    assert config_entry_2.options == NY_LOC

    # Check reload service exists.
    assert hass.services.has_service(DOMAIN, "reload")

    # Reload new config.
    reload_config = [TWINE_CONFIG, HW_CONFIG]
    with patch(
        "custom_components.sun2.async_integration_yaml_config",
        autospec=True,
        return_value={DOMAIN: reload_config},
    ):
        await hass.services.async_call(DOMAIN, "reload")
        await hass.async_block_till_done()

    # Check config entries match config.
    config_entries = hass.config_entries.async_entries(DOMAIN)
    assert len(config_entries) == 2
    config_entry_1 = config_entries[0]
    assert config_entry_1.unique_id == TWINE_CONFIG["unique_id"]
    assert config_entry_1.title == TWINE_CONFIG["location"]
    assert config_entry_1.options == TWINE_LOC
    config_entry_2 = config_entries[1]
    assert config_entry_2.unique_id == HW_CONFIG["unique_id"]
    assert config_entry_2.title == HW_CONFIG["location"]
    assert config_entry_2.options == HW_LOC

    # Reload with same config.
    reload_config = [TWINE_CONFIG, HW_CONFIG]
    with patch(
        "custom_components.sun2.async_integration_yaml_config",
        autospec=True,
        return_value={DOMAIN: reload_config},
    ):
        await hass.services.async_call(DOMAIN, "reload")
        await hass.async_block_till_done()

    # Check config entries haven't changed.
    orig = [config_entry.as_dict() for config_entry in config_entries]
    config_entries == hass.config_entries.async_entries(DOMAIN)
    assert [config_entry.as_dict() for config_entry in config_entries] == orig

    # Reload config with config removed.
    with patch(
        "custom_components.sun2.async_integration_yaml_config",
        autospec=True,
        return_value={},
    ):
        await hass.services.async_call(DOMAIN, "reload")
        await hass.async_block_till_done()

    # Check there are no config entries.
    assert not hass.config_entries.async_entries(DOMAIN)

    # Reload config again with config removed.
    # This also covers the case where there are no imported entries to remove, and not
    # imported entries to create or update.
    with patch(
        "custom_components.sun2.async_integration_yaml_config",
        autospec=True,
        return_value={},
    ):
        await hass.services.async_call(DOMAIN, "reload")
        await hass.async_block_till_done()

    # Check there are still no config entries.
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_ha_config_update(hass: HomeAssistant) -> None:
    """Test when HA config is updated."""
    new_time_zone = "America/New_York"
    new_location_name = "New York, NY"

    # Check some assumptions.
    assert hass.config.time_zone != new_time_zone
    assert hass.config.location_name != new_location_name

    await async_setup_component(hass, DOMAIN, {DOMAIN: [HOME_CONFIG]})
    await hass.async_block_till_done()

    # ConfigEntry object may change values, but it should not be replaced by a new
    # object.
    config_entry = hass.config_entries.async_entries(DOMAIN)[0]

    # Get baseline.
    old_values = config_entry.as_dict()
    assert old_values["title"] == hass.config.location_name

    # Fire an EVENT_CORE_CONFIG_UPDATE event with no data and check that nothing has
    # changed.
    hass.bus.async_fire(EVENT_CORE_CONFIG_UPDATE)
    await hass.async_block_till_done()
    assert hass.config_entries.async_entries(DOMAIN)[0] is config_entry
    new_values = config_entry.as_dict()
    assert new_values == old_values
    old_values = new_values

    # Change anything except for location_name and language and check that nothing
    # changes.
    await hass.config.async_update(time_zone=new_time_zone)
    await hass.async_block_till_done()
    assert hass.config_entries.async_entries(DOMAIN)[0] is config_entry
    new_values = config_entry.as_dict()
    assert new_values == old_values
    old_values = new_values

    # Change location_name and check that config entry reflects this change.
    # Note that this will cause a reload of YAML config.
    with patch(
        "custom_components.sun2.async_integration_yaml_config",
        autospec=True,
        return_value={DOMAIN: [HOME_CONFIG]},
    ):
        await hass.config.async_update(location_name=new_location_name)
        await hass.async_block_till_done()

    assert hass.config_entries.async_entries(DOMAIN)[0] is config_entry
    new_values = config_entry.as_dict()
    assert new_values != old_values
    assert new_values["title"] == new_location_name
