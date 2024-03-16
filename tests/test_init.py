"""Test init module."""
from __future__ import annotations

from collections.abc import Callable, Generator
from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, call, patch

from custom_components.sun2 import PLATFORMS
from custom_components.sun2.const import DOMAIN, SIG_HA_LOC_UPDATED
from custom_components.sun2.helpers import LocData, LocParams
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    assert_setup_component,
)

from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_USER
from homeassistant.const import EVENT_CORE_CONFIG_UPDATE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_registry import EntityRegistry
from homeassistant.setup import async_setup_component

from .const import HOME_CONFIG, NY_CONFIG, NY_LOC, TWINE_CONFIG

# ========== Fixtures ==================================================================


@pytest.fixture
def setup_entry_mock() -> Generator[AsyncMock, None, None]:
    """Mock async_setup_entry."""
    with patch("custom_components.sun2.async_setup_entry", autospec=True) as mock:
        mock.return_value = True
        yield mock


@pytest.fixture
def unload_entry_mock() -> Generator[AsyncMock, None, None]:
    """Mock async_setup_entry."""
    with patch("custom_components.sun2.async_unload_entry", autospec=True) as mock:
        mock.return_value = True
        yield mock


@pytest.fixture
def yaml_load_mock(hass: HomeAssistant) -> Generator[AsyncMock, None, None]:
    """Mock async_integration_yaml_config."""
    with patch(
        "custom_components.sun2.async_integration_yaml_config", autospec=True
    ) as mock:
        yield mock


@pytest.fixture
def dispatch_listener_mock(hass: HomeAssistant) -> AsyncMock:
    """Mock SIG_HA_LOC_UPDATED listener."""
    mock = AsyncMock()
    async_dispatcher_connect(hass, SIG_HA_LOC_UPDATED, mock)
    return mock


@pytest.fixture
def fwd_entry_setups_mock(hass: HomeAssistant) -> Generator[AsyncMock, None, None]:
    """Mock config_entries.async_reload."""
    with patch.object(
        hass.config_entries, "async_forward_entry_setups", autospec=True
    ) as mock:
        yield mock


@pytest.fixture
async def basic_setup(
    hass: HomeAssistant,
    setup_entry_mock: AsyncMock,
    unload_entry_mock: AsyncMock,
    yaml_load_mock: AsyncMock,
    dispatch_listener_mock: AsyncMock,
) -> tuple[MockConfigEntry, MockConfigEntry, MockConfigEntry]:
    """Set up integration with existing config entries.

    Create:
        - One UI config entry for Home.
        - One UI config entry for New York.
        - One YAML config entry for Biggest ball of twine.

    Return: A tuple of those config entries, in that order.
    """
    ui_home_entry = MockConfigEntry(
        domain=DOMAIN,
        source=SOURCE_USER,
        title=hass.config.location_name,
    )
    ui_home_entry.add_to_hass(hass)
    ui_ny_entry = MockConfigEntry(
        domain=DOMAIN, source=SOURCE_USER, title=NY_CONFIG["location"], options=NY_LOC
    )
    ui_ny_entry.add_to_hass(hass)

    await async_setup_component(hass, DOMAIN, {DOMAIN: [TWINE_CONFIG]})
    await hass.async_block_till_done()

    setup_entry_mock.reset_mock()
    unload_entry_mock.reset_mock()
    yaml_load_mock.reset_mock()
    dispatch_listener_mock.reset_mock()
    yaml_load_mock.return_value = {DOMAIN: [TWINE_CONFIG]}

    for config_entry in hass.config_entries.async_entries(DOMAIN):
        if config_entry.source == SOURCE_IMPORT:
            yaml_twine_entry = config_entry
            break

    return ui_home_entry, ui_ny_entry, yaml_twine_entry


# ========== async_setup Tests: No Config ==============================================


async def test_setup_no_config(
    hass: HomeAssistant, setup_entry_mock: AsyncMock, unload_entry_mock: AsyncMock
) -> None:
    """Test setup with no config."""
    with assert_setup_component(0, DOMAIN):
        await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, "reload")
    assert not setup_entry_mock.called
    assert not unload_entry_mock.called


# ========== async_setup Tests: YAML Config ============================================


