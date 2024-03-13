"""Sun2 test configuration."""
from __future__ import annotations

from collections.abc import AsyncGenerator
import logging

from custom_components.sun2.const import DOMAIN
import pytest
from pytest import FixtureRequest, LogCaptureFixture

from homeassistant.const import MAJOR_VERSION, MINOR_VERSION
from homeassistant.core import HomeAssistant

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations."""
    yield


def pytest_configure(config):
    """Register fixture parameters."""
    config.addinivalue_line(
        "markers", "cleanup_params(*, check_log_errors: bool = True)"
    )


@pytest.fixture(autouse=True)
async def cleanup(
    hass: HomeAssistant, caplog: LogCaptureFixture, request: FixtureRequest
) -> AsyncGenerator[None, None]:
    """Cleanup after test & optionally check log for any errors.

    Pass check_errors:

    @pytest.mark.cleanup_params(
        *, check_log_errors: bool = True, ignore_phrases: list[str] | None = None
    )

    async def test_abc() -> None:
        ...
    """
    check_log_errors = True
    ignore_phrases: list[str] = []
    if marker := request.node.get_closest_marker("cleanup_params"):
        if "check_log_errors" in marker.kwargs:
            check_log_errors = marker.kwargs["check_log_errors"]
        if "ignore_phrases" in marker.kwargs:
            ignore_phrases = marker.kwargs["ignore_phrases"] or []
    yield
    if check_log_errors:
        for when in ("setup", "call"):
            messages = [
                x.message
                for x in caplog.get_records(when)  # type: ignore[arg-type]
                if x.levelno == logging.ERROR
                and not any(phrase in x.message for phrase in ignore_phrases)
            ]
            if messages:
                pytest.fail(
                    f"ERROR messages encountered during {when} phase: {messages}"
                )
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
