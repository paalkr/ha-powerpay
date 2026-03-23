"""Tests for PowerPay coordinator."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.powerpay.api import PowerPayAuthError, PowerPayConnectionError
from custom_components.powerpay.const import SCAN_INTERVAL_ACTIVE, SCAN_INTERVAL_IDLE
from custom_components.powerpay.coordinator import PowerPayCoordinator

from .conftest import MOCK_CONSUMPTION_DATA, MOCK_RAW_SESSION, MOCK_SESSION_ID, MOCK_UID

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_client():
    """Create a mock API client."""
    client = AsyncMock()
    client.firebase_uid = MOCK_UID
    client.async_get_active_sessions = AsyncMock(return_value=[])
    client.async_get_session_consumption = AsyncMock(return_value=[])
    return client


@pytest.mark.asyncio
async def test_fetch_empty_sessions(hass: HomeAssistant, mock_client):
    """Test coordinator with no active sessions."""
    coordinator = PowerPayCoordinator(hass, mock_client)
    data = await coordinator._async_update_data()

    assert len(data.sessions) == 0
    assert coordinator.update_interval.total_seconds() == SCAN_INTERVAL_IDLE


@pytest.mark.asyncio
async def test_fetch_with_active_session(hass: HomeAssistant, mock_client):
    """Test coordinator with an active session."""
    mock_client.async_get_active_sessions = AsyncMock(return_value=[MOCK_RAW_SESSION])
    mock_client.async_get_session_consumption = AsyncMock(return_value=MOCK_CONSUMPTION_DATA)

    coordinator = PowerPayCoordinator(hass, mock_client)
    data = await coordinator._async_update_data()

    assert len(data.sessions) == 1
    session = data.sessions[0]
    assert session.session_id == MOCK_SESSION_ID
    assert session.energy_kwh == pytest.approx(3858.103, rel=0.01)  # API meter
    # First poll: calculated energy starts from API meter reading
    assert session.calculated_energy_kwh == pytest.approx(3858.103, rel=0.01)
    assert session.cost_nok == pytest.approx(3858.103 * 1.86, rel=0.01)
    assert session.billed_cost_nok == pytest.approx(6308.47, rel=0.01)  # from price_basis
    assert session.price_per_kwh == 1.86
    assert session.current_power_w == 1043
    assert coordinator.update_interval.total_seconds() == SCAN_INTERVAL_ACTIVE


@pytest.mark.asyncio
async def test_auth_failure_raises_config_entry_auth_failed(hass: HomeAssistant, mock_client):
    """Test that auth failure triggers reauth flow."""
    mock_client.async_get_active_sessions = AsyncMock(
        side_effect=PowerPayAuthError("Token expired")
    )

    coordinator = PowerPayCoordinator(hass, mock_client)
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_connection_failure_raises_update_failed(hass: HomeAssistant, mock_client):
    """Test that connection failure triggers retry."""
    mock_client.async_get_active_sessions = AsyncMock(
        side_effect=PowerPayConnectionError("Timeout")
    )

    coordinator = PowerPayCoordinator(hass, mock_client)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_device_parsing(hass: HomeAssistant, mock_client):
    """Test that device data is extracted from session."""
    mock_client.async_get_active_sessions = AsyncMock(return_value=[MOCK_RAW_SESSION])
    mock_client.async_get_session_consumption = AsyncMock(return_value=[])

    coordinator = PowerPayCoordinator(hass, mock_client)
    data = await coordinator._async_update_data()

    assert len(data.devices) == 1
    device = list(data.devices.values())[0]
    assert device.name == "Test Post 001"
    assert device.outlet_count == 4
    assert device.max_power == 3680


@pytest.mark.asyncio
async def test_price_extraction(hass: HomeAssistant, mock_client):
    """Test price extraction from model_string."""
    mock_client.async_get_active_sessions = AsyncMock(return_value=[MOCK_RAW_SESSION])
    mock_client.async_get_session_consumption = AsyncMock(return_value=[])

    coordinator = PowerPayCoordinator(hass, mock_client)
    data = await coordinator._async_update_data()

    assert data.sessions[0].price_per_kwh == 1.86