async def test_setup_yaml_config_new(
    hass: HomeAssistant, setup_entry_mock: AsyncMock, unload_entry_mock: AsyncMock
) -> None:
    """Test setup with new YAML configs."""
    with assert_setup_component(2, DOMAIN):
        await async_setup_component(hass, DOMAIN, {DOMAIN: [HOME_CONFIG, NY_CONFIG]})
    await hass.async_block_till_done()

    # Check that two distinct config entries were created, they have the expected unique
    # IDs & source type, they were passed to async_setup_entry, and that
    # async_unload_entry was not called.
    config_entries = hass.config_entries.async_entries(DOMAIN)
    assert len(config_entries) == 2
    assert config_entries[0] != config_entries[1]
    unique_ids = {config_entry.unique_id for config_entry in config_entries}
    assert unique_ids == {HOME_CONFIG["unique_id"], NY_CONFIG["unique_id"]}
    setup_entry_mock.call_count == 2
    setup_entry_mock.await_count == 2
    for config_entry in config_entries:
        assert config_entry.source == SOURCE_IMPORT
        setup_entry_mock.assert_any_call(hass, config_entry)
    assert not unload_entry_mock.called


async def test_setup_yaml_config_changed(
    hass: HomeAssistant, setup_entry_mock: AsyncMock, unload_entry_mock: AsyncMock
) -> None:
    """Test setup with a changed YAML config."""
    # Create and register an existing YAML config entry and save its values.
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        source=SOURCE_IMPORT,
        title=hass.config.location_name,
        unique_id=HOME_CONFIG["unique_id"],
    )
    config_entry.add_to_hass(hass)
    old_values = config_entry.as_dict()

    # Define changed config, keeping unique_id the same.
    new_config = NY_CONFIG | {"unique_id": HOME_CONFIG["unique_id"]}

    with assert_setup_component(1, DOMAIN):
        await async_setup_component(hass, DOMAIN, {DOMAIN: [new_config]})
    await hass.async_block_till_done()

    # Check that we have one config, which is the same object that was originally
    # registered, its unique_id hasn't changed, but other values have, and it is passed
    # to async_setup_entry.
    config_entries = hass.config_entries.async_entries(DOMAIN)
    assert len(config_entries) == 1
    assert config_entries[0] is config_entry
    assert config_entry.unique_id == old_values["unique_id"]
    assert config_entry.as_dict() != old_values
    setup_entry_mock.assert_called_once_with(hass, config_entry)
    assert not unload_entry_mock.called


async def test_setup_yaml_config_removed(
    hass: HomeAssistant, setup_entry_mock: AsyncMock, unload_entry_mock: AsyncMock
) -> None:
    """Test setup with a removed YAML config."""
    # Create and register an existing YAML config entry.
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        source=SOURCE_IMPORT,
        title=hass.config.location_name,
        unique_id=HOME_CONFIG["unique_id"],
    )
    config_entry.add_to_hass(hass)

    with assert_setup_component(0, DOMAIN):
        await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    # Check that the config entry is gone.
    config_entries = hass.config_entries.async_entries(DOMAIN)
    assert len(config_entries) == 0
    assert not setup_entry_mock.called
    assert not unload_entry_mock.called


async def test_setup_yaml_config_reload_same(
    hass: HomeAssistant,
    setup_entry_mock: AsyncMock,
    unload_entry_mock: AsyncMock,
    yaml_load_mock: AsyncMock,
) -> None:
    """Test reloading same YAML config."""
    with assert_setup_component(1, DOMAIN):
        await async_setup_component(hass, DOMAIN, {DOMAIN: [HOME_CONFIG]})
    await hass.async_block_till_done()
    setup_entry_mock.reset_mock()
    unload_entry_mock.reset_mock()
    yaml_load_mock.reset_mock()
    config_entry = hass.config_entries.async_entries(DOMAIN)[0]

    # Call reload service with same config.
    yaml_load_mock.return_value = {DOMAIN: [HOME_CONFIG]}
    await hass.services.async_call(DOMAIN, "reload")
    await hass.async_block_till_done()

    # With no change, config flow will directly reload config, so both
    # async_unload_entry and async_setup_entry should be called.
    unload_entry_mock.assert_called_once_with(hass, config_entry)
    unload_entry_mock.assert_awaited_once()
    setup_entry_mock.assert_called_once_with(hass, config_entry)
    setup_entry_mock.assert_awaited_once()


async def test_setup_yaml_config_reload_diff(
    hass: HomeAssistant,
    setup_entry_mock: AsyncMock,
    unload_entry_mock: AsyncMock,
    yaml_load_mock: AsyncMock,
) -> None:
    """Test reloading a different YAML config."""
    with assert_setup_component(1, DOMAIN):
        await async_setup_component(hass, DOMAIN, {DOMAIN: [HOME_CONFIG]})
    await hass.async_block_till_done()
    setup_entry_mock.reset_mock()
    unload_entry_mock.reset_mock()
    yaml_load_mock.reset_mock()

    # Call reload service with a changed config, keeping unique_id the same.
    new_config = NY_CONFIG | {"unique_id": HOME_CONFIG["unique_id"]}
    yaml_load_mock.return_value = {DOMAIN: [new_config]}
    await hass.services.async_call(DOMAIN, "reload")
    await hass.async_block_till_done()

    # With a change, config flow will not directly reload config, so neither
    # async_unload_entry nor async_setup_entry should be called. (Normally,
    # async_setup_entry would have set up a listener for changed configs, and that
    # listener would reload the config.)
    assert not setup_entry_mock.called
    assert not unload_entry_mock.called


