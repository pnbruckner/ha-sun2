"""Test init module."""
from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, call, patch

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
from homeassistant.setup import async_setup_component

from .const import HOME_CONFIG, NY_CONFIG, NY_LOC, TWINE_CONFIG

# ========== Fixtures ==================================================================


# @pytest.fixture(autouse=True)
# async def setup(hass: HomeAssistant) -> None:
#     """Set up tests in this module."""
#     await init_translations(hass)


# @pytest.fixture
# def mock_config_remove(hass: HomeAssistant) -> Generator[AsyncMock, None, None]:
#     """Mock config_entries.async_remove."""
#     with patch.object(hass.config_entries, "async_remove", autospec=True) as mock:
#         yield mock


# @pytest.fixture
# def mock_config_update(hass: HomeAssistant) -> Generator[MagicMock, None, None]:
#     """Mock config_entries.async_update_entry."""
#     with patch.object(hass.config_entries, "async_update_entry", autospec=True) as mock:
#         yield mock


# @pytest.fixture
# def mock_config_reload(hass: HomeAssistant) -> Generator[AsyncMock, None, None]:
#     """Mock config_entries.async_reload."""
#     with patch.object(hass.config_entries, "async_reload", autospec=True) as mock:
#         yield mock


# @pytest.fixture
# def mock_flow_init(hass: HomeAssistant) -> Generator[AsyncMock, None, None]:
#     """Mock config_entries.flow.async_init."""
#     with patch.object(hass.config_entries.flow, "async_init", autospec=True) as mock:
#         yield mock


# @pytest.fixture
# async def setup_w_config_entry(
#     hass: HomeAssistant,
#     mock_config_remove: AsyncMock,
#     mock_config_update: MagicMock,
#     mock_flow_init: AsyncMock,
#     mock_yaml_load: AsyncMock,
#     mock_dispatch_listener: AsyncMock,
#     request: FixtureRequest,
# ) -> MockConfigEntry | None:
#     """Call async_setup & create a "Home" config entry.

#     Pass config:
#     @pytest.mark.entry_config(
#         *, yaml: bool = True, loc_config: data[str, Any] | None = HOME_CONFIG
#     )

#     async def test_abc(setup_w_config_entry: MockConfigEntry | None) -> None:
#        ...
#     """
#     yaml = True
#     loc_config = HOME_CONFIG
#     if marker := request.node.get_closest_marker("entry_config"):
#         if "yaml" in marker.kwargs:
#             yaml = marker.kwargs["yaml"]
#         if "loc_config" in marker.kwargs:
#             loc_config = marker.kwargs["loc_config"]

#     if loc_config:
#         config = {DOMAIN: [loc_config]} if yaml else {}
#         title = loc_config.get("location", hass.config.location_name)
#         unique_id = loc_config["unique_id"] if yaml else None
#     else:
#         config = {}

#     await async_setup(hass, config)
#     await hass.async_block_till_done()
#     mock_config_remove.reset_mock()
#     mock_config_update.reset_mock()
#     mock_flow_init.reset_mock()
#     mock_yaml_load.reset_mock()
#     mock_yaml_load.return_value = config
#     mock_dispatch_listener.reset_mock()
#     if loc_config is None:
#         return None
#     config_entry = MockConfigEntry(
#         domain=DOMAIN,
#         source=SOURCE_IMPORT if yaml else SOURCE_USER,
#         title=title,
#         options={
#             k: v
#             for k, v in loc_config.items()
#             if k in ("latitude", "longitude", "time_zone", "elevation")
#         },
#         unique_id=unique_id,
#     )
#     config_entry.add_to_hass(hass)
#     return config_entry


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock, None, None]:
    """Mock async_setup_entry."""
    with patch("custom_components.sun2.async_setup_entry", autospec=True) as mock:
        mock.return_value = True
        yield mock


@pytest.fixture
def mock_unload_entry() -> Generator[AsyncMock, None, None]:
    """Mock async_setup_entry."""
    with patch("custom_components.sun2.async_unload_entry", autospec=True) as mock:
        mock.return_value = True
        yield mock


@pytest.fixture
def mock_yaml_load(hass: HomeAssistant) -> Generator[AsyncMock, None, None]:
    """Mock async_integration_yaml_config."""
    with patch(
        "custom_components.sun2.async_integration_yaml_config", autospec=True
    ) as mock:
        yield mock


@pytest.fixture
def mock_dispatch_listener(hass: HomeAssistant) -> AsyncMock:
    """Mock SIG_HA_LOC_UPDATED listener."""
    mock = AsyncMock()
    async_dispatcher_connect(hass, SIG_HA_LOC_UPDATED, mock)
    return mock


