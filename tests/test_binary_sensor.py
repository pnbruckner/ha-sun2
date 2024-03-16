"""Test binary_sensor module."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from astral import LocationInfo
from astral.location import Location
from custom_components.sun2.const import DOMAIN
import pytest
from pytest import LogCaptureFixture
from pytest_homeassistant_custom_component.common import (
    assert_setup_component,
    async_fire_time_changed,
)

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import EntityRegistry
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util, slugify
from tests.common import DtNowMock

from .const import NY_CONFIG

# ========== Fixtures ==================================================================


# ========== Tests =====================================================================


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
    dt_now: DtNowMock,
    elevation: str | float,
    name: str | None,
    slug: str,
) -> None:
    """Test YAML configured elevation binary sensor."""
    dt_now_real, dt_now_mock = dt_now

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
    base_time = dt_now_real(tz)

    # Set time to 00:00:00 tommorow.
    now = datetime.combine((base_time + timedelta(1)).date(), time()).replace(tzinfo=tz)

    dt_now_mock.return_value = now
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
    assert state
    # Sun is always below the horizon at midnight in New York.
    assert state.state == STATE_OFF
    # And is always above the horizon at noon.
    # Next change should be after midnight and before noon.
    next_change = state.attributes.get("next_change")
    noon = now.replace(hour=12)
    assert isinstance(next_change, datetime)
    assert now < next_change < noon

    # Move time to next_change and make sure state has changed.
    dt_now_mock.return_value = next_change
    async_fire_time_changed(hass, next_change)
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state
    assert state.state == STATE_ON


_SUN_NEVER_REACHES = "Sun elevation never reaches"


@pytest.mark.cleanup_params(ignore_phrases=[_SUN_NEVER_REACHES])
@pytest.mark.parametrize(
    "elevation,expected_state",
    (
        (85, STATE_OFF),
        (-85, STATE_ON),
    ),
)
async def test_always_on_or_off(
    hass: HomeAssistant,
    entity_registry: EntityRegistry,
    dt_now: DtNowMock,
    caplog: LogCaptureFixture,
    elevation: float,
    expected_state: str,
) -> None:
    """Test a binary sensor that is always on or off."""
    dt_now_real, dt_now_mock = dt_now

    config = NY_CONFIG | {
        "binary_sensors": [
            {
                "unique_id": "bs1",
                "elevation": elevation,
            }
        ]
    }

    tz = dt_util.get_time_zone(NY_CONFIG["time_zone"])
    base_time = dt_now_real(tz)

    # Set time to 00:00:00 tommorow.
    now = datetime.combine((base_time + timedelta(1)).date(), time()).replace(tzinfo=tz)

    dt_now_mock.return_value = now
    with assert_setup_component(1, DOMAIN):
        await async_setup_component(hass, DOMAIN, {DOMAIN: [config]})
    await hass.async_block_till_done()

    config_entry = hass.config_entries.async_entries(DOMAIN)[0]
    entity_id = entity_registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{config_entry.entry_id}-bs1"
    )
    assert entity_id

    # Check that state is as expected.
    state = hass.states.get(entity_id)
    assert state
    assert state.state == expected_state
    assert state.attributes["next_change"] is None

    # Check that there is an appropraite ERROR message.
    assert any(
        rec.levelname == "ERROR" and _SUN_NEVER_REACHES in rec.message
        for rec in caplog.get_records("call")
    )

    # Move time to noon.
    noon = now.replace(hour=12)
    dt_now_mock.return_value = noon
    async_fire_time_changed(hass, noon)
    await hass.async_block_till_done()

    # Check that state is still the same.
    state = hass.states.get(entity_id)
    assert state
    assert state.state == expected_state
    assert state.attributes["next_change"] is None


@pytest.mark.parametrize(
    "func,offset,expected_state", (("midnight", -1, STATE_ON), ("noon", 1, STATE_OFF))
)
async def test_next_change_greater_than_one_day(
    hass: HomeAssistant,
    entity_registry: EntityRegistry,
    dt_now: DtNowMock,
    caplog: LogCaptureFixture,
    func: str,
    offset: int,
    expected_state: str,
) -> None:
    """Test when binary sensor won't change for more than one day."""
    dt_now_real, dt_now_mock = dt_now

    config = NY_CONFIG | {
        "binary_sensors": [
            {
                "unique_id": "bs1",
            }
        ]
    }

    tz_str = NY_CONFIG["time_zone"]
    lat = NY_CONFIG["latitude"]
    lon = NY_CONFIG["longitude"]
    obs_elv = NY_CONFIG["elevation"]
    loc = Location(LocationInfo("", "", tz_str, lat, lon))
    tz = dt_util.get_time_zone(tz_str)

    # Get next year's September 20, since on this date neither the min nor max elevation
    # is near their extremes in New York, NY. Then get the min or max sun elevations.
    now_date = date(dt_now_real(tz).year + 1, 9, 20)
    elv = loc.solar_elevation(getattr(loc, func)(now_date), obs_elv)

    # Configure sensor with an elevation threshold just below or above.
    config["binary_sensors"][0]["elevation"] = elv + offset

    # Set time to midnight on that date.
    now = datetime.combine(now_date, time()).replace(tzinfo=tz)

    dt_now_mock.return_value = now
    with assert_setup_component(1, DOMAIN):
        await async_setup_component(hass, DOMAIN, {DOMAIN: [config]})
    await hass.async_block_till_done()

    config_entry = hass.config_entries.async_entries(DOMAIN)[0]
    entity_id = entity_registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{config_entry.entry_id}-bs1"
    )
    assert entity_id

    # Check that state is on & next_change has a value.
    state = hass.states.get(entity_id)
    assert state
    assert state.state == expected_state
    assert state.attributes["next_change"]

    # Check that there is an appropraite WARNING message.
    assert any(
        rec.levelname == "WARNING" and "Sun elevation will not reach" in rec.message
        for rec in caplog.get_records("call")
    )
