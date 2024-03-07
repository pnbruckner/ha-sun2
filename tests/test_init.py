from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import assert_setup_component

from homeassistant.const import MAJOR_VERSION, MINOR_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import EntityRegistry
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util, slugify

from custom_components.sun2.const import DOMAIN


@pytest.fixture
async def cleanup(hass: HomeAssistant):
    yield
    if (MAJOR_VERSION, MINOR_VERSION) > (2023, 5):
        return
    for entry in hass.config_entries.async_entries(DOMAIN):
        await hass.config_entries.async_unload(entry.entry_id)


async def test_basic_yaml_config(
    hass: HomeAssistant, entity_registry: EntityRegistry, cleanup: None
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