@pytest.fixture
async def basic_setup(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_unload_entry: AsyncMock,
    mock_yaml_load: AsyncMock,
    mock_dispatch_listener: AsyncMock,
) -> tuple[MockConfigEntry, MockConfigEntry, MockConfigEntry]:
    """Set up integration with existing config entries.

    Create:
        - One UI config entry for Home.
        - One UI config entry for New York.
        - One YAML config entry for Biggest ball of twine.

    Return: A tuple of those config entries, in that order.
    """
    ui_home_config = MockConfigEntry(
        domain=DOMAIN,
        source=SOURCE_USER,
        title=hass.config.location_name,
    )
    ui_home_config.add_to_hass(hass)
    ui_ny_config = MockConfigEntry(
        domain=DOMAIN, source=SOURCE_USER, title=NY_CONFIG["location"], options=NY_LOC
    )
    ui_ny_config.add_to_hass(hass)

    await async_setup_component(hass, DOMAIN, {DOMAIN: [TWINE_CONFIG]})
    await hass.async_block_till_done()

    mock_setup_entry.reset_mock()
    mock_unload_entry.reset_mock()
    mock_yaml_load.reset_mock()
    mock_dispatch_listener.reset_mock()
    mock_yaml_load.return_value = {DOMAIN: [TWINE_CONFIG]}

    for config_entry in hass.config_entries.async_entries(DOMAIN):
        if config_entry.source == SOURCE_IMPORT:
            yaml_twine_entry = config_entry
            break

    return ui_home_config, ui_ny_config, yaml_twine_entry


# ========== async_setup Tests: No Config ==============================================


async def test_setup_no_config(
    hass: HomeAssistant, mock_setup_entry: AsyncMock, mock_unload_entry: AsyncMock
) -> None:
    """Test setup with no config."""
    with assert_setup_component(0, DOMAIN):
        await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, "reload")
    assert not mock_setup_entry.called
    assert not mock_unload_entry.called


# ========== async_setup Tests: YAML Config ============================================