# ========== async_setup Tests: UI Config ==============================================


async def test_setup_ui_config(
    hass: HomeAssistant, setup_entry_mock: AsyncMock, unload_entry_mock: AsyncMock
) -> None:
    """Test setup with a changed YAML config."""
    # Create and register an existing UI config entry and save its values.
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        source=SOURCE_USER,
        title=hass.config.location_name,
    )
    config_entry.add_to_hass(hass)
    old_values = config_entry.as_dict()

    with assert_setup_component(0, DOMAIN):
        await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    # Check that UI config entry hasn't changed and was setup.
    assert config_entry.as_dict() == old_values
    setup_entry_mock.assert_called_once_with(hass, config_entry)
    setup_entry_mock.assert_awaited_once()
    assert not unload_entry_mock.called


# ========== async_setup Tests: HA Config Updated ======================================


async def test_setup_ha_config_updated_no_data(
    hass: HomeAssistant,
    setup_entry_mock: AsyncMock,
    unload_entry_mock: AsyncMock,
    dispatch_listener_mock: AsyncMock,
    basic_setup: tuple[MockConfigEntry, MockConfigEntry, MockConfigEntry],
) -> None:
    """Test EVENT_CORE_CONFIG_UPDATE with no data."""
    hass.bus.async_fire(EVENT_CORE_CONFIG_UPDATE)
    await hass.async_block_till_done()

    # Check that none of the monitored functions have been called.
    assert setup_entry_mock.call_count == 0
    assert unload_entry_mock.call_count == 0
    assert dispatch_listener_mock.call_count == 0


async def test_setup_ha_config_updated_loc_only(
    hass: HomeAssistant,
    setup_entry_mock: AsyncMock,
    unload_entry_mock: AsyncMock,
    dispatch_listener_mock: AsyncMock,
    basic_setup: tuple[MockConfigEntry, MockConfigEntry, MockConfigEntry],
) -> None:
    """Test EVENT_CORE_CONFIG_UPDATE w/ location data only."""
    await hass.config.async_update(latitude=hass.config.latitude + 10)
    await hass.async_block_till_done()

    # Check that only the dispatch listener was called.
    assert setup_entry_mock.call_count == 0
    assert unload_entry_mock.call_count == 0
    dispatch_listener_mock.assert_called_once_with(
        LocData(
            LocParams(
                hass.config.elevation,
                hass.config.latitude,
                hass.config.longitude,
                hass.config.time_zone,
            )
        )
    )
    dispatch_listener_mock.assert_awaited_once()


async def test_setup_ha_config_updated_name(
    hass: HomeAssistant,
    setup_entry_mock: AsyncMock,
    unload_entry_mock: AsyncMock,
    yaml_load_mock: AsyncMock,
    dispatch_listener_mock: AsyncMock,
    basic_setup: tuple[MockConfigEntry, MockConfigEntry, MockConfigEntry],
) -> None:
    """Test EVENT_CORE_CONFIG_UPDATE w/ name changed."""
    ui_home_entry, ui_ny_entry, yaml_twine_entry = basic_setup
    ui_home_values = ui_home_entry.as_dict()
    ui_ny_values = ui_ny_entry.as_dict()
    yaml_twine_values = yaml_twine_entry.as_dict()

    new_home_name = "New " + hass.config.location_name
    await hass.config.async_update(location_name=new_home_name)
    await hass.async_block_till_done()

    # Check that UI NY & YAML configs were reloaded, YAML was loaded, and dispatch
    # listener was not called.
    assert setup_entry_mock.call_count == 2
    assert setup_entry_mock.await_count == 2
    assert unload_entry_mock.call_count == 2
    assert unload_entry_mock.await_count == 2
    calls = [call(hass, ui_ny_entry), call(hass, yaml_twine_entry)]
    for a_call in setup_entry_mock.call_args_list:
        assert a_call in calls
    for a_call in unload_entry_mock.call_args_list:
        assert a_call in calls
    yaml_load_mock.assert_called_once()
    assert dispatch_listener_mock.call_count == 0

    # Check that only the UI Home entry has changed, and only its title.
    assert ui_home_entry.as_dict() == ui_home_values | {"title": new_home_name}
    assert ui_ny_entry.as_dict() == ui_ny_values
    assert yaml_twine_entry.as_dict() == yaml_twine_values


