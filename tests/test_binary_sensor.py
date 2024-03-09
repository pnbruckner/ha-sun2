"""Test binary_sensor module."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from unittest.mock import patch
import pytest

from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    assert_setup_component,
)

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import EntityRegistry
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util, slugify

from custom_components.sun2.const import DOMAIN

from .const import NY_CONFIG


@pytest.mark.parametrize(
    "elevation,name,slug",
    (
        ("horizon", None, "above_horizon"),
        (1, None, "above_1_0_deg"),
        (-1, None, "above_minus_1_0_deg"),
        (0, "Name Test", "name_test"),
    ),
)
async def test_yaml_binary_sensor(
    hass: HomeAssistant,
    entity_registry: EntityRegistry,
    elevation: str | float,
    name: str | None,
    slug: str,
) -> None:
    """Test YAML configured elevation binary sensor."""
    config = NY_CONFIG | {
        "binary_sensors": [
            {
                "unique_id": "bs1",
                "elevation": elevation,
            }
        ]
    }
    if name:
        config["binary_sensors"][0]["name"] = name

    tz = dt_util.get_time_zone(NY_CONFIG["time_zone"])
    base_time = dt_util.now(tz)

    # Set time to 00:00:00 tommorow.
    now = datetime.combine((base_time + timedelta(1)).date(), time()).replace(tzinfo=tz)

    with patch("homeassistant.util.dt.now", return_value=now):
        with assert_setup_component(1, DOMAIN):
            await async_setup_component(hass, DOMAIN, {DOMAIN: [config]})
        await hass.async_block_till_done()

    config_entry = hass.config_entries.async_entries(DOMAIN)[0]

    # Check that elevation binary_sensor was created with expected entity ID and it has
    # the expected state.
    entity_id = entity_registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{config_entry.entry_id}-bs1"
    )
    expected_id = f"binary_sensor.{slugify(NY_CONFIG['location'])}_sun_{slug}"
    assert entity_id == expected_id
    state = hass.states.get(entity_id)
    # Sun is always below the horizon at midnight in New York.
    assert state.state == STATE_OFF
    # And is always above the horizon at noon.
    # Next change should be after midnight and before noon.
    next_change = state.attributes.get("next_change")
    noon = now.replace(hour=12)
    assert isinstance(next_change, datetime)
    assert now < next_change < noon

    # Move time to next_change and make sure state has changed.
    with patch("homeassistant.util.dt.now", return_value=next_change):
        async_fire_time_changed(hass, next_change)
        await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.state == STATE_ON
