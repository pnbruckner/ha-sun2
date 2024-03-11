"""Test init module."""
from __future__ import annotations
from collections.abc import Generator

from unittest.mock import AsyncMock, Mock, patch

from custom_components.sun2 import async_setup
from custom_components.sun2.const import DOMAIN, SIG_HA_LOC_UPDATED
from custom_components.sun2.helpers import init_translations
import pytest
from pytest import FixtureRequest
from pytest_homeassistant_custom_component.common import MockConfigEntry, assert_setup_component

from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import EVENT_CORE_CONFIG_UPDATE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_registry import EntityRegistry
from homeassistant.setup import async_setup_component
from homeassistant.util import slugify

from .const import (
    HOME_CONFIG,
    HW_CONFIG,
    HW_LOC,
    NY_CONFIG,
    NY_LOC,
    TWINE_CONFIG,
    TWINE_LOC,
)


# ========== Fixtures ==================================================================


@pytest.fixture(autouse=True)
async def setup(hass: HomeAssistant) -> None:
    """Setup tests in this module."""
    await init_translations(hass)


@pytest.fixture
def mock_remove_config(hass: HomeAssistant) -> Generator[AsyncMock, None, None]:
    """Mock config_entries.async_remove."""
    with patch.object(hass.config_entries, "async_remove", autospec=True) as mock:
        yield mock


@pytest.fixture
def mock_flow_init(hass: HomeAssistant) -> Generator[AsyncMock, None, None]:
    """Mock config_entries.flow.async_init."""
    with patch.object(hass.config_entries.flow, "async_init", autospec=True) as mock:
        yield mock


@pytest.fixture
def mock_load_yaml(hass: HomeAssistant) -> Generator[AsyncMock, None, None]:
    """Mock async_integration_yaml_config."""
    with patch(
        "custom_components.sun2.async_integration_yaml_config", autospec=True
    ) as mock:
        yield mock


@pytest.fixture
def mock_dispatch_listener(hass: HomeAssistant) -> Generator[AsyncMock, None, None]:
    """Mock SIG_HA_LOC_UPDATED listener."""
    mock = AsyncMock()
    async_dispatcher_connect(hass, SIG_HA_LOC_UPDATED, mock)
    return mock


@pytest.fixture
async def init_yaml_config_entry(
    hass: HomeAssistant,
    mock_remove_config: AsyncMock,
    mock_flow_init: AsyncMock,
    mock_load_yaml: AsyncMock,
    mock_dispatch_listener: AsyncMock,
    request: FixtureRequest,
) -> MockConfigEntry:
    """Initialize a YAML config entry.

    Pass config:
    @pytest.mark.entry_config(CONFIG)\n
    async def test_abc(init_yaml_config_entry: MockConfigEntry) -> None:
       ...
    """
    marker = request.node.get_closest_marker("entry_config")
    if marker is None:
        config = HOME_CONFIG
    else:
        config = marker.args[0]
    await async_setup(hass, {DOMAIN: [config]})
    await hass.async_block_till_done()
    mock_remove_config.reset_mock()
    mock_flow_init.reset_mock()
    mock_load_yaml.reset_mock()
    mock_load_yaml.return_value = {DOMAIN: [HOME_CONFIG]}
    mock_dispatch_listener.reset_mock()
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        source=SOURCE_IMPORT,
        title=config.get("location", hass.config.location_name),
        unique_id=config["unique_id"],
    )
    config_entry.add_to_hass(hass)
    return config_entry


# ========== async_setup Tests: No Config ==============================================


async def test_setup_no_config(
    hass: HomeAssistant,
    mock_remove_config: AsyncMock,
    mock_flow_init: AsyncMock,
    mock_load_yaml: AsyncMock,
    mock_dispatch_listener: AsyncMock,
) -> None:
    """Test async_setup with no configuration."""
    await async_setup(hass, {})
    await hass.async_block_till_done()
    assert not mock_remove_config.called
    assert not mock_flow_init.called
    assert not mock_load_yaml.called
    assert not mock_dispatch_listener.called
    assert hass.services.has_service(DOMAIN, "reload")


# ========== async_setup Tests: YAML Config Tests ======================================


async def test_setup_yaml_config_new(
    hass: HomeAssistant,
    mock_remove_config: AsyncMock,
    mock_flow_init: AsyncMock,
    mock_load_yaml: AsyncMock,
    mock_dispatch_listener: AsyncMock,
) -> None:
    """Test async_setup with new YAML configuration."""
    await async_setup(hass, {DOMAIN: [HOME_CONFIG]})
    await hass.async_block_till_done()
    assert not mock_remove_config.called
    mock_flow_init.assert_called_once_with(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=HOME_CONFIG
    )
    mock_flow_init.assert_awaited_once()
    assert not mock_load_yaml.called
    assert not mock_dispatch_listener.called


