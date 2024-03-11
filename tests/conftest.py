"""Sun2 test configuration."""
from __future__ import annotations

from collections.abc import AsyncGenerator

from custom_components.sun2.const import DOMAIN
import pytest
from pytest import LogCaptureFixture

from homeassistant.const import MAJOR_VERSION, MINOR_VERSION
from homeassistant.core import HomeAssistant

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations."""
    yield


@pytest.fixture(autouse=True)
async def cleanup(
    hass: HomeAssistant, caplog: LogCaptureFixture, check_errors: bool = True
) -> AsyncGenerator[None, None]:
    """Cleanup after test & optionally check log for any errors."""
    yield
    if check_errors:
        assert "ERROR" not in caplog.text
    if (MAJOR_VERSION, MINOR_VERSION) > (2023, 5):
        return
    # Before 2023.5 configs were not unloaded at end of testing, since they are not
    # normally unloaded when HA shuts down. Unload them here to avoid errors about
    # lingering timers.
    for entry in hass.config_entries.async_entries(DOMAIN):
        await hass.config_entries.async_unload(entry.entry_id)


# @pytest.fixture
# def mock_setup_and_unload() -> Generator[tuple[AsyncMock, AsyncMock], None, None]:
#     """Mock async_setup_entry & async_unload_entry."""
#     with patch("custom_components.sun2.async_setup_entry") as mock_setup, patch(
#         "custom_components.sun2.async_unload_entry"
#     ) as mock_unload:
#         mock_setup.return_value = True
#         mock_unload.return_value = True
#         yield mock_setup, mock_unload