async def test_setup_yaml_config_new(
    hass: HomeAssistant, mock_setup_entry: AsyncMock, mock_unload_entry: AsyncMock
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
    mock_setup_entry.call_count == 2
    mock_setup_entry.await_count == 2
    for config_entry in config_entries:
        assert config_entry.source == SOURCE_IMPORT
        mock_setup_entry.assert_any_call(hass, config_entry)
    assert not mock_unload_entry.called


async def test_setup_yaml_config_changed(
    hass: HomeAssistant, mock_setup_entry: AsyncMock, mock_unload_entry: AsyncMock
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
    mock_setup_entry.assert_called_once_with(hass, config_entry)
    assert not mock_unload_entry.called


async def test_setup_yaml_config_removed(
    hass: HomeAssistant, mock_setup_entry: AsyncMock, mock_unload_entry: AsyncMock
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
    assert not mock_setup_entry.called
    assert not mock_unload_entry.called


async def test_setup_yaml_config_reload_same(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_unload_entry: AsyncMock,
    mock_yaml_load: AsyncMock,
) -> None:
    """Test reloading same YAML config."""
    with assert_setup_component(1, DOMAIN):
        await async_setup_component(hass, DOMAIN, {DOMAIN: [HOME_CONFIG]})
    await hass.async_block_till_done()
    mock_setup_entry.reset_mock()
    mock_unload_entry.reset_mock()
    mock_yaml_load.reset_mock()
    config_entry = hass.config_entries.async_entries(DOMAIN)[0]

    # Call reload service with same config.
    mock_yaml_load.return_value = {DOMAIN: [HOME_CONFIG]}
    await hass.services.async_call(DOMAIN, "reload")
    await hass.async_block_till_done()

    # With no change, config flow will directly reload config, so both
    # async_unload_entry and async_setup_entry should be called.
    mock_unload_entry.assert_called_once_with(hass, config_entry)
    mock_unload_entry.assert_awaited_once()
    mock_setup_entry.assert_called_once_with(hass, config_entry)
    mock_setup_entry.assert_awaited_once()


async def test_setup_yaml_config_reload_diff(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_unload_entry: AsyncMock,
    mock_yaml_load: AsyncMock,
) -> None:
    """Test reloading a different YAML config."""
    with assert_setup_component(1, DOMAIN):
        await async_setup_component(hass, DOMAIN, {DOMAIN: [HOME_CONFIG]})
    await hass.async_block_till_done()
    mock_setup_entry.reset_mock()
    mock_unload_entry.reset_mock()
    mock_yaml_load.reset_mock()

    # Call reload service with a changed config, keeping unique_id the same.
    new_config = NY_CONFIG | {"unique_id": HOME_CONFIG["unique_id"]}
    mock_yaml_load.return_value = {DOMAIN: [new_config]}
    await hass.services.async_call(DOMAIN, "reload")
    await hass.async_block_till_done()

    # With a change, config flow will not directly reload config, so neither
    # async_unload_entry nor async_setup_entry should be called. (Normally,
    # async_setup_entry would have set up a listener for changed configs, and that
    # listener would reload the config.)
    assert not mock_setup_entry.called
    assert not mock_unload_entry.called


# ========== async_setup Tests: UI Config ==============================================


async def test_setup_ui_config(
    hass: HomeAssistant, mock_setup_entry: AsyncMock, mock_unload_entry: AsyncMock
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
    mock_setup_entry.assert_called_once_with(hass, config_entry)
    mock_setup_entry.assert_awaited_once()
    assert not mock_unload_entry.called


# ========== async_setup Tests: HA Config Updated ======================================


async def test_setup_ha_config_updated_no_data(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_unload_entry: AsyncMock,
    mock_dispatch_listener: AsyncMock,
    basic_setup: tuple[MockConfigEntry, MockConfigEntry, MockConfigEntry],
) -> None:
    """Test EVENT_CORE_CONFIG_UPDATE with no data."""
    hass.bus.async_fire(EVENT_CORE_CONFIG_UPDATE)
    await hass.async_block_till_done()

    # Check that none of the monitored functions have been called.
    assert mock_setup_entry.call_count == 0
    assert mock_unload_entry.call_count == 0
    assert mock_dispatch_listener.call_count == 0


async def test_setup_ha_config_updated_loc_only(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_unload_entry: AsyncMock,
    mock_dispatch_listener: AsyncMock,
    basic_setup: tuple[MockConfigEntry, MockConfigEntry, MockConfigEntry],
) -> None:
    """Test EVENT_CORE_CONFIG_UPDATE w/ location data only."""
    await hass.config.async_update(latitude=hass.config.latitude + 10)
    await hass.async_block_till_done()

    # Check that only the dispatch listener was called.
    assert mock_setup_entry.call_count == 0
    assert mock_unload_entry.call_count == 0
    mock_dispatch_listener.assert_called_once_with(
        LocData(
            LocParams(
                hass.config.elevation,
                hass.config.latitude,
                hass.config.longitude,
                hass.config.time_zone,
            )
        )
    )
    mock_dispatch_listener.assert_awaited_once()


async def test_setup_ha_config_updated_name(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_unload_entry: AsyncMock,
    mock_yaml_load: AsyncMock,
    mock_dispatch_listener: AsyncMock,
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
    assert mock_setup_entry.call_count == 2
    assert mock_setup_entry.await_count == 2
    assert mock_unload_entry.call_count == 2
    assert mock_unload_entry.await_count == 2
    calls = [call(hass, ui_ny_entry), call(hass, yaml_twine_entry)]
    for a_call in mock_setup_entry.call_args_list:
        assert a_call in calls
    for a_call in mock_unload_entry.call_args_list:
        assert a_call in calls
    mock_yaml_load.assert_called_once()
    assert mock_dispatch_listener.call_count == 0

    # Check that only the UI Home entry has changed, and only its title.
    assert ui_home_entry.as_dict() == ui_home_values | {"title": new_home_name}
    assert ui_ny_entry.as_dict() == ui_ny_values
    assert yaml_twine_entry.as_dict() == yaml_twine_values


# async def test_basic_yaml_config(
#     hass: HomeAssistant, entity_registry: EntityRegistry
# ) -> None:
#     """Test basic YAML configuration."""
#     with assert_setup_component(1, DOMAIN):
#         await async_setup_component(hass, DOMAIN, {DOMAIN: [HOME_CONFIG]})
#     await hass.async_block_till_done()

#     expected_entities = (
#         (True, ("dawn", "dusk", "rising", "setting", "solar_midnight", "solar_noon")),
#         (
#             False,
#             (
#                 "astronomical_dawn",
#                 "astronomical_daylight",
#                 "astronomical_dusk",
#                 "astronomical_night",
#                 "azimuth",
#                 "civil_daylight",
#                 "civil_night",
#                 "daylight",
#                 "deconz_daylight",
#                 "elevation",
#                 "maximum_elevation",
#                 "minimum_elevation",
#                 "nautical_dawn",
#                 "nautical_daylight",
#                 "nautical_dusk",
#                 "nautical_night",
#                 "night",
#                 "phase",
#             ),
#         ),
#     )

#     # Check that the expected number of entities were created.
#     n_expected_entities = sum(len(x[1]) for x in expected_entities)
#     n_actual_entities = len(
#         [
#             entry
#             for entry in entity_registry.entities.values()
#             if entry.platform == DOMAIN
#         ]
#     )
#     assert n_actual_entities == n_expected_entities

#     # Check that the created entities have the correct IDs and enabled status.
#     location_name = hass.config.location_name
#     for enabled, suffixes in expected_entities:
#         for suffix in suffixes:
#             entry = entity_registry.async_get(
#                 f"sensor.{slugify(location_name)}_sun_{suffix}"
#             )
#             assert entry
#             assert entry.disabled != enabled