async def test_setup_yaml_config_changed(
    hass: HomeAssistant,
    mock_remove_config: AsyncMock,
    mock_flow_init: AsyncMock,
    mock_load_yaml: AsyncMock,
    mock_dispatch_listener: AsyncMock,
) -> None:
    """Test async_setup with changed YAML configuration."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        source=SOURCE_IMPORT,
        title=hass.config.location_name,
        unique_id=HOME_CONFIG["unique_id"],
    )
    config_entry.add_to_hass(hass)
    new_config = NY_CONFIG | {"unique_id": HOME_CONFIG["unique_id"]}

    await async_setup(hass, {DOMAIN: [new_config]})
    await hass.async_block_till_done()
    assert not mock_remove_config.called
    mock_flow_init.assert_called_once_with(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=new_config
    )
    mock_flow_init.assert_awaited_once()
    assert not mock_load_yaml.called
    assert not mock_dispatch_listener.called


async def test_setup_yaml_config_removed(
    hass: HomeAssistant,
    mock_remove_config: AsyncMock,
    mock_flow_init: AsyncMock,
    mock_load_yaml: AsyncMock,
    mock_dispatch_listener: AsyncMock,
) -> None:
    """Test async_setup with removed YAML configuration."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        source=SOURCE_IMPORT,
        title=hass.config.location_name,
        unique_id=HOME_CONFIG["unique_id"],
    )
    config_entry.add_to_hass(hass)

    await async_setup(hass, {})
    await hass.async_block_till_done()
    mock_remove_config.assert_called_once_with(config_entry.entry_id)
    mock_remove_config.assert_awaited_once()
    assert not mock_flow_init.called
    assert not mock_load_yaml.called
    assert not mock_dispatch_listener.called


async def test_setup_yaml_config_reload(
    hass: HomeAssistant,
    mock_remove_config: AsyncMock,
    mock_flow_init: AsyncMock,
    mock_load_yaml: AsyncMock,
    mock_dispatch_listener: AsyncMock,
    init_yaml_config_entry: MockConfigEntry,
) -> None:
    """Test reload of YAML configuration."""
    await hass.services.async_call(DOMAIN, "reload")
    await hass.async_block_till_done()
    assert not mock_remove_config.called
    mock_flow_init.assert_called_once_with(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=HOME_CONFIG
    )
    mock_flow_init.assert_awaited_once()
    mock_load_yaml.assert_called_once_with(hass, DOMAIN)
    mock_load_yaml.assert_awaited_once()
    assert not mock_dispatch_listener.called


# ========== async_setup Tests: HA Config Updated ======================================


async def test_setup_ha_config_updated_no_data(
    hass: HomeAssistant,
    mock_remove_config: AsyncMock,
    mock_flow_init: AsyncMock,
    mock_load_yaml: AsyncMock,
    mock_dispatch_listener: AsyncMock,
    init_yaml_config_entry: MockConfigEntry,
) -> None:
    """Test EVENT_CORE_CONFIG_UPDATE."""
    hass.bus.async_fire(EVENT_CORE_CONFIG_UPDATE)
    await hass.async_block_till_done()
    assert not mock_remove_config.called
    assert not mock_flow_init.called
    assert not mock_load_yaml.called
    assert not mock_dispatch_listener.called


async def test_setup_ha_config_updated_loc_only(
    hass: HomeAssistant,
    mock_remove_config: AsyncMock,
    mock_flow_init: AsyncMock,
    mock_load_yaml: AsyncMock,
    mock_dispatch_listener: AsyncMock,
    init_yaml_config_entry: MockConfigEntry,
) -> None:
    """Test EVENT_CORE_CONFIG_UPDATE w/ location data only."""
    await hass.config.async_update(latitude=hass.config.latitude + 10)
    await hass.async_block_till_done()
    assert not mock_remove_config.called
    assert not mock_flow_init.called
    assert not mock_load_yaml.called
    mock_dispatch_listener.assert_called_once()
    mock_dispatch_listener.assert_awaited_once()


async def test_setup_ha_config_updated_name_yaml(
    hass: HomeAssistant,
    mock_remove_config: AsyncMock,
    mock_flow_init: AsyncMock,
    mock_load_yaml: AsyncMock,
    mock_dispatch_listener: AsyncMock,
    init_yaml_config_entry: MockConfigEntry,
) -> None:
    """Test EVENT_CORE_CONFIG_UPDATE w/ name changed, YAML config."""
    await hass.config.async_update(location_name=f"New {hass.config.location_name}")
    await hass.async_block_till_done()
    assert not mock_remove_config.called
    mock_flow_init.assert_called_once()
    mock_flow_init.assert_awaited_once()
    mock_load_yaml.assert_called_once()
    mock_load_yaml.assert_awaited_once()
    assert not mock_dispatch_listener.called


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


# async def test_reload_service(hass: HomeAssistant) -> None:
#     """Test basic YAML configuration."""
#     init_config = [HOME_CONFIG, NY_CONFIG]
#     with assert_setup_component(len(init_config), DOMAIN):
#         await async_setup_component(hass, DOMAIN, {DOMAIN: init_config})
#     await hass.async_block_till_done()

