"""Test config flow module."""
from __future__ import annotations

from collections.abc import Generator
import logging
from typing import Any
from unittest.mock import AsyncMock, patch

from custom_components.sun2.const import DOMAIN
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .const import HOME_CONFIG, NY_CONFIG

_LOGGER = logging.getLogger(__name__)

# ========== Fixtures ==================================================================


@pytest.fixture
def reload_mock(hass: HomeAssistant) -> Generator[AsyncMock, None, None]:
    """Mock config_entries.async_reload."""
    with patch.object(hass.config_entries, "async_reload") as mock:
        yield mock


# ========== Import Flow Tests =========================================================


async def test_import_min_new(hass: HomeAssistant, reload_mock: AsyncMock):
    """Test minimum YAML config with new location."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=HOME_CONFIG.copy()
    )
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    config_entry: ConfigEntry = result["result"]
    assert config_entry.source == SOURCE_IMPORT
    assert config_entry.title == hass.config.location_name
    assert config_entry.data == {}
    assert config_entry.options == {}
    assert config_entry.unique_id == HOME_CONFIG["unique_id"]
    reload_mock.assert_not_called
    reload_mock.assert_not_awaited


@pytest.mark.parametrize(
    "new_config,changed",
    ((HOME_CONFIG, False), (NY_CONFIG | {"unique_id": HOME_CONFIG["unique_id"]}, True)),
)
async def test_import_min_old(
    hass: HomeAssistant,
    new_config: dict[str, Any],
    changed: bool,
):
    """Test minimum YAML config with an existing location."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        source=SOURCE_IMPORT,
        title=hass.config.location_name,
        state=ConfigEntryState.LOADED,
        unique_id=HOME_CONFIG["unique_id"],
    )
    config_entry.add_to_hass(hass)
    old_values = config_entry.as_dict()

    with patch.object(hass.config_entries, "async_reload") as reload_mock:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=new_config.copy()
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert changed ^ (config_entry.as_dict() == old_values)
    # When config changes, entry_updated will take care of reloading it. But when config
    # does not change, config flow will make sure it gets reloaded.
    assert changed ^ (reload_mock.call_count == 1)
    assert changed ^ (reload_mock.await_count == 1)
    if reload_mock.call_count == 1:
        reload_mock.assert_called_with(config_entry.entry_id)