# ========== async_setup_entry & entry_updated Tests: ==================================


async def test_entry_updated(
    hass: HomeAssistant,
    entity_registry: EntityRegistry,
    unload_entry_mock: AsyncMock,
    fwd_entry_setups_mock: AsyncMock,
) -> None:
    """Test entry_updated."""

    def create_options(uid: Callable[[int], str]) -> dict[str, Any]:
        """Create options dictionary."""
        return {
            "binary_sensors": [
                {"unique_id": uid(i), "elevation": float(i)} for i in range(2)
            ],
            "sensors": [
                {"unique_id": uid(i), "elevation_at_time": f"{i:02d}:00:00"}
                for i in range(2)
            ],
        }

    ui_uid = lambda i: f"{i:032d}"
    ui_options = create_options(ui_uid)
    ui_home_entry = MockConfigEntry(
        domain=DOMAIN,
        source=SOURCE_USER,
        title=hass.config.location_name,
        options=ui_options,
    )
    ui_home_entry.add_to_hass(hass)

    yaml_uid = lambda i: str(i)
    yaml_options = create_options(yaml_uid)
    yaml_config = NY_CONFIG | yaml_options
    await async_setup_component(hass, DOMAIN, {DOMAIN: [yaml_config]})
    await hass.async_block_till_done()

    for config_entry in hass.config_entries.async_entries(DOMAIN):
        if config_entry.source == SOURCE_IMPORT:
            yaml_ny_entry = config_entry
            break

    assert fwd_entry_setups_mock.call_count == 2
    assert fwd_entry_setups_mock.await_count == 2
    calls = [call(ui_home_entry, PLATFORMS), call(yaml_ny_entry, PLATFORMS)]
    for a_call in fwd_entry_setups_mock.call_args_list:
        assert a_call in calls

    unload_entry_mock.reset_mock()
    fwd_entry_setups_mock.reset_mock()

    # Config entries are now loaded, but entities have not been created due to test
    # patching, and therefore, entities have not been added to entity registry. Do that
    # now to simulate normal operation.
    for entry, options in ((ui_home_entry, ui_options), (yaml_ny_entry, yaml_options)):
        for key, sensor_type in (
            ("binary_sensors", "binary_sensor"),
            ("sensors", "sensor"),
        ):
            for sensor in options[key]:
                entity_registry.async_get_or_create(
                    sensor_type,
                    DOMAIN,
                    sensor["unique_id"],
                    config_entry=entry,
                )

    # Update UI config entry to remove a binary_sensor and a sensor.
    options = deepcopy(ui_options)
    removed_bs_uid = options["binary_sensors"].pop()["unique_id"]
    removed_s_uid = options["sensors"].pop()["unique_id"]
    remaining_bs_uids = [sensor["unique_id"] for sensor in options["binary_sensors"]]
    remaining_s_uids = [sensor["unique_id"] for sensor in options["sensors"]]

    assert hass.config_entries.async_update_entry(ui_home_entry, options=options)
    await hass.async_block_till_done()

    # For UI entry, check that removed sensors have been removed from entity registry,
    # and others remain.
    assert (
        entity_registry.async_get_entity_id("binary_sensor", DOMAIN, removed_bs_uid)
        is None
    )
    assert entity_registry.async_get_entity_id("sensor", DOMAIN, removed_s_uid) is None
    for uid in remaining_bs_uids:
        assert entity_registry.async_get_entity_id("binary_sensor", DOMAIN, uid)
    for uid in remaining_s_uids:
        assert entity_registry.async_get_entity_id("sensor", DOMAIN, uid)

    # Update YAML config entry to remove a binary_sensor and a sensor.
    options = deepcopy(yaml_options)
    removed_bs_uid = options["binary_sensors"].pop()["unique_id"]
    removed_s_uid = options["sensors"].pop()["unique_id"]
    remaining_bs_uids = [sensor["unique_id"] for sensor in options["binary_sensors"]]
    remaining_s_uids = [sensor["unique_id"] for sensor in options["sensors"]]

    assert hass.config_entries.async_update_entry(yaml_ny_entry, options=options)
    await hass.async_block_till_done()

    # For YAML entry, check that all sensors remain in entity registry.
    # NOTE: This may not be correct, but is how it currently works. Honestly, I can't
    #       remember why.
    for uid in [removed_bs_uid] + remaining_bs_uids:
        assert entity_registry.async_get_entity_id("binary_sensor", DOMAIN, uid)
    for uid in [removed_s_uid] + remaining_s_uids:
        assert entity_registry.async_get_entity_id("sensor", DOMAIN, uid)
