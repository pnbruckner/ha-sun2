from __future__ import annotations

from unittest.mock import patch
from pytest_homeassistant_custom_component.common import assert_setup_component

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import EntityRegistry
from homeassistant.setup import async_setup_component
from homeassistant.util import slugify

from custom_components.sun2.const import DOMAIN


async def test_basic_yaml_config(
    hass: HomeAssistant, entity_registry: EntityRegistry
) -> None:
    """Test basic YAML configuration."""
    with assert_setup_component(1, DOMAIN):
        await async_setup_component(hass, DOMAIN, {DOMAIN: [{"unique_id": 1}]})
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


async def test_reload_service(
    hass: HomeAssistant, entity_registry: EntityRegistry
) -> None:
    """Test basic YAML configuration."""
    config_1 = {"unique_id": "1"}

    loc_2a = {
        "latitude": 40.68954412564642,
        "longitude": -74.04486696480146,
        "elevation": 0,
        "time_zone": "America/New_York",
    }
    config_2a = {
        "unique_id": "Test 2",
        "location": "Statue of Liberty",
    } | loc_2a

    loc_2b = {
        "latitude": 39.50924426436838,
        "longitude": -98.43369506033378,
        "elevation": 10,
        "time_zone": "CST",
    }
    config_2b = {
        "unique_id": "Test 2",
        "location": "World's Largest Ball of Twine",
    } | loc_2b

    loc_3 = {
        "latitude": 34.134092337996336,
        "longitude": -118.32154780135669,
        "elevation": 391,
        "time_zone": "America/Los_Angeles",
    }
    config_3 = {
        "unique_id": "3",
        "location": "Hollywood Sign",
    } | loc_3

    init_config = [config_1, config_2a]
    with assert_setup_component(len(init_config), DOMAIN):
        await async_setup_component(hass, DOMAIN, {DOMAIN: init_config})
    await hass.async_block_till_done()

    # Check config entries match config.
    config_entries = hass.config_entries.async_entries(DOMAIN)
    assert len(config_entries) == 2
    config_entry_1 = config_entries[0]
    assert config_entry_1.unique_id == config_1["unique_id"]
    assert config_entry_1.title == hass.config.location_name
    assert config_entry_1.options == {}
    config_entry_2 = config_entries[1]
    assert config_entry_2.unique_id == config_2a["unique_id"]
    assert config_entry_2.title == config_2a["location"]
    assert config_entry_2.options == loc_2a

    # Check reload service exists.
    assert hass.services.has_service(DOMAIN, "reload")

    # Reload config.
    reload_config = [config_2b, config_3]
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
    assert config_entry_1.unique_id == config_2b["unique_id"]
    assert config_entry_1.title == config_2b["location"]
    assert config_entry_1.options == loc_2b
    config_entry_2 = config_entries[1]
    assert config_entry_2.unique_id == config_3["unique_id"]
    assert config_entry_2.title == config_3["location"]
    assert config_entry_2.options == loc_3