#     # Check config entries match config.
#     config_entries = hass.config_entries.async_entries(DOMAIN)
#     assert len(config_entries) == 2
#     config_entry_1 = config_entries[0]
#     assert config_entry_1.unique_id == HOME_CONFIG["unique_id"]
#     assert config_entry_1.title == hass.config.location_name
#     assert config_entry_1.options == {}
#     config_entry_2 = config_entries[1]
#     assert config_entry_2.unique_id == NY_CONFIG["unique_id"]
#     assert config_entry_2.title == NY_CONFIG["location"]
#     assert config_entry_2.options == NY_LOC

#     # Check reload service exists.
#     assert hass.services.has_service(DOMAIN, "reload")

#     # Reload new config.
#     reload_config = [TWINE_CONFIG, HW_CONFIG]
#     with patch(
#         "custom_components.sun2.async_integration_yaml_config",
#         autospec=True,
#         return_value={DOMAIN: reload_config},
#     ):
#         await hass.services.async_call(DOMAIN, "reload")
#         await hass.async_block_till_done()

#     # Check config entries match config.
#     config_entries = hass.config_entries.async_entries(DOMAIN)
#     assert len(config_entries) == 2
#     config_entry_1 = config_entries[0]
#     assert config_entry_1.unique_id == TWINE_CONFIG["unique_id"]
#     assert config_entry_1.title == TWINE_CONFIG["location"]
#     assert config_entry_1.options == TWINE_LOC
#     config_entry_2 = config_entries[1]
#     assert config_entry_2.unique_id == HW_CONFIG["unique_id"]
#     assert config_entry_2.title == HW_CONFIG["location"]
#     assert config_entry_2.options == HW_LOC

#     # Reload with same config.
#     reload_config = [TWINE_CONFIG, HW_CONFIG]
#     with patch(
#         "custom_components.sun2.async_integration_yaml_config",
#         autospec=True,
#         return_value={DOMAIN: reload_config},
#     ):
#         await hass.services.async_call(DOMAIN, "reload")
#         await hass.async_block_till_done()

#     # Check config entries haven't changed.
#     orig = [config_entry.as_dict() for config_entry in config_entries]
#     config_entries == hass.config_entries.async_entries(DOMAIN)
#     assert [config_entry.as_dict() for config_entry in config_entries] == orig

#     # Reload config with config removed.
#     with patch(
#         "custom_components.sun2.async_integration_yaml_config",
#         autospec=True,
#         return_value={},
#     ):
#         await hass.services.async_call(DOMAIN, "reload")
#         await hass.async_block_till_done()

#     # Check there are no config entries.
#     assert not hass.config_entries.async_entries(DOMAIN)

#     # Reload config again with config removed.
#     # This also covers the case where there are no imported entries to remove, and not
#     # imported entries to create or update.
#     with patch(
#         "custom_components.sun2.async_integration_yaml_config",
#         autospec=True,
#         return_value={},
#     ):
#         await hass.services.async_call(DOMAIN, "reload")
#         await hass.async_block_till_done()

#     # Check there are still no config entries.
#     assert not hass.config_entries.async_entries(DOMAIN)


# async def test_ha_config_update(hass: HomeAssistant) -> None:
#     """Test when HA config is updated."""
#     new_time_zone = "America/New_York"
#     new_location_name = "New York, NY"

#     # Check some assumptions.
#     assert hass.config.time_zone != new_time_zone
#     assert hass.config.location_name != new_location_name

#     await async_setup_component(hass, DOMAIN, {DOMAIN: [HOME_CONFIG]})
#     await hass.async_block_till_done()

#     # ConfigEntry object may change values, but it should not be replaced by a new
#     # object.
#     config_entry = hass.config_entries.async_entries(DOMAIN)[0]

#     # Get baseline.
#     old_values = config_entry.as_dict()
#     assert old_values["title"] == hass.config.location_name

#     # Fire an EVENT_CORE_CONFIG_UPDATE event with no data and check that nothing has
#     # changed.
#     hass.bus.async_fire(EVENT_CORE_CONFIG_UPDATE)
#     await hass.async_block_till_done()
#     assert hass.config_entries.async_entries(DOMAIN)[0] is config_entry
#     new_values = config_entry.as_dict()
#     assert new_values == old_values
#     old_values = new_values

#     # Change anything except for location_name and language and check that nothing
#     # changes.
#     await hass.config.async_update(time_zone=new_time_zone)
#     await hass.async_block_till_done()
#     assert hass.config_entries.async_entries(DOMAIN)[0] is config_entry
#     new_values = config_entry.as_dict()
#     assert new_values == old_values
#     old_values = new_values

#     # Change location_name and check that config entry reflects this change.
#     # Note that this will cause a reload of YAML config.
#     with patch(
#         "custom_components.sun2.async_integration_yaml_config",
#         autospec=True,
#         return_value={DOMAIN: [HOME_CONFIG]},
#     ):
#         await hass.config.async_update(location_name=new_location_name)
#         await hass.async_block_till_done()

#     assert hass.config_entries.async_entries(DOMAIN)[0] is config_entry
#     new_values = config_entry.as_dict()
#     assert new_values != old_values
#     assert new_values["title"] == new_location_name
